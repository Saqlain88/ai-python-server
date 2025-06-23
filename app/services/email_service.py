from flask import current_app
from flask_mail import Message
from app import mail

class EmailService:
    
    @staticmethod
    def send_email(to, subject, template):
        """Send email using Flask-Mail"""
        try:
            msg = Message(
                subject=subject,
                recipients=[to],
                html=template,
                sender=current_app.config['MAIL_USERNAME']
            )
            mail.send(msg)
            return True
        except Exception as e:
            current_app.logger.error(f'Failed to send email: {str(e)}')
            return False
    
    @staticmethod
    def send_verification_email(email, token):
        """Send email verification email"""
        frontend_url = current_app.config['FRONTEND_URL']
        verification_url = f"{frontend_url}/verify-email?token={token}"
        
        subject = "Verify Your Email Address"
        template = f"""
        <html>
        <body>
            <h2>Welcome! Please verify your email address</h2>
            <p>Thank you for registering with our service. To complete your registration, please click the link below:</p>
            <p><a href="{verification_url}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Verify Email Address</a></p>
            <p>If the button doesn't work, copy and paste this link into your browser:</p>
            <p>{verification_url}</p>
            <p>This link will expire in 24 hours.</p>
            <p>If you didn't create this account, please ignore this email.</p>
        </body>
        </html>
        """
        
        return EmailService.send_email(email, subject, template)
    
    @staticmethod
    def send_password_reset_email(email, token):
        """Send password reset email"""
        frontend_url = current_app.config['FRONTEND_URL']
        reset_url = f"{frontend_url}/reset-password?token={token}"
        
        subject = "Reset Your Password"
        template = f"""
        <html>
        <body>
            <h2>Password Reset Request</h2>
            <p>We received a request to reset your password. Click the link below to create a new password:</p>
            <p><a href="{reset_url}" style="background-color: #dc3545; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Reset Password</a></p>
            <p>If the button doesn't work, copy and paste this link into your browser:</p>
            <p>{reset_url}</p>
            <p>This link will expire in 1 hour.</p>
            <p>If you didn't request this password reset, please ignore this email.</p>
        </body>
        </html>
        """
        
        return EmailService.send_email(email, subject, template)
    
    @staticmethod
    def send_welcome_email(email, name=None):
        """Send welcome email to new users"""
        subject = "Welcome to Our Platform!"
        display_name = name if name else "there"
        
        template = f"""
        <html>
        <body>
            <h2>Welcome {display_name}!</h2>
            <p>Thank you for joining our platform. We're excited to have you on board!</p>
            <p>Here are some things you can do:</p>
            <ul>
                <li>Complete your profile</li>
                <li>Explore our features</li>
                <li>Connect with other users</li>
            </ul>
            <p>If you have any questions, feel free to contact our support team.</p>
            <p>Happy exploring!</p>
        </body>
        </html>
        """
        
        return EmailService.send_email(email, subject, template)