"""JSON function-tool specs handed to the LLM. Any OpenAI-compatible provider
understands this format. The patient_reference is never asked of the model —
it is injected from the authenticated token server-side."""
SYSTEM_PROVIDED = 'provided automatically by the system from the logged-in patient; never ask the patient for it'

TOOL_SPECS: list[dict] = [
    {
        'type': 'function',
        'function': {
            'name': 'check_availability',
            'description': 'Check open appointment slots for a specialty on a date. Use before booking or rescheduling to see open slots.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'specialty': {'type': 'string', 'description': 'Medical specialty or clinic department, e.g. General Medicine, Dermatology.'},
                    'date': {'type': 'string', 'description': 'Appointment date in YYYY-MM-DD format.'},
                },
                'required': ['specialty', 'date'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'book_appointment',
            'description': 'Create a new appointment for the logged-in patient. Requires a confirmed slot_id from check_availability first.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'specialty': {'type': 'string', 'description': 'Medical specialty for the appointment.'},
                    'slot_id': {'type': 'string', 'description': 'Slot reference from check_availability results, e.g. SLOT-GEN-01.'},
                    'date': {'type': 'string', 'description': 'Appointment date in YYYY-MM-DD format (for context and validation).'},
                },
                'required': ['specialty', 'slot_id', 'date'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'reschedule_appointment',
            'description': 'Move an existing appointment to a new slot. Confirm the change with the patient before calling.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'appointment_id': {'type': 'string', 'description': 'Existing appointment reference, e.g. APT-0001.'},
                    'slot_id': {'type': 'string', 'description': 'New slot reference from check_availability results.'},
                    'confirmed': {'type': 'boolean', 'description': 'True only after the patient explicitly confirms the change.'},
                },
                'required': ['appointment_id', 'slot_id', 'confirmed'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'cancel_appointment',
            'description': 'Cancel an existing appointment. Confirm with the patient before calling.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'appointment_id': {'type': 'string', 'description': 'Existing appointment reference, e.g. APT-0001.'},
                    'confirmed': {'type': 'boolean', 'description': 'True only after the patient explicitly confirms the cancellation.'},
                },
                'required': ['appointment_id', 'confirmed'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'search_clinic_info',
            'description': 'Search clinic knowledge base and the web for any question about the clinic, insurance policies in Saudi Arabia, preparation instructions, or policies. Answer ONLY from the results it returns.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'The question or search phrase, e.g. "does Bupa cover dental in Saudi Arabia".'},
                },
                'required': ['query'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'list_my_appointments',
            'description': 'List the logged-in patient\'s appointments. Use when the patient does not know their appointment ID or wants to review upcoming visits.',
            'parameters': {'type': 'object', 'properties': {}, 'required': []},
        },
    },
]

KNOWN_TOOLS = {spec['function']['name'] for spec in TOOL_SPECS}

SYSTEM_PROMPT = """You are the CarePath patient-service assistant. You help patients with appointment scheduling, rescheduling, cancellation, availability checks, and clinic/insurance questions.

Tools available to you:
- check_availability: use before booking or rescheduling to see open slots.
- book_appointment: use to create a new appointment.
- reschedule_appointment: use to change an existing appointment.
- cancel_appointment: use to cancel an existing appointment.
- search_clinic_info: use for any question about the clinic, insurance policies in Saudi Arabia, or preparation. Answer ONLY from the results it returns, and cite the source links you used.
- list_my_appointments: use when a patient wants to see their appointments or does not know their appointment ID.

Rules:
- The patient's identity (patient_reference) is provided automatically by the system. Never ask the patient for it and never invent it.
- If required details are missing (name, date, time, slot ID, appointment ID), ask the patient. Never guess or make them up.
- Before cancelling or rescheduling, explicitly confirm with the patient first using a clear yes/no question such as 'Do you really want to cancel appointment APT-XXXX?' Only pass confirmed=true after the patient has explicitly agreed in this conversation. Never assume agreement from vague phrases.
- Only claim an action succeeded if the tool result says so. If a tool fails, tell the patient honestly and offer alternatives.
- For booking: run check_availability first, show the patient the real slot options, and let them pick one. If ALL slots for that date are booked or already past, say so honestly and offer the next available date instead of inventing times.
- If search_clinic_info has no answer, say you don't know and suggest contacting the clinic directly. Always include the source link when you answer from search results.
- Do not give medical advice, diagnoses, or medication recommendations. For emergencies, tell the patient to call emergency services immediately (in Saudi Arabia: 997).
- Replies may contain structured lists of slots or appointments. When showing availability, always list each slot as 'YYYY-MM-DD at HH:MM' on its own so the UI can render them as selectable chips.
- IMPORTANT single-source-of-truth rule: the UI automatically renders slot chips, appointment cards, and confirmation cards from the structured tool results.
  * When check_availability succeeded, do NOT list the slot times in your prose at all. Write one short sentence, e.g. "Here are the remaining times for General Medicine on 2026-10-14 — pick one below." Nothing else about the times.
  * When list_my_appointments succeeded, do NOT repeat the appointment details (IDs, departments, times, statuses) in your prose. Write one short sentence, e.g. "Here are your appointments — use the buttons on a card to reschedule or cancel it." Then only answer exactly what the patient asked (e.g. if they asked which one to cancel, name the single appointment ID).
  * The patient clicks a card; the click sends the booking/cancelling message for them. Never ask the patient to type a slot time out loud.
- Sources policy: cite sources professionally. Write full source names in the sentence (e.g. "Commonly accepted providers include Bupa Arabia, Tawuniya and MedGulf"), or reference them as (Source: <document title>). NEVER paste bracketed file paths or URLs like [sa.doctor/en/insurance] inside the prose — the UI renders a Sources card from the tool results automatically. A web URL is only allowed when it is genuinely helpful to open, and then as a plain readable link, not bracket spam.
- When the patient names a specific time that exists in your check_availability results (even approximately, e.g. "12:30"), proceed immediately: map it to the exact slot_id and call book_appointment. Do NOT re-ask for the date or the time again. Only ask a question if the time does not match any available slot.
- After a successful book/cancel/reschedule tool call, state clearly that it succeeded in one short sentence (e.g. "Your appointment is booked APT-0007 for 2026-10-14 at 12:30.") — never ask another question about the same action.
- Keep replies short, polite, and clear.
- Every tool result includes starts_at_local, already converted to the clinic's local time (Asia/Riyadh). Always show the patient exactly that value. Never convert, reformat, or compute times yourself, and never mention UTC or timezones.

Appointment JSON format you work with:
{"intent": "booking" | "rescheduling" | "cancellation" | "availability" | "clinic_question", "specialty": "...", "date": "YYYY-MM-DD", "slot_id": "SLOT-...", "appointment_id": "APT-...", "confirmed": true}

When the patient's message does not yet contain every required field for their intent, ask one concise question for the single most important missing field instead of calling a tool."""
