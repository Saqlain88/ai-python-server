# app/routes/resume_routes.py
from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from io import BytesIO
from app.services.resume_service import (
    list_templates, create_resume, update_resume, get_resume_by_id,
    ats_check_resume, generate_modifications, apply_auto_modifications,
    generate_pdf_bytes, send_resume_to_hr
)
from app import db

resume_bp = Blueprint("resume", __name__, url_prefix="/api/resume")


@resume_bp.route("/templates", methods=["GET"])
@jwt_required()
def templates():
    return jsonify({"templates": list_templates()}), 200


@resume_bp.route("/", methods=["POST"])
@jwt_required()
def create():
    user_id = get_jwt_identity()
    data = request.get_json()
    template_id = data.get("template_id", "modern")
    content = data.get("content", {})
    resume = create_resume(user_id=user_id, template_id=template_id, content=content)
    return jsonify({"resume": resume.to_dict()}), 201


@resume_bp.route("/<int:resume_id>", methods=["GET"])
@jwt_required()
def get_resume(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"resume": resume.to_dict()}), 200


@resume_bp.route("/<int:resume_id>", methods=["PUT"])
@jwt_required()
def update(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    content = data.get("content")
    template_id = data.get("template_id")
    resume = update_resume(resume, content=content, template_id=template_id)
    return jsonify({"resume": resume.to_dict()}), 200


@resume_bp.route("/<int:resume_id>/ats-check", methods=["POST"])
@jwt_required()
def ats_check(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    result = ats_check_resume(resume.content)
    # save into resume
    resume.ats_score = result.get("score")
    resume.ats_report = result.get("raw") or ""
    db.session.commit()
    # Map rating categories
    score = result.get("score", 0)
    rating = "bad"
    if score < 40:
        rating = "bad"
    elif score < 60:
        rating = "average"
    elif score < 80:
        rating = "good"
    elif score <= 100:
        rating = "excellent"
    return jsonify({"score": score, "rating": rating, "summary": result.get("summary"), "suggestions": result.get("suggestions")}), 200


@resume_bp.route("/<int:resume_id>/suggestions", methods=["POST"])
@jwt_required()
def suggestions(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    body = request.get_json() or {}
    max_suggestions = body.get("max_suggestions", 3)
    suggestions = generate_modifications(resume.content, max_suggestions_per_section=max_suggestions)
    return jsonify(suggestions), 200


@resume_bp.route("/<int:resume_id>/apply-modification", methods=["POST"])
@jwt_required()
def apply_mod(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json() or {}
    # If client passes full modifications, use them; otherwise call generate_modifications and auto apply
    modifications = data.get("modifications")
    if not modifications:
        mods = generate_modifications(resume.content, max_suggestions_per_section=1)
        modifications = mods.get("modified_suggestions", {})
    updated = apply_auto_modifications(resume, modifications)
    return jsonify({"resume": updated.to_dict()}), 200


@resume_bp.route("/<int:resume_id>/download", methods=["GET"])
@jwt_required()
def download_resume(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    pdf_bytes = generate_pdf_bytes(resume.template_id or "modern", resume.content)
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=f"{resume.content.get('name','resume')}.pdf")


@resume_bp.route("/<int:resume_id>/send", methods=["POST"])
@jwt_required()
def send_to_hr(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    hr_info = {
        "hr_name": data.get("hr_name"),
        "hr_email": data.get("hr_email"),
        "company_name": data.get("company_name"),
        "company_address": data.get("company_address"),
        "company_email": data.get("company_email"),
        "experience_applied_for": data.get("experience_applied_for")
    }
    pdf_bytes = generate_pdf_bytes(resume.template_id or "modern", resume.content)
    send_result = send_resume_to_hr(resume, hr_info, pdf_bytes)
    return jsonify(send_result), 200
