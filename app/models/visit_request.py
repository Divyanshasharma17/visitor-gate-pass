import secrets
import string
from datetime import datetime
from ..extensions import db

APPROVAL_STATUSES = ("draft", "pending", "approved", "rejected", "cancelled")
VISIT_STATUSES = ("scheduled", "checked_in", "checked_out", "missed")

# Valid state transitions (enforced server-side in services)
APPROVAL_TRANSITIONS = {
    "draft": {"pending", "approved", "cancelled"},
    "pending": {"approved", "rejected", "cancelled"},
    "approved": {"cancelled"},
    "rejected": set(),
    "cancelled": set(),
}
VISIT_TRANSITIONS = {
    "scheduled": {"checked_in", "missed"},
    "checked_in": {"checked_out"},
    "checked_out": set(),
    "missed": set(),
}


def new_request_no():
    alphabet = string.ascii_uppercase + string.digits
    return "VR-" + datetime.now().strftime("%y%m%d") + "-" + "".join(secrets.choice(alphabet) for _ in range(5))


class VisitRequest(db.Model):
    __tablename__ = "visit_requests"
    id = db.Column(db.Integer, primary_key=True)
    request_no = db.Column(db.String(24), unique=True, nullable=False, index=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey("visitors.id"), nullable=False, index=True)
    host_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category = db.Column(db.String(40), nullable=False, index=True)
    purpose = db.Column(db.Text, nullable=False)
    visit_date = db.Column(db.Date, nullable=False, index=True)
    expected_arrival = db.Column(db.Time, nullable=False)
    expected_departure = db.Column(db.Time, nullable=False)
    companions = db.Column(db.Integer, nullable=False, default=0)
    group_members = db.Column(db.Text)
    vehicle_no = db.Column(db.String(20))
    document_ref = db.Column(db.String(100))
    is_walkin = db.Column(db.Boolean, nullable=False, default=False)
    consent = db.Column(db.Boolean, nullable=False, default=False)
    approval_status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    visit_status = db.Column(db.String(20), nullable=False, default="scheduled", index=True)
    cancel_reason = db.Column(db.String(255))
    reminder_sent = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    visitor = db.relationship("Visitor", back_populates="requests")
    host = db.relationship("User", foreign_keys=[host_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    department = db.relationship("Department", back_populates="requests")
    approvals = db.relationship("VisitApproval", back_populates="request",
                                order_by="VisitApproval.decided_at", cascade="all, delete-orphan")
    gate_pass = db.relationship("GatePass", back_populates="request", uselist=False)
    log = db.relationship("VisitLog", back_populates="request", uselist=False)

    def can_transition(self, new_status):
        return new_status in APPROVAL_TRANSITIONS.get(self.approval_status, set())


class VisitApproval(db.Model):
    __tablename__ = "visit_approvals"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("visit_requests.id"), nullable=False, index=True)
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"))  # null = automatic policy
    decision = db.Column(db.String(20), nullable=False)  # approved | rejected
    comments = db.Column(db.Text)
    decided_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    request = db.relationship("VisitRequest", back_populates="approvals")
    approver = db.relationship("User")
