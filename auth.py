"""Authentication utilities for GameArena."""
from flask_jwt_extended import create_access_token, create_refresh_token, get_jwt_identity
from datetime import timedelta
from models import User, db

def register_user(username, email, password):
    """Register a new user.
    
    Returns:
        tuple: (user_dict, error_message)
    """
    # Validate input
    if not username or len(username) < 3:
        return None, "Username must be at least 3 characters"
    if not email or '@' not in email:
        return None, "Invalid email address"
    if not password or len(password) < 6:
        return None, "Password must be at least 6 characters"
    
    # Check if user already exists
    if User.query.filter_by(username=username).first():
        return None, "Username already exists"
    if User.query.filter_by(email=email).first():
        return None, "Email already exists"
    
    # Create new user
    user = User(username=username, email=email)
    user.set_password(password)
    
    try:
        db.session.add(user)
        db.session.commit()
        return user.to_dict(), None
    except Exception as e:
        db.session.rollback()
        return None, f"Error creating user: {str(e)}"


def login_user(username, password):
    """Authenticate a user and generate tokens.
    
    Returns:
        tuple: (tokens_dict, error_message)
    """
    user = User.query.filter_by(username=username).first()
    
    if not user or not user.check_password(password):
        return None, "Invalid username or password"
    
    # Create tokens (identity must be a string)
    access_token = create_access_token(
        identity=str(user.id),
        expires_delta=timedelta(hours=24)
    )
    refresh_token = create_refresh_token(
        identity=str(user.id),
        expires_delta=timedelta(days=30)
    )
    
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user': user.to_dict()
    }, None


def get_current_user():
    """Get the current authenticated user from JWT token.
    
    Returns:
        User object or None
    """
    try:
        user_id = get_jwt_identity()
        if user_id:
            # Convert string identity back to int for database query
            return User.query.get(int(user_id))
    except:
        pass
    return None
