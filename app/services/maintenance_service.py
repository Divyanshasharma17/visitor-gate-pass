from datetime import datetime, date, timedelta, time
import os
from flask import current_app
from ..utils import link
from ..extensions import db
from ..models import GatePass, VisitRequest, Visitor, Setting
from . import audit_service, notification_service


def run_maintenance():
    """Expire passes, mark missed visits, send reminders. Safe to call repeatedly."""
    now = datetime.now()
    changed = False
    # Expired / missed visits
    stale = VisitRequest.query.join(GatePass).filter(
        GatePass.status == "active", GatePass.valid_until < now,
        VisitRequest.visit_status == "scheduled", VisitRequest.approval_status == "approved").all()
    for req in stale:
        req.visit_status = "missed"
        req.gate_pass.status = "expired"
        notification_service.notify(req.host, f"Missed visit: {req.visitor.full_name} did not arrive ({req.request_no})",
                                    link("visitors.detail", req_id=req.id), email=False)
        changed = True
    # Upcoming reminders
    minutes = int(Setting.get("reminder_minutes", "60") or 60)
    soon = VisitRequest.query.filter(
        VisitRequest.visit_date == now.date(), VisitRequest.approval_status == "approved",
        VisitRequest.visit_status == "scheduled", VisitRequest.reminder_sent.is_(False)).all()
    for req in soon:
        start = datetime.combine(req.visit_date, req.expected_arrival)
        if timedelta(0) <= start - now <= timedelta(minutes=minutes):
            notification_service.notify(req.host, f"Upcoming visit at {req.expected_arrival:%H:%M}: "
                                        f"{req.visitor.full_name}", link("visitors.detail", req_id=req.id))
            req.reminder_sent = True
            changed = True
    if changed:
        db.session.commit()
    return changed


def purge_old_records(days=None):
    """Retention policy: anonymise visitors whose last visit is older than N days."""
    days = days or int(Setting.get("retention_days", "365"))
    cutoff = date.today() - timedelta(days=days)
    count = 0
    for v in Visitor.query.filter(Visitor.anonymized.is_(False)).all():
        if v.requests and all(r.visit_date < cutoff for r in v.requests):
            if v.photo_filename:
                try:
                    os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], v.photo_filename))
                except OSError:
                    pass
            v.full_name, v.mobile, v.email, v.company, v.photo_filename, v.anonymized = \
                "Anonymized", "0000000000", None, None, None, True
            for r in v.requests:
                r.group_members = r.vehicle_no = r.document_ref = None
            count += 1
    audit_service.log("retention_purge", None, None, actor=None, anonymized=count, older_than_days=days)
    db.session.commit()
    return count
