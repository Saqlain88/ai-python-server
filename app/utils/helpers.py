import secrets
import string
from datetime import datetime, timezone

def generate_random_string(length=32):
    """Generate a random string"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_username_from_email(email):
    """Generate a username from email"""
    base_username = email.split('@')[0]
    # Remove any special characters except underscores and hyphens
    base_username = ''.join(c for c in base_username if c.isalnum() or c in '_-')
    
    # Add random suffix to make it unique
    random_suffix = generate_random_string(4)
    return f"{base_username}_{random_suffix}"

def format_datetime(dt):
    """Format datetime for JSON serialization"""
    if dt is None:
        return None
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.isoformat()

def parse_datetime(dt_string):
    """Parse datetime string"""
    try:
        return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None

def sanitize_filename(filename):
    """Sanitize filename for safe storage"""
    # Remove path separators and other potentially dangerous characters
    safe_chars = string.ascii_letters + string.digits + '.-_'
    return ''.join(c for c in filename if c in safe_chars)

def get_client_ip(request):
    """Get client IP address from request"""
    # Handle forwarded headers from proxy/load balancer
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr

def mask_email(email):
    """Mask email address for privacy"""
    if '@' not in email:
        return email
    
    username, domain = email.split('@', 1)
    
    if len(username) <= 2:
        masked_username = '*' * len(username)
    else:
        masked_username = username[0] + '*' * (len(username) - 2) + username[-1]
    
    return f"{masked_username}@{domain}"