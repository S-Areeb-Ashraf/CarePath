import secrets
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .supabase_repository import SupabaseRepository
from .schemas import (
    AppointmentLookupRequest,
    AssistantRequest,
    AssistantResponse,
    AuthResponse,
    AvailabilityRequest,
    BookingRequest,
    CancellationRequest,
    EscalationRequest,
    LoginRequest,
    PatientProfile,
    RescheduleRequest,
    SignupRequest,
    ToolResult,
)
from .services import AssistantService
from .session_store import ChatHistoryStore
from .tools import AppointmentTools
from .llm import LLMClient
from . import auth as auth_utils

settings = get_settings()
repo = SupabaseRepository(settings)
tools = AppointmentTools(repo, settings)
service = AssistantService(repo, settings)
app = FastAPI(title='CarePath Patient Assistant API', version='3.0.0', description='Authenticated patient service with an LLM tool-calling agent, ChromaDB RAG, and Serper web search.')
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=['GET','POST'], allow_headers=['*'])


def admin_guard(x_admin_key: str | None = Header(default=None)) -> None:
    if not x_admin_key or not secrets.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail='Admin key required')


def auth_secret() -> str:
    try:
        return settings.require_auth_secret()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def current_patient(authorization: str | None = Header(default=None)) -> PatientProfile:
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail='Missing bearer token')
    token = authorization.split(' ', 1)[1].strip()
    try:
        payload = auth_utils.verify_token(token, auth_secret())
    except auth_utils.TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    patient = repo.get_patient_by_reference(payload['patient_reference'])
    if not patient:
        raise HTTPException(status_code=401, detail='Patient account no longer exists')
    return PatientProfile(patient_reference=patient['patient_reference'], email=patient.get('email') or '', display_name=patient.get('display_name'))


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok', 'environment': settings.app_env}


@app.get('/health/llm')
def llm_health() -> dict[str, object]:
    return LLMClient(settings).check_connection()


@app.post('/auth/signup', response_model=AuthResponse)
def signup(request: SignupRequest) -> AuthResponse:
    secret = auth_secret()
    if repo.get_patient_by_email(request.email):
        raise HTTPException(status_code=409, detail='An account with this email already exists')
    existing = repo.client.table('patients').select('patient_reference').order('patient_reference', desc=True).limit(1).execute().data or []
    last = existing[0]['patient_reference'] if existing else 'PAT-000'
    try:
        next_number = int(last.split('-')[1]) + 1
    except (IndexError, ValueError):
        next_number = len(existing) + 1
    patient_reference = f'PAT-{next_number:03d}'
    patient = repo.create_patient_with_credentials(patient_reference, request.email, auth_utils.hash_password(request.password), request.display_name)
    token = auth_utils.create_token(patient['patient_reference'], request.email, secret, settings.auth_token_ttl_hours)
    return AuthResponse(token=token, patient=PatientProfile(patient_reference=patient['patient_reference'], email=request.email, display_name=request.display_name))


@app.post('/auth/login', response_model=AuthResponse)
def login(request: LoginRequest) -> AuthResponse:
    secret = auth_secret()
    patient = repo.get_patient_by_email(request.email)
    stored = (patient or {}).get('password_hash')
    if not patient or not stored or not auth_utils.verify_password(request.password, stored):
        raise HTTPException(status_code=401, detail='Invalid email or password')
    token = auth_utils.create_token(patient['patient_reference'], patient['email'], secret, settings.auth_token_ttl_hours)
    return AuthResponse(token=token, patient=PatientProfile(patient_reference=patient['patient_reference'], email=patient['email'], display_name=patient.get('display_name')))


@app.get('/auth/me', response_model=PatientProfile)
def me(patient: PatientProfile = Depends(current_patient)) -> PatientProfile:
    return patient


@app.post('/assistant/message', response_model=AssistantResponse)
def assistant_message(request: AssistantRequest, patient: PatientProfile = Depends(current_patient)) -> AssistantResponse:
    return service.handle(request, patient.patient_reference)


@app.post('/tools/check-availability', response_model=ToolResult)
def check_availability(request: AvailabilityRequest) -> ToolResult:
    return tools.check_availability(request)


@app.post('/tools/book-appointment', response_model=ToolResult)
def book_appointment(request: BookingRequest) -> ToolResult:
    return tools.book_appointment(request)


@app.post('/tools/reschedule-appointment', response_model=ToolResult)
def reschedule_appointment(request: RescheduleRequest) -> ToolResult:
    return tools.reschedule_appointment(request)


@app.post('/tools/cancel-appointment', response_model=ToolResult)
def cancel_appointment(request: CancellationRequest) -> ToolResult:
    return tools.cancel_appointment(request)


@app.post('/chat/clear', response_model=dict)
def clear_chat(patient: PatientProfile = Depends(current_patient)) -> dict:
    """Clear ONLY this patient's chat history. Appointments and slots are untouched."""
    ChatHistoryStore(settings).clear(patient.patient_reference)
    return {'cleared': True}


@app.get('/chat/history')
def chat_history(patient: PatientProfile = Depends(current_patient)) -> dict:
    """Restore the patient's saved chat so it survives sign-out / sign-in."""
    messages = ChatHistoryStore(settings).get(patient.patient_reference)
    return {'messages': messages}


@app.post('/tools/lookup-appointment', response_model=ToolResult)
def lookup_appointment(request: AppointmentLookupRequest) -> ToolResult:
    return tools.lookup_appointment(request)


@app.post('/tools/escalate-to-human', response_model=ToolResult)
def escalate_to_human(request: EscalationRequest) -> ToolResult:
    return tools.escalate_to_human(request)


@app.get('/content/overview')
def overview() -> dict:
    return {'sections': repo.list_sections('home_')}


@app.get('/content/knowledge')
def knowledge() -> dict:
    # Verified official Saudi links, matched by source slug so each card in the
    # Knowledge base page can link to the authority page it came from.
    verified_links = {
        'saudi/chi-insured-rights': 'https://www.chi.gov.sa/en/beneficiary/Resolutions%20and%20Circulars/Health%20Insurance%20beneficiaries%27%20right.pdf',
        'saudi/chi-benefit-package': 'https://www.chi.gov.sa/en/beneficiary/healthinsurancepolicy/Updated%20Essential%20Benefit%20Package%20%20(%20effective%201%20October%202022).pdf',
        'saudi/chi-emergency-insurance': 'https://www.chi.gov.sa/en/beneficiary/healthinsurancepolicy/Updated%20Essential%20Benefit%20Package%20%20(%20effective%201%20October%202022).pdf',
        'saudi/moh-patient-safety': 'https://www.moh.gov.sa/en/HealthAwareness/EducationalContent/HealthTips/Documents/Patient-Bill-of-Rights-and-Responsibilities.pdf',
        'saudi/moh-imaging-fasting': 'https://www.moh.gov.sa/en/Ministry/MediaCenter/Publications/Documents/Protocols-of-CM.pdf',
        'saudi/moh-sehhaty-appointments': 'https://www.moh.gov.sa/en/eservices/sehhaty/pages/appointment-booking-on-sehhaty.aspx',
        'policy/cancellation': 'https://www.moh.gov.sa/en/HealthAwareness/EducationalContent/HealthTips/Pages/default.aspx',
        'insurance/faq': 'https://www.chi.gov.sa/en/Pages/default.aspx',
        'prep/general': 'https://www.moh.gov.sa/en/eservices/pages/personal.aspx',
    }
    documents = repo.client.table('kb_documents').select('id,source,title,version,effective_date,requires_validation').order('title').execute().data or []
    return {'documents': [
        {**document, 'official_url': verified_links.get(document.get('source', ''))}
        for document in documents
    ]}


@app.get('/submission')
def submission() -> dict:
    return {'sections': repo.list_sections()}


@app.get('/eval/cases')
def eval_cases() -> dict:
    return {'cases': repo.list_eval_cases()}


@app.get('/patient/{patient_reference}/appointments')
def patient_appointments(patient_reference: str, patient: PatientProfile = Depends(current_patient)) -> dict:
    if patient_reference != patient.patient_reference:
        raise HTTPException(status_code=403, detail='You can only view your own appointments')
    from .timefmt import to_local_iso
    return {'appointments': [
        {'id': appointment.id, 'patient_reference': appointment.patient_reference, 'specialty': appointment.specialty,
         'slot_id': appointment.slot_id, 'status': appointment.status,
         'starts_at': to_local_iso(settings, appointment.starts_at)}
        for appointment in repo.list_appointments(patient_reference)
    ]}


@app.get('/ops/appointments', dependencies=[Depends(admin_guard)])
def appointments() -> dict:
    from .timefmt import to_local_iso
    return {'appointments': [
        {**appointment.__dict__, 'starts_at': to_local_iso(settings, appointment.starts_at)}
        for appointment in repo.list_appointments()
    ]}


@app.get('/ops/escalations', dependencies=[Depends(admin_guard)])
def escalations() -> dict:
    return {'escalations': repo.list_escalations()}
