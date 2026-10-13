from datetime import date
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field

class AssistantRequest(BaseModel):
    session_id: UUID | None = None
    message: str = Field(min_length=1, max_length=2000)
    patient_reference: str | None = Field(default=None, max_length=80)

class ToolCall(BaseModel):
    name: str
    status: Literal['confirmed','failed','timeout']
    error_code: str | None = None

class Source(BaseModel):
    source: str
    title: str
    version: str

class AssistantResponse(BaseModel):
    session_id: UUID
    reply: str
    intent: str
    status: Literal['completed','needs_clarification','escalated','pending_approval','refused','failed']
    tool_calls: list[ToolCall] = []
    sources: list[Source] = []
    requires_human: bool = False
    confidence: float | None = None
    request_id: UUID
    llm_used: bool = False
    llm_status: Literal['used','not_configured','failed','not_needed'] = 'not_needed'
    llm_error: str | None = None
    # Structured, machine-readable outcome of the last turn so the UI renders
    # chips/cards from real data instead of guessing from reply text.
    # shape: {"kind": "slots"|"appointments"|"confirmation"|"error"|"none",
    #         "specialty": str|None, "date": str|None,
    #         "slots": [{slot_id, starts_at_local, starts_at}],
    #         "appointments": [{appointment_id, specialty, starts_at_local, status}],
    #         "outcome": str|None, "appointment_id": str|None}
    structured: dict[str, Any] = {}

class CostRequest(BaseModel):
    interactions: int = Field(default=100000, ge=1)
    input_tokens: int = Field(default=700, ge=1)
    output_tokens: int = Field(default=250, ge=1)
    retry_rate: float = Field(default=0.05, ge=0, le=1)

class CostEstimate(BaseModel):
    model: str
    provider: str
    monthly_cost: float
    assumed_latency_ms: int
    assumptions: dict[str, Any]

class AvailabilityRequest(BaseModel):
    specialty: str = Field(min_length=2, max_length=80)
    date: date

class AppointmentLookupRequest(BaseModel):
    appointment_id: str = Field(pattern=r'^APT-[A-Z0-9-]{3,40}$')
    patient_reference: str = Field(pattern=r'^PAT-[A-Z0-9-]{3,40}$')

class BookingRequest(BaseModel):
    patient_reference: str = Field(pattern=r'^PAT-[A-Z0-9-]{3,40}$')
    specialty: str = Field(min_length=2, max_length=80)
    slot_id: str = Field(pattern=r'^SLOT-[A-Z0-9-]{3,40}$')
    idempotency_key: str = Field(min_length=8, max_length=120)

class RescheduleRequest(BaseModel):
    appointment_id: str = Field(pattern=r'^APT-[A-Z0-9-]{3,40}$')
    patient_reference: str = Field(pattern=r'^PAT-[A-Z0-9-]{3,40}$')
    slot_id: str = Field(pattern=r'^SLOT-[A-Z0-9-]{3,40}$')
    idempotency_key: str = Field(min_length=8, max_length=120)

class CancellationRequest(BaseModel):
    appointment_id: str = Field(pattern=r'^APT-[A-Z0-9-]{3,40}$')
    patient_reference: str = Field(pattern=r'^PAT-[A-Z0-9-]{3,40}$')
    idempotency_key: str = Field(min_length=8, max_length=120)

class EscalationRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    session_id: UUID | None = None
    appointment_id: str | None = None

class ToolResult(BaseModel):
    status: Literal['confirmed', 'failed', 'timeout']
    tool_name: str
    data: dict[str, Any] = {}
    error_code: str | None = None
    message: str | None = None

class SignupRequest(BaseModel):
    email: str = Field(pattern=r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)

class LoginRequest(BaseModel):
    email: str = Field(pattern=r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', max_length=254)
    password: str = Field(min_length=1, max_length=128)

class AuthResponse(BaseModel):
    token: str
    patient: 'PatientProfile'

class PatientProfile(BaseModel):
    patient_reference: str
    email: str
    display_name: str | None = None

AuthResponse.model_rebuild()
