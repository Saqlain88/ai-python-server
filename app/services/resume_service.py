import os
import io
import json
from openai import OpenAI
from flask import render_template
from weasyprint import HTML  # pip install weasyprint
from flask_mail import Message
from app import mail, db
from app.models.resume import Resume
from app.models.template import Template
import fitz  # PyMuPDF
from werkzeug.utils import secure_filename
import re
import json
from app.services.image_service import ImageService
import cloudinary.uploader
import cloudinary
from app.services.hf_service import generate_text, generate_json, HFError


# initialize openai client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# You may store simple templates on disk or in DB. For demo, two simple template IDs:
TEMPLATES = [
    {"id": "modern", "name": "Modern"},
    {"id": "classic", "name": "Classic"}
]

# def upload_image(file_path, public_id=None):
#     try:
#         response = cloudinary.uploader.upload(
#             file_path,
#             public_id=public_id,
#             overwrite=True,
#             resource_type="image"
#         )
#         return response
#     except Exception as e:
#         print(f"Image upload failed: {e}")
#         return None

# def create_templates(title: str, thumbnail: str, category: str):
#     response = ImageService.upload_image(thumbnail, public_id=f"uploads/{title.lower().replace(' ','_')}")
#     if not response or 'secure_url' not in response:
#         raise RuntimeError("Failed to upload template thumbnail to Cloudinary.")
#     template = Template(title=title, thumbnail=response.secure_url, category=category)
#     db.session.add(template)
#     db.session.commit()
#     return template

def list_templates():
    return TEMPLATES

def create_resume(user_id: int, template_id: str, content: dict) -> Resume:
    resume = Resume(user_id=user_id, template_id=template_id, content=content)
    db.session.add(resume)
    db.session.commit()
    return resume

def update_resume(resume: Resume, content: dict = None, template_id: str = None) -> Resume:
    if content is not None:
        resume.content = content
    if template_id is not None:
        resume.template_id = template_id
    db.session.commit()
    return resume


def get_resume_by_id(resume_id: int, user_id: int) -> Resume:
    return Resume.query.filter_by(id=resume_id, user_id=user_id).first()


# ---- ATS Analysis using AI ----
# We will ask the model to produce a structured JSON {score, explanation, suggestions: [...]}
def ats_check_resume(resume_content: dict) -> dict:
    """
    Send the resume content to OpenAI and ask it to return:
    { score: int (0-100), summary: str, suggestions: [ {section, suggestion, importance}] }
    """
    prompt = f"""
You are an expert ATS resume reviewer. The user will give you a resume JSON.
Return a JSON object EXACTLY with the following keys:
- score: integer 0-100 (higher is better)
- summary: short text (1-3 sentences)
- suggestions: array of objects with keys: section (e.g. experience, skills, projects), suggestion (text), importance (low|medium|high)
Analyze for general ATS compliance and keyword usage, formatting tips, and length. Do not include any other keys.

Resume JSON:
{json.dumps(resume_content, indent=2)}
"""
    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resp = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful resume reviewer who outputs JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        text = resp.choices[0].message.content.strip()
        # Attempt to parse returned JSON
        parsed = json.loads(text)
        # ensure types
        score = int(parsed.get("score", 0))
        return {
            "score": score,
            "summary": parsed.get("summary", ""),
            "suggestions": parsed.get("suggestions", []),
            "raw": text
        }
    except Exception as e:
        # fallback simple heuristic scoring if AI fails
        return {
            "score": 40,
            "summary": "Automated analysis unavailable. Try again later.",
            "suggestions": [{"section": "general", "suggestion": "Retry ATS check.", "importance": "low"}],
            "error": str(e)
        }


# ---- AI Modifier: generate multiple improved suggestions for sections ----
def generate_modifications(resume_content: dict, max_suggestions_per_section=3) -> dict:
    """
    Ask AI to propose multiple rewrites (suggestions) for the resume content.
    Returns a dict: {section: [ {label, text} ] }
    """
    prompt = f"""
You are an expert resume rewriting assistant. Given the resume JSON below, produce multiple alternate suggestions for improving content to increase ATS score.
Return JSON structured as:
{{ "experience": [{{"title":"Suggestion 1","text":"..."}}, ...], "skills":[...], "summary":[...], "projects":[...], "achievements":[...] }}

Provide up to {max_suggestions_per_section} suggestions per section. Do not include any extra text.
Resume:
{json.dumps(resume_content, indent=2)}
"""
    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resp = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a resume writer that outputs JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        text = resp.choices[0].message.content.strip()
        parsed = json.loads(text)
        return {"modified_suggestions": parsed, "raw": text}
    except Exception as e:
        return {"modified_suggestions": {}, "error": str(e)}


# ---- Apply an AI-chosen modification automatically (auto-generate new content) ----
def apply_auto_modifications(resume: Resume, modifications: dict) -> Resume:
    """
    modifications should be a dict structured like the suggestions returned above.
    We'll take first suggestion for each section and replace content.
    """
    content = resume.content.copy()
    # Example: replace skills, experiences, projects etc. if suggestions exist
    if "skills" in modifications and isinstance(modifications["skills"], list) and modifications["skills"]:
        # expect suggestions to be texts; take first suggestion and split by comma or newline
        s = modifications["skills"][0]
        if isinstance(s, dict) and "text" in s:
            # parse single suggestion text into list
            content["skills"] = [x.strip() for x in s["text"].split(",") if x.strip()]
        elif isinstance(s, str):
            content["skills"] = [x.strip() for x in s.split(",") if x.strip()]

    if "experience" in modifications and isinstance(modifications["experience"], list) and modifications["experience"]:
        # naive replacement: map suggestions back to experience entries
        # Here we replace descriptions of experience entries if suggestions provided in order
        for i, exp in enumerate(content.get("experience", [])):
            if i < len(modifications["experience"]):
                sugg = modifications["experience"][i]
                content["experience"][i]["description"] = sugg.get("text") if isinstance(sugg, dict) else str(sugg)

    # update resume and persist
    resume.content = content
    db.session.commit()
    return resume


# ---- PDF generation ----
def render_resume_html(template_id: str, content: dict) -> str:
    """
    Render HTML for the selected template. Use Jinja2 templates (templates/resume_modern.html etc.)
    For demo, we can build a minimal HTML string. Prefer using real templates.
    """
    # If you have Jinja templates, use render_template('resume_modern.html', content=content)
    # For demo fallback:
    name = content.get("name", "")
    title = content.get("title", "")
    email = content.get("email", "")
    phone = content.get("phone", "")
    skills = content.get("skills", [])
    experience = content.get("experience", [])

    html = render_template(f"resumes/{template_id}.html", content=content) if os.path.exists("templates/resumes/{}.html".format(template_id)) else f"""
    <html>
    <head>
      <meta charset="utf-8"/>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ text-align: center; }}
        .section {{ margin-top: 16px; }}
        .section h3 {{ border-bottom: 1px solid #eee; padding-bottom: 4px; }}
      </style>
    </head>
    <body>
      <div class="header">
        <h1>{name}</h1>
        <h3>{title}</h3>
        <div>{email} • {phone}</div>
      </div>

      <div class="section">
        <h3>Skills</h3>
        <div>{', '.join(skills)}</div>
      </div>

      <div class="section">
        <h3>Experience</h3>
        {"".join([f"<div><strong>{e.get('position')} - {e.get('company')}</strong><div>{e.get('duration')}</div><p>{e.get('description')}</p></div>" for e in experience])}
      </div>
    </body>
    </html>
    """
    return html


def generate_pdf_bytes(template_id: str, content: dict) -> bytes:
    html = render_resume_html(template_id, content)
    pdf_io = io.BytesIO()
    HTML(string=html).write_pdf(pdf_io)
    pdf_io.seek(0)
    return pdf_io.read()


# ---- Send to HR with AI-generated email ----
def generate_hr_email(resume: Resume, hr_info: dict) -> dict:
    """
    hr_info: { hr_name, hr_email, company_name, company_address, company_email, experience_applied_for }
    Returns {subject, body}
    """
    prompt = f"""
You are an expert professional who writes concise, persuasive outreach emails to HR/Recruiters to apply for roles.
Candidate resume JSON:
{json.dumps(resume.content, indent=2)}

Target HR/contact:
{json.dumps(hr_info, indent=2)}

Write a professional email subject and body. Keep body polite, concise (<= 300 words), mention 2-3 key achievements from resume, and include a short closing. Return a JSON object: {{ "subject":"...", "body":"..." }}
"""
    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resp = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a professional email writer that outputs JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=500,
        )
        text = resp.choices[0].message.content.strip()
        return json.loads(text)
    except Exception as e:
        return {"subject": f"Application - {resume.content.get('name','Candidate')}", "body": "Please contact candidate. Error generating email: " + str(e)}


def send_resume_to_hr(resume: Resume, hr_info: dict, pdf_bytes: bytes):
    """
    Sends an email to HR with the generated PDF attached. Requires flask-mail configured.
    hr_info: {hr_name, hr_email, company_name, company_address, company_email}
    """
    email_content = generate_hr_email(resume, hr_info)
    subject = email_content.get("subject", f"Application from {resume.content.get('name','Candidate')}")
    body = email_content.get("body", "")

    msg = Message(
        subject,
        recipients=[hr_info.get("hr_email")],
        body=body,
        sender=os.getenv("MAIL_USERNAME") or os.getenv("FROM_EMAIL")
    )
    # attach pdf
    msg.attach(f"{resume.content.get('name','resume')}.pdf", "application/pdf", pdf_bytes)
    mail.send(msg)
    return {"status": "sent", "to": hr_info.get("hr_email")}


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF file using PyMuPDF."""
    text = ""
    try:
        with fitz.open(file_path) as pdf:
            for page in pdf:
                text += page.get_text("text")
    except Exception as e:
        raise RuntimeError(f"Error reading PDF: {e}")
    return text.strip()

def analyze_pdf_resume(file_storage) -> dict:
    """
    Save uploaded file temporarily, extract text, and run ATS check using OpenAI.
    """
    filename = secure_filename(file_storage.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    file_storage.save(file_path)

    # Step 1: Extract text
    text = extract_text_from_pdf(file_path)
    if not text:
        raise ValueError("Could not extract text from the PDF.")

    # Step 2: Use AI to analyze resume content
    prompt = f"""
You are an expert ATS analyzer. Analyze the following resume text and return JSON ONLY with:
- score: integer 0-100
- rating: one of ['bad','average','good','excellent']
- summary: short summary of resume strengths
- suggestions: array of objects {{section, suggestion, importance}}

Resume Text:
{text[:6000]}  # truncate for token safety
"""

    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resp = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an ATS resume evaluator that outputs JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        ai_response = resp.choices[0].message.content.strip()
        result = json.loads(ai_response)

        # Validate structure
        score = int(result.get("score", 0))
        if score < 40:
            rating = "bad"
        elif score < 60:
            rating = "average"
        elif score < 80:
            rating = "good"
        else:
            rating = "excellent"

        result["rating"] = rating
        return result
    except Exception as e:
        raise RuntimeError(f"Error analyzing resume: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def analyze_resume_vs_job(resume_file, job_description_text=None, job_description_file=None):
    """
    Compare resume content (PDF) with job description text or file.
    Return ATS match report.
    """
    filename = secure_filename(resume_file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    resume_file.save(file_path)

    # Extract resume text
    resume_text = extract_text_from_pdf(file_path)

    # Extract or read job description
    jd_text = ""
    if job_description_text:
        jd_text = job_description_text
    elif job_description_file:
        jd_filename = secure_filename(job_description_file.filename)
        jd_path = os.path.join(UPLOAD_FOLDER, jd_filename)
        job_description_file.save(jd_path)
        jd_text = extract_text_from_pdf(jd_path)
        os.remove(jd_path)
    else:
        raise ValueError("Job description not provided.")

    # Cleanup
    if os.path.exists(file_path):
        os.remove(file_path)

    # --- AI Prompt ---
    prompt = f"""
You are an ATS resume evaluator and recruiter assistant.
Compare the following resume and job description.

Return JSON ONLY with fields:
- match_score: integer (0-100)
- rating: one of ['bad','average','good','excellent']
- missing_keywords: array of strings (keywords from JD missing in resume)
- summary: short summary of alignment
- suggestions: array of objects {{section, suggestion}}

Resume:
{resume_text[:6000]}

Job Description:
{jd_text[:3000]}
"""

    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        response = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an ATS resume evaluator that outputs JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=800,
        )
        # ai_response = response.choices[0].message.content.strip()

        # print("\n\n🧠 RAW AI RESPONSE:\n", ai_response, "\n\n")  # 👈 Debug line

        ai_response = response.choices[0].message.content.strip()
        # print("\n\n🧠 RAW AI RESPONSE:\n", ai_response, "\n\n")

        # --- Clean Markdown Wrappers ---
        # Removes ```json ... ``` or ``` ... ```
        cleaned = re.sub(r"^```[a-zA-Z]*\n|```$", "", ai_response, flags=re.MULTILINE).strip()

        # --- Try to extract JSON if surrounded by extra text ---
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                raise RuntimeError(f"AI returned invalid JSON after cleaning: {cleaned[:300]}")

        # Try parsing safely
        # try:
        #     result = json.loads(ai_response)
        # except json.JSONDecodeError as e:
        #     raise RuntimeError(f"AI returned invalid JSON: {ai_response[:500]}")
        #     # result = json.loads(ai_response)
        # result = json.loads(ai_response)

        score = int(result.get("match_score", 0))
        if score < 40:
            rating = "bad"
        elif score < 60:
            rating = "average"
        elif score < 80:
            rating = "good"
        else:
            rating = "excellent"

        result["rating"] = rating
        return result
    except Exception as e:
        raise RuntimeError(f"Error analyzing resume and job match: {e}")
    

# --- ADD: HF-based ATS resume analysis (structured JSON) ---
def ats_check_resume_hf(resume_content: dict) -> dict:
    """
    Hugging Face version of ATS check that returns:
    { score:int, summary:str, suggestions:[{section, suggestion, importance}] }
    """
    prompt = f"""
You are an expert ATS resume reviewer. The user will give you a resume JSON.
Return a JSON object EXACTLY with the following keys:
- score: integer 0-100 (higher is better)
- summary: short text (1-3 sentences)
- suggestions: array of objects with keys: section (e.g. experience, skills, projects), suggestion (text), importance (low|medium|high)
Analyze for ATS compliance, keyword usage, formatting, and length. Do not include any other keys.

Resume JSON:
{json.dumps(resume_content, indent=2)}
"""
    try:
        parsed = generate_json(prompt, max_new_tokens=800, temperature=0.2)
        score = int(parsed.get("score", 0))
        return {
            "score": score,
            "summary": parsed.get("summary", ""),
            "suggestions": parsed.get("suggestions", []),
            "raw": json.dumps(parsed)
        }
    except Exception as e:
        return {
            "score": 40,
            "summary": "Automated analysis unavailable. Try again later.",
            "suggestions": [{"section": "general", "suggestion": "Retry ATS check.", "importance": "low"}],
            "error": str(e)
        }

# --- ADD: HF-based email generation for HR ---
def generate_hr_email_hf(resume: Resume, hr_info: dict) -> dict:
    """
    hr_info: { hr_name, hr_email, company_name, company_address, company_email, experience_applied_for }
    Returns {subject, body}
    """
    prompt = f"""
You are an expert professional who writes concise, persuasive outreach emails to HR/Recruiters to apply for roles.
Candidate resume JSON:
{json.dumps(resume.content, indent=2)}

Target HR/contact:
{json.dumps(hr_info, indent=2)}

Write a professional email subject and body. Keep body polite, concise (<= 300 words), mention 2-3 key achievements from resume, and include a short closing.
Return a JSON object with exactly: {{ "subject":"...", "body":"..." }}
"""
    try:
        return generate_json(prompt, max_new_tokens=600, temperature=0.5)
    except Exception as e:
        return {"subject": f"Application - {resume.content.get('name','Candidate')}", "body": "Please contact candidate. Error generating email: " + str(e)}

# --- ADD: HF-based PDF resume text analysis (single file) ---
def analyze_pdf_resume_hf(file_storage) -> dict:
    """
    Save uploaded file temporarily, extract text, and run ATS check using HF.
    """
    filename = secure_filename(file_storage.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    file_storage.save(file_path)

    text = extract_text_from_pdf(file_path)
    if not text:
        raise ValueError("Could not extract text from the PDF.")

    prompt = f"""
You are an expert ATS analyzer. Analyze the following resume text and return JSON ONLY with:
- score: integer 0-100
- rating: one of ['bad','average','good','excellent']
- summary: short summary of resume strengths
- suggestions: array of objects {{section, suggestion, importance}}
Resume Text:
{text[:6000]}
"""
    try:
        result = generate_json(prompt, max_new_tokens=800, temperature=0.2)
        score = int(result.get("score", 0))
        if score < 40:
            rating = "bad"
        elif score < 60:
            rating = "average"
        elif score < 80:
            rating = "good"
        else:
            rating = "excellent"
        result["rating"] = rating
        return result
    except Exception as e:
        raise RuntimeError(f"Error analyzing resume: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# --- ADD: HF-based resume vs JD comparison ---
def analyze_resume_vs_job_hf(resume_file, job_description_text=None, job_description_file=None):
    filename = secure_filename(resume_file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    resume_file.save(file_path)

    resume_text = extract_text_from_pdf(file_path)

    jd_text = ""
    if job_description_text:
        jd_text = job_description_text
    elif job_description_file:
        jd_filename = secure_filename(job_description_file.filename)
        jd_path = os.path.join(UPLOAD_FOLDER, jd_filename)
        job_description_file.save(jd_path)
        jd_text = extract_text_from_pdf(jd_path)
        os.remove(jd_path)
    else:
        raise ValueError("Job description not provided.")

    if os.path.exists(file_path):
        os.remove(file_path)

    prompt = f"""
You are an ATS resume evaluator and recruiter assistant.
Compare the following resume and job description.

Return JSON ONLY with fields:
- match_score: integer (0-100)
- rating: one of ['bad','average','good','excellent']
- missing_keywords: array of strings (keywords from JD missing in resume)
- summary: short summary of alignment
- suggestions: array of objects {{section, suggestion}}

Resume:
{resume_text[:6000]}

Job Description:
{jd_text[:3000]}
"""
    try:
        result = generate_json(prompt, max_new_tokens=800, temperature=0.3)
        score = int(result.get("match_score", 0))
        if score < 40:
            rating = "bad"
        elif score < 60:
            rating = "average"
        elif score < 80:
            rating = "good"
        else:
            rating = "excellent"
        result["rating"] = rating
        return result
    except Exception as e:
        raise RuntimeError(f"Error analyzing resume and job match: {e}")

