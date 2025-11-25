
from models import get_user_token, refresh_access_token, get_user_prompt
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

def _get_message_subject(access_token, message_id):
    """Extract just the subject line from an email for fast categorization."""
    r = requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                     headers={"Authorization": f"Bearer {access_token}"}, params={"format":"minimal"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    return headers.get("Subject", "")

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
        print(f"summarize: fetching message text for {message_id}")
        text = _get_message_text(access_token, message_id)
        print(f"summarize: got message text length={len(text)}")
        
        # Get custom prompt if exists, else use default
        custom_prompt_obj = get_user_prompt(email, "summarize")
        if custom_prompt_obj:
            system_prompt = custom_prompt_obj["custom_prompt"].format(email_body=text)
        else:
            system_prompt = f"""You are Inbox AI Assistant. Output ONLY valid JSON with keys:
- summary: a short 1-2 sentence plain-text summary
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
        print(f"summarize: LLM response={text_out[:200]}")
        parsed = None
        try:
            parsed = json.loads(text_out)
        except Exception:
            import re
            # Strip markdown code blocks - try multiple patterns
            clean_text = text_out
            
            # Try pattern 1: ```json\n...\n```
            match = re.search(r"```(?:json)?\s*\n(.*?)\n```", clean_text, re.DOTALL)
            if match:
                clean_text = match.group(1)
            # Try pattern 2: just remove the markdown markers
            else:
                clean_text = re.sub(r"^```.*?\n", "", clean_text, flags=re.MULTILINE)
                clean_text = re.sub(r"\n```.*?$", "", clean_text, flags=re.MULTILINE)
            
            # Try to parse cleaned text
            try:
                print(f"summarize: trying to parse clean_text={clean_text[:100]}")
                parsed = json.loads(clean_text)
            except Exception as e:
                print(f"summarize: clean parse failed, trying regex extract: {e}")
                # If still not valid, try extracting JSON object
                m = re.search(r"\{.*\}", clean_text, flags=re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except Exception:
                        parsed = {"raw": text_out}
                else:
                    parsed = {"raw": text_out}
        print(f"summarize: parsed={parsed}")
        return {"llm_text": text_out, "parsed": parsed}
    elif task_type == "classify":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        # Use only subject line for fast classification at inbox load
        subject = _get_message_subject(access_token, message_id)
        
        # Get custom prompt if exists, else use default
        custom_prompt_obj = get_user_prompt(email, "classify")
        if custom_prompt_obj:
            system_prompt = custom_prompt_obj["custom_prompt"].format(email_subject=subject)
        else:
            system_prompt = f'''You are an Inbox classifier. Classify the email subject line into one of these categories and respond ONLY with a JSON object with keys:
- category: one of ["Important", "Newsletter", "Spam", "To-Do"]
- reason: a short (1-2 sentence) explanation of why this category was chosen

Email Subject:
{subject}
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
            # Strip markdown code blocks first
            clean_text = re.sub(r"^```(?:json)?\s*", "", text_out, flags=re.MULTILINE)
            clean_text = re.sub(r"\s*```$", "", clean_text, flags=re.MULTILINE)
            # Try to parse cleaned text
            try:
                parsed = json.loads(clean_text)
            except Exception:
                # If still not valid, try extracting JSON object
                m = re.search(r"\{.*\}", clean_text, flags=re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except Exception:
                        parsed = {"raw": text_out}
                else:
                    parsed = {"raw": text_out}
        return {"llm_text": text_out, "parsed": parsed}
    elif task_type == "batch_classify":
        # payload expected: { message_items: [ { id: str, subject: str }, ... ] }
        items = payload.get("message_items") or []
        if not items:
            return {"error": "message_items required"}
        # build a prompt listing items for a single LLM call
        lines = []
        for it in items:
            mid = it.get('id')
            subj = (it.get('subject') or '').strip()
            lines.append(f'"{mid}": "{subj}"')
        items_blob = ",\n".join(lines)

        custom_prompt_obj = get_user_prompt(email, "classify")
        if custom_prompt_obj:
            # Some user-provided prompts may use {email_subject} (singular) or {email_subjects} (plural).
            # Provide both keys to avoid KeyError and be backward compatible.
            system_prompt = custom_prompt_obj["custom_prompt"].format(email_subjects=items_blob, email_subject=items_blob)
        else:
            system_prompt = f'''You are an Inbox classifier. You will be given a JSON-like mapping of message ids to their subject lines.
For each message id, decide one category from ["Important","Newsletter","Spam","To-Do"].
Respond ONLY with a JSON object whose keys are message ids and values are objects with keys `category` and `reason`.

EmailSubjects:
{{
{items_blob}
}}
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
            # detect rate-limit string in exception
            errstr = str(e)
            if '429' in errstr or 'Rate' in errstr or 'quota' in errstr.lower():
                return {"error": "rate_limit", "detail": errstr}
            return {"error": "llm_call_failed", "detail": errstr}

        # try to parse a JSON mapping
        parsed = None
        import json, re
        try:
            parsed = json.loads(text_out)
        except Exception:
            # Strip markdown code blocks - try multiple patterns
            clean_text = text_out
            
            # Try pattern 1: ```json\n...\n```
            match = re.search(r"```(?:json)?\s*\n(.*?)\n```", clean_text, re.DOTALL)
            if match:
                clean_text = match.group(1)
            # Try pattern 2: just remove the markdown markers
            else:
                clean_text = re.sub(r"^```.*?\n", "", clean_text, flags=re.MULTILINE)
                clean_text = re.sub(r"\n```.*?$", "", clean_text, flags=re.MULTILINE)
            
            # Try to parse cleaned text
            try:
                parsed = json.loads(clean_text)
            except Exception:
                # If still not valid, try extracting JSON object
                m = re.search(r"\{.*\}", clean_text, flags=re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except Exception:
                        parsed = {"raw": text_out}
                else:
                    parsed = {"raw": text_out}

        print(f"batch_classify: LLM text_out={text_out[:200]}")
        print(f"batch_classify: parsed={parsed}")
        print(f"batch_classify: parsed keys={list(parsed.keys()) if isinstance(parsed, dict) else 'not dict'}")
        # Normalize parsed into mapping of id -> { category, reason }
        normalized = {}
        if isinstance(parsed, dict):
            for k, v in parsed.items():
                # If value is a simple string like "Newsletter", convert to object
                if isinstance(v, str):
                    normalized[str(k)] = {"category": v, "reason": "LLM returned category string"}
                elif isinstance(v, dict):
                    cat = v.get("category") or v.get("label") or None
                    reason = v.get("reason") or v.get("explain") or None
                    if cat:
                        normalized[str(k)] = {"category": cat, "reason": reason or "LLM batch classification"}
                    else:
                        # try to coerce if dict contains one key mapping to category
                        # e.g., {"category":"Important"} or {"label":"Newsletter"}
                        if len(v) == 1:
                            sole = list(v.values())[0]
                            if isinstance(sole, str):
                                normalized[str(k)] = {"category": sole, "reason": "LLM returned single-value mapping"}
                            else:
                                normalized[str(k)] = {"category": "Uncategorized", "reason": "Unable to extract category from LLM response"}
                        else:
                            normalized[str(k)] = {"category": "Uncategorized", "reason": "Incomplete LLM classification output"}
                else:
                    normalized[str(k)] = {"category": "Uncategorized", "reason": "Unexpected value type from LLM"}
        else:
            # If parsed is not a dict, we cannot map; return empty mapping so frontend knows
            normalized = {}

        # Ensure all requested ids are present in the mapping (fill with Uncategorized if missing)
        try:
            for it in items:
                mid = str(it.get('id'))
                if mid not in normalized:
                    normalized[mid] = {"category": "Uncategorized", "reason": "No classification returned by LLM"}
        except Exception:
            pass

        # If some items are still Uncategorized or missing, fall back to per-item classification
        # to guarantee one category per input id. This is slower but ensures correctness.
        try:
            missing = [it for it in items if str(it.get('id')) not in normalized or normalized.get(str(it.get('id')), {}).get('category') == 'Uncategorized']
            if missing:
                print(f"batch_classify: missing {len(missing)} ids, falling back to per-item classification")
                import re
                import json as _json
                for it in missing:
                    mid = str(it.get('id'))
                    subj = (it.get('subject') or '').strip()
                    # Build per-item prompt using user's custom prompt if available
                    custom_prompt_obj_item = get_user_prompt(email, "classify")
                    if custom_prompt_obj_item:
                        per_prompt = custom_prompt_obj_item["custom_prompt"].format(email_subject=subj)
                    else:
                        per_prompt = f'''You are an Inbox classifier. Classify the email subject line into one of these categories and respond ONLY with a JSON object with keys:\n- category: one of ["Important", "Newsletter", "Spam", "To-Do"]\n- reason: a short (1-2 sentence) explanation of why this category was chosen\n\nEmail Subject:\n{subj}\n'''
                    try:
                        resp = client.models.generate_content(model="gemini-2.5-flash-lite", contents=per_prompt)
                        text_single = getattr(resp, "text", None)
                        if text_single is None:
                            try:
                                text_single = resp.text()
                            except Exception:
                                text_single = str(resp)
                    except Exception as e:
                        normalized[mid] = {"category": "Uncategorized", "reason": f"llm_call_failed: {str(e)}"}
                        continue

                    parsed_single = None
                    try:
                        parsed_single = _json.loads(text_single)
                    except Exception:
                        # try to clean markdown fences then parse
                        clean_single = re.sub(r"^```(?:json)?\s*", "", text_single, flags=re.MULTILINE)
                        clean_single = re.sub(r"\s*```$", "", clean_single, flags=re.MULTILINE)
                        try:
                            parsed_single = _json.loads(clean_single)
                        except Exception:
                            m = re.search(r"\{[\s\S]*\}", clean_single)
                            if m:
                                try:
                                    parsed_single = _json.loads(m.group(0))
                                except Exception:
                                    parsed_single = None
                    # If parsed_single yields a category, use it
                    if isinstance(parsed_single, dict):
                        cat = parsed_single.get('category') or parsed_single.get('label')
                        reason = parsed_single.get('reason') or parsed_single.get('explain') or None
                        if cat:
                            normalized[mid] = {"category": cat, "reason": reason or "LLM per-item classification"}
                            continue

                    # Fallback: try to find a keyword in the LLM text
                    found = None
                    for candidate in ["Important", "Newsletter", "Spam", "To-Do", "To Do", "Todo", "To-do"]:
                        if re.search(rf"\b{re.escape(candidate)}\b", text_single or "", flags=re.IGNORECASE):
                            found = candidate
                            break
                    if found:
                        if found.lower().startswith('to'):
                            found = 'To-Do'
                        normalized[mid] = {"category": found, "reason": "LLM text contained category keyword"}
                    else:
                        normalized[mid] = {"category": "Uncategorized", "reason": "Unable to parse per-item LLM response"}
        except Exception:
            # if fallback fails for any reason, continue and return whatever we have
            pass

        return {"llm_text": text_out, "parsed": normalized}
    elif task_type == "ask":
        message_id = payload.get("message_id")
        question = payload.get("question")
        if not message_id or not question:
            return {"error": "message_id and question required"}
        text = _get_message_text(access_token, message_id)
        
        # Get custom prompt if exists, else use default
        custom_prompt_obj = get_user_prompt(email, "ask")
        if custom_prompt_obj:
            system_prompt = custom_prompt_obj["custom_prompt"].format(email_body=text, question=question)
        else:
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
            # Strip markdown code blocks - handle both ``` and ```json
            clean_text = text_out
            if "```" in clean_text:
                # Extract content between first ``` and last ```
                match = re.search(r"```(?:json)?\s*\n(.*?)\n```", clean_text, re.DOTALL)
                if match:
                    clean_text = match.group(1)
            # Try to parse cleaned text
            try:
                parsed = json.loads(clean_text)
            except Exception:
                # If still not valid, try extracting JSON object
                m = re.search(r"\{.*\}", clean_text, flags=re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except Exception:
                        parsed = None
                else:
                    parsed = None
        return {"llm_text": text_out, "parsed": parsed, "answer": (text_out if not parsed else None)}

    elif task_type == "actions":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        text = _get_message_text(access_token, message_id)
        
        # Get custom prompt if exists, else use default
        custom_prompt_obj = get_user_prompt(email, "actions")
        if custom_prompt_obj:
            system_prompt = custom_prompt_obj["custom_prompt"].format(email_body=text)
        else:
            system_prompt = f'''You are an action-item extraction assistant. Analyze the email and extract any action items that the user should take. Respond ONLY with a JSON object with key:
- actions: array of objects with keys task, deadline (optional), meta (optional)

If no action items are present, return an empty array.

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
            # Strip markdown code blocks first
            clean_text = re.sub(r"^```(?:json)?\s*", "", text_out, flags=re.MULTILINE)
            clean_text = re.sub(r"\s*```$", "", clean_text, flags=re.MULTILINE)
            # Try to parse cleaned text
            try:
                parsed = json.loads(clean_text)
            except Exception:
                # If still not valid, try extracting JSON object
                m = re.search(r"\{.*\}", clean_text, flags=re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except Exception:
                        parsed = {"raw": text_out}
                else:
                    parsed = {"raw": text_out}
        return {"llm_text": text_out, "parsed": parsed}
    elif task_type == "draft":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        text = _get_message_text(access_token, message_id)
        
        # Get custom prompt if exists, else use default
        custom_prompt_obj = get_user_prompt(email, "draft")
        if custom_prompt_obj:
            system_prompt = custom_prompt_obj["custom_prompt"].format(email_body=text)
        else:
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
            # Strip markdown code blocks first
            clean_text = re.sub(r"^```(?:json)?\s*", "", text_out, flags=re.MULTILINE)
            clean_text = re.sub(r"\s*```$", "", clean_text, flags=re.MULTILINE)
            # Try to parse cleaned text
            try:
                parsed = json.loads(clean_text)
            except Exception:
                # If still not valid, try extracting JSON object
                m = re.search(r"\{.*\}", clean_text, flags=re.DOTALL)
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
