# CarePath — AI patient services

CarePath is an **AI** patient-facing website and assistant for everyday clinic operations. It is built as a demonstration for Apex AI Arabia: a signed-in patient talks to an **LLM** (large language model) agent that books, reschedules, and cancels appointments, answers clinic and insurance questions with **RAG** (retrieval-augmented generation) from trusted sources, and never claims a change succeeded unless the appointment system confirmed it.

This is not a live hospital information system. Data is synthetic, identity checks are those of a demo login, and medical advice is out of scope. Emergencies should go to local emergency services (in Saudi Arabia: 997).

## What the website does

After sign-in, patients use a workspace with these pages:

| Page | What you can do |
|---|---|
| **Home** | Overview of patient services and how to start a conversation or open appointments. |
| **Assistant** | Chat with the AI agent: check availability, book a slot, reschedule or cancel (after explicit confirmation), list your visits, or ask about clinic policy and Saudi insurance. The LLM calls tools; RAG supplies sourced answers. Slot times appear as clickable chips; appointments appear as cards with actions. |
| **My appointments** | Live list of visits for the signed-in account only. Changes are made through the assistant. |
| **Knowledge base** | Approved guidance documents indexed for RAG (embeddings in a local Chroma vector store), with links to official public sources where available. |
| **Evaluation** | Demo view of quality scenarios used to exercise safe assistant behaviour. |

Accounts are created on the sign-in screen. Each patient only sees their own appointments and chat history. Chat can be cleared without deleting bookings. Times are shown in the clinic timezone (Asia/Riyadh).

The assistant is an **LLM tool-calling agent**, not a free-form chatbot. The model decides which tools to run (availability, booking, RAG search, web search when configured). It must confirm before cancel or reschedule. Cancellations inside a 24-hour window can require approval instead of taking effect immediately. It does not diagnose, prescribe, or guess missing dates or slot IDs.

## How the AI works

| Piece | Role |
|---|---|
| **LLM** | Reads the patient message and conversation, chooses tools, and writes the reply. Any OpenAI-compatible chat API can be configured (Gemini is the example). |
| **Tools** | Deterministic appointment actions plus `search_clinic_info`. The LLM cannot invent a booking; it must call the tool and only then report success. |
| **RAG** | Clinic and insurance questions are answered from retrieved chunks, not from the model’s memory alone. If retrieval is weak, the assistant should abstain rather than guess. |
| **Embeddings + Chroma** | Approved documents are turned into vectors and stored locally. Ingest with `python -m app.ingest_kb` after the database is seeded. |
| **Optional web search** | Serper can supplement RAG when a question needs current public information. |

The website never talks to the LLM directly. The FastAPI backend runs the agent loop, RAG lookup, and appointment tools.

## Purpose

- Give patients a single place to manage visits and get **AI**-sourced answers about clinic and insurance topics relevant to Saudi care.
- Show an **LLM** agent with gated tools: validation, confirmation, honest failure messages, and human escalation when needed.
- Show **RAG**: grounded retrieval from a knowledge base (Chroma embeddings) instead of uncited model text.
- Keep a clear split between the website (React), the API (FastAPI), hosted data (Supabase), the LLM provider, and the local RAG index.

Longer notes on architecture, limitations, and assessment write-ups live in `docs/`. Do not treat those files as a substitute for this README when running the app.

## Repository layout

```
backend/     API, LLM agent, RAG ingest, tests
frontend/    React (Vite) patient website
supabase/    Database setup and seed scripts (run in the Supabase SQL editor)
docs/        Assessment and design notes
```

Do not commit `.env` files. Copy the example templates only.

## What you need

- Python 3.11+
- Node.js 18+ (npm)
- A [Supabase](https://supabase.com) project
- An OpenAI-compatible LLM and embeddings provider (the example env is Gemini; other compatible hosts work)
- Optional: a Serper API key if you want live web search for clinic questions
- Optional: Docker, if you want to run the API as an image

## Run locally

### 1. Database

In the Supabase SQL editor, run the scripts in `supabase/` in this order:

1. `schema.sql` — empty project
2. `seed.sql`
3. `seed_saudi_knowledge.sql`
4. `slot_generation.sql` (if you want generated appointment slots)

If this project was already applied once and you only need account/chat updates, use `auth_migration.sql` and `add_chat_history.sql` instead of replaying the full schema. If an older scaffold is already on the project, run `migrate_existing.sql` **before** seeding.

Do not paste database passwords, service keys, or table definitions into this README or into git. Use the values from your own Supabase project dashboard.

### 2. Backend environment

```powershell
cd backend
copy .env.example .env
```

On macOS/Linux: `cp .env.example .env`.

Edit `.env` and replace every `replace-me` value. At minimum you need:

- Supabase project URL and service role key (server-side only)
- LLM API key, base URL, and model names
- Embedding base URL and model (RAG will not work without this)
- `AUTH_SECRET` (a long random string you generate)
- `ADMIN_API_KEY` (a secret you generate; not a login password)
- `CORS_ORIGINS=http://localhost:5173` for local Vite

Leave `EMBEDDING_API_KEY` blank to reuse the LLM key when both use the same provider. Raise `LLM_TIMEOUT_SECONDS` (for example `30`) if the model is slow; one patient message can trigger several tool calls.

The full variable list is in `backend/.env.example`. Put secrets only in your local `.env`, never in git. Typical Gemini settings:

- `LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`
- `LLM_MODEL_PRIMARY=gemini-2.5-flash`
- `EMBEDDING_MODEL=text-embedding-004`

Other OpenAI-compatible hosts (OpenRouter, Groq, local Ollama, xAI) work by changing `LLM_BASE_URL`, model ids, and keys only. Keep embeddings on a model that matches the index you already built; changing the embedding model requires re-ingest.

### 3. Install and start the API

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.ingest_kb
uvicorn app.main:app --reload
```

On macOS/Linux activate with `source .venv/bin/activate`.

`ingest_kb` builds the RAG index: it embeds approved knowledge into the local Chroma store. Re-run it after you change seed content or the embedding model. Without ingest, the LLM can still call appointment tools, but clinic/insurance RAG will be empty. The API is at `http://localhost:8000`. `GET /health` should return ok. Optional: `GET /health/llm` checks the configured LLM.

### 4. Frontend

```powershell
cd frontend
copy .env.example .env
npm install
npm run dev
```

On macOS/Linux: `cp .env.example .env`.

`frontend/.env.example` only has public Vite values, for example:

```
VITE_API_BASE_URL=http://localhost:8000
VITE_CLINIC_TIMEZONE=Asia/Riyadh
```

Open the URL Vite prints (usually `http://localhost:5173`). Create an account, then use Assistant and My appointments.

### 5. Tests and evaluation (optional)

From `backend` with the virtualenv active:

```powershell
pytest
python -m app.evals.run
```

Offline tests do not need a live LLM. The evaluation runner does talk to the configured model when you run it.

## Docker (API only)

The image in `backend/Dockerfile` is the API. It does not include Supabase, the website, or an LLM.

From the repository root:

```powershell
docker build -f backend/Dockerfile .
```

Pass the same environment variables at runtime that you use in `backend/.env`. Point `CORS_ORIGINS` at the website origin.

## Deploy (high level)

A typical split is the API on Render and the website on Vercel. After Vercel assigns a domain, add that origin to the API `CORS_ORIGINS`. Only `VITE_` variables belong in the frontend; they are public. Keep Supabase service keys, LLM keys, `AUTH_SECRET`, and the admin key on the server.

## What this is not

- Not a production hospital scheduler or identity provider
- Not a substitute for licensed medical or PDPL/healthcare legal review
- Not a guarantee of perfect answers; models can be wrong, and connected systems can fail

Reliability in this demo comes from RAG (sourced retrieval), an LLM that must use tools instead of inventing outcomes, confirmation before destructive actions, and telling the patient when a tool or the AI service failed.
