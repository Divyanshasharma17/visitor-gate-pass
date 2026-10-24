from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, url_for, flash, redirect, abort
from flask_login import current_user
from ..extensions import db, limiter
from ..models import VisitRequest, VisitLog, GatePass, Visitor
from ..services import gate_pass_service, gate_service, audit_service, notification_service
from ..services.gate_service import GateError
from ..utils import gate_required, roles_required

bp = Blueprint("gate", __name__, url_prefix="/gate")


@bp.route("/verify")
@gate_required
def verify():
    return render_template("gate/verify.html")


def _describe(gp):
    req = gp.request
    if req.visit_status == "checked_in":
        action, ok, reason = "checkout", True, None
    else:
        ok, reason = gate_pass_service.check_validity(gp)
        action = "checkin" if ok else None
    warnings = []
    for m in gate_service.restrictions_for(req.visitor):
        w = {"level": m.level, "note": "Possible match - verify identity before proceeding."}
        if current_user.role in ("admin", "guard"):
            w["reason"] = m.reason
        warnings.append(w)
    return {"ok": True, "pass_no": gp.pass_no, "pass_status": gp.status, "valid": ok, "reason": reason,
            "action": action, "visitor": req.visitor.full_name, "company": req.visitor.company or "-",
            "host": req.host.name, "department": req.department.name, "request_no": req.request_no,
            "visit_date": req.visit_date.strftime("%d %b %Y"),
            "window": f"{req.expected_arrival:%H:%M} - {req.expected_departure:%H:%M}",
            "companions": req.companions, "vehicle": req.vehicle_no or "-", "category": req.category,
            "photo": url_for("visitors.photo", filename=req.visitor.photo_filename) if req.visitor.photo_filename else None,
            "visit_status": req.visit_status, "warnings": warnings}


@bp.route("/lookup", methods=["POST"])
@gate_required
@limiter.limit("60 per minute")
def lookup():
    code = (request.get_json(silent=True) or {}).get("code", "")
    gp = gate_pass_service.find_by_code(code)
    if not gp:
        audit_service.log("invalid_pass_scan", "GatePass", None)  # no token stored
        db.session.commit()
        return jsonify(ok=False, message="Invalid pass. Not recognised."), 404
    return jsonify(_describe(gp))


def _action(fn_name):
    data = request.get_json(silent=True) or {}
    gp = GatePass.query.filter_by(pass_no=(data.get("pass_no") or "").upper()).first()
    if not gp:
        return jsonify(ok=False, message="Invalid pass."), 404
    try:
        if fn_name == "in":
            gate_service.check_in(gp, current_user, data.get("ack_note"))
            return jsonify(ok=True, message=f"Checked in: {gp.request.visitor.full_name}")
        gate_service.check_out(gp, current_user)
        return jsonify(ok=True, message=f"Checked out: {gp.request.visitor.full_name}")
    except GateError as e:
        return jsonify(ok=False, message=str(e), code=e.code), 409 if e.code != "ack_required" else 428


@bp.route("/checkin", methods=["POST"])
@gate_required
@limiter.limit("60 per minute")
def checkin():
    return _action("in")


@bp.route("/checkout", methods=["POST"])
@gate_required
@limiter.limit("60 per minute")
def checkout():
    return _action("out")


@bp.route("/inside")
@gate_required
def inside():
    rows = VisitRequest.query.filter_by(visit_status="checked_in").join(VisitLog).order_by(VisitLog.entry_time).all()
    now = datetime.now()
    overdue = {r.id for r in rows if datetime.combine(r.visit_date, r.expected_departure) < now}
    return render_template("gate/inside.html", rows=rows, overdue=overdue, now=now)


@bp.route("/history")
@gate_required
def history():
    q = VisitLog.query.join(VisitRequest).join(Visitor)
    term = request.args.get("q", "").strip()
    if term:
        q = q.filter(Visitor.full_name.ilike(f"%{term}%") | VisitRequest.request_no.ilike(f"%{term}%"))
    pg = q.order_by(VisitLog.entry_time.desc()).paginate(page=request.args.get("page", 1, type=int),
                                                          per_page=15, error_out=False)
    return render_template("gate/history.html", pg=pg)


@bp.route("/correct/<int:req_id>", methods=["POST"])
@roles_required("admin")
def correct(req_id):
    req = db.get_or_404(VisitRequest, req_id)

    def parse(v):
        try:
            return datetime.strptime(v, "%Y-%m-%dT%H:%M") if v else None
        except ValueError:
            return None
    entry, exit_ = parse(request.form.get("entry_time")), parse(request.form.get("exit_time"))
    if request.form.get("force_checkout"):
        exit_ = datetime.now()
    try:
        gate_service.correct(req, current_user, entry, exit_, request.form.get("reason"))
        flash("Correction saved and audited.", "success")
    except GateError as e:
        flash(str(e), "danger")
    return redirect(request.form.get("next") if (request.form.get("next") or "").startswith("/") else url_for("gate.history"))


@bp.route("/report", methods=["POST"])
@gate_required
def report_suspicious():
    desc = (request.form.get("description") or "").strip()
    if len(desc) < 5:
        flash("Please describe the incident (min 5 characters).", "danger")
        return redirect(url_for("gate.verify"))
    audit_service.log("suspicious_report", None, None, description=desc[:500])
    notification_service.notify_roles(["admin"], f"Security alert from {current_user.name}: {desc[:150]}",
                                      url_for("admin.audit"))
    db.session.commit()
    flash("Incident reported to administrators.", "success")
    return redirect(url_for("gate.verify"))
