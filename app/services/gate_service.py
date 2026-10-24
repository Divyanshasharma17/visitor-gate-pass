from datetime import datetime
from ..utils import link
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models import VisitRequest, VisitLog, GatePass, VisitorRestriction
from . import audit_service, notification_service
from .gate_pass_service import check_validity


class GateError(Exception):
    def __init__(self, message, code="denied"):
        super().__init__(message)
        self.code = code


def restrictions_for(visitor):
    return VisitorRestriction.matches(visitor.full_name, visitor.mobile)


def _deny(gp, guard, reason):
    audit_service.log("gate_denied", "GatePass", gp.id, actor=guard, reason=reason, pass_no=gp.pass_no)
    db.session.commit()
    raise GateError(reason)


def check_in(gp, guard, ack_note=None):
    req, now = gp.request, datetime.now()
    if req.visit_status == "checked_in":
        _deny(gp, guard, "Duplicate check-in: visitor is already inside")
    ok, reason = check_validity(gp, now)
    if not ok:
        _deny(gp, guard, reason)
    matches = restrictions_for(req.visitor)
    if matches and not (ack_note and len(ack_note.strip()) >= 5):
        raise GateError("Possible watchlist match - verify identity and enter a note to proceed.", "ack_required")
    # Atomic claim: only one concurrent request can flip scheduled -> checked_in
    n = VisitRequest.query.filter_by(id=req.id, visit_status="scheduled", approval_status="approved") \
        .update({"visit_status": "checked_in"}, synchronize_session=False)
    if n != 1:
        db.session.rollback()
        raise GateError("Duplicate or concurrent check-in rejected")
    try:
        entry = VisitLog(request_id=req.id, pass_id=gp.id, entry_time=now, entry_guard_id=guard.id)
        db.session.add(entry)
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise GateError("Duplicate check-in rejected")
    audit_service.log("gate_entry", "VisitRequest", req.id, actor=guard, pass_no=gp.pass_no)
    if matches:
        audit_service.log("restriction_override", "VisitRequest", req.id, actor=guard, note=ack_note.strip()[:200],
                          levels=",".join(m.level for m in matches))
    lnk = link("visitors.detail", req_id=req.id)
    msg = f"Visitor arrived: {req.visitor.full_name} ({req.request_no})"
    notification_service.notify(req.host, msg, lnk)
    if req.created_by_id != req.host_id:
        notification_service.notify(req.created_by_id, msg, lnk, email=False)
    db.session.commit()
    return entry


def check_out(gp, guard):
    req, now = gp.request, datetime.now()
    if req.visit_status == "checked_out":
        _deny(gp, guard, "Duplicate check-out: visitor already checked out")
    if req.visit_status != "checked_in":
        _deny(gp, guard, "Visitor has not checked in")
    n = VisitRequest.query.filter_by(id=req.id, visit_status="checked_in") \
        .update({"visit_status": "checked_out"}, synchronize_session=False)
    if n != 1:
        db.session.rollback()
        raise GateError("Duplicate or concurrent check-out rejected")
    VisitLog.query.filter_by(request_id=req.id).update(
        {"exit_time": now, "exit_guard_id": guard.id}, synchronize_session=False)
    GatePass.query.filter_by(id=gp.id).update({"status": "used"}, synchronize_session=False)
    audit_service.log("gate_exit", "VisitRequest", req.id, actor=guard, pass_no=gp.pass_no)
    notification_service.notify(req.host, f"Visitor checked out: {req.visitor.full_name} ({req.request_no})",
                                link("visitors.detail", req_id=req.id), email=False)
    db.session.commit()


def correct(req, admin, entry_time=None, exit_time=None, reason=""):
    """Authorized correction (mandatory reason + audit trail)."""
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise GateError("A reason (min 5 characters) is required for corrections.")
    log = req.log
    old = {"entry": str(log.entry_time) if log else None, "exit": str(log.exit_time) if log else None}
    if not log:
        if not entry_time:
            raise GateError("Entry time is required to create a record.")
        log = VisitLog(request_id=req.id, pass_id=req.gate_pass.id if req.gate_pass else None, entry_time=entry_time)
        db.session.add(log)
    if entry_time:
        log.entry_time = entry_time
    if exit_time:
        if log.entry_time and exit_time < log.entry_time:
            raise GateError("Exit time cannot be before entry time.")
        log.exit_time = exit_time
        req.visit_status = "checked_out"
        if req.gate_pass and req.gate_pass.status == "active":
            req.gate_pass.status = "used"
    elif req.visit_status == "scheduled":
        req.visit_status = "checked_in"
    log.corrected_by_id = admin.id
    log.correction_reason = reason[:255]
    audit_service.log("gate_correction", "VisitRequest", req.id, actor=admin, reason=reason[:200],
                      old=str(old), new=str({"entry": str(log.entry_time), "exit": str(log.exit_time)}))
    db.session.commit()
