from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from .auth import hash_password

@dataclass
class Appointment:
    id: str
    patient_reference: str
    specialty: str
    slot_id: str
    starts_at: datetime
    status: str = 'booked'

@dataclass
class Slot:
    id: str
    specialty: str
    starts_at: datetime
    status: str = 'available'

@dataclass
class Repository:
    kb: list[dict[str, Any]] = field(default_factory=list)
    appointments: dict[str, Appointment] = field(default_factory=dict)
    slots: dict[str, Slot] = field(default_factory=dict)
    escalations: list[dict[str, Any]] = field(default_factory=list)
    idempotency: set[str] = field(default_factory=set)
    sections: list[dict[str, Any]] = field(default_factory=list)
    eval_cases: list[dict[str, Any]] = field(default_factory=list)
    sessions: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    patients: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def seeded(cls) -> 'Repository':
        now = datetime.now(timezone.utc)
        repo = cls()
        repo.kb = [
            {'source':'insurance/faq','title':'Insurance FAQ','version':'1','text':'Coverage depends on the member plan. Confirm benefits with the insurer before care.','score':0.98},
            {'source':'prep/general','title':'Preparation guidance','version':'1','text':'Bring your appointment reference and arrive ten minutes early.','score':0.96},
            {'source':'policy/cancellation','title':'Cancellation policy','version':'1','text':'Appointments more than 24 hours away may be cancelled automatically. Within 24 hours, approval is required.','score':0.99},
        ]
        repo.slots = {
            'SLOT-GEN-01': Slot('SLOT-GEN-01','General Medicine',now + timedelta(days=2)),
            'SLOT-GEN-02': Slot('SLOT-GEN-02','General Medicine',now + timedelta(days=3)),
            'SLOT-DERM-01': Slot('SLOT-DERM-01','Dermatology',now + timedelta(days=4)),
        }
        repo.appointments = {
            'APT-FUTURE': Appointment('APT-FUTURE','PAT-001','General Medicine','SLOT-GEN-01',now + timedelta(days=3)),
            'APT-SOON': Appointment('APT-SOON','PAT-001','General Medicine','SLOT-GEN-02',now + timedelta(hours=23)),
        }
        repo.patients = {
            'PAT-001': {'patient_reference':'PAT-001','email':'pat001@example.com','password_hash':hash_password('TestPass123!'),'display_name':'Test Patient One'},
            'PAT-002': {'patient_reference':'PAT-002','email':None,'password_hash':None,'display_name':None},
        }
        repo.slots['SLOT-GEN-01'].status = 'booked'
        repo.sections = [{'slug':'overview','title':'Patient service operations','body':'A reliable assistant for trusted answers, appointment operations, and transparent human escalation.','sort_order':0}]
        categories = ['booking','rescheduling','cancellation-over-24h','cancellation-under-24h','availability','preparation','insurance-supported','insurance-unsupported','ambiguous','unavailable','invalid-id','timeout','injection','other-patient','medical-advice','human-escalation']
        repo.eval_cases = [{'id':f'case-{i:02d}','category':category,'expected_behavior':'validated and safe response','criteria':{'status':'completed'}} for i,category in enumerate(categories,1)]
        return repo

    def search_kb(self, query: str, top_k: int, minimum: float) -> list[dict[str, Any]]:
        terms = set(query.lower().split())
        return [item for item in self.kb if terms & set(item['text'].lower().split()) and item['score'] >= minimum][:top_k]

    def list_slots(self, specialty: str | None = None, on_date: Any = None) -> list[Slot]:
        return [slot for slot in self.slots.values() if (not specialty or slot.specialty.lower() == specialty.lower()) and (not on_date or slot.starts_at.date() == on_date)]

    def get_slot(self, slot_id: str) -> Slot | None:
        return self.slots.get(slot_id)

    def save_slot(self, slot: Slot) -> None:
        self.slots[slot.id] = slot

    def get_appointment(self, appointment_id: str) -> Appointment | None:
        return self.appointments.get(appointment_id)

    def save_appointment(self, appointment: Appointment) -> None:
        self.appointments[appointment.id] = appointment

    def next_appointment_reference(self) -> str:
        return f'APT-{len(self.appointments) + 1:04d}'

    def has_idempotency_key(self, key: str) -> bool:
        return key in self.idempotency

    def save_idempotency_key(self, key: str) -> None:
        self.idempotency.add(key)

    def list_appointments(self, patient_reference: str | None = None) -> list[Appointment]:
        return [item for item in self.appointments.values() if not patient_reference or item.patient_reference == patient_reference]

    def list_escalations(self) -> list[dict[str, Any]]:
        return self.escalations

    def list_sections(self, slug_prefix: str | None = None) -> list[dict[str, Any]]:
        return [item for item in self.sections if not slug_prefix or item['slug'].startswith(slug_prefix)]

    def list_eval_cases(self) -> list[dict[str, Any]]:
        return self.eval_cases

    def get_session_state(self, session_id: UUID) -> dict[str, Any]:
        return self.sessions.get(session_id, {})

    def save_session_state(self, session_id: UUID, state: dict[str, Any]) -> None:
        self.sessions[session_id] = state

    def escalate(self, reason: str, session_id: UUID, appointment_id: str | None = None) -> dict[str, Any]:
        item = {'reason':reason,'session_id':str(session_id),'appointment_id':appointment_id,'status':'open','type':'human'}
        self.escalations.append(item)
        return item

    def get_patient_by_email(self, email: str) -> dict[str, Any] | None:
        for item in self.patients.values():
            if item.get('email', '').lower() == email.lower():
                return item
        return None

    def get_patient_by_reference(self, patient_reference: str) -> dict[str, Any] | None:
        return self.patients.get(patient_reference)

    def create_patient_with_credentials(self, patient_reference: str, email: str, password_hash: str, display_name: str | None) -> dict[str, Any]:
        patient = {'patient_reference': patient_reference, 'email': email, 'password_hash': password_hash, 'display_name': display_name}
        self.patients[patient_reference] = patient
        return patient
