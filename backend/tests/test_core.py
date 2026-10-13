from datetime import datetime, timedelta, timezone
from app.services import cancellation_decision, guarded_reply
from app.schemas import ToolCall
from app.config import Settings
from app.repositories import Repository
from app.tools import AppointmentTools
from app.schemas import BookingRequest, CancellationRequest

def test_cancellation_boundaries():
    now = datetime.now(timezone.utc)
    assert cancellation_decision(now + timedelta(hours=24, minutes=1), now, 24) == 'auto'
    assert cancellation_decision(now + timedelta(hours=24), now, 24) == 'approval'
    assert cancellation_decision(now + timedelta(hours=23, minutes=59), now, 24) == 'approval'

def test_success_is_gated():
    assert guarded_reply(ToolCall(name='x', status='timeout'), 'success', 'not confirmed') == 'not confirmed'

def test_booking_is_idempotent_and_confirmed():
    settings = Settings(app_env='test', supabase_url='x', supabase_service_role_key='x', llm_api_key='x', llm_model_primary='x', llm_model_secondary='y', cors_origins=['http://test'], admin_api_key='x')
    repo = Repository.seeded(); tools = AppointmentTools(repo, settings)
    request = BookingRequest(patient_reference='PAT-001', specialty='Dermatology', slot_id='SLOT-DERM-01', idempotency_key='booking-key-1')
    first = tools.book_appointment(request); second = tools.book_appointment(request)
    assert first.status == 'confirmed'
    assert second.data['idempotent_replay'] is True

def test_cancellation_within_window_still_cancels():
    settings = Settings(app_env='test', supabase_url='x', supabase_service_role_key='x', llm_api_key='x', llm_model_primary='x', llm_model_secondary='y', cors_origins=['http://test'], admin_api_key='x')
    repo = Repository.seeded(); tools = AppointmentTools(repo, settings)
    result = tools.cancel_appointment(CancellationRequest(appointment_id='APT-SOON', patient_reference='PAT-001', idempotency_key='cancel-key-1'))
    assert result.status == 'confirmed'
    assert result.data['cancelled'] is True
    assert tools.repo.get_appointment('APT-SOON').status == 'cancelled'
