
from models import get_user_token, refresh_access_token, get_user_prompt
import requests, base64, json, re, os
from bs4 import BeautifulSoup
from llm_groq_langchain import llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from collections import deque

# Import the prompt building function
from routes.prompts import build_full_prompt, DEFAULT_PROMPTS

# Global dictionary to store conversation memories per user
user_memories = {}

class SimpleConversationMemory:
    """Simple conversation memory that keeps last N conversation turns"""
    def __init__(self, k=5):
        self.k = k
        self.messages = deque(maxlen=k*2)  # k*2 to store both user and AI messages
    
    def add_user_message(self, content):
        self.messages.append(HumanMessage(content=content))
    
    def add_ai_message(self, content):
        self.messages.append(AIMessage(content=content))
    
    def get_messages(self):
        return list(self.messages)

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

def _get_complete_message_info(access_token, message_id):
    """Get comprehensive email information including subject, sender, body, etc."""
    r = requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                     headers={"Authorization": f"Bearer {access_token}"}, params={"format":"full"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    
    # Extract headers
    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    subject = headers.get("Subject", "(No Subject)")
    sender = headers.get("From", "(Unknown Sender)")
    date = headers.get("Date", "(Unknown Date)")
    to = headers.get("To", "")
    
    # Extract body (reuse existing logic)
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
        body = data.get("snippet", "")
    else:
        body = base64.urlsafe_b64decode(body_b64 + "==").decode("utf-8", errors="ignore")
        if "<html" in body.lower():
            soup = BeautifulSoup(body, "html.parser")
            body = soup.get_text(separator="\n")
    
    return {
        "subject": subject,
        "sender": sender,
        "date": date,
        "to": to,
        "body": body,
        "snippet": data.get("snippet", "")
    }

def _get_message_subject(access_token, message_id):
    """Extract just the subject line from an email for fast categorization."""
    r = requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                     headers={"Authorization": f"Bearer {access_token}"}, params={"format":"minimal"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    return headers.get("Subject", "")

def _get_or_create_memory(email, task_type):
    """Get or create conversation memory for a specific user and task type"""
    memory_key = f"{email}_{task_type}"
    if memory_key not in user_memories:
        # Create a simple conversation memory that keeps last 5 conversations
        user_memories[memory_key] = SimpleConversationMemory(k=5)
    return user_memories[memory_key]

def _stream_langchain_with_memory(prompt_content, email, task_type):
    """Stream response from LangChain LLM with conversation memory"""
    memory = _get_or_create_memory(email, task_type)
    
    # Get chat history from memory
    chat_history = memory.get_messages()
    
    # Create the full message list with history + new prompt
    messages = chat_history + [HumanMessage(content=prompt_content)]
    
    text_out = ""
    for chunk in llm.stream(messages):
        delta = chunk.content or ""
        text_out += delta
    
    # Save the conversation to memory
    memory.add_user_message(prompt_content)
    memory.add_ai_message(text_out)
    
    return text_out


def ask_stream_generator(email, message_id, question):
    """Generator that yields token deltas from LangChain LLM for an ask request."""
    rec = get_user_token(email)
    if not rec:
        yield 'Error: no_tokens'
        return
    token_payload = rec['payload']
    access_token = token_payload.get('access_token')
    try:
        email_info = _get_complete_message_info(access_token, message_id)
    except Exception as e:
        yield f'Error fetching message: {str(e)}'
        return

    custom_prompt_obj = get_user_prompt(email, 'ask')
    if custom_prompt_obj:
        core_instruction = custom_prompt_obj['custom_prompt']
        prompt_content = build_full_prompt('ask', core_instruction, email_info=email_info, question=question)
    else:
        prompt_content = build_full_prompt('ask', DEFAULT_PROMPTS['ask'], email_info=email_info, question=question)

    # Use LangChain streaming with memory
    memory = _get_or_create_memory(email, 'ask')
    chat_history = memory.get_messages()
    messages = chat_history + [HumanMessage(content=prompt_content)]
    
    try:
        text_out = ""
        for chunk in llm.stream(messages):
            delta = chunk.content or ''
            if delta:
                text_out += delta
                yield delta
        
        # Save conversation to memory
        memory.add_user_message(prompt_content)
        memory.add_ai_message(text_out)
        
    except Exception as e:
        # Stream an error message
        yield f'Error: {str(e)}'


def summarize_stream_generator(email, message_id):
    """Generator that yields token deltas from LangChain LLM for a summarize request."""
    rec = get_user_token(email)
    if not rec:
        yield 'Error: no_tokens'
        return
    token_payload = rec['payload']
    access_token = token_payload.get('access_token')
    try:
        email_info = _get_complete_message_info(access_token, message_id)
    except Exception as e:
        yield f'Error fetching message: {str(e)}'
        return

    custom_prompt_obj = get_user_prompt(email, 'summarize')
    if custom_prompt_obj:
        core_instruction = custom_prompt_obj['custom_prompt']
        prompt_content = build_full_prompt('summarize', core_instruction, email_info=email_info)
    else:
        prompt_content = build_full_prompt('summarize', DEFAULT_PROMPTS['summarize'], email_info=email_info)
    
    print(f"[DEBUG] Summarize stream prompt (first 500 chars): {prompt_content[:500]}...")  # Enhanced debug logging

    # Use LangChain streaming with memory
    memory = _get_or_create_memory(email, 'summarize')
    chat_history = memory.get_messages()
    messages = chat_history + [HumanMessage(content=prompt_content)]

    try:
        text_out = ""
        for chunk in llm.stream(messages):
            delta = chunk.content or ''
            if delta:
                text_out += delta
                yield delta
        
        # Save conversation to memory
        memory.add_user_message(prompt_content)
        memory.add_ai_message(text_out)
        
    except Exception as e:
        yield f'Error: {str(e)}'


def actions_stream_generator(email, message_id):
    """Generator that yields token deltas from LangChain LLM for an actions extraction request."""
    rec = get_user_token(email)
    if not rec:
        yield 'Error: no_tokens'
        return
    token_payload = rec['payload']
    access_token = token_payload.get('access_token')
    try:
        email_info = _get_complete_message_info(access_token, message_id)
    except Exception as e:
        yield f'Error fetching message: {str(e)}'
        return

    custom_prompt_obj = get_user_prompt(email, 'actions')
    if custom_prompt_obj:
        core_instruction = custom_prompt_obj['custom_prompt']
        prompt_content = build_full_prompt('actions', core_instruction, email_info=email_info)
    else:
        prompt_content = build_full_prompt('actions', DEFAULT_PROMPTS['actions'], email_info=email_info)
    
    print(f"[DEBUG] Actions stream prompt (first 500 chars): {prompt_content[:500]}...")  # Enhanced debug logging
    print(f"[DEBUG] Actions stream - Using custom prompt: {custom_prompt_obj is not None}")  # Debug custom prompt usage

    # Use LangChain streaming with memory
    memory = _get_or_create_memory(email, 'actions')
    chat_history = memory.get_messages()
    messages = chat_history + [HumanMessage(content=prompt_content)]

    try:
        text_out = ""
        for chunk in llm.stream(messages):
            delta = chunk.content or ''
            if delta:
                text_out += delta
                yield delta
        
        # Save conversation to memory
        memory.add_user_message(prompt_content)
        memory.add_ai_message(text_out)
        
    except Exception as e:
        yield f'Error: {str(e)}'

def _parse_json_response(text_out):
    """Try to parse JSON from LLM response, handling markdown code blocks"""
    try:
        return json.loads(text_out)
    except Exception:
        clean_text = text_out
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", clean_text, re.DOTALL)
        if match:
            clean_text = match.group(1)
        else:
            clean_text = re.sub(r"^```.*?\n", "", clean_text, flags=re.MULTILINE)
            clean_text = re.sub(r"\n```.*?$", "", clean_text, flags=re.MULTILINE)
        try:
            return json.loads(clean_text)
        except Exception:
            m = re.search(r"\{.*\}", clean_text, flags=re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    return {"raw": text_out}
            return {"raw": text_out}

def llm_worker_run(email, task_type, payload):
    rec = get_user_token(email)
    if not rec:
        return {'error': 'no_tokens'}
    token_payload = rec['payload']
    access_token = token_payload.get('access_token')
    
    if task_type == "summarize":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        print(f"summarize: fetching message info for {message_id}")
        email_info = _get_complete_message_info(access_token, message_id)
        print(f"[DEBUG] Summarize task - Email info: Subject='{email_info['subject']}', From='{email_info['sender']}', To='{email_info['to']}', Body_length={len(email_info['body'])}")
        print(f"summarize: got email info - subject: {email_info['subject'][:50]}...")
        
        custom_prompt_obj = get_user_prompt(email, "summarize")
        if custom_prompt_obj:
            core_instruction = custom_prompt_obj["custom_prompt"]
            prompt_content = build_full_prompt("summarize", core_instruction, email_info=email_info)
        else:
            prompt_content = build_full_prompt("summarize", DEFAULT_PROMPTS["summarize"], email_info=email_info)
        
        print(f"[DEBUG] Summarize task prompt (first 500 chars): {prompt_content[:500]}...")  # Enhanced debug logging
        
        text_out = _stream_langchain_with_memory(prompt_content, email, "summarize")
        print(f"summarize: LLM response={text_out[:200]}")
        parsed = _parse_json_response(text_out)
        print(f"summarize: parsed={parsed}")
        return {"llm_text": text_out, "parsed": parsed}
    
    elif task_type == "classify":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        subject = _get_message_subject(access_token, message_id)
        
        custom_prompt_obj = get_user_prompt(email, "classify")
        if custom_prompt_obj:
            core_instruction = custom_prompt_obj["custom_prompt"]
            prompt_content = build_full_prompt("classify", core_instruction, email_subject=subject)
        else:
            prompt_content = build_full_prompt("classify", DEFAULT_PROMPTS["classify"], email_subject=subject)
        
        try:
            text_out = _stream_langchain_with_memory(prompt_content, email, "classify")
            parsed = _parse_json_response(text_out)
            return {'llm_text': text_out, 'parsed': parsed}
        except Exception as e:
            return {'error': 'llm_call_failed', 'detail': str(e)}
    
    elif task_type == "batch_classify":
        items = payload.get("message_items") or []
        if not items:
            return {"error": "message_items required"}
        
        lines = []
        for it in items:
            mid = it.get('id')
            subj = (it.get('subject') or '').strip()
            lines.append(f'"{mid}": "{subj}"')
        items_blob = ",\n".join(lines)
        
        custom_prompt_obj = get_user_prompt(email, "classify")
        if custom_prompt_obj:
            user_prompt = custom_prompt_obj["custom_prompt"]
        else:
            user_prompt = DEFAULT_PROMPTS["classify"]
        
        prompt_content = build_full_prompt("batch_classify", user_prompt, items_blob=items_blob)
        
        try:
            text_out = _stream_langchain_with_memory(prompt_content, email, "classify")
        except Exception as e:
            errstr = str(e)
            if '429' in errstr or 'Rate' in errstr or 'quota' in errstr.lower():
                return {'error': 'rate_limit', 'detail': errstr}
            return {'error': 'llm_call_failed', 'detail': errstr}
        
        parsed = _parse_json_response(text_out)
        print(f"batch_classify: LLM text_out={text_out[:200]}")
        print(f"batch_classify: parsed={parsed}")
        
        # Normalize parsed into mapping of id -> { category, reason }
        normalized = {}
        if isinstance(parsed, dict):
            for k, v in parsed.items():
                if isinstance(v, str):
                    normalized[str(k)] = {"category": v, "reason": "LLM returned category string"}
                elif isinstance(v, dict):
                    cat = v.get("category") or v.get("label") or None
                    reason = v.get("reason") or v.get("explain") or None
                    if cat:
                        normalized[str(k)] = {"category": cat, "reason": reason or "LLM batch classification"}
                    else:
                        normalized[str(k)] = {"category": "Uncategorized", "reason": "Unable to extract category from LLM response"}
                else:
                    normalized[str(k)] = {"category": "Uncategorized", "reason": "Unexpected value type from LLM"}
        
        # Ensure all requested ids are present
        for it in items:
            mid = str(it.get('id'))
            if mid not in normalized:
                normalized[mid] = {"category": "Uncategorized", "reason": "No classification returned by LLM"}
        
        return {"llm_text": text_out, "parsed": normalized}
    
    elif task_type == "ask":
        message_id = payload.get("message_id")
        question = payload.get("question")
        if not message_id or not question:
            return {"error": "message_id and question required"}
        email_info = _get_complete_message_info(access_token, message_id)
        
        custom_prompt_obj = get_user_prompt(email, "ask")
        if custom_prompt_obj:
            core_instruction = custom_prompt_obj["custom_prompt"]
            prompt_content = build_full_prompt("ask", core_instruction, email_info=email_info, question=question)
        else:
            prompt_content = build_full_prompt("ask", DEFAULT_PROMPTS["ask"], email_info=email_info, question=question)
        
        try:
            text_out = _stream_langchain_with_memory(prompt_content, email, "ask")
            parsed = _parse_json_response(text_out)
            return {'llm_text': text_out, 'parsed': parsed, 'answer': (text_out if not parsed else None)}
        except Exception as e:
            return {'error': 'llm_call_failed', 'detail': str(e)}
    
    elif task_type == "actions":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        email_info = _get_complete_message_info(access_token, message_id)
        
        custom_prompt_obj = get_user_prompt(email, "actions")
        if custom_prompt_obj:
            core_instruction = custom_prompt_obj["custom_prompt"]
            prompt_content = build_full_prompt("actions", core_instruction, email_info=email_info)
        else:
            prompt_content = build_full_prompt("actions", DEFAULT_PROMPTS["actions"], email_info=email_info)
        
        print(f"[DEBUG] Actions task prompt (first 500 chars): {prompt_content[:500]}...")  # Enhanced debug logging
        print(f"[DEBUG] Actions task - Using custom prompt: {custom_prompt_obj is not None}")  # Debug custom prompt usage
        print(f"[DEBUG] Actions task - Using custom prompt: {custom_prompt_obj is not None}")  # Debug custom prompt usage
        
        try:
            text_out = _stream_langchain_with_memory(prompt_content, email, "actions")
            parsed = _parse_json_response(text_out)
            print(f"[DEBUG] Actions task - LLM text_out (first 300 chars): {text_out[:300]}...")
            print(f"[DEBUG] Actions task - Parsed result: {parsed}")
            print(f"[DEBUG] Actions task - Parsed type: {type(parsed)}")
            if isinstance(parsed, dict):
                print(f"[DEBUG] Actions task - Parsed keys: {list(parsed.keys())}")
                if 'actions' in parsed:
                    print(f"[DEBUG] Actions task - Actions field: {parsed['actions']}")
                    print(f"[DEBUG] Actions task - Actions type: {type(parsed['actions'])}")
            return {"llm_text": text_out, "parsed": parsed}
        except Exception as e:
            return {"error": "llm_call_failed", "detail": str(e)}
    
    elif task_type == "draft":
        message_id = payload.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        email_info = _get_complete_message_info(access_token, message_id)
        
        custom_prompt_obj = get_user_prompt(email, "draft")
        if custom_prompt_obj:
            core_instruction = custom_prompt_obj["custom_prompt"]
            prompt_content = build_full_prompt("draft", core_instruction, email_info=email_info)
        else:
            prompt_content = build_full_prompt("draft", DEFAULT_PROMPTS["draft"], email_info=email_info)
        
        try:
            text_out = _stream_langchain_with_memory(prompt_content, email, "draft")
            parsed = _parse_json_response(text_out)
            return {"llm_text": text_out, "parsed": parsed}
        except Exception as e:
            return {"error": "llm_call_failed", "detail": str(e)}
    
    else:
        return {"error":"unknown task_type"}
