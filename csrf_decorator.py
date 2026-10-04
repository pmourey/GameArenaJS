from functools import wraps
from flask import request, jsonify
from flask_wtf.csrf import validate_csrf
from wtforms import ValidationError

def csrf_protected(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            validate_csrf(request.headers.get('X-CSRF-Token'))
        except ValidationError:
            return jsonify({'error': 'CSRF validation failed'}), 400
        return f(*args, **kwargs)
    return decorated_function
