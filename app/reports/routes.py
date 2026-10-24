import csv
import io
from collections import OrderedDict
from datetime import date, timedelta
from flask import Blueprint, render_template, request, Response, abort, send_file
from flask_login import current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from ..extensions import db
from ..models import VisitRequest, Department, User, Setting
from ..services import audit_service
from ..utils import roles_required, csv_safe

bp = Blueprint("reports", __name__, url_prefix="/reports")

REPORT_TYPES = OrderedDict([
    ("history", "Entry / Exit history"), ("daily", "Daily visitor report"), ("monthly", "Monthly visitor report"),
    ("department", "Department-wise"), ("host", "Host-wise"), ("category", "Visitor category"),
    ("inside", "Currently inside")])
AGG_COLS = ["Group", "Total", "Approved", "Pending", "Rejected", "Cancelled", "Visited", "Walk-ins"]


def _agg(reqs, keyfn):
    out = OrderedDict()
    for r in reqs:
        k = keyfn(r)
        row = out.setdefault(k, [k, 0, 0, 0, 0, 0, 0, 0])
        row[1] += 1
        row[2] += r.approval_status == "approved"
        row[3] += r.approval_status == "pending"
        row[4] += r.approval_status == "rejected"
        row[5] += r.approval_status == "cancelled"
        row[6] += r.visit_status in ("checked_in", "checked_out")
        row[7] += bool(r.is_walkin)
    return list(out.values())


def build(rtype, args):
    today = date.today()
    try:
        d_from = date.fromisoformat(args.get("from") or "") if args.get("from") else today - timedelta(days=30)
        d_to = date.fromisoformat(args.get("to")) if args.get("to") else today
    except ValueError:
        d_from, d_to = today - timedelta(days=30), today
    q = VisitRequest.query.options(joinedload(VisitRequest.visitor), joinedload(VisitRequest.host),
                                   joinedload(VisitRequest.department), joinedload(VisitRequest.log))
    if current_user.role == "host":   # object-level: hosts only see their own data
        q = q.filter(or_(VisitRequest.host_id == current_user.id, VisitRequest.created_by_id == current_user.id))
    if rtype == "inside":
        q = q.filter(VisitRequest.visit_status == "checked_in")
    else:
        q = q.filter(VisitRequest.visit_date >= d_from, VisitRequest.visit_date <= d_to)
    if args.get("department_id", type=int):
        q = q.filter(VisitRequest.department_id == args.get("department_id", type=int))
    if args.get("host_id", type=int) and current_user.role != "host":
        q = q.filter(VisitRequest.host_id == args.get("host_id", type=int))
    if args.get("category"):
        q = q.filter(VisitRequest.category == args.get("category"))
    reqs = q.order_by(VisitRequest.visit_date.desc(), VisitRequest.expected_arrival).all()

    if rtype in ("history", "inside"):
        cols = ["Request No", "Visitor", "Company", "Host", "Department", "Category", "Date", "Entry", "Exit", "Minutes"]
        rows = []
        for r in reqs:
            lg = r.log
            if rtype == "history" and not (lg and lg.entry_time):
                continue
            rows.append([r.request_no, r.visitor.full_name, r.visitor.company or "", r.host.name, r.department.name,
                         r.category, r.visit_date.isoformat(), lg.entry_time.strftime("%H:%M") if lg and lg.entry_time else "",
                         lg.exit_time.strftime("%H:%M") if lg and lg.exit_time else "",
                         lg.duration_minutes if lg and lg.duration_minutes is not None else ""])
        return cols, rows
    keyfns = {"daily": lambda r: r.visit_date.isoformat(), "monthly": lambda r: r.visit_date.strftime("%Y-%m"),
              "department": lambda r: r.department.name, "host": lambda r: r.host.name, "category": lambda r: r.category}
    cols = ["Date" if rtype == "daily" else "Month" if rtype == "monthly" else rtype.capitalize()] + AGG_COLS[1:]
    rows = _agg(reqs, keyfns[rtype])
    if rtype in ("daily", "monthly"):
        rows.sort(key=lambda x: x[0])
    return cols, rows


@bp.route("/")
@roles_required("admin", "receptionist", "host", "guard")
def index():
    rtype = request.args.get("type", "history")
    if rtype not in REPORT_TYPES:
        rtype = "history"
    if current_user.role == "guard":
        if rtype != "inside":
            rtype = "inside"           # guards: currently-inside report only
    elif current_user.role == "host" and rtype == "host":
        rtype = "history"
    cols, rows = build(rtype, request.args)
    fmt = request.args.get("format")
    if fmt in ("csv", "xlsx"):
        audit_service.log("report_export", "Report", None, report=rtype, format=fmt, rows=len(rows))
        db.session.commit()
        safe = [[csv_safe(c) for c in row] for row in rows]
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(cols)
            w.writerows(safe)
            return Response(buf.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition": f"attachment; filename={rtype}_report.csv"})
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = rtype[:30]
        ws.append(cols)
        for row in safe:
            ws.append(row)
        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)
        return send_file(bio, as_attachment=True, download_name=f"{rtype}_report.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    types = REPORT_TYPES
    if current_user.role == "guard":
        types = {"inside": REPORT_TYPES["inside"]}
    elif current_user.role == "host":
        types = {k: v for k, v in REPORT_TYPES.items() if k != "host"}
    return render_template("reports/index.html", cols=cols, rows=rows, rtype=rtype, types=types,
                           departments=Department.query.order_by(Department.name).all(),
                           hosts=User.query.filter(User.role.in_(["host", "admin"])).order_by(User.name).all(),
                           categories=[c.strip() for c in Setting.get("categories").split(",") if c.strip()],
                           title=REPORT_TYPES[rtype], today=date.today())
