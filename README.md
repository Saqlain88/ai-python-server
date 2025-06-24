# Backend API with Authentication

A comprehensive Flask-based REST API with authentication features including email/password signup/login, OAuth integration (Google, Facebook, GitHub), password reset functionality, and JWT token management.

## Features

- **Email/Password Authentication**
  - User registration with email verification
  - Login with JWT token generation
  - Password strength validation
  - Forgot/reset password functionality

- **OAuth Integration**
  - Google OAuth login
  - Facebook OAuth login
  - GitHub OAuth login
  - Account linking/unlinking

- **Security Features**
  - JWT token authentication
  - Password hashing with bcrypt
  - Email verification
  - Rate limiting (ready for implementation)
  - CORS support

- **Extensible Architecture**
  - Modular design for easy feature addition
  - Placeholder AI routes for future implementation
  - Service layer pattern
  - Database migrations with Flask-Migrate

## Installation

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd backend_api
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Initialize database**
   ```bash
   flask init-db
   ```

6. **Run the application**
   ```bash
   python run.py
   ```

## Environment Variables

Configure the following variables in your `.env` file:

### Flask Configuration
- `SECRET_KEY`: Flask secret key
- `JWT_SECRET_KEY`: JWT secret key
- `FLASK_ENV`: Environment (development/production)

### Database
- `DATABASE_URL`: Database connection string

### Email Configuration (for password reset and verification)
- `MAIL_SERVER`: SMTP server
- `MAIL_PORT`: SMTP port
- `MAIL_USE_TLS`: Use TLS (True/False)
- `MAIL_USERNAME`: Email username
- `MAIL_PASSWORD`: Email password/app password

### OAuth Configuration
- `GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET`
- `FACEBOOK_CLIENT_ID` & `FACEBOOK_CLIENT_SECRET`
- `GITHUB_CLIENT_ID` & `GITHUB_CLIENT_SECRET`

### Frontend URL
- `FRONTEND_URL`: Frontend application URL for email links

## API Endpoints

### Authentication Routes (`/api/auth`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/register` | Register new user | No |
| POST | `/login` | User login | No |
| POST | `/verify-email` | Verify email address | No |
| POST | `/forgot-password` | Request password reset | No |
| POST | `/reset-password` | Reset password with token | No |
| POST | `/refresh` | Refresh access token | Yes (Refresh Token) |
| GET | `/me` | Get current user info | Yes |
| POST | `/logout` | Logout user | Yes |

### OAuth Routes (`/api/oauth`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/google` | Google OAuth login | No |
| POST | `/facebook` | Facebook OAuth login | No |
| POST | `/github` | GitHub OAuth login | No |
| DELETE | `/unlink/<provider>` | Unlink OAuth provider | Yes |
| GET | `/providers` | Get linked providers | Yes |

### AI Routes (`/api/ai`) - Placeholder

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/chat` | AI chat endpoint | Yes |
| POST | `/generate` | AI content generation | Yes |
| POST | `/analyze` | AI analysis | Yes |

## Usage Examples

### Register User
```bash
curl -X POST http://localhost:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123!",
    "first_name": "John",
    "last_name": "Doe"
  }'
```

### Login
```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123!"
  }'
```

### Access Protected Route
```bash
curl -X GET http://localhost:5000/api/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### OAuth Login (Google)
```bash
curl -X POST http://localhost:5000/api/oauth/google \
  -H "Content-Type: application/json" \
  -d '{
    "access_token": "GOOGLE_ACCESS_TOKEN"
  }'
```

## OAuth Setup

### Google OAuth
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google+ API
4. Create OAuth 2.0 credentials
5. Add your domain to authorized origins

### Facebook OAuth
1. Go to [Facebook Developers](https://developers.facebook.com/)
2. Create a new app
3. Add Facebook Login product
4. Configure OAuth redirect URIs

### GitHub OAuth
1. Go to GitHub Settings > Developer settings > OAuth Apps
2. Create a new OAuth app
3. Set authorization callback URL

## Database Schema

### User Model
- `id`: Primary key
- `email`: Unique email address
- `username`: Optional username
- `password_hash`: Hashed password
- `first_name`, `last_name`: User names
- `google_id`, `facebook_id`, `github_id`: OAuth IDs
- `is_active`, `is_verified`: Account status
- `created_at`, `updated_at`, `last_login`: Timestamps

### Token Model
-