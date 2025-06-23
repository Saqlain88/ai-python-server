import re
from email_validator import validate_email as validate_email_format, EmailNotValidError

def validate_email(email):
    """Validate email format"""
    try:
        validate_email_format(email)
        return None
    except EmailNotValidError as e:
        return str(e)

def validate_password(password):
    """Validate password strength"""
    if not password:
        return "Password is required"
    
    if len(password) < 8:
        return "Password must be at least 8 characters long"
    
    if len(password) > 128:
        return "Password must be less than 128 characters"
    
    # Check for at least one uppercase letter
    if not re.search(r'[A-Z]', password):
        return "Password must contain at least one uppercase letter"
    
    # Check for at least one lowercase letter
    if not re.search(r'[a-z]', password):
        return "Password must contain at least one lowercase letter"
    
    # Check for at least one digit
    if not re.search(r'\d', password):
        return "Password must contain at least one number"
    
    # Check for at least one special character
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return "Password must contain at least one special character (!@#$%^&*(),.?\":{}|<>)"
    
    return None

def validate_name(name, field_name="Name"):
    """Validate name fields"""
    if not name:
        return None  # Names are optional
    
    name = name.strip()
    
    if len(name) < 1:
        return f"{field_name} cannot be empty"
    
    if len(name) > 100:
        return f"{field_name} must be less than 100 characters"
    
    # Allow letters, spaces, hyphens, and apostrophes
    if not re.match(r"^[a-zA-Z\s\-']+$", name):
        return f"{field_name} can only contain letters, spaces, hyphens, and apostrophes"
    
    return None

def validate_username(username):
    """Validate username"""
    if not username:
        return None  # Username is optional
    
    username = username.strip()
    
    if len(username) < 3:
        return "Username must be at least 3 characters long"
    
    if len(username) > 30:
        return "Username must be less than 30 characters"
    
    # Allow letters, numbers, underscores, and hyphens
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        return "Username can only contain letters, numbers, underscores, and hyphens"
    
    # Must start with a letter or number
    if not re.match(r"^[a-zA-Z0-9]", username):
        return "Username must start with a letter or number"
    
    return None