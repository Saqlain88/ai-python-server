from datetime import datetime
from flask_jwt_extended import create_access_token, create_refresh_token
from app import db
from app.models.user import User
from app.models.token import Token
from app.services.email_service import EmailService

class AuthService:
    
    @staticmethod
    def register_user(email, password, first_name=None, last_name=None, username=None):
        """Register a new user with email and password"""
        # Check if user already exists
        if User.query.filter_by(email=email).first():
            return {'error': 'Email already registered'}, 400
        
        if username and User.query.filter_by(username=username).first():
            return {'error': 'Username already taken'}, 400
        
        # Create new user
        user = User(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        # Create verification token
        verification_token = Token.create_verification_token(user.id)
        
        # Send verification email
        EmailService.send_verification_email(user.email, verification_token.token)
        
        return {
            'message': 'User registered successfully. Please check your email for verification.',
            'user': user.to_dict()
        }, 201
    
    @staticmethod
    def login_user(email, password):
        """Login user with email and password"""
        user = User.query.filter_by(email=email).first()
        
        if not user or not user.check_password(password):
            return {'error': 'Invalid email or password'}, 401
        
        if not user.is_active:
            return {'error': 'Account is deactivated'}, 401
        
        # Update last login
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        # Generate tokens
        access_token = create_access_token(identity=user.id)
        refresh_token = create_refresh_token(identity=user.id)
        
        return {
            'message': 'Login successful',
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user': user.to_dict()
        }, 200
    
    @staticmethod
    def verify_email(token):
        """Verify user email with token"""
        token_obj = Token.query.filter_by(
            token=token,
            token_type='email_verification'
        ).first()
        
        if not token_obj or not token_obj.is_valid():
            return {'error': 'Invalid or expired verification token'}, 400
        
        user = User.query.get(token_obj.user_id)
        user.is_verified = True
        token_obj.mark_as_used()
        
        db.session.commit()
        
        return {'message': 'Email verified successfully'}, 200
    
    @staticmethod
    def request_password_reset(email):
        """Request password reset for user"""
        user = User.query.filter_by(email=email).first()
        
        if not user:
            # Don't reveal if email exists or not
            return {'message': 'If email exists, password reset instructions have been sent'}, 200
        
        if not user.has_password():
            return {'error': 'This account was created with social login. Please use social login or contact support.'}, 400
        
        # Create reset token
        reset_token = Token.create_reset_token(user.id)
        
        # Send reset email
        EmailService.send_password_reset_email(user.email, reset_token.token)
        
        return {'message': 'If email exists, password reset instructions have been sent'}, 200
    
    @staticmethod
    def reset_password(token, new_password):
        """Reset user password with token"""
        token_obj = Token.query.filter_by(
            token=token,
            token_type='reset_password'
        ).first()
        
        if not token_obj or not token_obj.is_valid():
            return {'error': 'Invalid or expired reset token'}, 400
        
        user = User.query.get(token_obj.user_id)
        user.set_password(new_password)
        token_obj.mark_as_used()
        
        db.session.commit()
        
        return {'message': 'Password reset successfully'}, 200
    
    @staticmethod
    def refresh_access_token(user_id):
        """Create new access token"""
        access_token = create_access_token(identity=user_id)
        return {'access_token': access_token}, 200
    
    @staticmethod
    def get_user_by_id(user_id):
        """Get user by ID"""
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        return {'user': user.to_dict()}, 200