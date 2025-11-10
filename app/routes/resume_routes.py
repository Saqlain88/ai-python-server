from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required, get_jwt_identity
from io import BytesIO
from app.services.resume_service import (
    list_templates, create_resume, update_resume, get_resume_by_id,
    ats_check_resume, generate_modifications, apply_auto_modifications,
    generate_pdf_bytes, send_resume_to_hr
)
import os
import uuid
from datetime import datetime
from app import db

from app.services.resume_service import analyze_resume_vs_job


# Upload Resume Configuration
UPLOAD_FOLDER = 'uploads/resumes'
ALLOWED_EXTENSIONS = {'pdf'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

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


@resume_bp.route("/<string:resume_id>", methods=["GET"])
@jwt_required()
def get_resume(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"resume": resume.to_dict()}), 200


@resume_bp.route("/<string:resume_id>", methods=["PUT"])
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


@resume_bp.route("/<string:resume_id>/ats-check", methods=["POST"])
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


@resume_bp.route("/<string:resume_id>/suggestions", methods=["POST"])
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


@resume_bp.route("/<string:resume_id>/apply-modification", methods=["POST"])
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


@resume_bp.route("/<string:resume_id>/download", methods=["GET"])
@jwt_required()
def download_resume(resume_id):
    user_id = get_jwt_identity()
    resume = get_resume_by_id(resume_id, user_id)
    if not resume:
        return jsonify({"error": "Not found"}), 404
    pdf_bytes = generate_pdf_bytes(resume.template_id or "modern", resume.content)
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=f"{resume.content.get('name','resume')}.pdf")


@resume_bp.route("/<string:resume_id>/send", methods=["POST"])
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

@resume_bp.route("/ats-match", methods=["POST"])
@jwt_required()
def ats_match():
    """
    Compare resume PDF with job description (text or file).
    """
    resume_file = request.files.get("resume")
    jd_file = request.files.get("jd_file")
    jd_text = request.form.get("jd_text")

    if not resume_file:
        return jsonify({"error": "Resume file is required"}), 400

    try:
        result = analyze_resume_vs_job(resume_file, job_description_text=jd_text, job_description_file=jd_file)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@resume_bp.route("/template", methods=["POST"])
@jwt_required()
def create_template():
    data = request.get_json()
    title = data.get("title")
    thumbnail = request.files.get("thumbnail")
    category = data.get("category")
    template = create_resume(title=title, thumbnail=thumbnail, category=category)
    return jsonify({"template": template.to_dict()}), 201


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_pdf_file(file):
    """Validate PDF file"""
    # Check if file exists
    if not file or file.filename == '':
        raise ValueError("No file selected")
    
    # Check file extension
    if not allowed_file(file.filename):
        raise ValueError("Only PDF files are allowed")
    
    # Check file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    
    if size > MAX_FILE_SIZE:
        raise ValueError(f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")
    
    if size == 0:
        raise ValueError("File is empty")
    
    # Check PDF magic bytes
    header = file.read(4)
    file.seek(0)
    
    if header != b'%PDF':
        raise ValueError("Invalid PDF file format")
    
    return True

@resume_bp.route('/upload-pdf', methods=['POST'])
def upload_resume_pdf():
    """
    Upload resume PDF file
    
    Request:
        - file: PDF file (multipart/form-data)
        - Optional: user_id, metadata
    
    Response:
        {
            "success": true,
            "file_path": "uploads/resumes/xxx_resume.pdf",
            "filename": "xxx_resume.pdf",
            "original_name": "resume.pdf",
            "file_size": 12345
        }
    """
    try:
        # Check if file is in request
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in request'}), 400
        
        file = request.files['file']
        
        # Validate file
        try:
            validate_pdf_file(file)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        
        # Get user ID if authenticated (optional)
        user_id = None
        try:
            user_id = get_jwt_identity()
        except:
            pass  # Allow anonymous uploads
        
        # Generate unique filename
        original_filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        
        if user_id:
            new_filename = f"{user_id}_{timestamp}_{unique_id}_{original_filename}"
        else:
            new_filename = f"anonymous_{timestamp}_{unique_id}_{original_filename}"
        
        # Ensure upload directory exists
        upload_path = os.path.join(current_app.root_path, '..', UPLOAD_FOLDER)
        os.makedirs(upload_path, exist_ok=True)
        
        # Save file
        file_path = os.path.join(upload_path, new_filename)
        file.save(file_path)
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Optional: Extract text from PDF for preview
        # pdf_text = extract_pdf_text(file_path)
        
        # Return success response
        return jsonify({
            'success': True,
            'file_path': os.path.join(UPLOAD_FOLDER, new_filename),
            'filename': new_filename,
            'original_name': original_filename,
            'file_size': file_size,
            'uploaded_at': datetime.now().isoformat(),
            'user_id': user_id
        }), 200
        
    except Exception as e:
        print(f"Upload error: {e}")
        return jsonify({
            'error': 'Failed to upload file',
            'details': str(e)
        }), 500

@resume_bp.route('/upload-pdf/base64', methods=['POST'])
def upload_resume_pdf_base64():
    """
    Upload resume PDF from base64 data (for frontend file upload)
    
    Request JSON:
        {
            "filename": "resume.pdf",
            "data": "base64_encoded_data",
            "user_id": "optional"
        }
    
    Response:
        Same as upload_resume_pdf
    """
    try:
        data = request.get_json()
        
        if not data or 'data' not in data or 'filename' not in data:
            return jsonify({'error': 'Missing filename or data'}), 400
        
        filename = secure_filename(data['filename'])
        base64_data = data['data']
        
        # Validate filename
        if not allowed_file(filename):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        # Decode base64
        import base64
        try:
            # Remove data URL prefix if present
            if ',' in base64_data:
                base64_data = base64_data.split(',')[1]
            
            file_bytes = base64.b64decode(base64_data)
        except Exception as e:
            return jsonify({'error': 'Invalid base64 data'}), 400
        
        # Validate size
        if len(file_bytes) > MAX_FILE_SIZE:
            return jsonify({'error': f'File too large. Maximum {MAX_FILE_SIZE // (1024*1024)}MB'}), 400
        
        if len(file_bytes) == 0:
            return jsonify({'error': 'File is empty'}), 400
        
        # Validate PDF format
        if file_bytes[:4] != b'%PDF':
            return jsonify({'error': 'Invalid PDF file format'}), 400
        
        # Get user ID
        user_id = data.get('user_id')
        if not user_id:
            try:
                user_id = get_jwt_identity()
            except:
                pass
        
        # Generate unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        
        if user_id:
            new_filename = f"{user_id}_{timestamp}_{unique_id}_{filename}"
        else:
            new_filename = f"anonymous_{timestamp}_{unique_id}_{filename}"
        
        # Ensure upload directory exists
        upload_path = os.path.join(current_app.root_path, '..', UPLOAD_FOLDER)
        os.makedirs(upload_path, exist_ok=True)
        
        # Save file
        file_path = os.path.join(upload_path, new_filename)
        with open(file_path, 'wb') as f:
            f.write(file_bytes)
        
        return jsonify({
            'success': True,
            'file_path': os.path.join(UPLOAD_FOLDER, new_filename),
            'filename': new_filename,
            'original_name': filename,
            'file_size': len(file_bytes),
            'uploaded_at': datetime.now().isoformat(),
            'user_id': user_id
        }), 200
        
    except Exception as e:
        print(f"Base64 upload error: {e}")
        return jsonify({
            'error': 'Failed to upload file',
            'details': str(e)
        }), 500

@resume_bp.route('/validate-pdf', methods=['POST'])
def validate_pdf():
    """
    Validate PDF file without saving
    
    Use this to check file before upload
    """
    try:
        if 'file' not in request.files:
            return jsonify({'valid': False, 'error': 'No file provided'}), 200
        
        file = request.files['file']
        
        try:
            validate_pdf_file(file)
            return jsonify({
                'valid': True,
                'message': 'Valid PDF file',
                'filename': secure_filename(file.filename)
            }), 200
        except ValueError as e:
            return jsonify({
                'valid': False,
                'error': str(e)
            }), 200
            
    except Exception as e:
        return jsonify({
            'valid': False,
            'error': 'Validation failed'
        }), 500

# Optional: Extract text from PDF
def extract_pdf_text(file_path):
    """Extract text content from PDF file"""
    try:
        import PyPDF2
        
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            
            for page in reader.pages:
                text += page.extract_text() + "\n"
            
            return text.strip()
    except Exception as e:
        print(f"PDF text extraction error: {e}")
        return None

# Optional: Get PDF metadata
def get_pdf_metadata(file_path):
    """Get PDF metadata"""
    try:
        import PyPDF2
        
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            info = reader.metadata
            
            return {
                'title': info.get('/Title', ''),
                'author': info.get('/Author', ''),
                'subject': info.get('/Subject', ''),
                'creator': info.get('/Creator', ''),
                'producer': info.get('/Producer', ''),
                'creation_date': info.get('/CreationDate', ''),
                'pages': len(reader.pages)
            }
    except Exception as e:
        print(f"PDF metadata extraction error: {e}")
        return None