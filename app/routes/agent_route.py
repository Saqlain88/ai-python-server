# app/routes/agent_route.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import Tool
from langchain_core.messages import HumanMessage, AIMessage
from app import db
from app.models.user import User
from app.models.resume import Resume
from flask_mail import Message as MailMessage
from app import mail
import os
import json
from datetime import datetime

agent_bp = Blueprint('agent', __name__)

# Initialize LLM
def get_llm():
    """Get LLM instance with API key from config"""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    
    return ChatOpenAI(
        model="gpt-4",
        temperature=0.7,
        openai_api_key=api_key
    )

# Conversation State Manager (In-memory for now, can be moved to Redis)
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

# Intent Recognition Tool
def recognize_intent(query: str) -> dict:
    """Recognize user intent from their message"""
    query_lower = query.lower()
    
    intents = {
        "resume_maker": ["resume maker", "create resume", "build resume", "make resume"],
        "ats_checker": ["ats", "ats check", "resume check", "check resume", "ats score"],
        "code_generator": ["code generator", "generate code", "create code", "code gen", "write code"],
        "image_generator": ["image generator", "generate image", "create image", "image gen", "make image"],
        "send_to_hr": ["send resume", "send to hr", "email hr", "apply job", "apply for"]
    }
    
    for intent, keywords in intents.items():
        if any(keyword in query_lower for keyword in keywords):
            return {
                "intent": intent,
                "confidence": 0.9,
                "keywords_matched": [kw for kw in keywords if kw in query_lower]
            }
    
    return {"intent": "unknown", "confidence": 0.0, "keywords_matched": []}

# Email Generation Tool
def generate_email_content(hr_name: str, company_name: str, job_description: str, user_name: str) -> str:
    """Generate personalized email using AI"""
    try:
        llm = get_llm()
        
        prompt = f"""
        Generate a professional job application email with the following details:
        
        HR Manager: {hr_name}
        Company: {company_name}
        Applicant Name: {user_name}
        Job Description: {job_description[:500]}...
        
        Requirements:
        1. Professional and concise tone
        2. Express genuine interest in the position
        3. Highlight relevant skills based on JD
        4. Mention resume attachment
        5. Include proper greeting and closing
        6. Keep it under 250 words
        
        Generate ONLY the email body without subject line.
        """
        
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        print(f"Error generating email: {e}")
        return f"""Dear {hr_name},

I am writing to express my strong interest in the position at {company_name}. 

After reviewing the job description, I believe my skills and experience align well with the requirements. I have attached my resume for your review, which provides detailed information about my qualifications and professional background.

I am enthusiastic about the opportunity to contribute to your team and would welcome the chance to discuss how my experience can benefit {company_name}.

Thank you for considering my application. I look forward to hearing from you.

Best regards,
{user_name}"""

# Agent Tools
def create_agent_tools():
    """Create tools for the agent"""
    return [
        Tool(
            name="IntentRecognizer",
            func=recognize_intent,
            description="Recognizes user intent from their message. Use this to understand what the user wants to do."
        ),
    ]

# Agent Prompt
def get_agent_prompt():
    """Get agent prompt template"""
    return ChatPromptTemplate.from_messages([
        ("system", """You are a helpful AI Assistant for a web application with the following features:
        1. Resume Maker - Create professional resumes
        2. ATS Checker - Check resume compatibility with ATS systems
        3. Code Generator - Generate code snippets
        4. Image Generator - Create AI-generated images
        5. Send Resume to HR - Apply for jobs by sending resume to HR
        
        Your job is to:
        - Understand user intent
        - Guide them through multi-step processes
        - Provide clear, concise responses
        - Be friendly and professional
        
        For "Send Resume to HR" feature, follow this flow:
        1. Ask how they want to provide resume (by ID or PDF upload)
        2. Collect resume details
        3. Ask for HR details (name, email)
        4. Ask for company details (name, email optional)
        5. Ask for job description
        6. Generate and preview email
        7. Confirm before sending
        
        Always be conversational and helpful. Keep responses concise (2-3 sentences max).
        Use emojis sparingly to make conversations friendly.
        """),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad")
    ])

def create_agent():
    """Create and return agent executor"""
    try:
        llm = get_llm()
        tools = create_agent_tools()
        prompt = get_agent_prompt()
        
        agent = create_openai_functions_agent(llm, tools, prompt)
        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            handle_parsing_errors=True
        )
    except Exception as e:
        print(f"Error creating agent: {e}")
        return None

def process_conversation(message: str, history: list, user_id: str = None) -> dict:
    """Process conversation with state management"""
    
    session_id = user_id or "anonymous"
    state = state_manager.get_state(session_id)
    intent_result = recognize_intent(message)
    
    # Convert history to LangChain format
    chat_history = []
    for msg in history[-10:]:  # Keep last 10 messages for context
        if msg.get('sender') == 'user':
            chat_history.append(HumanMessage(content=msg.get('text', '')))
        elif msg.get('sender') == 'bot':
            chat_history.append(AIMessage(content=msg.get('text', '')))
    
    # Handle different flows based on state
    if state["current_flow"] == "send_to_hr":
        return handle_send_to_hr_flow(message, state, session_id, user_id)
    
    # Initial intent recognition
    if intent_result["intent"] != "unknown":
        if intent_result["intent"] == "send_to_hr":
            state_manager.update_state(session_id, {
                "current_flow": "send_to_hr",
                "step": "choose_method",
                "data": {}
            })
            return {
                "output": "I can help you send your resume to HR! 📧\n\nHow would you like to provide your resume?\n\n1️⃣ By Resume ID (from our database)\n2️⃣ Upload PDF file\n\nPlease choose an option (1 or 2).",
                "route": "/resume/send-hr",
                "action": "choose_resume_method"
            }
        else:
            # Route to other features
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
            return {
                "output": f"Great! I'll take you to the {feature}. ✨",
                "route": route,
                "action": "navigate"
            }
    
    # Use agent for general conversation
    try:
        agent_executor = create_agent()
        if agent_executor:
            response = agent_executor.invoke({
                "input": message,
                "chat_history": chat_history
            })
            return {"output": response.get("output", "I'm here to help!")}
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Fallback response
    return {
        "output": "I can help you with:\n\n• 📝 Resume Maker\n• ✅ ATS Checker\n• 💻 Code Generator\n• 🎨 Image Generator\n• 📧 Send Resume to HR\n\nWhat would you like to do?"
    }

def handle_send_to_hr_flow(message: str, state: dict, session_id: str, user_id: str = None) -> dict:
    """Handle the send to HR multi-step flow"""
    
    step = state["step"]
    data = state["data"]
    
    if step == "choose_method":
        if "1" in message or "id" in message.lower():
            state_manager.update_state(session_id, {"step": "ask_resume_id"})
            return {
                "output": "📋 Please provide your Resume ID:",
                "action": "collect_resume_id"
            }
        elif "2" in message or "pdf" in message.lower() or "upload" in message.lower():
            state_manager.update_state(session_id, {"step": "ask_pdf"})
            return {
                "output": "📎 Please upload your resume PDF file.",
                "action": "collect_pdf"
            }
        else:
            return {
                "output": "Please choose either:\n1️⃣ Resume by ID\n2️⃣ Upload PDF\n\nType 1 or 2:",
                "action": "choose_resume_method"
            }
    
    elif step == "ask_resume_id":
        resume_id = message.strip()
        
        # Validate resume exists in database
        if user_id:
            resume = Resume.query.filter_by(id=resume_id, user_id=user_id).first()
            if not resume:
                return {
                    "output": "❌ Resume not found. Please check your Resume ID and try again:",
                    "action": "collect_resume_id"
                }
            data["resume_id"] = resume_id
            data["resume_data"] = resume.to_dict()
        else:
            data["resume_id"] = resume_id
        
        state_manager.update_state(session_id, {"step": "ask_hr_name", "data": data})
        return {
            "output": "✅ Resume found! Now, what is the HR Manager's name?",
            "action": "collect_hr_name"
        }
    
    elif step == "ask_pdf":
        data["resume_method"] = "pdf"
        state_manager.update_state(session_id, {"step": "ask_hr_name", "data": data})
        return {
            "output": "✅ Resume uploaded! What is the HR Manager's name?",
            "action": "collect_hr_name"
        }
    
    elif step == "ask_hr_name":
        data["hr_name"] = message.strip()
        state_manager.update_state(session_id, {"step": "ask_hr_email", "data": data})
        return {
            "output": f"👤 Thank you! What is {data['hr_name']}'s email address?",
            "action": "collect_hr_email"
        }
    
    elif step == "ask_hr_email":
        email = message.strip()
        # Basic email validation
        if "@" not in email or "." not in email:
            return {
                "output": "❌ Please provide a valid email address:",
                "action": "collect_hr_email"
            }
        data["hr_email"] = email
        state_manager.update_state(session_id, {"step": "ask_company_name", "data": data})
        return {
            "output": "🏢 What is the company name?",
            "action": "collect_company_name"
        }
    
    elif step == "ask_company_name":
        data["company_name"] = message.strip()
        state_manager.update_state(session_id, {"step": "ask_company_email", "data": data})
        return {
            "output": "📧 What is the company email? (Optional - type 'skip' to continue)",
            "action": "collect_company_email"
        }
    
    elif step == "ask_company_email":
        if message.lower().strip() != "skip":
            data["company_email"] = message.strip()
        state_manager.update_state(session_id, {"step": "ask_jd", "data": data})
        return {
            "output": "📄 Please provide the Job Description (JD) or paste the job posting:",
            "action": "collect_jd"
        }
    
    elif step == "ask_jd":
        data["job_description"] = message.strip()
        
        # Get user name
        user_name = "Candidate"
        if user_id:
            user = User.query.get(user_id)
            if user:
                user_name = user.name or user.email.split('@')[0]
        
        # Generate email
        try:
            email_content = generate_email_content(
                hr_name=data["hr_name"],
                company_name=data["company_name"],
                job_description=data["job_description"],
                user_name=user_name
            )
            
            data["generated_email"] = email_content
            data["user_name"] = user_name
            state_manager.update_state(session_id, {"step": "confirm_send", "data": data})
            
            return {
                "output": f"✨ Here's the generated email:\n\n---\n\n{email_content}\n\n---\n\n📬 Would you like to send this email?\n\nType:\n• 'yes' to send\n• 'no' to cancel\n• 'edit' to modify",
                "action": "confirm_send",
                "data": {"email_preview": email_content}
            }
        except Exception as e:
            print(f"Error generating email: {e}")
            state_manager.reset_state(session_id)
            return {
                "output": "❌ Sorry, I couldn't generate the email. Please try again later.",
                "action": "error"
            }
    
    elif step == "confirm_send":
        response_lower = message.lower().strip()
        
        if "yes" in response_lower:
            # Send email
            try:
                send_resume_email(
                    to_email=data["hr_email"],
                    hr_name=data["hr_name"],
                    company_name=data["company_name"],
                    email_body=data["generated_email"],
                    user_name=data["user_name"],
                    resume_data=data.get("resume_data")
                )
                
                state_manager.reset_state(session_id)
                return {
                    "output": "✅ Email sent successfully to HR! 🎉\n\nIs there anything else I can help you with?",
                    "action": "email_sent",
                    "success": True
                }
            except Exception as e:
                print(f"Error sending email: {e}")
                state_manager.reset_state(session_id)
                return {
                    "output": "❌ Failed to send email. Please try again later or contact support.",
                    "action": "email_failed",
                    "success": False
                }
        
        elif "no" in response_lower or "cancel" in response_lower:
            state_manager.reset_state(session_id)
            return {
                "output": "❌ Email cancelled. Is there anything else I can help you with?",
                "action": "cancelled"
            }
        
        elif "edit" in response_lower:
            state_manager.update_state(session_id, {"step": "edit_email"})
            return {
                "output": "✏️ Please provide your edited version of the email:",
                "action": "edit_email"
            }
        else:
            return {
                "output": "Please respond with:\n• 'yes' to send\n• 'no' to cancel\n• 'edit' to modify",
                "action": "confirm_send"
            }
    
    elif step == "edit_email":
        data["generated_email"] = message.strip()
        state_manager.update_state(session_id, {"step": "confirm_send", "data": data})
        return {
            "output": f"✅ Email updated!\n\n---\n\n{message.strip()}\n\n---\n\nWould you like to send this email? (yes/no)",
            "action": "confirm_send",
            "data": {"email_preview": message.strip()}
        }
    
    return {"output": "I'm here to help! What would you like to do?"}

def send_resume_email(to_email: str, hr_name: str, company_name: str, 
                     email_body: str, user_name: str, resume_data: dict = None):
    """Send email to HR"""
    try:
        msg = MailMessage(
            subject=f"Application for Position at {company_name}",
            sender=os.environ.get('MAIL_USERNAME'),
            recipients=[to_email]
        )
        
        # Create HTML email
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                {email_body.replace(chr(10), '<br>')}
            </body>
        </html>
        """
        
        msg.html = html_body
        msg.body = email_body
        
        # Attach resume if available
        if resume_data:
            # TODO: Attach actual resume PDF
            pass
        
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        raise e

# API Endpoints
@agent_bp.route('/agent', methods=['POST'])
def chat_agent():
    """Main chat endpoint"""
    try:
        data = request.get_json()
        
        if not data or 'message' not in data:
            return jsonify({"error": "Message is required"}), 400
        
        message = data.get('message', '')
        history = data.get('history', [])
        context = data.get('context', {})
        
        # Get user ID from JWT if available (optional)
        user_id = None
        try:
            user_id = get_jwt_identity()
        except:
            pass  # Anonymous user
        
        # Process conversation
        response = process_conversation(
            message=message,
            history=history,
            user_id=user_id
        )
        
        return jsonify(response), 200
        
    except Exception as e:
        print(f"Agent error: {e}")
        return jsonify({
            "output": "⚠️ I'm having trouble connecting right now. Please try again.",
            "error": str(e)
        }), 500

@agent_bp.route('/agent/reset', methods=['POST'])
def reset_conversation():
    """Reset conversation state"""
    try:
        # Get user ID from JWT if available
        user_id = None
        try:
            user_id = get_jwt_identity()
        except:
            pass
        
        session_id = user_id or "anonymous"
        state_manager.reset_state(session_id)
        
        return jsonify({
            "message": "Conversation reset successfully",
            "success": True
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@agent_bp.route('/agent/health', methods=['GET'])
def agent_health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "AI Agent"
    }), 200