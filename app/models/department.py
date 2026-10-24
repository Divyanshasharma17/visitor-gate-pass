from datetime import datetime
from ..extensions import db


class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(10), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    users = db.relationship("User", back_populates="department")
    requests = db.relationship("VisitRequest", back_populates="department")
