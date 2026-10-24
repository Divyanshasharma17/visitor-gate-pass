from datetime import date, datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user
from ..extensions import db
from ..models import (User, Department, VisitorRestriction, Setting, AuditLog, ROLES)
from ..services import audit_service
from ..utils import roles_required
from .forms import UserForm, DepartmentForm, RestrictionForm, SettingsForm

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------- users ----------------
@bp.route("/users")
@roles_required("admin")
def users():
    q = User.query
    term = request.args.get("q", "").strip()
    if term:
        q = q.filter(User.name.ilike(f"%{term}%") | User.email.ilike(f"%{term}%"))
    if request.args.get("role") in ROLES:
        q = q.filter_by(role=request.args["role"])
    pg = q.order_by(User.name).paginate(page=request.args.get("page", 1, type=int), per_page=12, error_out=False)
    return render_template("admin/users.html", pg=pg, roles=ROLES)


def _user_form(u=None):
    form = UserForm(obj=u)
    form.department_id.choices = [(0, "- None -")] + [(d.id, d.name) for d in Department.query.order_by(Department.name)]
    return form


@bp.route("/users/new", methods=["GET", "POST"])
@roles_required("admin")
def user_new():
    form = _user_form()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            form.email.errors.append("Email already in use.")
        elif not form.password.data:
            form.password.errors.append("Password is required for new users.")
        else:
            u = User(name=form.name.data.strip(), email=email, phone=form.phone.data, role=form.role.data,
                     department_id=form.department_id.data or None, active=form.active.data)
            u.set_password(form.password.data)
            db.session.add(u)
            db.session.flush()
            audit_service.log("user_created", "User", u.id, role=u.role)
            db.session.commit()
            flash("User created.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/form.html", form=form, title="New User", back=url_for("admin.users"))


@bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@roles_required("admin")
def user_edit(uid):
    u = db.get_or_404(User, uid)
    form = _user_form(u)
    if request.method == "GET":
        form.department_id.data = u.department_id or 0
        form.password.data = ""
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        other = User.query.filter(User.email == email, User.id != u.id).first()
        if other:
            form.email.errors.append("Email already in use.")
        elif u.id == current_user.id and (form.role.data != u.role or not form.active.data):
            flash("You cannot change your own role or deactivate yourself.", "danger")
        else:
            changes = {}
            if form.role.data != u.role:
                changes["role"] = f"{u.role}->{form.role.data}"
            if form.active.data != u.active:
                changes["active"] = f"{u.active}->{form.active.data}"
            u.name, u.email, u.phone = form.name.data.strip(), email, form.phone.data
            u.role, u.department_id, u.active = form.role.data, form.department_id.data or None, form.active.data
            if form.password.data:
                u.set_password(form.password.data)
                changes["password"] = "changed"
            audit_service.log("user_updated", "User", u.id, **changes)
            db.session.commit()
            flash("User updated.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/form.html", form=form, title=f"Edit {u.name}", back=url_for("admin.users"))


@bp.route("/users/<int:uid>/toggle", methods=["POST"])
@roles_required("admin")
def user_toggle(uid):
    u = db.get_or_404(User, uid)
    if u.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
    else:
        u.active = not u.active
        audit_service.log("user_activated" if u.active else "user_deactivated", "User", u.id)
        db.session.commit()
        flash(f"User {'activated' if u.active else 'deactivated'}.", "success")
    return redirect(url_for("admin.users"))


# ---------------- departments ----------------
@bp.route("/departments", methods=["GET", "POST"])
@roles_required("admin")
def departments():
    form = DepartmentForm()
    if form.validate_on_submit():
        if Department.query.filter(Department.name.ilike(form.name.data.strip())).first():
            form.name.errors.append("Department already exists.")
        else:
            d = Department(name=form.name.data.strip(), code=(form.code.data or "").strip().upper() or None)
            db.session.add(d)
            db.session.flush()
            audit_service.log("department_created", "Department", d.id)
            db.session.commit()
            flash("Department added.", "success")
            return redirect(url_for("admin.departments"))
    return render_template("admin/departments.html", form=form, depts=Department.query.order_by(Department.name).all())


@bp.route("/departments/<int:did>/delete", methods=["POST"])
@roles_required("admin")
def department_delete(did):
    d = db.get_or_404(Department, did)
    if d.users or d.requests:
        flash("Department is in use and cannot be deleted.", "danger")
    else:
        audit_service.log("department_deleted", "Department", d.id)
        db.session.delete(d)
        db.session.commit()
        flash("Department deleted.", "success")
    return redirect(url_for("admin.departments"))


# ---------------- restrictions ----------------
@bp.route("/restrictions", methods=["GET", "POST"])
@roles_required("admin")
def restrictions():
    form = RestrictionForm()
    if form.validate_on_submit():
        from ..utils import normalize_mobile
        r = VisitorRestriction(full_name=form.full_name.data.strip(), mobile=normalize_mobile(form.mobile.data) or None,
                               level=form.level.data, reason=form.reason.data.strip(),
                               review_date=form.review_date.data, created_by_id=current_user.id)
        db.session.add(r)
        db.session.flush()
        audit_service.log("restriction_created", "VisitorRestriction", r.id, level=r.level)
        db.session.commit()
        flash("Restriction recorded.", "success")
        return redirect(url_for("admin.restrictions"))
    rows = VisitorRestriction.query.order_by(VisitorRestriction.active.desc(), VisitorRestriction.created_at.desc()).all()
    return render_template("admin/restrictions.html", form=form, rows=rows, today=date.today())


@bp.route("/restrictions/<int:rid>/review", methods=["POST"])
@roles_required("admin")
def restriction_review(rid):
    r = db.get_or_404(VisitorRestriction, rid)
    action = request.form.get("action")
    note = (request.form.get("note") or "").strip()
    if len(note) < 5:
        flash("A review note is required.", "danger")
        return redirect(url_for("admin.restrictions"))
    r.last_reviewed_at, r.last_reviewed_by_id, r.review_note = datetime.now(), current_user.id, note
    if action == "lift":
        r.active = False
    elif action == "extend":
        try:
            r.review_date = date.fromisoformat(request.form.get("review_date", ""))
        except ValueError:
            flash("Provide a valid new review date.", "danger")
            return redirect(url_for("admin.restrictions"))
    audit_service.log("restriction_reviewed", "VisitorRestriction", r.id, decision=action, note=note[:200])
    db.session.commit()
    flash("Review recorded.", "success")
    return redirect(url_for("admin.restrictions"))


# ---------------- settings ----------------
@bp.route("/settings", methods=["GET", "POST"])
@roles_required("admin")
def settings():
    form = SettingsForm()
    keys = ["org_name", "require_approval", "walkin_requires_approval", "host_self_approve", "receptionist_gate",
            "categories", "retention_days", "reminder_minutes"]
    flags = {"require_approval", "walkin_requires_approval", "host_self_approve", "receptionist_gate"}
    if request.method == "GET":
        for k in keys:
            fld = getattr(form, k)
            fld.data = Setting.flag(k) if k in flags else Setting.get(k)
    if form.validate_on_submit():
        for k in keys:
            v = getattr(form, k).data
            Setting.set(k, ("1" if v else "0") if k in flags else v)
        audit_service.log("settings_changed", "Setting", None)
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/form.html", form=form, title="System Settings", back=None)


# ---------------- audit ----------------
@bp.route("/audit")
@roles_required("admin")
def audit():
    q = AuditLog.query
    action, term = request.args.get("action", ""), request.args.get("q", "").strip()
    if action:
        q = q.filter(AuditLog.action == action)
    if term:
        q = q.join(User, AuditLog.actor_id == User.id, isouter=True).filter(User.name.ilike(f"%{term}%"))
    pg = q.order_by(AuditLog.created_at.desc()).paginate(page=request.args.get("page", 1, type=int),
                                                          per_page=25, error_out=False)
    actions = [a[0] for a in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action)]
    return render_template("admin/audit.html", pg=pg, actions=actions)
