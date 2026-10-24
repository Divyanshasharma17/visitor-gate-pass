from flask import request, has_request_context
from flask_login import current_user
from ..extensions import db
from ..models import AuditLog


def log(action, target_type=None, target_id=None, actor=None, **details):
    """Add an audit entry to the current session (caller commits).
    Never pass passwords, QR tokens or unnecessary personal data in details."""
    if actor is None and has_request_context() and current_user.is_authenticated:
        actor = current_user
    ip = request.remote_addr if has_request_context() else None
    clean = {k: (v if isinstance(v, (int, float, bool, type(None))) else str(v)) for k, v in details.items()}
    db.session.add(AuditLog(actor_id=getattr(actor, "id", None), action=action,
                            target_type=target_type, target_id=target_id,
                            details=clean or None, ip_address=ip))
