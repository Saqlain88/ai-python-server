from flask import Blueprint, request, jsonify
from app.services.ai_service import generate_react_code
from flask_jwt_extended import jwt_required  # if you’re using JWT auth

ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")


@ai_bp.route("/generate", methods=["POST"])
@jwt_required()  # optional, if your app uses authentication
def generate():
    """
    Route for generating React code from a text prompt.
    """
    data = request.get_json()
    prompt = data.get("prompt")

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    try:
        code = generate_react_code(prompt)
        return jsonify({"code": code}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
