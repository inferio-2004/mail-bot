
import os
from flask import Blueprint, request, jsonify, session
from models import save_user_token

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.route("/store_tokens", methods=["POST"])
def store_tokens():
    data = request.get_json() or {}
    email = data.get("email")
    name = data.get("name")
    token_payload = data.get("token_payload")
    scopes = data.get("scopes")
    if not email or not token_payload:
        return jsonify({"error":"email and token_payload required"}), 400
    save_user_token(email=email, name=name, token_payload=token_payload, scopes=scopes)
    return jsonify({"status":"saved","email":email})


@auth_bp.route('/dev_login', methods=['POST'])
def dev_login():
    """Development-only login: set session and save a dummy token so app works without Google OAuth.
    Enabled only when environment variable ALLOW_DEV_LOGIN is set to a truthy value.
    """
    allow = os.environ.get('ALLOW_DEV_LOGIN', 'true').lower() in ('1', 'true', 'yes')
    if not allow:
        return jsonify({"error": "dev_login_disabled"}), 403
    data = request.get_json() or {}
    email = data.get('email')
    name = data.get('name', '')
    if not email:
        return jsonify({"error": "email required"}), 400
    # create a minimal dummy token payload so other code that expects tokens doesn't error
    dummy_payload = {
        "access_token": "dev-access-token",
        "refresh_token": "dev-refresh-token",
        "obtained_at": datetime.datetime.utcnow().isoformat(),
        "expires_in": 3600,
        "scope": "openid email profile https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose"
    }
    try:
        save_user_token(email=email, name=name, token_payload=dummy_payload, scopes=dummy_payload.get('scope'))
    except Exception:
        # ignore save failures for dev-only flow
        pass
    session['user_email'] = email
    return jsonify({"status": "dev_logged_in", "email": email})
