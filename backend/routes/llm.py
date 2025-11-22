
from flask import Blueprint, request, jsonify, session
from llm_worker import llm_worker_run

llm_bp = Blueprint("llm", __name__, url_prefix="/llm")

@llm_bp.route("/summarize", methods=["POST"])
def summarize_email():
    """Summarize an email and extract actions/draft"""
    data = request.get_json() or {}
    user_email = data.get("email") or session.get("user_email")
    message_id = data.get("message_id")
    
    if not user_email:
        return jsonify({"error": "user_email required"}), 400
    if not message_id:
        return jsonify({"error": "message_id required"}), 400
    
    result = llm_worker_run(user_email, "summarize", {"message_id": message_id})
    return jsonify(result)


@llm_bp.route("/classify", methods=["POST"])
def classify_email():
    """Classify an email into Important/Newsletter/Spam/To-Do"""
    data = request.get_json() or {}
    user_email = data.get("email") or session.get("user_email")
    message_id = data.get("message_id")
    if not user_email:
        return jsonify({"error": "user_email required"}), 400
    if not message_id:
        return jsonify({"error": "message_id required"}), 400

    result = llm_worker_run(user_email, "classify", {"message_id": message_id})
    return jsonify(result)


@llm_bp.route('/ask', methods=['POST'])
def ask_email():
    """Ask an arbitrary question about an email; returns assistant answer or parsed JSON."""
    data = request.get_json() or {}
    user_email = data.get('email') or session.get('user_email')
    message_id = data.get('message_id')
    question = data.get('question')
    if not user_email:
        return jsonify({'error': 'user_email required'}), 400
    if not message_id or not question:
        return jsonify({'error': 'message_id and question required'}), 400
    result = llm_worker_run(user_email, 'ask', {'message_id': message_id, 'question': question})
    return jsonify(result)


@llm_bp.route('/draft', methods=['POST'])
def generate_draft():
    """Generate a reply draft for an email (returns parsed subject/body)."""
    data = request.get_json() or {}
    user_email = data.get('email') or session.get('user_email')
    message_id = data.get('message_id')
    if not user_email:
        return jsonify({'error': 'user_email required'}), 400
    if not message_id:
        return jsonify({'error': 'message_id required'}), 400
    result = llm_worker_run(user_email, 'draft', {'message_id': message_id})
    return jsonify(result)
