from collections import Counter
from datetime import date, datetime, time, timedelta
from flask import Blueprint, render_template, redirect, url_for, jsonify, request, abort
from flask_login import login_required, current_user
from sqlalchemy import or_
from ..extensions import db
from ..models import VisitRequest, VisitLog, Notification
from ..services.maintenance_service import run_maintenance

bp = Blueprint("dashboard", __name__)


def scoped_requests():
    q = VisitRequest.query
    if current_user.role == "host":
        q = q.filter(or_(VisitRequest.host_id == current_user.id, VisitRequest.created_by_id == current_user.id))
    return q


@bp.route("/")
@login_required
def index():
    run_maintenance()
    today = date.today()
    start_today = datetime.combine(today, time.min)
    base = scoped_requests()
    logs = VisitLog.query.join(VisitRequest)
    if current_user.role == "host":
        logs = logs.filter(or_(VisitRequest.host_id == current_user.id, VisitRequest.created_by_id == current_user.id))
    stats = {
        "total_today": logs.filter(VisitLog.entry_time >= start_today).count(),
        "expected": base.filter(VisitRequest.visit_date == today, VisitRequest.approval_status == "approved").count(),
        "inside": base.filter(VisitRequest.visit_status == "checked_in").count(),
        "checked_out": logs.filter(VisitLog.exit_time >= start_today).count(),
        "pending": base.filter(VisitRequest.approval_status == "pending").count(),
        "rejected": base.filter(VisitRequest.approval_status == "rejected",
                                VisitRequest.visit_date >= today - timedelta(days=30)).count(),
    }
    since = today - timedelta(days=13)
    valid = base.filter(VisitRequest.approval_status.notin_(["draft", "cancelled"]))
    dates = [r[0] for r in valid.with_entities(VisitRequest.visit_date).filter(VisitRequest.visit_date >= since).all()]
    c = Counter(dates)
    daily = {"labels": [(since + timedelta(days=i)).strftime("%d %b") for i in range(14)],
             "data": [c.get(since + timedelta(days=i), 0) for i in range(14)]}
    m_start = (today.replace(day=1) - timedelta(days=150)).replace(day=1)
    mdates = [r[0] for r in valid.with_entities(VisitRequest.visit_date).filter(VisitRequest.visit_date >= m_start).all()]
    mc = Counter(d.strftime("%Y-%m") for d in mdates)
    months, y, m = [], today.year, today.month
    for _ in range(6):
        months.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    monthly = {"labels": months, "data": [mc.get(k, 0) for k in months]}
    dept_rows = valid.filter(VisitRequest.visit_date >= today - timedelta(days=30)).all()
    dc = Counter(r.department.name for r in dept_rows)
    dept = {"labels": list(dc.keys()), "data": list(dc.values())}
    recent = base.order_by(VisitRequest.created_at.desc()).limit(8).all()
    recent_logs = logs.order_by(VisitLog.created_at.desc()).limit(6).all()
    pending_for_me = []
    if current_user.role in ("host", "admin"):
        q = VisitRequest.query.filter_by(approval_status="pending")
        if current_user.role == "host":
            q = q.filter_by(host_id=current_user.id)
        pending_for_me = q.order_by(VisitRequest.visit_date).limit(5).all()
    return render_template("dashboard/index.html", stats=stats, daily=daily, monthly=monthly, dept=dept,
                           recent=recent, recent_logs=recent_logs, pending_for_me=pending_for_me)


@bp.route("/notifications")
@login_required
def notifications():
    page = request.args.get("page", 1, type=int)
    pg = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()) \
        .paginate(page=page, per_page=20, error_out=False)
    return render_template("dashboard/notifications.html", pg=pg)


@bp.route("/notifications/<int:nid>/open")
@login_required
def open_notification(nid):
    n = db.session.get(Notification, nid)
    if not n or n.user_id != current_user.id:
        abort(404)
    n.is_read = True
    db.session.commit()
    return redirect(n.link if n.link and n.link.startswith("/") else url_for("dashboard.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(request.referrer or url_for("dashboard.notifications"))


@bp.route("/api/notifications/count")
@login_required
def notif_count():
    return jsonify(count=Notification.query.filter_by(user_id=current_user.id, is_read=False).count())
