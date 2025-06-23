import os
from app import create_app, db
from app.models.user import User
from app.models.token import Token

# Create Flask application
app = create_app(os.getenv('FLASK_ENV', 'development'))

# Shell context for Flask CLI
@app.shell_context_processor
def make_shell_context():
    return {
        'db': db,
        'User': User,
        'Token': Token
    }

# CLI command to create database tables
@app.cli.command()
def init_db():
    """Initialize the database."""
    db.create_all()
    print('Database initialized.')

# CLI command to create a superuser
@app.cli.command()
def create_superuser():
    """Create a superuser."""
    email = input('Email: ')
    password = input('Password: ')
    
    if User.query.filter_by(email=email).first():
        print('User already exists.')
        return
    
    user = User(
        email=email,
        is_verified=True,
        is_active=True
    )
    user.set_password(password)
    
    # Add admin flag if you add this field to User model
    # user.is_admin = True
    
    db.session.add(user)
    db.session.commit()
    
    print(f'Superuser created: {email}')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)