import os
import re
from datetime import date, datetime, timedelta
from flask import (Blueprint, render_template, redirect, url_for, flash, request, abort, send_from_directory,
                   current_app, Response)
from flask_login import current_user
from flask_mail import Message
from sqlalchemy import or_, func
from ..extensions import db, mail
from ..models import (User, Department, Visitor, VisitRequest, VisitorRestriction, Setting)
from ..models.visit_request import new_request_no
from ..services import approval_service, gate_pass_service, audit_service
from ..services.approval_service import WorkflowError
from ..utils import roles_required, normalize_mobile, save_photo
from .forms import VisitRequestForm

bp = Blueprint("visitors", __name__, url_prefix="/visitors")
STAFF = ("admin", "receptionist", "host")


def _scope(q):
    if current_user.role == "host":
        q = q.filter(or_(VisitRequest.host_id == current_user.id, VisitRequest.created_by_id == current_user.id))
    return q


def _get_req(req_id):
    req = db.get_or_404(VisitRequest, req_id)
    if current_user.role == "host" and current_user.id not in (req.host_id, req.created_by_id):
        abort(403)  # object-level permission
    return req


def _setup(form):
    hosts = User.query.filter(User.active.is_(True), User.role.in_(["host", "admin"])).order_by(User.name).all()
    form.host_id.choices = [(u.id, f"{u.name} ({u.department.name if u.department else '-'})") for u in hosts]
    form.department_id.choices = [(d.id, d.name) for d in Department.query.order_by(Department.name)]
    form.category.choices = [(c.strip(), c.strip()) for c in Setting.get("categories").split(",") if c.strip()]


def _duplicate(visitor_id, host_id, visit_date, arrival, departure, exclude_id=None):
    q = VisitRequest.query.filter(
        VisitRequest.visitor_id == visitor_id, VisitRequest.host_id == host_id,
        VisitRequest.visit_date == visit_date,
        VisitRequest.approval_status.in_(["draft", "pending", "approved"]),
        VisitRequest.expected_arrival < departure, VisitRequest.expected_departure > arrival)
    if exclude_id:
        q = q.filter(VisitRequest.id != exclude_id)
    return q.first()


def _find_visitor(form):
    mobile = normalize_mobile(form.mobile.data)
    name = form.full_name.data.strip()
    v = Visitor.query.filter(Visitor.mobile == mobile, func.lower(Visitor.full_name) == name.lower(),
                             Visitor.anonymized.is_(False)).first()
    if not v:
        v = Visitor(full_name=name, mobile=mobile)
        db.session.add(v)
    v.email = form.email.data or v.email
    v.company = form.company.data or v.company
    return v


def _save(form, req=None, walkin=False):
    """Validate business rules and persist. Returns request or None (errors flashed)."""
    host_id = current_user.id if current_user.role == "host" else form.host_id.data
    visit_date = date.today() if walkin else form.visit_date.data
    visitor = _find_visitor(form)
    db.session.flush()
    dup = _duplicate(visitor.id, host_id, visit_date, form.expected_arrival.data, form.expected_departure.data,
                     req.id if req else None)
    if dup:
        db.session.rollback()
        flash(f"Duplicate booking: this visitor already has request {dup.request_no} with this host in that time slot.",
              "danger")
        return None
    try:
        photo = save_photo(form.photo.data)
    except ValueError as e:
        db.session.rollback()
        form.photo.errors.append(str(e))
        return None
    if photo:
        visitor.photo_filename = photo
    is_new = req is None
    if is_new:
        req = VisitRequest(request_no=new_request_no(), created_by_id=current_user.id, is_walkin=walkin)
        db.session.add(req)
    req.visitor_id = visitor.id
    req.host_id = host_id
    req.department_id = form.department_id.data
    req.category = form.category.data
    req.purpose = form.purpose.data.strip()
    req.visit_date = visit_date
    req.expected_arrival = form.expected_arrival.data
    req.expected_departure = form.expected_departure.data
    req.companions = form.companions.data or 0
    req.group_members = (form.group_members.data or "").strip() or None
    req.vehicle_no = (form.vehicle_no.data or "").strip().upper() or None
    req.document_ref = (form.document_ref.data or "").strip() or None
    req.consent = True
    db.session.flush()
    audit_service.log("visitor_created" if is_new else "visitor_edited", "VisitRequest", req.id,
                      request_no=req.request_no, walkin=walkin)
    db.session.commit()
    if current_user.role in ("admin", "receptionist") and VisitorRestriction.matches(visitor.full_name, visitor.mobile):
        flash("Notice: this visitor is a possible match on a restriction list. Security will verify identity at the gate.",
              "warning")
    return req


def _render_form(form, title, walkin=False, req=None):
    return render_template("visitors/form.html", form=form, title=title, walkin=walkin, req=req)


@bp.route("/")
@roles_required(*STAFF)
def list_():
    q = _scope(VisitRequest.query.join(Visitor))
    term = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    d_from, d_to = request.args.get("from", ""), request.args.get("to", "")
    if term:
        like = f"%{term}%"
        q = q.filter(or_(Visitor.full_name.ilike(like), Visitor.mobile.ilike(like), Visitor.company.ilike(like),
                         VisitRequest.request_no.ilike(like)))
    if status in ("draft", "pending", "approved", "rejected", "cancelled"):
        q = q.filter(VisitRequest.approval_status == status)
    elif status in ("scheduled", "checked_in", "checked_out", "missed"):
        q = q.filter(VisitRequest.visit_status == status)
    for val, op in ((d_from, ">="), (d_to, "<=")):
        try:
            if val:
                dv = date.fromisoformat(val)
                q = q.filter(VisitRequest.visit_date >= dv if op == ">=" else VisitRequest.visit_date <= dv)
        except ValueError:
            pass
    pg = q.order_by(VisitRequest.visit_date.desc(), VisitRequest.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=12, error_out=False)
    return render_template("visitors/list.html", pg=pg)


@bp.route("/expected")
@roles_required(*STAFF)
def expected():
    q = _scope(VisitRequest.query).filter(
        VisitRequest.visit_date >= date.today(), VisitRequest.approval_status.in_(["pending", "approved"]),
        VisitRequest.visit_status == "scheduled").order_by(VisitRequest.visit_date, VisitRequest.expected_arrival)
    pg = q.paginate(page=request.args.get("page", 1, type=int), per_page=12, error_out=False)
    return render_template("visitors/expected.html", pg=pg)


@bp.route("/new", methods=["GET", "POST"])
@roles_required(*STAFF)
def new():
    form = VisitRequestForm()
    _setup(form)
    if request.method == "GET":
        form.visit_date.data = date.today()
        form.companions.data = 0
        if current_user.role == "host":
            form.host_id.data = current_user.id
            form.department_id.data = current_user.department_id
    if form.validate_on_submit():
        req = _save(form)
        if req:
            if request.form.get("action") == "submit":
                try:
                    approval_service.submit(req, current_user)
                    flash(f"Request {req.request_no} submitted.", "success")
                except WorkflowError as e:
                    flash(str(e), "danger")
            else:
                flash(f"Draft {req.request_no} saved.", "success")
            return redirect(url_for("visitors.detail", req_id=req.id))
    return _render_form(form, "Register Visitor")


@bp.route("/walkin", methods=["GET", "POST"])
@roles_required("admin", "receptionist")
def walkin():
    form = VisitRequestForm()
    _setup(form)
    if request.method == "POST":
        form.visit_date.data = date.today()   # walk-ins are always for today
    if request.method == "GET":
        now = datetime.now()
        form.visit_date.data = date.today()
        form.expected_arrival.data = now.time().replace(second=0, microsecond=0)
        end = (now + timedelta(hours=2))
        form.expected_departure.data = end.time().replace(second=0, microsecond=0) if end.date() == now.date() \
            else now.time().replace(hour=23, minute=59, second=0, microsecond=0)
        form.companions.data = 0
    if form.validate_on_submit():
        req = _save(form, walkin=True)
        if req:
            try:
                approval_service.submit(req, current_user)
                flash(f"Walk-in {req.request_no} registered.", "success")
            except WorkflowError as e:
                flash(str(e), "danger")
            return redirect(url_for("visitors.detail", req_id=req.id))
    return _render_form(form, "Walk-in Registration", walkin=True)


@bp.route("/<int:req_id>")
@roles_required(*STAFF)
def detail(req_id):
    req = _get_req(req_id)
    return render_template("visitors/detail.html", req=req)


@bp.route("/<int:req_id>/edit", methods=["GET", "POST"])
@roles_required(*STAFF)
def edit(req_id):
    req = _get_req(req_id)
    if req.approval_status not in ("draft", "pending"):
        flash("Only draft or pending requests can be edited. Cancel and re-register instead.", "warning")
        return redirect(url_for("visitors.detail", req_id=req.id))
    form = VisitRequestForm(obj=req) if request.method == "GET" else VisitRequestForm()
    _setup(form)
    if request.method == "GET":
        form.full_name.data, form.mobile.data = req.visitor.full_name, req.visitor.mobile
        form.email.data, form.company.data = req.visitor.email, req.visitor.company
        form.consent.data = False
    if form.validate_on_submit():
        if _save(form, req=req, walkin=req.is_walkin):
            flash("Request updated.", "success")
            return redirect(url_for("visitors.detail", req_id=req.id))
    return _render_form(form, f"Edit {req.request_no}", walkin=req.is_walkin, req=req)


@bp.route("/<int:req_id>/submit", methods=["POST"])
@roles_required(*STAFF)
def submit(req_id):
    req = _get_req(req_id)
    try:
        approval_service.submit(req, current_user)
        flash("Request submitted.", "success")
    except WorkflowError as e:
        flash(str(e), "danger")
    return redirect(url_for("visitors.detail", req_id=req.id))


@bp.route("/<int:req_id>/cancel", methods=["POST"])
@roles_required(*STAFF)
def cancel(req_id):
    req = _get_req(req_id)
    try:
        approval_service.cancel(req, current_user, request.form.get("reason", ""))
        flash("Request cancelled and pass revoked.", "success")
    except WorkflowError as e:
        flash(str(e), "danger")
    return redirect(url_for("visitors.detail", req_id=req.id))


# ---------------- gate pass ----------------
@bp.route("/<int:req_id>/pass")
@roles_required(*STAFF)
def pass_view(req_id):
    req = _get_req(req_id)
    gp = req.gate_pass
    if not gp:
        flash("No gate pass exists for this request (approval required).", "warning")
        return redirect(url_for("visitors.detail", req_id=req.id))
    qr = gate_pass_service.qr_data_uri(gp) if gp.status == "active" else None
    return render_template("visitors/pass.html", req=req, gp=gp, qr=qr)


@bp.route("/<int:req_id>/pass/revoke", methods=["POST"])
@roles_required(*STAFF)
def pass_revoke(req_id):
    req = _get_req(req_id)
    reason = request.form.get("reason", "").strip()
    if len(reason) < 3:
        flash("A reason is required to revoke a pass.", "danger")
    elif req.gate_pass and req.visit_status == "scheduled" and gate_pass_service.revoke(req.gate_pass, current_user, reason):
        audit_service.log("pass_revoked", "GatePass", req.gate_pass.id, reason=reason[:200])
        db.session.commit()
        flash("Pass revoked.", "success")
    else:
        flash("This pass cannot be revoked.", "danger")
    return redirect(url_for("visitors.pass_view", req_id=req.id))


@bp.route("/<int:req_id>/pass/reissue", methods=["POST"])
@roles_required("admin", "receptionist")
def pass_reissue(req_id):
    req = _get_req(req_id)
    gp = req.gate_pass
    if gp and gp.status == "active" and req.visit_status == "scheduled":
        gate_pass_service.rotate(gp)
        audit_service.log("pass_reissued", "GatePass", gp.id)
        db.session.commit()
        flash("New QR code issued. Previously shared QR codes no longer work.", "success")
    else:
        flash("Only active, unused passes can be reissued.", "danger")
    return redirect(url_for("visitors.pass_view", req_id=req.id))


@bp.route("/<int:req_id>/pass/email", methods=["POST"])
@roles_required("admin", "receptionist", "host")
def pass_email(req_id):
    req = _get_req(req_id)
    gp = req.gate_pass
    if not (gp and gp.status == "active"):
        flash("No active pass to send.", "danger")
    elif not req.visitor.email:
        flash("Visitor has no email address.", "warning")
    elif not current_app.config.get("MAIL_SERVER"):
        flash("Email is not configured on this server. Print the pass instead.", "warning")
    else:
        try:
            msg = Message(f"Your visitor gate pass {gp.pass_no}", recipients=[req.visitor.email],
                          body=f"Dear {req.visitor.full_name},\n\nYour visit on {req.visit_date:%d %b %Y} is approved. "
                               f"Show the attached QR code at the gate. Pass: {gp.pass_no}")
            msg.attach(f"{gp.pass_no}.png", "image/png", gate_pass_service.qr_png_bytes(gp))
            mail.send(msg)
            audit_service.log("pass_emailed", "GatePass", gp.id)
            db.session.commit()
            flash("Pass emailed to visitor.", "success")
        except Exception as exc:
            current_app.logger.warning("Pass email failed: %s", exc)
            flash("Could not send email.", "danger")
    return redirect(url_for("visitors.pass_view", req_id=req.id))


@bp.route("/photo/<filename>")
@roles_required("admin", "receptionist", "guard", "host")
def photo(filename):
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png)", filename):
        abort(404)
    v = Visitor.query.filter_by(photo_filename=filename).first_or_404()
    if current_user.role == "host" and not VisitRequest.query.filter(
            VisitRequest.visitor_id == v.id,
            or_(VisitRequest.host_id == current_user.id, VisitRequest.created_by_id == current_user.id)).first():
        abort(403)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)
