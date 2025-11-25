from flask import Blueprint, request, jsonify, session, current_app
from models import get_user_token, refresh_access_token
import requests, base64
from email.mime.text import MIMEText
import datetime
import logging

logger = logging.getLogger(__name__)
email_bp = Blueprint("email", __name__, url_prefix="/email")

def ensure_access_token(email):
    """
    Returns (access_token, None) on success, or (None, error_code) on failure.
    Error codes: no_email, no_tokens, refresh_failed, no_access_token
    """
    if not email:
        return None, "no_email"

    rec = get_user_token(email)
    if not rec:
        return None, "no_tokens"

    payload = rec.get("payload", {}) or {}
    access_token = payload.get("access_token")
    obtained = payload.get("obtained_at")
    try:
        expires_in = int(payload.get("expires_in", 3600))
    except Exception:
        expires_in = 3600

    # If we have a timestamp, try to parse safely and refresh if required.
    if obtained:
        try:
            # try ISO format first, fallback to epoch seconds
            try:
                obtained_dt = datetime.datetime.fromisoformat(obtained)
            except Exception:
                obtained_dt = datetime.datetime.utcfromtimestamp(float(obtained))

            # normalize to naive UTC for comparison
            if obtained_dt.tzinfo is not None:
                obtained_dt = obtained_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)

            # refresh if token will expire within 60s
            if datetime.datetime.utcnow() > (obtained_dt + datetime.timedelta(seconds=expires_in - 60)):
                logger.info("Access token for %s is expired/near-expiry, refreshing", email)
                new = refresh_access_token(email)
                if not new or not isinstance(new, dict):
                    logger.error("refresh_access_token failed for %s: %s", email, new)
                    return None, "refresh_failed"
                # expect the refresh function to return at least access_token (and ideally new payload)
                access_token = new.get("access_token") or access_token
        except Exception as e:
            logger.exception("Error while checking/refreshing token for %s: %s", email, e)
            # If parsing failed, we'll validate below whether we have a usable token.

    if not access_token:
        logger.warning("No access_token available for %s after checks", email)
        return None, "no_access_token"

    return access_token, None

@email_bp.route("/read", methods=["GET"])
def read_mail():
    # debug-first: show session and args in logs to diagnose missing session/email issues
    logger.debug("read_mail called. session keys: %s args: %s", list(session.keys()), request.args.to_dict())

    user_email = request.args.get("email") or session.get("user_email")
    if not user_email:
        logger.warning("read_mail: missing user_email. session=%s args=%s", dict(session), request.args.to_dict())
        return jsonify({"error":"user_email required", "session": dict(session), "args": request.args.to_dict()}), 400

    q = request.args.get("q", "in:inbox")
    try:
        max_results = int(request.args.get("max", 10))
    except Exception:
        max_results = 10

    access_token, err = ensure_access_token(user_email)
    if err:
        logger.warning("ensure_access_token failed for %s: %s", user_email, err)
        return jsonify({"error": err}), 400

    resp = requests.get("https://gmail.googleapis.com/gmail/v1/users/me/messages",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={"q": q, "maxResults": max_results}, timeout=15)
    if resp.status_code != 200:
        logger.error("Gmail list API failed for %s: %s %s", user_email, resp.status_code, resp.text)
        return jsonify({"error":"gmail_list_failed","detail":resp.text}), resp.status_code
    msgs = resp.json().get("messages", [])
    out = []
    for m in msgs:
        mid = m.get("id")
        if not mid:
            continue
        r2 = requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                          headers={"Authorization": f"Bearer {access_token}"},
                          params={"format":"full"}, timeout=15)
        if r2.status_code != 200:
            logger.warning("Failed to fetch message %s for %s: %s", mid, user_email, r2.text)
            continue
        data = r2.json()
        snippet = data.get("snippet")
        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
        out.append({"id": mid, "snippet": snippet, "headers": headers})
    return jsonify({"messages": out})


@email_bp.route('/message', methods=['GET'])
def get_message_body():
    """Return the full text body for a given message_id."""
    user_email = request.args.get('email') or session.get('user_email')
    message_id = request.args.get('message_id')
    if not user_email:
        return jsonify({'error':'user_email required'}), 400
    if not message_id:
        return jsonify({'error':'message_id required'}), 400

    access_token, err = ensure_access_token(user_email)
    if err:
        return jsonify({'error': err}), 400

    try:
        r2 = requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                          headers={"Authorization": f"Bearer {access_token}"},
                          params={"format":"full"}, timeout=15)
        if r2.status_code != 200:
            return jsonify({'error':'fetch_failed','detail': r2.text}), r2.status_code
        data = r2.json()
        # extract body similarly to llm_worker
        def walk_parts(payload):
            if not payload:
                return None
            if payload.get('mimeType') == 'text/plain' and payload.get('body', {}).get('data'):
                return payload['body']['data']
            if payload.get('mimeType') == 'text/html' and payload.get('body', {}).get('data'):
                return payload['body']['data']
            for part in payload.get('parts', []) or []:
                res = walk_parts(part)
                if res:
                    return res
            return None

        body_b64 = walk_parts(data.get('payload'))
        if not body_b64:
            return jsonify({'body': data.get('snippet','')})
        text = base64.urlsafe_b64decode(body_b64 + '==').decode('utf-8', errors='ignore')
        # strip html if present
        if '<html' in text.lower() or '<body' in text.lower() or '<head' in text.lower():
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(text, 'html.parser')
                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()
                # Get text
                text = soup.get_text(separator='\n')
                # Clean up excessive newlines
                lines = [line.strip() for line in text.splitlines()]
                text = '\n'.join(line for line in lines if line)
            except Exception:
                pass
        return jsonify({'body': text})
    except Exception as e:
        current_app.logger.exception('Failed to fetch message body %s: %s', message_id, e)
        return jsonify({'error':'exception','detail': str(e)}), 500

def create_gmail_draft_raw(access_token, to_email, subject, body_text):
    if not access_token:
        raise ValueError("access_token required to create draft")
    message = MIMEText(body_text)
    message["to"] = to_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    payload = {"message": {"raw": raw}}
    resp = requests.post("https://gmail.googleapis.com/gmail/v1/users/me/drafts",
                         headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                         json=payload, timeout=15)
    return resp

@email_bp.route("/draft", methods=["POST"])
def create_draft():
    data = request.get_json() or {}
    user_email = data.get("email") or session.get("user_email")
    to = data.get("to")
    subject = data.get("subject", "Draft from Agent")
    body = data.get("body", "Hello from the AI agent")
    if not user_email:
        logger.warning("create_draft: missing user_email. session=%s body_args=%s", dict(session), data)
        return jsonify({"error":"user_email required"}), 400

    access_token, err = ensure_access_token(user_email)
    if err:
        logger.warning("ensure_access_token failed for %s: %s", user_email, err)
        return jsonify({"error":err}), 400

    # default to sending to self if `to` not provided
    to_addr = to or user_email
    try:
        resp = create_gmail_draft_raw(access_token, to_addr, subject, body)
    except ValueError as ve:
        logger.exception("create_gmail_draft_raw missing token for %s: %s", user_email, ve)
        return jsonify({"error":"no_access_token"}), 400
    except Exception as e:
        logger.exception("Unexpected error while creating draft for %s: %s", user_email, e)
        return jsonify({"error":"draft_failed","detail": str(e)}), 500

    if resp.status_code not in (200,201):
        logger.error("Draft creation failed for %s: %s %s", user_email, resp.status_code, resp.text)
        return jsonify({"error":"draft_failed","detail":resp.text}), resp.status_code
    return jsonify({"status":"draft_created","resp": resp.json()})
