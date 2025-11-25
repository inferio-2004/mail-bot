# Mail-Bot — Inbox AI Assistant

A small prototype that augments Gmail with LLM-powered summaries, action extraction, and LLM-only inbox classification. Backend is Flask (Python); frontend is React + TypeScript.

**Status:** Working prototype — recent updates include stricter LLM-only classification, robust batch classification, improved summary parsing, UI tweaks, and customizable prompts.

**Key Features**
- **LLM-only Classification:** Inbox categories are produced by the server-side LLM. Frontend no longer uses client-side heuristics.
- **Batch Classification (normalized):** `/llm/classify-batch` returns a normalized mapping `{ message_id: { category, reason } }`. If the LLM does not return per-item results, the backend falls back to per-message classification to guarantee one category per message.
- **Summarization & Actions:** `/llm/summarize` returns `llm_text` and a `parsed` JSON object (summary, draft, etc.). `/llm/actions` extracts action items. Parsing is robust to markdown fences; the frontend falls back to `llm_text` when `parsed.summary` is missing.
- **Prompt Customization:** Users can view/save custom system prompts via `/prompts/*` endpoints. Custom prompts are stored per-user in the DB.
- **Frontend UX changes:**
   - The AI summary is shown in the Summary panel but is no longer auto-seeded into the chat.
   - The per-item classification badge was removed from the Summary panel (still shown in the Inbox list).
   - Actions card is vertically scrollable to avoid layout overflow.
- **Rate-limit Handling:** Backend detects LLM rate-limit errors and returns `429` when appropriate; frontend surfaces a friendly message.
- **Local caching:** Frontend uses `localStorage` to cache summaries, classifications and message bodies per user to reduce redundant LLM calls.

**Repository Layout**
- `backend/` — Flask app, LLM worker, DB models, API routes
   - `app.py` — Flask app entrypoint
   - `llm_worker.py` — LLM orchestration, batch classification, summarization logic
   - `routes/llm.py` — LLM endpoints (`/llm/summarize`, `/llm/classify-batch`, `/llm/classify`, `/llm/actions`, `/llm/draft`, `/llm/ask`, `/llm/enqueue`)
   - `routes/email.py` — Gmail list/message/draft helpers (`/email/read`, `/email/message`, `/email/draft`)
   - `routes/prompts.py` — prompt management endpoints (`/prompts/*`)
   - `models.py` — SQLAlchemy models for tokens and prompts
- `frontend/` — React + TypeScript UI
   - `src/App.tsx` — main app
   - `src/App.css` — styles (includes actions card scroll changes)

**Important Environment Variables**
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — OAuth client credentials
- `REDIRECT_URI` (optional) — OAuth redirect (default: `http://127.0.0.1:5000/oauth2callback`)
- `FRONTEND_ORIGIN` (optional) — origin allowed for CORS (default: `http://127.0.0.1:3000`)
- `FERNET_KEY` — required: symmetic key used to encrypt stored tokens in DB (must be 32 url-safe base64 bytes)
- `DATABASE_URL` — SQLAlchemy DB URL (default in code uses Postgres placeholder)
- `FLASK_SECRET` — Flask session secret

**Session & Persistent Login**
 The app uses standard Flask cookie sessions for SPA authentication. The backend sets `session.permanent = True` and `app.permanent_session_lifetime` to 30 days so the browser session cookie is long-lived and the user remains signed in across browser restarts.
 We do not persist session state to a filesystem or DB by default — the session cookie remains the primary mechanism. (During earlier experimentation a filesystem session store was briefly used; that has been removed in favor of the simpler cookie flow.)
 If you prefer server-side session storage for production (Redis, database), enable a secure session backend and configure `SESSION_COOKIE_SECURE=True` and an appropriate `SESSION_COOKIE_DOMAIN` in `app.py` for your deployment.

 The AI summary is shown in the Summary panel and now includes the LLM-provided **category badge and reason** displayed above the summary text.
 Saving a custom prompt now re-fetches the prompts from the server so the DB is the canonical source of truth (the Settings UI reflects saved values immediately).
 The per-item classification badge remains visible in the Inbox list.
```

**Run Locally (Windows PowerShell)**

1) Backend
```powershell
cd \path\to\mail-bot\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# set required env vars for this session (example):
$env:FERNET_KEY = "<FERNET_KEY>"
$env:GOOGLE_CLIENT_ID = "<CLIENT_ID>"
$env:GOOGLE_CLIENT_SECRET = "<CLIENT_SECRET>"
# optionally set DATABASE_URL and other vars
python app.py
```

2) Frontend
```powershell
cd \path\to\mail-bot\frontend
npm install
npm start   # or `npm run dev` depending on your project setup
```

Open your browser at `http://127.0.0.1:3000` and use **Connect Gmail** to authorize. Backend runs on port `5000` by default.

**Important API Endpoints**
- `GET /email/read` — returns recent messages for the connected user (used to build the inbox)
- `GET /email/message?message_id=...` — returns the full text body for a message
- `POST /llm/classify-batch` — batch classify an array of `{ id, subject }` into `{ id: {category, reason} }`
- `POST /llm/classify` — classify a single message (subject-only fast path)
- `POST /llm/summarize` — summarize a message (returns `llm_text` and `parsed` JSON)
- `POST /llm/actions` — extract action items from a message
- `POST /llm/draft` — generate a reply draft
- `POST /llm/ask` — ask an arbitrary question about a message
- `POST /prompts/save`, `GET /prompts/get/<type>`, `GET /prompts/get-all`, `POST /prompts/reset/<type>` — manage per-user prompts
- `POST /email/draft` — create Gmail draft via API
- `GET /user/session` — returns session user info (email/name/picture)

**Behavioral Notes / Design Decisions**
- Classification is strictly LLM-provided. Frontend will not attempt to infer categories locally.
- `classify-batch` returns a normalized mapping. If the LLM returns a single combined answer, the backend will attempt to coerce it into per-message entries and, failing that, will run per-item classification requests to ensure one category per message.
- Summaries prefer `parsed.summary` from the LLM; if missing, the backend/frontend will fall back to the first paragraph of `llm_text`.
- Chat messages are independent of the summary: the summary panel no longer seeds the chat automatically.
- Actions panel now scrolls vertically to avoid pushing layout.

**Troubleshooting**
- If you see all emails classified the same, inspect the response for `POST /llm/classify-batch` in DevTools → Network. The backend returns both `llm_text` and a `parsed` mapping — paste them here if you want help refining parsing.
- If you get `429` responses from LLM endpoints, the UI will show a rate-limit message. Reducing batch sizes or adding retries can help.

**Next Improvements (ideas)**
- Add stricter example-based prompts to force JSON output from the LLM.
- Add server-side retry/backoff for rate limits and parallelize safe per-item fallbacks.
- Add CI, tests, and deploy using a reverse proxy (Nginx) or Docker Compose for production.

---

If you want, I can also open a quick sample of responses from your current run and refine the prompts to make `classify-batch` even more deterministic.
# Inbox AI Assistant — Prototype (Flask + Simple Frontend)

## What this is
A minimal Flask prototype demonstrating:
- Sign in with Google (OAuth)
- Request Gmail scopes (read + compose)
- Exchange code for tokens and store them locally
- Create a Gmail draft in the user's Drafts folder via Gmail REST API

## Files
- `app.py` — Flask backend
- `templates/index.html` — simple frontend UI
- `templates/success.html` — post-OAuth landing page
- `requirements.txt` — python deps
- `data/tokens.json` — where tokens will be saved after OAuth

## Setup (local)
1. Create OAuth client in Google Cloud:
   - OAuth redirect URI must be `http://localhost:8080/oauth2callback`
   - Add your test users on the OAuth consent screen.

2. Set environment variables (Linux/macOS):
```bash
export GOOGLE_CLIENT_ID="YOUR_CLIENT_ID"
export GOOGLE_CLIENT_SECRET="YOUR_CLIENT_SECRET"
export GOOGLE_REDIRECT_URI="http://localhost:8080/oauth2callback"
export FLASK_SECRET="change-this-secret"
```

3. Install dependencies:
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

4. Run:
```bash
python app.py
```

5. In browser open `http://localhost:8080` and click **Connect Gmail**.
   - After consenting, you'll be redirected back to the app.
   - Tokens will be stored at `data/tokens.json`.

## OAuth URL (how it's constructed)
Google's OAuth URL (used by `/connect_gmail`) looks like:

```
https://accounts.google.com/o/oauth2/v2/auth?client_id=YOUR_CLIENT_ID&redirect_uri=YOUR_REDIRECT_URI&response_type=code&scope=openid%20email%20profile%20https://www.googleapis.com/auth/gmail.readonly%20https://www.googleapis.com/auth/gmail.compose&access_type=offline&prompt=consent
```

Replace `YOUR_CLIENT_ID` and `YOUR_REDIRECT_URI`.

## Notes & Next steps
- Implement token refresh (exchange refresh_token for new access_token when expired).
- Add proper error handling and logging.
- When moving to production, request OAuth verification for Gmail scopes so non-test users can connect.
