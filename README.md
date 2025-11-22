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
- This prototype stores tokens in a local file for simplicity. In production, store encrypted tokens in a secure DB.
- Implement token refresh (exchange refresh_token for new access_token when expired).
- Add proper error handling and logging.
- When moving to production, request OAuth verification for Gmail scopes so non-test users can connect.