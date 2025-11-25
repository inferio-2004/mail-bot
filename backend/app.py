
import os
import json
import datetime
from urllib.parse import urlencode
from flask import Flask, request, redirect, session, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from llm_gemini import GeminiLLM
from models import save_user_token, get_user_token, refresh_access_token, init_db
from routes.auth import auth_bp
from routes.email import email_bp
from routes.llm import llm_bp
from routes.prompts import prompts_bp
from llm_worker import llm_worker_run
dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env")
# Load environment
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/oauth2callback")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://127.0.0.1:3000")

# Flask app
CORS(app, origins=FRONTEND_ORIGIN, supports_credentials=True)
# Flask app
app = Flask(__name__)
# make cookies usable during local dev OAuth redirect
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",   # allows top-level GET redirect cookies during OAuth
    SESSION_COOKIE_SECURE=False,     # must be False for http://localhost (True requires https)
    SESSION_COOKIE_DOMAIN=None       # let browser use default domain (localhost)
)
CORS(app, origins=FRONTEND_ORIGIN, supports_credentials=True)
# Make Flask sessions persistent across browser restarts for development
import datetime as _dt
app.permanent_session_lifetime = _dt.timedelta(days=30)

# Rate limiter (simple)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per minute"]
)

# Initialize DB (creates tables)
init_db()

# Initialize LLM and attach to app.config (LangChain wrapper)
app.config["LLM"] = GeminiLLM(model_name=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"))

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(email_bp)
app.register_blueprint(llm_bp)
app.register_blueprint(prompts_bp)

@app.route("/")
def health():
    return jsonify({"status":"ok","time": datetime.datetime.utcnow().isoformat()})

@app.route("/user/session")
def get_user_session():
    """Return current user session info from session cookie"""
    user_email = session.get("user_email")
    user_name = session.get("user_name")
    user_picture = session.get("user_picture")
    print(f"[DEBUG] /user/session called: user_email={user_email}, session.keys={list(session.keys())}")
    if not user_email:
        return jsonify({"error": "not_authenticated"}), 401
    return jsonify({
        "email": user_email,
        "name": user_name,
        "picture": user_picture
    })

@app.route("/auth/logout", methods=["POST"])
def logout():
    """Clear user session"""
    session.clear()
    return jsonify({"status": "logged_out"})

@app.route("/connect_gmail")
def connect_gmail():
    SCOPES = [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose"
    ]
    auth_base = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent"
    }
    return redirect(auth_base + "?" + urlencode(params))

@app.route("/oauth2callback")
def oauth2callback():
    # Exchange code for tokens; save to DB and create a session for SPA (cookie)
    code = request.args.get("code")
    if not code:
        return jsonify({"error":"missing_code"}), 400
    token_url = "https://oauth2.googleapis.com/token"
    import requests
    payload = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    r = requests.post(token_url, data=payload, timeout=15)
    if r.status_code != 200:
        return jsonify({"error":"token_exchange_failed","detail": r.text}), 400
    token_data = r.json()
    access_token = token_data.get("access_token")
    # fetch userinfo
    uresp = requests.get("https://www.googleapis.com/oauth2/v3/userinfo",
                         headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    if uresp.status_code != 200:
        return jsonify({"error":"userinfo_failed","detail": uresp.text}), 400
    print(uresp.text)
    userinfo = uresp.json()
    email = userinfo.get("email")
    name = userinfo.get("name") or userinfo.get("given_name")
    picture = userinfo.get("picture")  # Google profile picture URL
    # Save tokens securely
    save_user_token(email=email, name=name, token_payload=token_data, scopes=token_data.get("scope"))
    # create session cookie for SPA
    session["user_email"] = email
    session["user_name"] = name
    session["user_picture"] = picture
    # Make the session persistent so user remains logged in across browser restarts
    session.permanent = True
    app.logger.info("set session user_email=%s, session keys=%s", email, list(session.keys()))
    # Redirect back to frontend (SPA) with success flag
    frontend_url = os.environ.get("FRONTEND_AFTER_AUTH", FRONTEND_ORIGIN + "/?connected=1")
    return redirect(frontend_url)

# Route to enqueue LLM job quickly from frontend
@app.route("/llm/enqueue", methods=["POST"])
@limiter.limit("10 per minute")
def enqueue():
    data = request.get_json() or {}
    email = data.get("email") or session.get("user_email")
    task_type = data.get("task_type")  # e.g., "summarize", "draft"
    payload = data.get("payload") or {}
    if not email or not task_type:
        return jsonify({"error":"email and task_type required"}), 400
    # Call LLM worker directly (synchronous for now)
    result = llm_worker_run(email, task_type, payload)
    return jsonify(result)

# Job status endpoint removed - using synchronous LLM calls for now

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
