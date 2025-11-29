from flask import Blueprint, request, jsonify, session
from models import get_user_prompt, save_user_prompt, get_all_user_prompts
import logging

logger = logging.getLogger(__name__)
prompts_bp = Blueprint("prompts", __name__, url_prefix="/prompts")

# Default system prompts - Only the core user-editable instructions
# System formatting and JSON structure are added automatically in llm_worker.py
DEFAULT_PROMPTS = {
    "classify": "You are an Inbox classifier. Classify the email subject line into one of these categories: Important, Newsletter, Spam, or To-Do. Provide a brief explanation for your choice.",
    "summarize": "You are Inbox AI Assistant. Provide a concise 1-2 sentence summary of the email and generate a polite reply draft.",
    "actions": "You are an action-item extraction assistant. Analyze the email and extract any action items that the user should take. If no actions are needed, explain why.",
    "draft": "You are an Inbox assistant. Generate a polite and professional reply draft to the email.",
    "ask": "You are an Inbox assistant. Use only the information in the email to answer the user's question. Be concise and factual."
}

def build_full_prompt(prompt_type, user_prompt, **kwargs):
    """
    Build complete prompt by combining user instructions with system formatting requirements.
    This protects critical JSON formatting and variable placeholders from user modification.
    """
    if prompt_type == "classify":
        email_subject = kwargs.get('email_subject', '{email_subject}')
        return f'''{user_prompt}

Respond ONLY with a JSON object with keys:
- category: one of ["Important", "Newsletter", "Spam", "To-Do"]  
- reason: a short (1-2 sentence) explanation of why this category was chosen

Email Subject:
{email_subject}'''

    elif prompt_type == "batch_classify":
        items_blob = kwargs.get('items_blob', '{items_blob}')
        return f'''{user_prompt}

For each message id, decide one category from ["Important","Newsletter","Spam","To-Do"].
Respond ONLY with a JSON object whose keys are message ids and values are objects with keys `category` and `reason`.

EmailSubjects:
{{
{items_blob}
}}'''

    elif prompt_type == "summarize":
        email_info = kwargs.get('email_info', {})
        if isinstance(email_info, dict):
            email_content = f"""Subject: {email_info.get('subject', 'N/A')}
From: {email_info.get('sender', 'N/A')}
To: {email_info.get('to', 'N/A')}
Date: {email_info.get('date', 'N/A')}

Body:
{email_info.get('body', '')}"""
        else:
            email_content = kwargs.get('email_body', '{email_body}')
        
        return f'''{user_prompt}

Output ONLY valid JSON with keys:
- summary: a short 1-2 sentence plain-text summary
- draft: object with keys subject and body

Email:
{email_content}'''

    elif prompt_type == "actions":
        email_info = kwargs.get('email_info', {})
        if isinstance(email_info, dict):
            email_content = f"""Subject: {email_info.get('subject', 'N/A')}
From: {email_info.get('sender', 'N/A')}
To: {email_info.get('to', 'N/A')}
Date: {email_info.get('date', 'N/A')}

Body:
{email_info.get('body', '')}"""
        else:
            email_content = kwargs.get('email_body', '{email_body}')
        
        return f'''{user_prompt}

Respond ONLY with a JSON object with key:
- actions: array of objects with keys task, deadline (optional), meta (optional)
- message: optional string explaining if no actions are needed

If no action items are present or no actions are required, return an empty array for actions and include a brief message explaining why no actions are needed (e.g., "This is an informational email with no action required", "No follow-up needed", etc.).

Email:
{email_content}'''

    elif prompt_type == "draft":
        email_info = kwargs.get('email_info', {})
        if isinstance(email_info, dict):
            email_content = f"""Subject: {email_info.get('subject', 'N/A')}
From: {email_info.get('sender', 'N/A')}
To: {email_info.get('to', 'N/A')}
Date: {email_info.get('date', 'N/A')}

Body:
{email_info.get('body', '')}"""
        else:
            email_content = kwargs.get('email_body', '{email_body}')
        
        return f'''{user_prompt}

Respond ONLY with a JSON object containing keys `subject` and `body`.

Email:
{email_content}'''

    elif prompt_type == "ask":
        email_info = kwargs.get('email_info', {})
        if isinstance(email_info, dict):
            email_content = f"""Subject: {email_info.get('subject', 'N/A')}
From: {email_info.get('sender', 'N/A')}
To: {email_info.get('to', 'N/A')}
Date: {email_info.get('date', 'N/A')}

Body:
{email_info.get('body', '')}"""
        else:
            email_content = kwargs.get('email_body', '{email_body}')
        question = kwargs.get('question', '{question}')
        
        return f'''{user_prompt}

If the question requests a draft reply, respond with a JSON object with key `draft` containing `subject` and `body`.

Email:
{email_content}

User question: {question}'''

    else:
        # Fallback: return user prompt as-is
        return user_prompt

@prompts_bp.route("/get/<prompt_type>", methods=["GET"])
def get_prompt(prompt_type):
    """Get custom prompt or default for a user"""
    user_email = session.get("user_email")
    if not user_email:
        return jsonify({"error": "user_email required"}), 400
    
    if prompt_type not in DEFAULT_PROMPTS:
        return jsonify({"error": "invalid prompt_type"}), 400
    
    # Try to get custom prompt
    custom = get_user_prompt(user_email, prompt_type)
    if custom:
        return jsonify({"prompt_type": prompt_type, "prompt": custom["custom_prompt"], "is_custom": True})
    
    # Return default
    return jsonify({"prompt_type": prompt_type, "prompt": DEFAULT_PROMPTS[prompt_type], "is_custom": False})

@prompts_bp.route("/save", methods=["POST"])
def save_prompt():
    """Save custom prompt for a user"""
    data = request.get_json() or {}
    user_email = session.get("user_email")
    if not user_email:
        return jsonify({"error": "user_email required"}), 400
    
    prompt_type = data.get("prompt_type")
    custom_prompt = data.get("prompt")
    
    if not prompt_type or not custom_prompt:
        return jsonify({"error": "prompt_type and prompt required"}), 400
    
    if prompt_type not in DEFAULT_PROMPTS:
        return jsonify({"error": "invalid prompt_type"}), 400
    
    try:
        save_user_prompt(user_email, prompt_type, custom_prompt)
        return jsonify({"status": "saved", "prompt_type": prompt_type})
    except Exception as e:
        logger.exception("Failed to save prompt for %s: %s", user_email, e)
        return jsonify({"error": "save_failed", "detail": str(e)}), 500

@prompts_bp.route("/get-all", methods=["GET"])
def get_all_prompts():
    """Get all custom prompts for a user"""
    user_email = session.get("user_email")
    if not user_email:
        return jsonify({"error": "user_email required"}), 400
    
    try:
        custom_prompts = get_all_user_prompts(user_email)
        # Build response with defaults for missing prompt types
        result = {}
        for prompt_type in DEFAULT_PROMPTS.keys():
            custom = next((p for p in custom_prompts if p["prompt_type"] == prompt_type), None)
            if custom:
                result[prompt_type] = {"prompt": custom["custom_prompt"], "is_custom": True}
            else:
                result[prompt_type] = {"prompt": DEFAULT_PROMPTS[prompt_type], "is_custom": False}
        return jsonify(result)
    except Exception as e:
        logger.exception("Failed to get all prompts for %s: %s", user_email, e)
        return jsonify({"error": "fetch_failed", "detail": str(e)}), 500

@prompts_bp.route("/reset/<prompt_type>", methods=["POST"])
def reset_prompt(prompt_type):
    """Reset a prompt to default by deleting custom version"""
    user_email = session.get("user_email")
    if not user_email:
        return jsonify({"error": "user_email required"}), 400
    
    if prompt_type not in DEFAULT_PROMPTS:
        return jsonify({"error": "invalid prompt_type"}), 400
    
    try:
        from models import SessionLocal
        session_db = SessionLocal()
        try:
            obj = session_db.query(__import__('models', fromlist=['UserPrompt']).UserPrompt).filter_by(
                email=user_email, prompt_type=prompt_type
            ).first()
            if obj:
                session_db.delete(obj)
                session_db.commit()
        finally:
            session_db.close()
        return jsonify({"status": "reset", "prompt_type": prompt_type})
    except Exception as e:
        logger.exception("Failed to reset prompt for %s: %s", user_email, e)
        return jsonify({"error": "reset_failed", "detail": str(e)}), 500
