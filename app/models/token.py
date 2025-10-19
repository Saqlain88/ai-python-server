from datetime import datetime, timedelta
from app import db
import secrets

class Token(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    token_type = db.Column(db.String(50), nullable=False)  # 'reset_password', 'email_verification'
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @staticmethod
    def generate_token():
        """Generate a secure random token"""
        return secrets.token_urlsafe(32)
    
    @classmethod
    def create_reset_token(cls, user_id, expiry_hours=1):
        """Create a password reset token"""
        token = cls(
            user_id=user_id,
            token=cls.generate_token(),
            token_type='reset_password',
            expires_at=datetime.utcnow() + timedelta(hours=expiry_hours)
        )
        db.session.add(token)
        db.session.commit()
        return token
    
    @classmethod
    def create_verification_token(cls, user_id, expiry_hours=24):
        """Create an email verification token"""
        token = cls(
            user_id=user_id,
            token=cls.generate_token(),
            token_type='email_verification',
            expires_at=datetime.utcnow() + timedelta(hours=expiry_hours)
        )
        db.session.add(token)
        db.session.commit()
        return token
    
    def is_valid(self):
        """Check if token is valid (not used and not expired)"""
        return not self.used and datetime.utcnow() < self.expires_at
    
    def mark_as_used(self):
        """Mark token as used"""
        self.used = True
        db.session.commit()
    
    def __repr__(self):
        return f'<Token {self.token_type} for user {self.user_id}>'