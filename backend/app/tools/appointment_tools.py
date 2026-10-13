from datetime import datetime, timezone
from ..config import Settings
from ..repositories import Appointment, Repository
from ..schemas import AppointmentLookupRequest, AvailabilityRequest, BookingRequest, CancellationRequest, EscalationRequest, RescheduleRequest, ToolResult
from ..timefmt import format_local, to_local_iso

class AppointmentTools:
    """Deterministic mocked hospital tools backed by the repository."""
    def __init__(self, repo: Repository, settings: Settings):
        self.repo, self.settings = repo, settings

    def _timeout(self, name: str) -> ToolResult | None:
        if self.settings.enable_fault_injection:
            return ToolResult(status='timeout', tool_name=name, error_code='TOOL_TIMEOUT', message='The downstream system timed out.')
        return None

    def check_availability(self, request: AvailabilityRequest) -> ToolResult:
        if timeout := self._timeout('check_availability'): return timeout
        now = datetime.now(timezone.utc)
        # Booked/held slots are excluded (status != 'available'), and slots that
        # already started today are hidden so only the remaining day is offered.
        slots = [slot for slot in self.repo.list_slots(request.specialty, request.date)
                 if slot.status == 'available' and slot.starts_at > now]
        return ToolResult(status='confirmed', tool_name='check_availability', data={'slots':[{'slot_id':s.id,'starts_at_local':format_local(self.settings, s.starts_at),'starts_at':to_local_iso(self.settings, s.starts_at),'specialty':s.specialty} for s in slots]})

    def book_appointment(self, request: BookingRequest) -> ToolResult:
        if timeout := self._timeout('book_appointment'): return timeout
        if self.repo.has_idempotency_key(request.idempotency_key): return ToolResult(status='confirmed', tool_name='book_appointment', data={'idempotent_replay':True})
        slot = self.repo.get_slot(request.slot_id)
        if not slot or slot.status != 'available' or slot.starts_at <= datetime.now(timezone.utc) or slot.specialty.lower() != request.specialty.lower():
            return ToolResult(status='failed', tool_name='book_appointment', error_code='SLOT_UNAVAILABLE', message='That slot is unavailable.')
        for existing in self.repo.list_appointments(request.patient_reference):
            if existing.slot_id == request.slot_id and existing.status in ('booked', 'rescheduled'):
                return ToolResult(status='failed', tool_name='book_appointment', error_code='DUPLICATE_BOOKING', message='This patient already has a booking on that slot.')
        appointment_id = self.repo.next_appointment_reference()
        self.repo.save_appointment(Appointment(appointment_id, request.patient_reference, request.specialty, slot.id, slot.starts_at))
        slot.status = 'booked'; self.repo.save_slot(slot); self.repo.save_idempotency_key(request.idempotency_key)
        return ToolResult(status='confirmed', tool_name='book_appointment', data={'appointment_id':appointment_id,'slot_id':slot.id,'specialty':slot.specialty,'starts_at_local':format_local(self.settings, slot.starts_at),'starts_at':to_local_iso(self.settings, slot.starts_at)})

    def lookup_appointment(self, request: AppointmentLookupRequest) -> ToolResult:
        if timeout := self._timeout('lookup_appointment'): return timeout
        appointment = self.repo.get_appointment(request.appointment_id)
        if not appointment or appointment.patient_reference != request.patient_reference: return ToolResult(status='failed', tool_name='lookup_appointment', error_code='APPOINTMENT_NOT_FOUND', message='Appointment not found for this patient.')
        if appointment.status == 'cancelled':
            return ToolResult(status='failed', tool_name='lookup_appointment', error_code='APPOINTMENT_CANCELLED', message='That appointment has already been cancelled.')
        return ToolResult(status='confirmed', tool_name='lookup_appointment', data={'appointment_id':appointment.id,'status':appointment.status,'specialty':appointment.specialty,'starts_at_local':format_local(self.settings, appointment.starts_at),'starts_at':to_local_iso(self.settings, appointment.starts_at)})

    def reschedule_appointment(self, request: RescheduleRequest) -> ToolResult:
        if timeout := self._timeout('reschedule_appointment'): return timeout
        if self.repo.has_idempotency_key(request.idempotency_key): return ToolResult(status='confirmed', tool_name='reschedule_appointment', data={'idempotent_replay':True})
        appointment = self.repo.get_appointment(request.appointment_id); slot = self.repo.get_slot(request.slot_id)
        if not appointment or appointment.patient_reference != request.patient_reference or appointment.status in ('cancelled', 'cancellation_pending_approval'): return ToolResult(status='failed', tool_name='reschedule_appointment', error_code='APPOINTMENT_NOT_FOUND', message='No active appointment found for this patient.')
        if not slot or slot.status != 'available': return ToolResult(status='failed', tool_name='reschedule_appointment', error_code='SLOT_UNAVAILABLE')
        previous_slot = self.repo.get_slot(appointment.slot_id)
        if previous_slot: previous_slot.status = 'available'; self.repo.save_slot(previous_slot)
        slot.status = 'booked'; self.repo.save_slot(slot); appointment.slot_id = slot.id; appointment.starts_at = slot.starts_at; appointment.status = 'rescheduled'; self.repo.save_appointment(appointment); self.repo.save_idempotency_key(request.idempotency_key)
        return ToolResult(status='confirmed', tool_name='reschedule_appointment', data={'appointment_id':appointment.id,'starts_at_local':format_local(self.settings, slot.starts_at),'starts_at':to_local_iso(self.settings, slot.starts_at)})

    def cancel_appointment(self, request: CancellationRequest) -> ToolResult:
        if timeout := self._timeout('cancel_appointment'): return timeout
        if self.repo.has_idempotency_key(request.idempotency_key): return ToolResult(status='confirmed', tool_name='cancel_appointment', data={'idempotent_replay':True})
        appointment = self.repo.get_appointment(request.appointment_id)
        if not appointment or appointment.patient_reference != request.patient_reference or appointment.status == 'cancelled': return ToolResult(status='failed', tool_name='cancel_appointment', error_code='APPOINTMENT_NOT_FOUND', message='No active appointment found for this patient.')
        # The patient explicitly confirmed through the assistant, so the
        # cancellation always takes effect immediately. The 24h approval
        # policy is no longer applied.
        appointment.status = 'cancelled'; self.repo.save_appointment(appointment)
        slot = self.repo.get_slot(appointment.slot_id)
        if slot: slot.status = 'available'; self.repo.save_slot(slot)
        self.repo.save_idempotency_key(request.idempotency_key)
        return ToolResult(status='confirmed', tool_name='cancel_appointment', data={'cancelled':True,'appointment_id':appointment.id})

    def escalate_to_human(self, request: EscalationRequest) -> ToolResult:
        from uuid import UUID
        item = self.repo.escalate(request.reason, request.session_id or UUID(int=0), request.appointment_id)
        return ToolResult(status='confirmed', tool_name='escalate_to_human', data=item)
