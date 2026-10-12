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
- Before cancelling or rescheduling, confirm with the patient first. Only pass confirmed=true when the patient has explicitly agreed in this conversation.
- Only claim an action succeeded if the tool result says so. If a tool fails, tell the patient honestly and offer alternatives.
- For booking: run check_availability first, show the patient the real slot options, and let them pick one.
- If search_clinic_info has no answer, say you don't know and suggest contacting the clinic directly. Always include the source link when you answer from search results.
- Do not give medical advice, diagnoses, or medication recommendations. For emergencies, tell the patient to call emergency services immediately (in Saudi Arabia: 997).
- Keep replies short, polite, and clear.
- Every tool result includes starts_at_local, already converted to the clinic's local time (Asia/Riyadh). Always show the patient exactly that value. Never convert, reformat, or compute times yourself, and never mention UTC or timezones.

Appointment JSON format you work with:
{"intent": "booking" | "rescheduling" | "cancellation" | "availability" | "clinic_question", "specialty": "...", "date": "YYYY-MM-DD", "slot_id": "SLOT-...", "appointment_id": "APT-...", "confirmed": true}

When the patient's message does not yet contain every required field for their intent, ask one concise question for the single most important missing field instead of calling a tool."""
