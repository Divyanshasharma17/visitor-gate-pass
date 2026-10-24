import base64
import hashlib
import hmac
import io
import secrets
import string
from datetime import datetime, time
import qrcode
from flask import current_app
from ..extensions import db
from ..models import GatePass
from . import audit_service


def _derive_token(pass_no, nonce):
    key = current_app.config["SECRET_KEY"].encode()
    digest = hmac.new(key, f"{pass_no}:{nonce}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def token_for(gp):
    return _derive_token(gp.pass_no, gp.nonce)


def _new_pass_no():
    alphabet = string.ascii_uppercase + string.digits
    while True:
        no = "GP-" + datetime.now().strftime("%y%m%d") + "-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not GatePass.query.filter_by(pass_no=no).first():
            return no


def issue(req):
    pass_no = _new_pass_no()
    nonce = secrets.token_hex(16)
    gp = GatePass(request_id=req.id, pass_no=pass_no, nonce=nonce,
                  token_hash=hash_token(_derive_token(pass_no, nonce)),
                  valid_from=datetime.combine(req.visit_date, time.min),
                  valid_until=datetime.combine(req.visit_date, time(23, 59, 59)))
    db.session.add(gp)
    db.session.flush()
    return gp


def rotate(gp):
    """Replace the secret (old QR codes stop working)."""
    gp.nonce = secrets.token_hex(16)
    gp.token_hash = hash_token(token_for(gp))


def revoke(gp, user, reason):
    if gp.status in ("revoked", "used"):
        return False
    gp.status = "revoked"
    gp.revoked_at = datetime.now()
    gp.revoked_by_id = getattr(user, "id", None)
    gp.revoke_reason = (reason or "")[:255]
    return True


def find_by_code(code):
    """code = QR token or pass number."""
    code = (code or "").strip()
    if code.upper().startswith("GP-"):
        return GatePass.query.filter_by(pass_no=code.upper()).first()
    return GatePass.query.filter_by(token_hash=hash_token(code)).first()


def check_validity(gp, now=None):
    now = now or datetime.now()
    req = gp.request
    if gp.status == "revoked":
        return False, "Pass has been revoked"
    if gp.status == "used":
        return False, "Pass already used - visit completed"
    if gp.status == "expired":
        return False, "Pass has expired"
    if req.approval_status != "approved":
        return False, f"Visit request is {req.approval_status}"
    if req.visit_status == "checked_out":
        return False, "Visit already completed"
    if req.visit_status == "missed":
        return False, "Visit was marked as missed"
    if now < gp.valid_from:
        return False, f"Pass is not valid before {req.visit_date.strftime('%d %b %Y')}"
    if now > gp.valid_until:
        return False, "Pass has expired"
    return True, None


def qr_data_uri(gp):
    """QR encodes only the opaque token - no personal information."""
    img = qrcode.make(token_for(gp), box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def qr_png_bytes(gp):
    buf = io.BytesIO()
    qrcode.make(token_for(gp), box_size=8, border=2).save(buf, format="PNG")
    return buf.getvalue()
