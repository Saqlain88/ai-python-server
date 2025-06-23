from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.auth_service import AuthService
from app.utils.validators import validate_email, validate_password
from email_validator import validate_email as validate_email_format, EmailNotValidError

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    """Register new user with email and password"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email and password are required'}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        
        # Validate email format
        try:
            validate_email_format(email)
        except EmailNotValidError:
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Validate password
        password_error = validate_password(password)
        if password_error:
            return jsonify({'error': password_error}), 400
        
        # Register user
        result, status_code = AuthService.register_user(
            email=email,
            password=password,
            first_name=data.get('first_name', '').strip(),
            last_name=data.get('last_name', '').strip(),
            username=data.get('username', '').strip() or None
        )
        
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Registration failed'}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    """Login user with email and password"""
    try:
        data = request.get_json()
        
        if not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email and password are required'}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        
        result, status_code = AuthService.login_user(email, password)
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Login failed'}), 500

@auth_bp.route('/verify-email', methods=['POST'])
def verify_email():
    """Verify user email with token"""
    try:
        data = request.get_json()
        
        if not data.get('token'):
            print(data['token'])
            return jsonify({'error': 'Verification token is required'}), 400
        
        result, status_code = AuthService.verify_email(data['token'])
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Email verification failed'}), 500

@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Request password reset"""
    try:
        data = request.get_json()
        
        if not data.get('email'):
            return jsonify({'error': 'Email is required'}), 400
        
        email = data['email'].lower().strip()
        
        # Validate email format
        try:
            validate_email_format(email)
        except EmailNotValidError:
            return jsonify({'error': 'Invalid email format'}), 400
        
        result, status_code = AuthService.request_password_reset(email)
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Password reset request failed'}), 500

@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Reset password with token"""
    try:
        data = request.get_json()
        
        if not data.get('token') or not data.get('password'):
            return jsonify({'error': 'Token and new password are required'}), 400
        
        # Validate password
        password_error = validate_password(data['password'])
        if password_error:
            return jsonify({'error': password_error}), 400
        
        result, status_code = AuthService.reset_password(data['token'], data['password'])
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Password reset failed'}), 500

@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token"""
    try:
        current_user_id = get_jwt_identity()
        result, status_code = AuthService.refresh_access_token(current_user_id)
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Token refresh failed'}), 500

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current user information"""
    try:
        current_user_id = get_jwt_identity()
        result, status_code = AuthService.get_user_by_id(current_user_id)
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Failed to get user information'}), 500

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout user (client-side token removal)"""
    # In a production app, you might want to implement token blacklisting
    return jsonify({'message': 'Logged out successfully'}), 200