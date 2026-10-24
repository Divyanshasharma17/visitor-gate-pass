from datetime import datetime
from ..utils import link
from ..extensions import db
from ..models import VisitRequest, VisitApproval, Setting
from ..models.visit_request import APPROVAL_TRANSITIONS
from . import audit_service, gate_pass_service, notification_service


class WorkflowError(Exception):
    pass


def _transition(req, from_status, to_status):
    """Atomic conditional state change - prevents duplicate approval actions."""
    if to_status not in APPROVAL_TRANSITIONS.get(from_status, set()):
        raise WorkflowError(f"Invalid transition {from_status} -> {to_status}")
    n = VisitRequest.query.filter_by(id=req.id, approval_status=from_status) \
        .update({"approval_status": to_status}, synchronize_session=False)
    if n != 1:
        db.session.rollback()
        raise WorkflowError("This request has already been processed.")
    db.session.refresh(req)


def _needs_approval(req):
    if not Setting.flag("require_approval"):
        return False
    if req.is_walkin and not Setting.flag("walkin_requires_approval"):
        return False
    if req.created_by_id == req.host_id and Setting.flag("host_self_approve"):
        return False
    return True


def _finalize_approval(req, approver, comments):
    db.session.add(VisitApproval(request_id=req.id, approver_id=getattr(approver, "id", None),
                                 decision="approved", comments=comments))
    gp = gate_pass_service.issue(req)
    audit_service.log("pass_generated", "GatePass", gp.id, request_no=req.request_no)
    return gp


def submit(req, actor):
    if req.approval_status != "draft":
        raise WorkflowError("Only draft requests can be submitted.")
    if _needs_approval(req):
        _transition(req, "draft", "pending")
        audit_service.log("request_submitted", "VisitRequest", req.id, actor=actor)
        notification_service.notify(
            req.host, f"Approval needed: {req.visitor.full_name} on {req.visit_date:%d %b} ({req.request_no})",
            link("approvals.inbox"))
    else:
        _transition(req, "draft", "approved")
        _finalize_approval(req, None, "Auto-approved by policy")
        audit_service.log("request_auto_approved", "VisitRequest", req.id, actor=actor)
        notification_service.notify(req.host, f"Visit approved: {req.visitor.full_name} on {req.visit_date:%d %b}",
                                    link("visitors.detail", req_id=req.id), email=False)
    db.session.commit()


def decide(req, user, decision, comments=""):
    if decision not in ("approved", "rejected"):
        raise WorkflowError("Invalid decision.")
    if user.role != "admin" and req.host_id != user.id:
        raise WorkflowError("Only the host can decide on this request.")
    comments = (comments or "").strip()
    if decision == "rejected" and len(comments) < 3:
        raise WorkflowError("Please provide a reason for rejection.")
    _transition(req, "pending", decision)
    if decision == "approved":
        _finalize_approval(req, user, comments)
    else:
        db.session.add(VisitApproval(request_id=req.id, approver_id=user.id, decision="rejected", comments=comments))
    audit_service.log(f"request_{decision}", "VisitRequest", req.id, actor=user)
    lnk = link("visitors.detail", req_id=req.id)
    msg = f"Visit {decision}: {req.visitor.full_name} on {req.visit_date:%d %b} ({req.request_no})"
    notification_service.notify(req.created_by_id, msg, lnk)
    if req.created_by_id != req.host_id:
        notification_service.notify_roles(["receptionist"], msg, lnk)
    db.session.commit()


def cancel(req, user, reason=""):
    if req.visit_status != "scheduled":
        raise WorkflowError("A visit in progress or completed cannot be cancelled.")
    if not req.can_transition("cancelled"):
        raise WorkflowError(f"A {req.approval_status} request cannot be cancelled.")
    _transition(req, req.approval_status, "cancelled")
    req.cancel_reason = (reason or "")[:255]
    if req.gate_pass:
        gate_pass_service.revoke(req.gate_pass, user, "Visit cancelled")
        audit_service.log("pass_revoked", "GatePass", req.gate_pass.id, actor=user, reason="cancelled")
    audit_service.log("request_cancelled", "VisitRequest", req.id, actor=user)
    notification_service.notify(req.host, f"Visit cancelled: {req.visitor.full_name} ({req.request_no})",
                                link("visitors.detail", req_id=req.id), email=False)
    db.session.commit()
