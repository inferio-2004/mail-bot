
from flask import Blueprint, request, jsonify, session
from llm_worker import llm_worker_run
from llm_worker import ask_stream_generator
from flask import Response, stream_with_context
from llm_worker import summarize_stream_generator, actions_stream_generator

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


@llm_bp.route('/classify-batch', methods=['POST'])
def classify_batch():
    """Classify multiple emails in a single LLM call. Expects JSON { message_items: [{id, subject}, ...] }"""
    data = request.get_json() or {}
    user_email = data.get('email') or session.get('user_email')
    items = data.get('message_items')
    if not user_email:
        return jsonify({'error': 'user_email required'}), 400
    if not items or not isinstance(items, list):
        return jsonify({'error': 'message_items required and must be a list'}), 400

    print('classify-batch: received', len(items), 'items')
    result = llm_worker_run(user_email, 'batch_classify', {'message_items': items})
    print('classify-batch: llm result keys=', list(result.keys()) if isinstance(result, dict) else type(result))
    # If rate-limited, propagate 429 status for frontend to handle display
    if isinstance(result, dict) and result.get('error') == 'rate_limit':
        print('classify-batch: rate limit detected, detail=', result.get('detail'))
        return jsonify(result), 429
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


@llm_bp.route('/ask-stream', methods=['POST'])
def ask_email_stream():
    """Stream assistant text for a question about an email."""
    data = request.get_json() or {}
    user_email = data.get('email') or session.get('user_email')
    message_id = data.get('message_id')
    question = data.get('question')
    if not user_email:
        return jsonify({'error': 'user_email required'}), 400
    if not message_id or not question:
        return jsonify({'error': 'message_id and question required'}), 400

    gen = ask_stream_generator(user_email, message_id, question)
    return Response(stream_with_context(gen), mimetype='text/plain')


@llm_bp.route('/summarize-stream', methods=['POST'])
def summarize_email_stream():
    data = request.get_json() or {}
    user_email = data.get('email') or session.get('user_email')
    message_id = data.get('message_id')
    if not user_email:
        return jsonify({'error': 'user_email required'}), 400
    if not message_id:
        return jsonify({'error': 'message_id required'}), 400
    gen = summarize_stream_generator(user_email, message_id)
    return Response(stream_with_context(gen), mimetype='text/plain')


@llm_bp.route('/actions-stream', methods=['POST'])
def actions_email_stream():
    data = request.get_json() or {}
    user_email = data.get('email') or session.get('user_email')
    message_id = data.get('message_id')
    if not user_email:
        return jsonify({'error': 'user_email required'}), 400
    if not message_id:
        return jsonify({'error': 'message_id required'}), 400
    gen = actions_stream_generator(user_email, message_id)
    return Response(stream_with_context(gen), mimetype='text/plain')


@llm_bp.route('/actions', methods=['POST'])
def extract_actions():
    """Extract action items from an email."""
    data = request.get_json() or {}
    user_email = data.get('email') or session.get('user_email')
    message_id = data.get('message_id')
    if not user_email:
        return jsonify({'error': 'user_email required'}), 400
    if not message_id:
        return jsonify({'error': 'message_id required'}), 400
    result = llm_worker_run(user_email, 'actions', {'message_id': message_id})
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
