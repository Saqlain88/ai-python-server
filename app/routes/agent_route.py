from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import Tool
from langchain_core.messages import HumanMessage, AIMessage
from app import db, mail
from app.models.user import User
from app.models.resume import Resume
from flask_mail import Message as MailMessage
import os
from datetime import datetime

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
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")

    return ChatOpenAI(
        model="gpt-4",
        temperature=0.7,
        openai_api_key=api_key
    )


# =========================
# Conversation State Manager
# =========================
class ConversationStateManager:
    def __init__(self):
        self.states = {}

    def get_state(self, session_id: str) -> dict:
        if session_id not in self.states:
            self.states[session_id] = {
                "current_flow": None,
                "step": "initial",
                "data": {},
                "awaiting": None
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
    query_lower = query.lower()

    intents = {
        "resume_maker": ["resume maker", "create resume", "build resume", "make resume"],
        "ats_checker": ["ats", "ats check", "resume check", "check resume", "ats score"],
        "code_generator": ["code generator", "generate code", "create code", "code gen"],
        "image_generator": ["image generator", "generate image", "create image"],
        "send_to_hr": ["send resume", "send to hr", "email hr", "apply job"]
    }

    for intent, keywords in intents.items():
        if any(keyword in query_lower for keyword in keywords):
            return {"intent": intent, "confidence": 0.9}

    return {"intent": "unknown", "confidence": 0.0}


# =========================
# Email Generator
# =========================
def generate_email_content(hr_name: str, company_name: str, job_description: str, user_name: str) -> str:
    try:
        llm = get_llm()
        prompt = f"""
        Generate a professional job application email with these details:

        HR Manager: {hr_name}
        Company: {company_name}
        Applicant Name: {user_name}
        Job Description: {job_description[:500]}...

        Requirements:
        - Professional tone
        - Under 250 words
        - Mention resume attached
        - Include greeting and closing
        """

        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        print(f"Error generating email: {e}")
        return f"Dear {hr_name},\n\nI am writing to express interest in the position at {company_name}.\n\nBest regards,\n{user_name}"


# =========================
# Agent Setup
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
        print(f"Agent creation error: {e}")
        return None


# =========================
# Conversation Processor
# =========================
def process_conversation(message: str, history: list, user_id: str = None) -> dict:
    session_id = user_id or "anonymous"
    state = state_manager.get_state(session_id)
    intent_result = recognize_intent(message)

    chat_history = []
    for msg in history[-10:]:
        if msg.get('sender') == 'user':
            chat_history.append(HumanMessage(content=msg.get('text', '')))
        elif msg.get('sender') == 'bot':
            chat_history.append(AIMessage(content=msg.get('text', '')))

    # Handle send_to_hr flow
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
                {"type": "list", "items": ["1️⃣ By Resume ID", "2️⃣ Upload PDF file"]}
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

    # Default fallback if unknown intent
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
# Send to HR Flow
# =========================
def handle_send_to_hr_flow(message: str, state: dict, session_id: str, user_id: str = None) -> dict:
    step = state["step"]
    data = state["data"]

    # Step 1: Choose method
    if step == "choose_method":
        if "1" in message:
            state_manager.update_state(session_id, {"step": "ask_resume_id"})
            return format_response("Please provide your Resume ID:", action="collect_resume_id")
        elif "2" in message:
            state_manager.update_state(session_id, {"step": "ask_pdf"})
            return format_response("Please upload your resume PDF file.", action="collect_pdf")
        else:
            return format_response("Please choose 1 (Resume ID) or 2 (Upload PDF).", action="choose_resume_method")

    # Step 2: Ask HR Name
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
        if "@" not in email:
            return format_response("Invalid email. Please enter again:", action="collect_hr_email")
        data["hr_email"] = email
        state_manager.update_state(session_id, {"step": "ask_company_name", "data": data})
        return format_response("🏢 What is the company name?", action="collect_company_name")

    # Step 5: Job Description
    if step == "ask_company_name":
        data["company_name"] = message.strip()
        state_manager.update_state(session_id, {"step": "ask_jd", "data": data})
        return format_response("Please provide the Job Description (JD):", action="collect_jd")

    # Step 6: Generate email preview
    if step == "ask_jd":
        data["job_description"] = message.strip()
        user_name = "Candidate"
        if user_id:
            user = User.query.get(user_id)
            if user:
                user_name = user.name or user.email.split('@')[0]

        email_content = generate_email_content(
            hr_name=data["hr_name"],
            company_name=data["company_name"],
            job_description=data["job_description"],
            user_name=user_name
        )

        data["generated_email"] = email_content
        data["user_name"] = user_name
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
        msg = message.lower().strip()
        if "yes" in msg:
            state_manager.reset_state(session_id)
            return format_response("Email sent successfully to HR!", action="email_sent", success=True)
        elif "no" in msg:
            state_manager.reset_state(session_id)
            return format_response("Email cancelled. Anything else?", action="cancelled")
        elif "edit" in msg:
            state_manager.update_state(session_id, {"step": "edit_email"})
            return format_response("Please provide your edited email text:", action="edit_email")
        else:
            return format_response("Please type 'yes', 'no', or 'edit'.", action="confirm_send")

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
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Message is required"}), 400

        message = data.get('message')
        history = data.get('history', [])

        user_id = None
        try:
            user_id = get_jwt_identity()
        except:
            pass

        response = process_conversation(message, history, user_id)
        return jsonify(response), 200
    except Exception as e:
        print(f"Agent error: {e}")
        return jsonify(format_response("I'm having trouble right now. Please try again.")), 500


@agent_bp.route('/agent/reset', methods=['POST'])
def reset_conversation():
    try:
        user_id = None
        try:
            user_id = get_jwt_identity()
        except:
            pass
        session_id = user_id or "anonymous"
        state_manager.reset_state(session_id)
        return jsonify({"message": "Conversation reset successfully", "success": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@agent_bp.route('/agent/health', methods=['GET'])
def agent_health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "AI Agent"
    }), 200
