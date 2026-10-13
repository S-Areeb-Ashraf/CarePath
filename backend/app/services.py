"""Patient assistant as an LLM tool-calling agent loop.

The LLM decides which tools to call using the JSON specs in tool_specs.py.
Tools are executed against the validated AppointmentTools, Serper search, and
the ChromaDB knowledge base. Any OpenAI-compatible provider works — switching
provider or model is an environment change, not a code change.
"""
import json
from datetime import date as date_type
from datetime import datetime
from uuid import uuid4

from .config import Settings
from .llm import LLMClient, LLMUnavailable
from .rag import KnowledgeBase, EmbeddingError
from .repositories import Repository
from .schemas import (
    AppointmentLookupRequest,
    AssistantRequest,
    AssistantResponse,
    AvailabilityRequest,
    BookingRequest,
    CancellationRequest,
    RescheduleRequest,
    Source,
    ToolCall,
    ToolResult,
)
from .tools import AppointmentTools
from .tools.tool_specs import SYSTEM_PROMPT, TOOL_SPECS, KNOWN_TOOLS
from .tools.web_search import SerperSearch

def cancellation_decision(starts_at: datetime, now: datetime, auto_hours: int) -> str:
    return 'auto' if (starts_at - now).total_seconds() / 3600 > auto_hours else 'approval'

def guarded_reply(tool_status: str, confirmed: str, not_confirmed: str) -> str:
    return confirmed if tool_status == 'confirmed' else not_confirmed

MAX_TOOL_ITERATIONS_FALLBACK = 6
INSURANCE_HINTS = ('insurance', 'policy', 'coverage', 'copay', 'copayment', 'bupa', 'tawuniya', 'medgulf', 'malath', 'chi', 'claim', 'reimburse')


class AssistantService:
    def __init__(self, repo: Repository, settings: Settings):
        self.repo = repo
        self.settings = settings
        self.tools = AppointmentTools(repo, settings)
        self.llm = LLMClient(settings)
        self.search = SerperSearch(settings)
        self.kb = KnowledgeBase(settings)

    # ---------- public entry point ----------

    def handle(self, request: AssistantRequest, patient_reference: str) -> AssistantResponse:
        session_id = request.session_id or uuid4()
        request_id = uuid4()
        self.llm_status = 'not_needed'
        self.llm_error = None
        sources: list[Source] = []
        tool_trace: list[ToolCall] = []

        try:
            history = self._load_history(session_id, request.message, patient_reference)
            reply, used_tools, used_sources = self._agent_loop(history, patient_reference, tool_trace, sources)
        except LLMUnavailable as exc:
            self._set_llm_failure(exc)
            return self._response(session_id, request_id, 'The assistant service is temporarily unavailable. Please try again shortly or ask for a human representative.', 'error', 'failed', tool_trace, sources=sources)
        except Exception as exc:  # knowledge base or tool failure must not 500
            self.llm_error = str(exc)
            return self._response(session_id, request_id, 'Something went wrong while handling your request. Please try again or ask for a human representative.', 'error', 'failed', tool_trace, sources=sources)

        self._save_history(session_id, request, reply)
        return self._response(session_id, request_id, reply, 'assistant', 'completed', tool_trace, sources=sources)

    # ---------- agent loop ----------

    def _agent_loop(self, history: list[dict], patient_reference: str, tool_trace: list[ToolCall], sources: list[Source]) -> tuple[str, list[ToolCall], list[Source]]:
        max_iterations = self.settings.agent_max_iterations or MAX_TOOL_ITERATIONS_FALLBACK
        messages = list(history)
        for _ in range(max_iterations):
            turn = self.llm.chat_completion(messages, tools=TOOL_SPECS)
            if turn.tool_calls:
                messages.append({'role': 'assistant', 'content': turn.content or None, 'tool_calls': [
                    self._echo_tool_call(call, index) for index, call in enumerate(turn.tool_calls)
                ]})
                for index, call in enumerate(turn.tool_calls):
                    result = self._execute_tool(call, patient_reference, sources)
                    tool_trace.append(ToolCall(name=result.tool_name, status=result.status, error_code=result.error_code))
                    messages.append({'role': 'tool', 'tool_call_id': call.id or f'call_{index}', 'content': json.dumps(result.model_dump(mode='json'), default=str)})
                continue
            if turn.content:
                self.llm_status = 'used'
                return turn.content, tool_trace, sources
            break
        return 'I could not complete that request in the allowed number of steps. Could you rephrase or split it into smaller requests?', tool_trace, sources

    @staticmethod
    def _echo_tool_call(call, index: int) -> dict:
        """Rebuild the assistant tool-call message. Gemini 3 requires the
        thought_signature to be echoed back verbatim inside
        extra_content.google; OpenAI-compatible providers ignore it."""
        payload = {'id': call.id or f'call_{index}', 'type': 'function', 'function': {'name': call.name, 'arguments': json.dumps(call.arguments)}}
        if getattr(call, 'thought_signature', None):
            payload['extra_content'] = {'google': {'thought_signature': call.thought_signature}}
        return payload

    def _execute_tool(self, call, patient_reference: str, sources: list[Source]):
        name = call.name
        arguments = call.arguments or {}
        if name not in KNOWN_TOOLS:
            return self._tool_error(name, 'UNKNOWN_TOOL', 'That tool does not exist.')
        try:
            if name == 'check_availability':
                return self._tool_check_availability(arguments)
            if name == 'book_appointment':
                return self._tool_book(arguments, patient_reference)
            if name == 'reschedule_appointment':
                return self._tool_reschedule(arguments, patient_reference)
            if name == 'cancel_appointment':
                return self._tool_cancel(arguments, patient_reference)
            if name == 'list_my_appointments':
                return self._tool_list_mine(patient_reference)
            if name == 'search_clinic_info':
                return self._tool_search_clinic_info(arguments, sources)
        except (ValueError, KeyError, TypeError) as exc:
            return self._tool_error(name, 'INVALID_ARGUMENTS', f'Invalid arguments: {exc}')
        return self._tool_error(name, 'UNKNOWN_TOOL', 'That tool does not exist.')

    # ---------- tool adapters ----------

    @staticmethod
    def _tool_error(name: str, code: str, message: str):
        from .schemas import ToolResult
        return ToolResult(status='failed', tool_name=name, error_code=code, message=message)

    def _tool_check_availability(self, arguments: dict):
        specialty = str(arguments.get('specialty') or '').strip()
        raw_date = str(arguments.get('date') or '').strip()
        if not specialty or not raw_date:
            return self._tool_error('check_availability', 'MISSING_FIELDS', 'specialty and date (YYYY-MM-DD) are required.')
        try:
            parsed = date_type.fromisoformat(raw_date)
        except ValueError:
            return self._tool_error('check_availability', 'INVALID_DATE', 'date must be YYYY-MM-DD.')
        return self.tools.check_availability(AvailabilityRequest(specialty=specialty, date=parsed))

    def _tool_book(self, arguments: dict, patient_reference: str):
        specialty = str(arguments.get('specialty') or '').strip()
        slot_id = str(arguments.get('slot_id') or '').strip()
        if not specialty or not slot_id:
            return self._tool_error('book_appointment', 'MISSING_FIELDS', 'specialty and slot_id are required. Run check_availability first and let the patient pick a slot.')
        return self.tools.book_appointment(BookingRequest(
            patient_reference=patient_reference,
            specialty=specialty,
            slot_id=slot_id,
            idempotency_key=f'book-{patient_reference}-{slot_id}-{uuid4()}',
        ))

    def _tool_reschedule(self, arguments: dict, patient_reference: str):
        appointment_id = str(arguments.get('appointment_id') or '').strip()
        slot_id = str(arguments.get('slot_id') or '').strip()
        confirmed = bool(arguments.get('confirmed'))
        if not confirmed:
            return self._tool_error('reschedule_appointment', 'CONFIRMATION_REQUIRED', 'The patient must explicitly confirm the rescheduling first. Ask them and call again with confirmed=true.')
        if not appointment_id or not slot_id:
            return self._tool_error('reschedule_appointment', 'MISSING_FIELDS', 'appointment_id and slot_id are required.')
        return self.tools.reschedule_appointment(RescheduleRequest(
            appointment_id=appointment_id,
            patient_reference=patient_reference,
            slot_id=slot_id,
            idempotency_key=f'reschedule-{appointment_id}-{slot_id}-{uuid4()}',
        ))

    def _tool_cancel(self, arguments: dict, patient_reference: str):
        appointment_id = str(arguments.get('appointment_id') or '').strip()
        confirmed = bool(arguments.get('confirmed'))
        if not confirmed:
            return self._tool_error('cancel_appointment', 'CONFIRMATION_REQUIRED', 'The patient must explicitly confirm the cancellation first. Ask them and call again with confirmed=true.')
        if not appointment_id:
            return self._tool_error('cancel_appointment', 'MISSING_FIELDS', 'appointment_id is required.')
        return self.tools.cancel_appointment(CancellationRequest(
            appointment_id=appointment_id,
            patient_reference=patient_reference,
            idempotency_key=f'cancel-{appointment_id}-{uuid4()}',
        ))

    def _tool_list_mine(self, patient_reference: str):
        from .timefmt import format_local, to_local_iso
        appointments = self.repo.list_appointments(patient_reference)
        return ToolResult(
            status='confirmed', tool_name='list_my_appointments',
            data={'appointments': [
                {'appointment_id': item.id, 'specialty': item.specialty, 'starts_at_local': format_local(self.settings, item.starts_at), 'starts_at': to_local_iso(self.settings, item.starts_at), 'status': item.status}
                for item in appointments
            ]},
        )

    def _tool_search_clinic_info(self, arguments: dict, sources: list[Source]):
        query = str(arguments.get('query') or '').strip()
        if not query:
            return self._tool_error('search_clinic_info', 'MISSING_FIELDS', 'query is required.')
        chunks: list[dict] = []
        try:
            chunks = self.kb.search(query)
        except (EmbeddingError, Exception) as exc:  # noqa: BLE001 — KB failure must not crash the chat
            self.llm_error = f'knowledge base unavailable: {exc}'
        lowered = query.lower()
        needs_web = any(hint in lowered for hint in INSURANCE_HINTS) or not chunks
        web_results: list[dict] = []
        if needs_web:
            result = self.search.search(query)
            if result.status == 'confirmed':
                web_results = result.data.get('results', [])
            else:
                self.llm_error = result.message
        combined = {
            'knowledge_base': [
                {'source': chunk['source'], 'title': chunk['title'], 'text': chunk['text'], 'url': chunk.get('url', '')}
                for chunk in chunks
            ],
            'web_results': web_results,
        }
        for chunk in chunks:
            if chunk['source'] not in {source.source for source in sources}:
                sources.append(Source(source=chunk['source'], title=chunk['title'], version=chunk['version']))
        for item in web_results[:3]:
            label = item.get('link', '')
            if label and label not in {source.source for source in sources}:
                sources.append(Source(source=label, title=item.get('title', 'Web source'), version='web'))
        if not combined['knowledge_base'] and not combined['web_results']:
            return ToolResult(status='failed', tool_name='search_clinic_info', error_code='NO_RESULTS', message='No information found. Tell the patient you do not know and suggest contacting the clinic directly.')
        return ToolResult(status='confirmed', tool_name='search_clinic_info', data=combined)

    # ---------- history persistence ----------

    def _load_history(self, session_id, message: str, patient_reference: str) -> list[dict]:
        state = self.repo.get_session_state(session_id) or {}
        turns = state.get('messages', []) if isinstance(state, dict) else []
        system = {
            'role': 'system',
            'content': SYSTEM_PROMPT + f'\n\nLogged-in patient_reference: {patient_reference}. Today is {datetime.now().date().isoformat()}.',
        }
        return [system] + turns[-12:] + [{'role': 'user', 'content': message}]

    def _save_history(self, session_id, request: AssistantRequest, reply: str) -> None:
        state = self.repo.get_session_state(session_id) or {}
        turns = state.get('messages', []) if isinstance(state, dict) else []
        turns = turns + [
            {'role': 'user', 'content': request.message},
            {'role': 'assistant', 'content': reply},
        ]
        self.repo.save_session_state(session_id, {'messages': turns[-12:]})

    # ---------- helpers ----------

    def _set_llm_failure(self, exc: LLMUnavailable) -> None:
        text = str(exc)
        self.llm_status = 'not_configured' if ('not configured' in text or 'required' in text) else 'failed'
        self.llm_error = text

    def _response(self, session_id, request_id, reply: str, intent: str, status: str, calls: list[ToolCall] | None = None, human: bool = False, sources: list[Source] | None = None) -> AssistantResponse:
        return AssistantResponse(
            session_id=session_id,
            request_id=request_id,
            reply=reply,
            intent=intent,
            status=status,
            tool_calls=calls or [],
            requires_human=human,
            sources=sources or [],
            llm_used=self.llm_status == 'used',
            llm_status=self.llm_status,
            llm_error=getattr(self, 'llm_error', None),
        )
