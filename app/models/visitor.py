from datetime import datetime, date
from sqlalchemy import func, or_
from ..extensions import db


class Visitor(db.Model):
    __tablename__ = "visitors"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False, index=True)
    mobile = db.Column(db.String(20), nullable=False, index=True)
    email = db.Column(db.String(160))
    company = db.Column(db.String(120))
    photo_filename = db.Column(db.String(80))
    anonymized = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    requests = db.relationship("VisitRequest", back_populates="visitor")


class VisitorRestriction(db.Model):
    """Watchlist / blacklist entry. Minimum data: name + mobile + reason."""
    __tablename__ = "visitor_restrictions"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False, index=True)
    mobile = db.Column(db.String(20), index=True)
    level = db.Column(db.String(20), nullable=False, default="watchlist")  # watchlist | blacklist
    reason = db.Column(db.Text, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    review_date = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_reviewed_at = db.Column(db.DateTime)
    last_reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    review_note = db.Column(db.Text)

    created_by = db.relationship("User", foreign_keys=[created_by_id])

    @staticmethod
    def matches(name, mobile):
        """Possible matches only - a human must verify identity (never auto-deny)."""
        q = VisitorRestriction.query.filter(
            VisitorRestriction.active.is_(True),
            or_(VisitorRestriction.review_date.is_(None), VisitorRestriction.review_date >= date.today()))
        conds = [func.lower(VisitorRestriction.full_name) == (name or "").strip().lower()]
        if mobile:
            conds.append(VisitorRestriction.mobile == mobile)
        return q.filter(or_(*conds)).all()
