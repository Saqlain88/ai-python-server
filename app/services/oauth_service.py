import requests
from datetime import datetime
from flask import current_app
from flask_jwt_extended import create_access_token, create_refresh_token
from app import db
from app.models.user import User
from app.services.email_service import EmailService

class OAuthService:
    
    @staticmethod
    def get_google_user_info(access_token):
        """Get user info from Google OAuth"""
        try:
            response = requests.get(
                'https://www.googleapis.com/oauth2/v2/userinfo',
                headers={'Authorization': f'Bearer {access_token}'}
            )
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            current_app.logger.error(f'Google OAuth error: {str(e)}')
            return None
    
    @staticmethod
    def get_facebook_user_info(access_token):
        """Get user info from Facebook OAuth"""
        try:
            response = requests.get(
                f'https://graph.facebook.com/me?fields=id,email,first_name,last_name&access_token={access_token}'
            )
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            current_app.logger.error(f'Facebook OAuth error: {str(e)}')
            return None
    
    @staticmethod
    def get_github_user_info(access_token):
        """Get user info from GitHub OAuth"""
        try:
            # Get user info
            user_response = requests.get(
                'https://api.github.com/user',
                headers={'Authorization': f'token {access_token}'}
            )
            
            if user_response.status_code != 200:
                return None
            
            user_data = user_response.json()
            
            # Get primary email if not public
            if not user_data.get('email'):
                email_response = requests.get(
                    'https://api.github.com/user/emails',
                    headers={'Authorization': f'token {access_token}'}
                )
                
                if email_response.status_code == 200:
                    emails = email_response.json()
                    primary_email = next((e['email'] for e in emails if e['primary']), None)
                    user_data['email'] = primary_email
            
            return user_data
        except Exception as e:
            current_app.logger.error(f'GitHub OAuth error: {str(e)}')
            return None
    
    @staticmethod
    def handle_oauth_login(provider, user_info):
        """Handle OAuth login/registration"""
        if not user_info or not user_info.get('email'):
            return {'error': 'Unable to get user information from OAuth provider'}, 400
        
        email = user_info['email']
        provider_id = str(user_info['id'])
        
        # Check if user exists
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Update OAuth ID if not set
            if provider == 'google' and not user.google_id:
                user.google_id = provider_id
            elif provider == 'facebook' and not user.facebook_id:
                user.facebook_id = provider_id
            elif provider == 'github' and not user.github_id:
                user.github_id = provider_id
        else:
            # Create new user
            user = User(
                email=email,
                first_name=user_info.get('given_name') or user_info.get('first_name'),
                last_name=user_info.get('family_name') or user_info.get('last_name'),
                is_verified=True  # OAuth users are considered verified
            )
            
            # Set OAuth ID
            if provider == 'google':
                user.google_id = provider_id
            elif provider == 'facebook':
                user.facebook_id = provider_id
            elif provider == 'github':
                user.github_id = provider_id
                # GitHub might have name in 'name' field
                if not user.first_name and user_info.get('name'):
                    name_parts = user_info['name'].split(' ', 1)
                    user.first_name = name_parts[0]
                    if len(name_parts) > 1:
                        user.last_name = name_parts[1]
            
            db.session.add(user)
            
            # Send welcome email for new users
            EmailService.send_welcome_email(user.email, user.first_name)
        
        # Update last login
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        # Generate tokens
        access_token = create_access_token(identity=user.id)
        refresh_token = create_refresh_token(identity=user.id)
        
        return {
            'message': 'OAuth login successful',
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user': user.to_dict()
        }, 200
    
    @staticmethod
    def unlink_oauth_provider(user_id, provider):
        """Unlink OAuth provider from user account"""
        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}, 404
        
        # Check if user has password or other OAuth providers
        has_password = user.has_password()
        has_other_oauth = False
        
        if provider == 'google':
            user.google_id = None
            has_other_oauth = user.facebook_id or user.github_id
        elif provider == 'facebook':
            user.facebook_id = None
            has_other_oauth = user.google_id or user.github_id
        elif provider == 'github':
            user.github_id = None
            has_other_oauth = user.google_id or user.facebook_id
        else:
            return {'error': 'Invalid OAuth provider'}, 400
        
        # Ensure user has at least one way to login
        if not has_password and not has_other_oauth:
            return {'error': 'Cannot unlink last authentication method. Set a password first.'}, 400
        
        db.session.commit()
        
        return {'message': f'{provider.capitalize()} account unlinked successfully'}, 200