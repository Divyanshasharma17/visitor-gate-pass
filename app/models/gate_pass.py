from datetime import datetime
from ..extensions import db

PASS_STATUSES = ("active", "used", "revoked", "expired")


class GatePass(db.Model):
    __tablename__ = "gate_passes"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("visit_requests.id"), unique=True, nullable=False)
    pass_no = db.Column(db.String(24), unique=True, nullable=False, index=True)
    nonce = db.Column(db.String(64), nullable=False)          # random; token = HMAC(secret, pass_no:nonce)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)  # sha256 of token
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    valid_from = db.Column(db.DateTime, nullable=False)
    valid_until = db.Column(db.DateTime, nullable=False)
    issued_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    revoked_at = db.Column(db.DateTime)
    revoked_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    revoke_reason = db.Column(db.String(255))

    request = db.relationship("VisitRequest", back_populates="gate_pass")
    revoked_by = db.relationship("User")
