from datetime import datetime
from ..extensions import db


class VisitLog(db.Model):
    """One entry/exit record per visit (unique request_id prevents duplicate check-in)."""
    __tablename__ = "visit_logs"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("visit_requests.id"), unique=True, nullable=False)
    pass_id = db.Column(db.Integer, db.ForeignKey("gate_passes.id"))
    entry_time = db.Column(db.DateTime, index=True)
    exit_time = db.Column(db.DateTime)
    entry_guard_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    exit_guard_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    corrected_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    correction_reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    request = db.relationship("VisitRequest", back_populates="log")
    entry_guard = db.relationship("User", foreign_keys=[entry_guard_id])
    exit_guard = db.relationship("User", foreign_keys=[exit_guard_id])

    @property
    def duration_minutes(self):
        if self.entry_time and self.exit_time:
            return int((self.exit_time - self.entry_time).total_seconds() // 60)
        return None
