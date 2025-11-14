# agent_route.py
import os
import json
import uuid
import tempfile
from datetime import datetime
from typing import List

from flask import Blueprint, request, jsonify, current_app, Response, stream_with_context
from flask_jwt_extended import get_jwt_identity
from flask_mail import Message as MailMessage

# LangChain/OpenAI imports (keep as used in your repo)
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import Tool
from langchain_core.messages import HumanMessage, AIMessage

from app import db, mail
from app.models.user import User
from app.models.resume import Resume

agent_bp = Blueprint('agent', __name__)

# =========================
# Helper: Response Formatter
# =========================
def format_response(content, action=None, route=None, success=None, data=None):
    """
    Standardizes assistant responses for frontend rendering.
    - Accepts plain strings or structured lists.
    - Outputs consistent JSON for React/React Native/HTML rendering.
    """
    if isinstance(content, str):
        formatted = [{"type": "text", "value": content}]
    else:
        formatted = content

    response = {"type": "assistant_reply", "content": formatted}
    if action:
        response["action"] = action
    if route:
        response["route"] = route
    if success is not None:
        response["success"] = success
    if data:
        response["data"] = data
    return response


# =========================
# Initialize LLM
# =========================
def get_llm():
    """
    Returns a configured ChatOpenAI instance.
    - Allows configuring via env variables:
      * OPENAI_API_KEY (default)
      * LLM_MODEL (optional model name override)
      * LLM_TEMPERATURE
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("No LLM API key found in environment variables. Set OPENAI_API_KEY or GROQ_API_KEY")

    model = os.environ.get("LLM_MODEL", "gpt-4")
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0.6"))

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        openai_api_key=api_key
    )


# =========================
# Conversation State Manager
# =========================
class ConversationStateManager:
    def __init__(self):
        # simple in-memory dict; in production use redis or DB for persistence / multi-process
        self.states = {}

    def get_state(self, session_id: str) -> dict:
        if session_id not in self.states:
            self.states[session_id] = {
                "current_flow": None,
                "step": "initial",
                "data": {},
                "awaiting": None,
                "history": []  # store simple list of turns if desired
            }
        return self.states[session_id]

    def update_state(self, session_id: str, updates: dict):
        state = self.get_state(session_id)
        state.update(updates)
        return state

    def reset_state(self, session_id: str):
        if session_id in self.states:
            del self.states[session_id]


state_manager = ConversationStateManager()


# =========================
# Intent Recognition Tool
# =========================
def recognize_intent(query: str) -> dict:
    query_lower = (query or "").lower()

    intents = {
        "resume_maker": ["resume maker", "create resume", "build resume", "make resume"],
        "ats_checker": ["ats", "ats check", "resume check", "check resume", "ats score"],
        "code_generator": ["code generator", "generate code", "create code", "code gen"],
        "image_generator": ["image generator", "generate image", "create image"],
        "send_to_hr": ["send resume", "send to hr", "email hr", "apply job", "apply to job"]
    }

    for intent, keywords in intents.items():
        if any(keyword in query_lower for keyword in keywords):
            return {"intent": intent, "confidence": 0.9}

    return {"intent": "unknown", "confidence": 0.0}


# =========================
# Email Generator
# =========================
def generate_email_content(hr_name: str,
                           company_name: str,
                           job_description: str,
                           user_name: str,
                           resume_summary: str = "",
                           skills: str = "",
                           experience: str = "") -> str:
    """
    Generate a professional job application email using JD + resume summary + skills + experience.
    Returns a string (the email body).
    """
    try:
        llm = get_llm()
        prompt = f"""
You are a professional assistant that writes concise job application emails.

HR Name: {hr_name}
Company: {company_name}
Applicant Name: {user_name}

Job Description:
{job_description}

Candidate summary:
{resume_summary}

Candidate skills:
{skills}

Candidate experience summary:
{experience}

Requirements:
- Write a clear, professional email of ~180-220 words.
- Include a strong opening sentence connecting candidate experience/skills to the JD.
- State that the resume is attached.
- Add a friendly but professional closing with contact details.
- Keep tone confident and concise.
"""
        # If your ChatOpenAI supports a simple call style, adapt accordingly.
        # Here we use a blocking call and return full content.
        response = llm.invoke(prompt)
        if hasattr(response, "content"):
            return response.content
        return str(response)
    except Exception as e:
        current_app.logger.exception("Error generating email content")
        # Fallback minimal email
        return f"""Dear {hr_name},

I am writing to express my interest in the role at {company_name}. Please find my resume attached for your consideration. I have relevant experience and skills that match the job description and would welcome the opportunity to discuss further.

Best regards,
{user_name}
"""


# =========================
# Agent Setup (kept for future use)
# =========================
def create_agent_tools():
    return [
        Tool(
            name="IntentRecognizer",
            func=recognize_intent,
            description="Recognizes user intent from message."
        )
    ]


def get_agent_prompt():
    return ChatPromptTemplate.from_messages([
        ("system", """You are a helpful AI assistant for a web app with features:
        1️⃣ Resume Maker
        2️⃣ ATS Checker
        3️⃣ Code Generator
        4️⃣ Image Generator
        5️⃣ Send Resume to HR
        Always guide users clearly and concisely. Use emojis lightly.
        """),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad")
    ])


def create_agent():
    try:
        llm = get_llm()
        tools = create_agent_tools()
        prompt = get_agent_prompt()
        agent = create_openai_functions_agent(llm, tools, prompt)
        return AgentExecutor(agent=agent, tools=tools, verbose=True)
    except Exception as e:
        current_app.logger.exception("Agent creation error")
        return None


# =========================
# Helpers to extract resume fields
# =========================
def extract_resume_fields_from_content(content_json: dict) -> dict:
    if not content_json:
        return {"name": "", "email": "", "skills": "", "experience": "", "resume_summary": ""}

    name = content_json.get("name") or content_json.get("basics", {}).get("name", "")
    email = content_json.get("email") or content_json.get("basics", {}).get("email", "")
    skills_list = content_json.get("skills", [])
    if isinstance(skills_list, list):
        parsed_skills = []
        for s in skills_list:
            if isinstance(s, str):
                parsed_skills.append(s)
            elif isinstance(s, dict):
                parsed_skills.append(s.get("name") or s.get("skill") or "")
        skills = ", ".join([s for s in parsed_skills if s])
    else:
        skills = str(skills_list)

    exp_items = content_json.get("experience") or content_json.get("work") or []
    if isinstance(exp_items, list) and len(exp_items) > 0:
        exp_summaries = []
        for e in exp_items[:3]:
            company = e.get("company") or e.get("employer") or ""
            title = e.get("position") or e.get("title") or ""
            desc = e.get("description") or e.get("summary") or ""
            dur = e.get("duration") or e.get("startDate", "") or e.get("endDate", "")
            parts = [p for p in [title, company, dur] if p]
            header = " - ".join(parts) if parts else ""
            if desc:
                exp_summaries.append(f"{header}: {desc}")
            else:
                exp_summaries.append(header)
        experience = " | ".join(exp_summaries)
    else:
        experience = ""

    resume_summary = content_json.get("summary") or content_json.get("about") or ""
    if not resume_summary:
        resume_summary = ""
        if exp_items:
            first = exp_items[0]
            resume_summary = first.get("description", "")[:400]
        if skills:
            resume_summary = (resume_summary + "\nTop skills: " + skills) if resume_summary else ("Top skills: " + skills)

    return {
        "name": name,
        "email": email,
        "skills": skills,
        "experience": experience,
        "resume_summary": resume_summary
    }


# =========================
# Conversation Processor
# =========================
def process_conversation(message: str, history: List[dict], session_id: str, user_id: str = None) -> dict:
    """
    Main synchronous processor. Uses session_id for state isolation.
    Returns a formatted response dict (same as format_response output).
    """
    state = state_manager.get_state(session_id)
    intent_result = recognize_intent(message)

    # Build chat_history for agent if needed
    chat_history = []
    for msg in (history or [])[-10:]:
        if msg.get('sender') == 'user':
            chat_history.append(HumanMessage(content=msg.get('text', '')))
        elif msg.get('sender') == 'bot':
            chat_history.append(AIMessage(content=msg.get('text', '')))

    # Universal commands
    lower_msg = (message or "").lower().strip()
    if lower_msg in ["restart", "reset", "start over"]:
        state_manager.reset_state(session_id)
        return format_response([
            {"type": "text", "value": "🔄 Conversation restarted!"},
            {"type": "text", "value": "I can help you with:"},
            {"type": "list", "items": [
                "1️⃣ Resume Maker",
                "2️⃣ ATS Checker",
                "3️⃣ Code Generator",
                "4️⃣ Image Generator",
                "5️⃣ Send Resume to HR"
            ]}
        ], action="menu")

    if lower_msg in ["help", "how you help me", "features", "what can you do", "menu", "give me features"]:
        return format_response([
            {"type": "text", "value": "Here’s what I can help you with ✨"},
            {"type": "list", "items": [
                "1️⃣ Resume Maker",
                "2️⃣ ATS Checker",
                "3️⃣ Code Generator",
                "4️⃣ Image Generator",
                "5️⃣ Send Resume to HR"
            ]}
        ], action="menu")

    # If user currently in a send_to_hr flow, delegate
    if state["current_flow"] == "send_to_hr":
        return handle_send_to_hr_flow(message, state, session_id, user_id)

    # Intent routing
    if intent_result["intent"] != "unknown":
        if intent_result["intent"] == "send_to_hr":
            state_manager.update_state(session_id, {
                "current_flow": "send_to_hr",
                "step": "choose_method",
                "data": {}
            })
            return format_response([
                {"type": "text", "value": "I can help you send your resume to HR! 📧"},
                {"type": "list", "items": ["1 By Resume ID", "2️ Upload PDF file"]}
            ], action="choose_resume_method", route="/resume/send-hr")

        routes = {
            "resume_maker": "/resume-maker",
            "ats_checker": "/resume/ats-check",
            "code_generator": "/code-generator",
            "image_generator": "/image-generator"
        }
        feature_names = {
            "resume_maker": "Resume Maker",
            "ats_checker": "ATS Checker",
            "code_generator": "Code Generator",
            "image_generator": "Image Generator"
        }

        route = routes.get(intent_result["intent"])
        feature = feature_names.get(intent_result["intent"], "feature")
        return format_response(
            [{"type": "text", "value": f"Great! I'll take you to the {feature}. ✨"}],
            action="navigate",
            route=route
        )

    # Default fallback
    return format_response([
        {"type": "text", "value": "I can help you with:"},
        {"type": "list", "items": [
            "Resume Maker",
            "ATS Checker",
            "Code Generator",
            "Image Generator",
            "Send Resume to HR"
        ]}
    ], action="menu")


# =========================
# Send to HR Flow (unchanged logic but uses session_id)
# =========================

@agent_bp.route('/agent/upload-resume', methods=['POST'])
def upload_resume_file():
    try:
        session_id = request.form.get("session_id")
        file = request.files.get("file")

        if not session_id:
            return jsonify({"error": "session_id required"}), 400
        
        if not file:
            return jsonify({"error": "PDF file required"}), 400
        
        # read file binary
        pdf_bytes = file.read()

        # save in state for that session
        state = state_manager.get_state(session_id)
        state["uploaded_pdf"] = pdf_bytes

        return jsonify({
            "success": True,
            "message": "PDF uploaded successfully"
        }), 200

    except Exception as e:
        current_app.logger.exception("Upload error")
        return jsonify({"error": "Upload failed"}), 500

def handle_send_to_hr_flow(message: str, state: dict, session_id: str, user_id: str = None) -> dict:
    step = state["step"]
    data = state["data"] or {}

    # Step 1: Choose method
    if step == "choose_method":
        lower = (message or "").lower()
        if ("1" in lower) or ("resume" in lower and "id" in lower):
            state_manager.update_state(session_id, {"step": "ask_resume_id", "data": data})
            return format_response("Please provide your Resume ID:", action="collect_resume_id")
        elif ("2" in lower) or ("upload" in lower) or ("pdf" in lower):
            state_manager.update_state(session_id, {"step": "ask_pdf", "data": data})
            return format_response("Please upload your resume PDF file (or reply 'skip' to use stored resume):", action="collect_pdf")
        else:
            return format_response("Please choose 1 (Resume ID) or 2 (Upload PDF).", action="choose_resume_method")

    # Step 2: Ask HR Name (after resume selection)
    if step in ["ask_resume_id", "ask_pdf"]:
        data["resume_method"] = "id" if step == "ask_resume_id" else "pdf"
        state_manager.update_state(session_id, {"step": "ask_hr_name", "data": data})
        return format_response("Got it! What is the HR Manager’s name?", action="collect_hr_name")

    # Step 3: HR Email
    if step == "ask_hr_name":
        data["hr_name"] = message.strip()
        state_manager.update_state(session_id, {"step": "ask_hr_email", "data": data})
        return format_response(f"Great! What is {data['hr_name']}'s email address?", action="collect_hr_email")

    # Step 4: Company Name
    if step == "ask_hr_email":
        email = message.strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            return format_response("Invalid email. Please enter again:", action="collect_hr_email")
        data["hr_email"] = email
        state_manager.update_state(session_id, {"step": "ask_company_name", "data": data})
        return format_response("🏢 What is the company name?", action="collect_company_name")

    # Step 5: Job Description
    if step == "ask_company_name":
        data["company_name"] = message.strip()
        state_manager.update_state(session_id, {"step": "ask_jd", "data": data})
        return format_response("Please provide the Job Description (JD):", action="collect_jd")

    # Step 6: Receive JD and generate email preview
    if step == "ask_jd":
        data["job_description"] = message.strip()
        # fetch user info / resume to include in prompt
        user_name = "Candidate"
        resume_text = ""
        resume_content_json = {}
        skills = ""
        experience = ""
        resume_summary = ""

        if user_id:
            user = User.query.get(user_id)
            if user:
                user_name = user.name or (user.email.split('@')[0] if user.email else "Candidate")

            user_resume = Resume.query.filter_by(user_id=user_id).first()
            if user_resume:
                resume_content_json = user_resume.content or {}
                extracted = extract_resume_fields_from_content(resume_content_json)
                skills = extracted.get("skills", "")
                experience = extracted.get("experience", "")
                resume_summary = extracted.get("resume_summary", "")
                try:
                    resume_text = json.dumps(resume_content_json, indent=2)[:3000]
                except Exception:
                    resume_text = str(resume_content_json)[:3000]

        email_content = generate_email_content(
            hr_name=data.get("hr_name", "Hiring Manager"),
            company_name=data.get("company_name", ""),
            job_description=data.get("job_description", ""),
            user_name=user_name,
            resume_summary=resume_summary,
            skills=skills,
            experience=experience
        )

        data["generated_email"] = email_content
        data["user_name"] = user_name
        data["resume_content_json"] = resume_content_json
        data["resume_text"] = resume_text
        state_manager.update_state(session_id, {"step": "confirm_send", "data": data})

        return format_response([
            {"type": "text", "value": "✨ Here's the generated email:"},
            {"type": "divider"},
            {"type": "email_preview", "value": email_content},
            {"type": "divider"},
            {"type": "text", "value": "Would you like to send this email?"},
            {"type": "list", "items": ["yes - send", "no - cancel", "edit - modify"]}
        ], action="confirm_send", data={"email_preview": email_content})

    # Step 7: Confirm send
    if step == "confirm_send":
        msg = (message or "").lower().strip()
        # if "yes" in msg or msg == "send":
        #     try:
        #         subject = f"Application for role at {data.get('company_name','Company')}"
        #         body = data.get("generated_email") or "Please find my application attached."
        #         recipient = data.get("hr_email")
        #         sender = current_app.config.get("MAIL_DEFAULT_SENDER") or data.get("user_name") or "noreply@example.com"

        #         mail_msg = MailMessage(subject=subject, recipients=[recipient], body=body, sender=sender)

        #         attached = False
        #         resume_text = data.get("resume_text", "")
        #         if resume_text:
        #             tf = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
        #             tf.write(resume_text)
        #             tf.flush()
        #             tf.close()
        #             try:
        #                 with open(tf.name, "rb") as f:
        #                     mail_msg.attach(filename=f"{data.get('user_name', 'resume')}.txt",
        #                                     content_type="text/plain",
        #                                     data=f.read())
        #                     attached = True
        #             except Exception:
        #                 current_app.logger.exception("Failed to attach resume file")
        #         mail.send(mail_msg)
        #         state_manager.reset_state(session_id)
        #         return format_response("Email sent successfully to HR! ✅ (Resume attached)" if attached else "Email sent successfully to HR! ✅", action="email_sent", success=True)
        #     except Exception as e:
        #         current_app.logger.exception("Failed to send email")
        #         return format_response("There was an error sending the email. Please try again or type 'restart' to start over.", action="email_error", success=False)
        if "yes" in msg or msg == "send":
            try:
                subject = f"Application for role at {data.get('company_name','Company')}"
                body = data.get("generated_email") or "Please find my application attached."
                recipient = data.get("hr_email")
                sender = current_app.config.get("MAIL_DEFAULT_SENDER") or "noreply@example.com"
                mail_msg = MailMessage(subject=subject, recipients=[recipient], body=body, sender=sender)

                attached = False
                
                state = state_manager.get_state(session_id)

                # ---------------------------------------------
                # 1️⃣ IF USER UPLOADED PDF → ATTACH THAT
                # ---------------------------------------------
                uploaded_pdf = state.get("uploaded_pdf")
                if uploaded_pdf:
                    mail_msg.attach(
                        filename="Resume.pdf",
                        content_type="application/pdf",
                        data=uploaded_pdf
                    )
                    attached = True

                # ---------------------------------------------
                # 2️⃣ IF Resume ID method → attach stored DB resume as PDF (if exist)
                # ---------------------------------------------
                elif data.get("resume_method") == "id" and user_id:
                    db_resume = Resume.query.filter_by(user_id=user_id).first()
                    if db_resume and db_resume.template_id == "pdf":
                        pdf_path = db_resume.content.get("pdf_path")
                        if pdf_path and os.path.exists(pdf_path):
                            with open(pdf_path, "rb") as f:
                                mail_msg.attach("Resume.pdf", "application/pdf", f.read())
                                attached = True

                # ---------------------------------------------
                # 3️⃣ Otherwise attach JSON resume as .txt (fallback)
                # ---------------------------------------------
                else:
                    resume_text = data.get("resume_text", "")
                    if resume_text:
                        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
                        tf.write(resume_text)
                        tf.flush()
                        tf.close()
                        with open(tf.name, "rb") as f:
                            mail_msg.attach(filename="resume.txt", content_type="text/plain", data=f.read())
                            attached = True

                # SEND EMAIL
                mail.send(mail_msg)
                state_manager.reset_state(session_id)

                if attached:
                    return format_response("Email sent with resume attached! ✅", action="email_sent", success=True)
                else:
                    return format_response("Email sent but no resume was attached ❗", action="email_sent", success=False)

            except Exception as e:
                current_app.logger.exception("Email send failed")
                return format_response("There was an error sending the email. Please try again or type 'restart' to start over.", action="email_error", success=False)


        elif "no" in msg or "cancel" in msg:
                    state_manager.reset_state(session_id)
                    return format_response("Email cancelled. Anything else I can help with?", action="cancelled")

        elif "edit" in msg or "modify" in msg:
                    state_manager.update_state(session_id, {"step": "edit_email", "data": data})
                    return format_response("Please provide your edited email text (paste full email):", action="edit_email")

        else:
            return format_response("Please type 'yes' to send, 'no' to cancel, or 'edit' to modify the email.", action="confirm_send")

    # Step 8: Edit email
    if step == "edit_email":
        data["generated_email"] = message.strip()
        state_manager.update_state(session_id, {"step": "confirm_send", "data": data})
        return format_response([
            {"type": "text", "value": "Email updated!"},
            {"type": "divider"},
            {"type": "email_preview", "value": message.strip()},
            {"type": "divider"},
            {"type": "text", "value": "Would you like to send this email? (yes/no)"}
        ], action="confirm_send")

    return format_response("I'm here to help! What would you like to do?")


# =========================
# Flask Endpoints
# =========================
@agent_bp.route('/agent', methods=['POST'])
def chat_agent():
    """
    Standard synchronous endpoint — returns JSON after processing.
    Expects JSON:
    {
      "message": "hello",
      "history": [...],
      "session_id": "<optional>",
    }
    """
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Message is required"}), 400

        message = data.get('message')
        history = data.get('history', [])

        # Attempt to get session_id from payload first
        session_id = data.get("session_id")
        user_id = None
        try:
            user_id = get_jwt_identity()
        except Exception:
            user_id = None

        # Fallback logic for session_id
        if not session_id:
            if user_id:
                session_id = str(user_id)
            else:
                # generate ephemeral guest id for this client (non-persistent)
                session_id = "guest_" + str(uuid.uuid4())

        response = process_conversation(message, history, session_id=session_id, user_id=user_id)
        return jsonify(response), 200
    except Exception as e:
        current_app.logger.exception("Agent error")
        return jsonify(format_response("I'm having trouble right now. Please try again.")), 500


@agent_bp.route('/agent/stream', methods=['POST'])
def chat_agent_stream():
    """
    SSE streaming endpoint. Accepts same payload as /agent plus "session_id".
    Streams assistant text chunks as SSE events.

    Client should connect with "Accept: text/event-stream" and keep connection open.
    """
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Message is required"}), 400

        message = data.get('message')
        history = data.get('history', [])

        session_id = data.get("session_id")
        user_id = None
        try:
            user_id = get_jwt_identity()
        except Exception:
            user_id = None

        if not session_id:
            if user_id:
                session_id = str(user_id)
            else:
                # For streaming, keep session deterministic if client doesn't provide one
                session_id = "guest_" + str(uuid.uuid4())

        # Process conversation synchronously to obtain the structured response,
        # then stream textual content in chunks as SSE events.
        response_obj = process_conversation(message, history, session_id=session_id, user_id=user_id)

        # generator to stream SSE
        def event_stream(resp):
            """
            Yield SSE 'data:' events. We'll stream only textual pieces here.
            For each piece of type 'text', chunk it and yield progressively.
            """
            try:
                content = resp.get("content", [])
                # First yield a meta event so client knows stream started
                meta = {"event": "meta", "session_id": session_id, "action": resp.get("action")}
                yield f"event: meta\ndata: {json.dumps(meta)}\n\n"

                for item in content:
                    typ = item.get("type")
                    if typ == "text":
                        text = item.get("value", "")
                        # chunk size — adjust as desired
                        chunk_size = 150
                        for i in range(0, len(text), chunk_size):
                            chunk = text[i:i + chunk_size]
                            payload = {"type": "text", "value": chunk}
                            # send as 'message' event so client can append pieces
                            yield f"event: message\ndata: {json.dumps(payload)}\n\n"
                    else:
                        # For non-text items (list, divider, email_preview), send as single event
                        payload = {"type": typ, "value": item.get("value", item.get("items", None))}
                        yield f"event: message\ndata: {json.dumps(payload)}\n\n"

                # final done event with whole JSON response (client can use to reconstruct)
                yield f"event: done\ndata: {json.dumps({'full_response': resp})}\n\n"

            except GeneratorExit:
                # client closed connection
                current_app.logger.debug(f"SSE client disconnected for session {session_id}")
                return
            except Exception:
                current_app.logger.exception("Error while streaming SSE")
                yield f"event: error\ndata: {json.dumps({'error':'streaming_error'})}\n\n"

        # Use Flask's streaming Response with proper MIME type
        return Response(stream_with_context(event_stream(response_obj)), mimetype="text/event-stream")
    except Exception as e:
        current_app.logger.exception("Agent stream error")
        return jsonify(format_response("I'm having trouble with streaming right now. Please try the non-streaming endpoint.")), 500


@agent_bp.route('/agent/reset', methods=['POST'])
def reset_conversation():
    """
    Reset a session by session_id or by JWT user.
    Payload: {"session_id": "..."} optional
    """
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        user_id = None
        try:
            user_id = get_jwt_identity()
        except Exception:
            user_id = None
        if not session_id:
            session_id = str(user_id) if user_id else None
        if not session_id:
            return jsonify({"error": "session_id required to reset guest sessions"}), 400

        state_manager.reset_state(session_id)
        return jsonify({"message": "Conversation reset successfully", "success": True}), 200
    except Exception as e:
        current_app.logger.exception("Reset error")
        return jsonify({"error": str(e)}), 500


@agent_bp.route('/agent/health', methods=['GET'])
def agent_health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": "AI Agent"
    }), 200

