
from models import get_user_token, refresh_access_token
import requests, base64, json
from bs4 import BeautifulSoup

def _get_message_text(access_token, message_id):
    r = requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                     headers={"Authorization": f"Bearer {access_token}"}, params={"format":"full"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    def walk_parts(payload):
        if not payload:
            return None
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return payload["body"]["data"]
        if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
            return payload["body"]["data"]
        for part in payload.get("parts", []) or []:
            res = walk_parts(part)
            if res:
                return res
        return None
    body_b64 = walk_parts(data.get("payload"))
    if not body_b64:
        return data.get("snippet","")
    text = base64.urlsafe_b64decode(body_b64 + "==").decode("utf-8", errors="ignore")
    if "<html" in text.lower():
        soup = BeautifulSoup(text, "html.parser")
        return soup.get_text(separator="\n")
    return text

def llm_worker_run(email, task_type, payload):
    rec = get_user_token(email)
    if not rec:
        return {"error":"no_tokens"}
    token_payload = rec["payload"]
    access_token = token_payload.get("access_token")
    if task_type == "summarize":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error":"message_id required"}
        text = _get_message_text(access_token, message_id)
        system_prompt = f"""You are Inbox AI Assistant. Output ONLY valid JSON with keys:
- summary: a short 1-2 sentence plain-text summary
- actions: array of objects with keys task, deadline, meta
- draft: object with keys subject and body

Email:
{text}
"""
        from google import genai
        client = genai.Client()
        response = client.models.generate_content(model="gemini-2.5-flash-lite", contents=system_prompt)
        text_out = getattr(response, "text", None)
        if text_out is None:
            try:
                text_out = response.text()
            except Exception:
                text_out = str(response)
        parsed = None
        try:
            parsed = json.loads(text_out)
        except Exception:
            import re
            m = re.search(r"\{.*\}", text_out, flags=re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except Exception:
                    parsed = {"raw": text_out}
            else:
                parsed = {"raw": text_out}
        return {"llm_text": text_out, "parsed": parsed}
    elif task_type == "classify":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        text = _get_message_text(access_token, message_id)
        # Prompt the LLM to classify into one of: Important, Newsletter, Spam, To-Do
        system_prompt = f'''You are an Inbox classifier. Read the email body and respond ONLY with a JSON object with keys:
- category: one of ["Important", "Newsletter", "Spam", "To-Do"]
- reason: a short (1-2 sentence) explanation of why this category was chosen
- tags: an array of short tag strings (optional)

Email:
{text}
'''
        from google import genai
        client = genai.Client()
        try:
            response = client.models.generate_content(model="gemini-2.5-flash-lite", contents=system_prompt)
            text_out = getattr(response, "text", None)
            if text_out is None:
                try:
                    text_out = response.text()
                except Exception:
                    text_out = str(response)
        except Exception as e:
            return {"error": "llm_call_failed", "detail": str(e)}

        parsed = None
        import json, re
        try:
            parsed = json.loads(text_out)
        except Exception:
            m = re.search(r"\{.*\}", text_out, flags=re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except Exception:
                    parsed = {"raw": text_out}
            else:
                parsed = {"raw": text_out}
        return {"llm_text": text_out, "parsed": parsed}
    elif task_type == "ask":
        message_id = payload.get("message_id")
        question = payload.get("question")
        if not message_id or not question:
            return {"error": "message_id and question required"}
        text = _get_message_text(access_token, message_id)
        system_prompt = f"""You are an Inbox assistant. Use only the information in the email to answer the user's question.
Be concise and factual. If the question requests a draft reply, respond with a JSON object with key `draft` containing `subject` and `body`.

Email:
{text}

User question: {question}
"""
        from google import genai
        client = genai.Client()
        try:
            response = client.models.generate_content(model="gemini-2.5-flash-lite", contents=system_prompt)
            text_out = getattr(response, "text", None)
            if text_out is None:
                try:
                    text_out = response.text()
                except Exception:
                    text_out = str(response)
        except Exception as e:
            return {"error": "llm_call_failed", "detail": str(e)}

        # Try to parse a JSON draft if present, otherwise return plain text answer
        parsed = None
        import json, re
        try:
            # if the assistant returned JSON, return it under 'answer_parsed'
            parsed = json.loads(text_out)
        except Exception:
            m = re.search(r"\{.*\}", text_out, flags=re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except Exception:
                    parsed = None
        return {"llm_text": text_out, "parsed": parsed, "answer": (text_out if not parsed else None)}

    elif task_type == "draft":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        text = _get_message_text(access_token, message_id)
        system_prompt = f'''You are an Inbox assistant. Generate a polite reply draft to the email below. Respond ONLY with a JSON object containing keys `subject` and `body`.

Email:
{text}
'''
        from google import genai
        client = genai.Client()
        try:
            response = client.models.generate_content(model="gemini-2.5-flash-lite", contents=system_prompt)
            text_out = getattr(response, "text", None)
            if text_out is None:
                try:
                    text_out = response.text()
                except Exception:
                    text_out = str(response)
        except Exception as e:
            return {"error": "llm_call_failed", "detail": str(e)}

        parsed = None
        import json, re
        try:
            parsed = json.loads(text_out)
        except Exception:
            m = re.search(r"\{.*\}", text_out, flags=re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except Exception:
                    parsed = {"raw": text_out}
            else:
                parsed = {"raw": text_out}
        return {"llm_text": text_out, "parsed": parsed}
    else:
        return {"error":"unknown task_type"}
