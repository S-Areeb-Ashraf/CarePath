from datetime import date, datetime, timezone
import re
from typing import Any
from uuid import UUID
from supabase import Client, create_client
from .config import Settings
from .repositories import Appointment, Slot

class SupabaseRepository:
    """Production repository. All application data is read/written through Supabase."""
    def __init__(self, settings: Settings):
        self.client: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    @staticmethod
    def _first(response: Any) -> dict[str, Any] | None:
        rows = getattr(response, 'data', None) or []
        return rows[0] if rows else None

    @staticmethod
    def _slot(row: dict[str, Any]) -> Slot:
        return Slot(row['slot_reference'], row.get('specialty') or '', datetime.fromisoformat(row['starts_at'].replace('Z', '+00:00')), row['status'])

    @staticmethod
    def _appointment(row: dict[str, Any]) -> Appointment:
        return Appointment(row['appointment_reference'], row['patient_reference'], row.get('specialty') or '', row['slot_reference'], datetime.fromisoformat(row['starts_at'].replace('Z', '+00:00')), row['status'])

    def list_slots(self, specialty: str | None = None, on_date: date | None = None) -> list[Slot]:
        query = self.client.table('appointment_slots').select('*')
        if specialty: query = query.eq('specialty', specialty)
        if on_date: query = query.gte('starts_at', f'{on_date.isoformat()}T00:00:00+00:00').lt('starts_at', f'{on_date.isoformat()}T23:59:59+00:00')
        response = query.execute()
        return [self._slot(row) for row in (response.data or [])]

    def get_slot(self, slot_id: str) -> Slot | None:
        row = self._first(self.client.table('appointment_slots').select('*').eq('slot_reference', slot_id).limit(1).execute())
        return self._slot(row) if row else None

    def save_slot(self, slot: Slot) -> None:
        self.client.table('appointment_slots').update({'status':slot.status}).eq('slot_reference', slot.id).execute()

    def get_appointment(self, appointment_id: str) -> Appointment | None:
        row = self._first(self.client.table('appointments').select('*').eq('appointment_reference', appointment_id).limit(1).execute())
        return self._appointment(row) if row else None

    def save_appointment(self, appointment: Appointment) -> None:
        self.client.table('appointments').upsert({'appointment_reference':appointment.id,'patient_reference':appointment.patient_reference,'specialty':appointment.specialty,'slot_reference':appointment.slot_id,'starts_at':appointment.starts_at.isoformat(),'status':appointment.status,'updated_at':datetime.now(timezone.utc).isoformat()}, on_conflict='appointment_reference').execute()

    def next_appointment_reference(self) -> str:
        response = self.client.table('appointments').select('appointment_reference').like('appointment_reference', 'APT-%').execute()
        return f"APT-{len(response.data or []) + 1:04d}"

    def has_idempotency_key(self, key: str) -> bool:
        row = self._first(self.client.table('tool_calls').select('id').eq('idempotency_key', key).limit(1).execute())
        return row is not None

    def save_idempotency_key(self, key: str) -> None:
        self.client.table('tool_calls').insert({'tool_name':'appointment_mutation','inputs':{},'status':'confirmed','idempotency_key':key}).execute()

    def _search_kb_tables(self, query: str, top_k: int, minimum: float) -> list[dict[str, Any]]:
        documents = self.client.table('kb_documents').select('id,source,title,version,requires_validation').eq('requires_validation', False).execute().data or []
        chunks = self.client.table('kb_chunks').select('document_id,body').execute().data or []
        by_id = {row['id']: row for row in documents}
        stop_words = {'a', 'an', 'and', 'are', 'about', 'can', 'could', 'do', 'for', 'give', 'have', 'i', 'information', 'is', 'me', 'my', 'of', 'on', 'please', 'question', 'regarding', 'some', 'tell', 'the', 'to', 'what', 'with'}
        terms = {term.rstrip('s') for term in re.findall(r'[a-z0-9]+', query.lower()) if term not in stop_words}
        matches: list[dict[str, Any]] = []
        for chunk in chunks:
            document = by_id.get(chunk.get('document_id'))
            body = chunk.get('body') or ''
            if not document or not terms:
                continue
            body_terms = {term.rstrip('s') for term in re.findall(r'[a-z0-9]+', body.lower())}
            overlap = terms & body_terms
            if overlap:
                matches.append({'source':document['source'],'title':document['title'],'version':document['version'],'text':body,'score':len(overlap) / len(terms)})
        matches.sort(key=lambda row: row['score'], reverse=True)
        return [row for row in matches[:top_k] if row['score'] >= minimum]

    def search_kb(self, query: str, top_k: int, minimum: float) -> list[dict[str, Any]]:
        try:
            response = self.client.rpc('search_kb_chunks', {'search_query':query, 'result_limit':top_k}).execute()
            hits = [row for row in (response.data or []) if float(row.get('score', 0)) >= minimum]
            return hits or self._search_kb_tables(query, top_k, minimum)
        except Exception as exc:
            # Older Supabase projects may have the KB tables but not the RPC from
            # schema.sql yet. Keep RAG backed by Supabase while that migration is
            # being applied instead of turning a knowledge question into HTTP 500.
            if 'search_kb_chunks' not in str(exc) and 'PGRST202' not in str(exc):
                raise RuntimeError(f'Supabase knowledge search failed: {exc}') from exc
            try:
                return self._search_kb_tables(query, top_k, minimum)
            except Exception as fallback_exc:
                raise RuntimeError('Supabase knowledge search is not available. Apply supabase/migrate_existing.sql to deploy search_kb_chunks.') from fallback_exc

    def escalate(self, reason: str, session_id: UUID, appointment_id: str | None = None) -> dict[str, Any]:
        row = {'reason':reason,'type':'human','status':'open','appointment_reference':appointment_id}
        response = self.client.table('escalations').insert(row).execute()
        return (response.data or [row])[0]

    def list_appointments(self, patient_reference: str | None = None) -> list[Appointment]:
        query = self.client.table('appointments').select('*')
        if patient_reference: query = query.eq('patient_reference', patient_reference)
        return [self._appointment(row) for row in (query.execute().data or [])]

    def list_escalations(self) -> list[dict[str, Any]]:
        return self.client.table('escalations').select('*').order('id', desc=True).execute().data or []

    def list_sections(self, slug_prefix: str | None = None) -> list[dict[str, Any]]:
        query = self.client.table('submission_sections').select('slug,title,body,sort_order').order('sort_order')
        if slug_prefix: query = query.like('slug', f'{slug_prefix}%')
        return query.execute().data or []

    def list_eval_cases(self) -> list[dict[str, Any]]:
        return self.client.table('eval_cases').select('*').order('id').execute().data or []

    def get_session_state(self, session_id: UUID) -> dict[str, Any]:
        row = self._first(self.client.table('conversations').select('state').eq('id', str(session_id)).limit(1).execute())
        return (row or {}).get('state') or {}

    def save_session_state(self, session_id: UUID, state: dict[str, Any]) -> None:
        self.client.table('conversations').upsert({'id':str(session_id),'state':state}, on_conflict='id').execute()

    def get_patient_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._first(self.client.table('patients').select('patient_reference,email,password_hash,display_name').eq('email', email).limit(1).execute())
        return row

    def get_patient_by_reference(self, patient_reference: str) -> dict[str, Any] | None:
        row = self._first(self.client.table('patients').select('patient_reference,email,password_hash,display_name').eq('patient_reference', patient_reference).limit(1).execute())
        return row

    def create_patient_with_credentials(self, patient_reference: str, email: str, password_hash: str, display_name: str | None) -> dict[str, Any]:
        row = {'patient_reference': patient_reference, 'email': email, 'password_hash': password_hash, 'display_name': display_name}
        response = self.client.table('patients').insert(row).execute()
        return (response.data or [row])[0]
