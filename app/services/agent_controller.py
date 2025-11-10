# agent_controller.py
from flask import Blueprint, request, jsonify
from resume_service import ats_check_resume, generate_hr_email, send_resume_to_hr
from app.models.resume import Resume
import json

agent_bp = Blueprint('agent', __name__)

@agent_bp.route('/chat', methods=['POST'])
def agent_chat():
    user_msg = request.json.get("message")
    user_id = request.json.get("user_id")

    # 1. Greeting step
    if user_msg.lower() in ["hi", "hello", "start"]:
        return jsonify({
            "reply": "Hi! I can help with:\n1. AI Code Generator\n2. AI Resume Maker\n3. ATS Checker\n4. Send Resume to HR\n5. AI Image Generator\nType a number to continue.",
            "action": None
        })

    # 2. Redirect actions
    if user_msg == "1":
        return jsonify({"reply": "Opening AI Code Generator…", "action": "redirect:/code-generator"})

    if user_msg == "2":
        return jsonify({"reply": "Opening Resume Builder…", "action": "redirect:/resume"})

    if user_msg == "3":
        return jsonify({"reply": "Upload your resume PDF for ATS scanning.", "action": "ats_wait"})

    if "send to hr" in user_msg.lower():
        return jsonify({"reply": "Please provide HR details.", "action": "ask_hr"})

    return jsonify({"reply": "Sorry, I didn't understand. Please enter 1-5.", "action": None})
