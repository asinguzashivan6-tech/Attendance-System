import re

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]*$")


def validate_name(name):
    """Returns an error message or None if valid."""
    name = (name or '').strip()
    if len(name) < 2:
        return 'Full name must be at least 2 characters'
    if len(name) > 100:
        return 'Full name is too long'
    if not NAME_RE.match(name):
        return 'Full name may only contain letters, spaces, apostrophes, hyphens and dots'
    return None


def validate_email(email):
    """Returns an error message or None if valid."""
    email = (email or '').strip()
    if not email:
        return 'Email is required'
    if len(email) > 120:
        return 'Email is too long'
    if not EMAIL_RE.match(email):
        return 'Enter a valid email address (e.g. name@university.ac.ke)'
    return None


def validate_password(password):
    """Returns an error message or None if valid."""
    password = password or ''
    if len(password) < 8:
        return 'Password must be at least 8 characters'
    if len(password) > 128:
        return 'Password is too long'
    if not re.search(r'[A-Za-z]', password):
        return 'Password must contain at least one letter'
    if not re.search(r'\d', password):
        return 'Password must contain at least one number'
    return None
