from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.oauth_service import OAuthService

oauth_bp = Blueprint('oauth', __name__)

@oauth_bp.route('/google', methods=['POST'])
def google_oauth():
    """Handle Google OAuth login"""
    try:
        data = request.get_json()
        
        if not data.get('access_token'):
            return jsonify({'error': 'Google access token is required'}), 400
        
        # Get user info from Google
        user_info = OAuthService.get_google_user_info(data['access_token'])
        
        if not user_info:
            return jsonify({'error': 'Failed to get user information from Google'}), 400
        
        # Handle OAuth login
        result, status_code = OAuthService.handle_oauth_login('google', user_info)
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Google OAuth login failed'}), 500

@oauth_bp.route('/facebook', methods=['POST'])
def facebook_oauth():
    """Handle Facebook OAuth login"""
    try:
        data = request.get_json()
        
        if not data.get('access_token'):
            return jsonify({'error': 'Facebook access token is required'}), 400
        
        # Get user info from Facebook
        user_info = OAuthService.get_facebook_user_info(data['access_token'])
        
        if not user_info:
            return jsonify({'error': 'Failed to get user information from Facebook'}), 400
        
        # Handle OAuth login
        result, status_code = OAuthService.handle_oauth_login('facebook', user_info)
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Facebook OAuth login failed'}), 500

@oauth_bp.route('/github', methods=['POST'])
def github_oauth():
    """Handle GitHub OAuth login"""
    try:
        data = request.get_json()
        
        if not data.get('access_token'):
            return jsonify({'error': 'GitHub access token is required'}), 400
        
        # Get user info from GitHub
        user_info = OAuthService.get_github_user_info(data['access_token'])
        
        if not user_info:
            return jsonify({'error': 'Failed to get user information from GitHub'}), 400
        
        # Handle OAuth login
        result, status_code = OAuthService.handle_oauth_login('github', user_info)
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'GitHub OAuth login failed'}), 500

@oauth_bp.route('/unlink/<provider>', methods=['DELETE'])
@jwt_required()
def unlink_oauth_provider(provider):
    """Unlink OAuth provider from user account"""
    try:
        current_user_id = get_jwt_identity()
        
        if provider not in ['google', 'facebook', 'github']:
            return jsonify({'error': 'Invalid OAuth provider'}), 400
        
        result, status_code = OAuthService.unlink_oauth_provider(current_user_id, provider)
        return jsonify(result), status_code
    
    except Exception as e:
        return jsonify({'error': 'Failed to unlink OAuth provider'}), 500

@oauth_bp.route('/providers', methods=['GET'])
@jwt_required()
def get_linked_providers():
    """Get list of linked OAuth providers for current user"""
    try:
        from app.models.user import User
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        providers = {
            'google': bool(user.google_id),
            'facebook': bool(user.facebook_id),
            'github': bool(user.github_id),
            'has_password': user.has_password()
        }
        
        return jsonify({'providers': providers}), 200
    
    except Exception as e:
        return jsonify({'error': 'Failed to get linked providers'}), 500