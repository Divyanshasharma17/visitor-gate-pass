import os
import re
import uuid
from functools import wraps
from flask import abort, current_app
from flask_login import current_user
from PIL import Image
from .extensions import login_manager


def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return f(*a, **k)
        return wrapper
    return deco


def gate_required(f):
    """Guards and admins always; receptionists only if enabled in settings."""
    @wraps(f)
    def wrapper(*a, **k):
        from .models import Setting
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        r = current_user.role
        if r in ("admin", "guard") or (r == "receptionist" and Setting.flag("receptionist_gate")):
            return f(*a, **k)
        abort(403)
    return wrapper


def normalize_mobile(value):
    return re.sub(r"[\s-]", "", value or "")


def password_problem(pw):
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "Password must contain letters and digits."
    return None


def save_photo(file_storage):
    """Validate (type, content) and store an uploaded image. Returns filename or None."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ("jpg", "jpeg", "png"):
        raise ValueError("Photo must be a JPG or PNG image.")
    try:
        img = Image.open(file_storage.stream)
        fmt = img.format
        img.verify()
    except Exception:
        raise ValueError("Uploaded file is not a valid image.")
    if fmt not in ("JPEG", "PNG"):
        raise ValueError("Photo must be a JPG or PNG image.")
    file_storage.stream.seek(0)
    name = f"{uuid.uuid4().hex}.{'png' if fmt == 'PNG' else 'jpg'}"
    file_storage.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    return name


def safe_next(url):
    return url if url and url.startswith("/") and not url.startswith("//") else None


def csv_safe(v):
    """Prevent spreadsheet formula injection in exports."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def link(endpoint, **values):
    """url_for that also works outside a request (CLI / background maintenance)."""
    from flask import has_request_context, url_for
    if has_request_context():
        return url_for(endpoint, **values)
    with current_app.test_request_context():
        return url_for(endpoint, **values)
