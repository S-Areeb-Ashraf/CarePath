from app.config import Settings
from app.repositories import Repository
from app.tools import AppointmentTools
from app.schemas import CancellationRequest, RescheduleRequest
from app.services import AssistantService
from app.tools.tool_specs import TOOL_SPECS, SYSTEM_PROMPT, KNOWN_TOOLS


def make_settings(**overrides) -> Settings:
    values = dict(
        app_env='test', supabase_url='x', supabase_service_role_key='x',
        llm_api_key='x', llm_model_primary='x', llm_model_secondary='y',
        cors_origins=['http://test'], admin_api_key='x',
    )
    values.update(overrides)
    return Settings(**values)


def test_tool_specs_are_valid_openai_format():
    for spec in TOOL_SPECS:
        assert spec['type'] == 'function'
        function = spec['function']
        assert function['name'] in KNOWN_TOOLS
        assert function['parameters']['type'] == 'object'
        assert isinstance(function['parameters'].get('required', []), list)


def test_all_five_required_tools_present():
    names = {spec['function']['name'] for spec in TOOL_SPECS}
    assert {'check_availability', 'book_appointment', 'reschedule_appointment', 'cancel_appointment', 'search_clinic_info'} <= names


def test_system_prompt_has_safety_rules():
    assert 'Never guess or make them up' in SYSTEM_PROMPT
    assert 'confirm with the patient first' in SYSTEM_PROMPT
    assert 'Only claim an action succeeded if the tool result says so' in SYSTEM_PROMPT
    assert 'emergency services' in SYSTEM_PROMPT


def test_cancel_without_confirmation_is_rejected():
    settings = make_settings()
    service = AssistantService(Repository.seeded(), settings)
    result = service._execute_tool(type('Call', (), {'name': 'cancel_appointment', 'arguments': {'appointment_id': 'APT-FUTURE'}})(), 'PAT-001', [])
    assert result.status == 'failed'
    assert result.error_code == 'CONFIRMATION_REQUIRED'


def test_reschedule_without_confirmation_is_rejected():
    settings = make_settings()
    service = AssistantService(Repository.seeded(), settings)
    result = service._execute_tool(type('Call', (), {'name': 'reschedule_appointment', 'arguments': {'appointment_id': 'APT-FUTURE', 'slot_id': 'SLOT-GEN-02'}})(), 'PAT-001', [])
    assert result.status == 'failed'
    assert result.error_code == 'CONFIRMATION_REQUIRED'


def test_unknown_tool_is_rejected():
    service = AssistantService(Repository.seeded(), make_settings())
    result = service._execute_tool(type('Call', (), {'name': 'delete_all_patients', 'arguments': {}})(), 'PAT-001', [])
    assert result.status == 'failed'
    assert result.error_code == 'UNKNOWN_TOOL'


def test_list_my_appointments_scopes_to_patient():
    service = AssistantService(Repository.seeded(), make_settings())
    result = service._execute_tool(type('Call', (), {'name': 'list_my_appointments', 'arguments': {}})(), 'PAT-001', [])
    assert result.status == 'confirmed'
    ids = {item['appointment_id'] for item in result.data['appointments']}
    assert 'APT-FUTURE' in ids
    service_two = AssistantService(Repository.seeded(), make_settings())
    other = service_two._execute_tool(type('Call', (), {'name': 'list_my_appointments', 'arguments': {}})(), 'PAT-999', [])
    assert other.data['appointments'] == []


def test_cancel_with_confirmation_succeeds_for_future_appointment():
    settings = make_settings()
    service = AssistantService(Repository.seeded(), settings)
    result = service._execute_tool(type('Call', (), {'name': 'cancel_appointment', 'arguments': {'appointment_id': 'APT-FUTURE', 'confirmed': True}})(), 'PAT-001', [])
    assert result.status == 'confirmed'


def test_reschedule_rejects_cancelled_appointment():
    repo = Repository.seeded()
    settings = make_settings()
    tools = AppointmentTools(repo, settings)
    tools.cancel_appointment(CancellationRequest(appointment_id='APT-FUTURE', patient_reference='PAT-001', idempotency_key='cancel-1'))
    result = tools.reschedule_appointment(RescheduleRequest(appointment_id='APT-FUTURE', patient_reference='PAT-001', slot_id='SLOT-GEN-03', idempotency_key='resched-1'))
    assert result.status == 'failed'
    assert result.error_code == 'APPOINTMENT_NOT_FOUND'
