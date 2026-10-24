from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from ..extensions import db
from ..models import VisitRequest, VisitApproval
from ..services import approval_service
from ..services.approval_service import WorkflowError
from ..utils import roles_required

bp = Blueprint("approvals", __name__, url_prefix="/approvals")


@bp.route("/")
@roles_required("host", "admin")
def inbox():
    tab = request.args.get("tab", "pending")
    page = request.args.get("page", 1, type=int)
    q = VisitRequest.query
    if current_user.role == "host":
        q = q.filter_by(host_id=current_user.id)
    if tab == "pending":
        q = q.filter_by(approval_status="pending").order_by(VisitRequest.visit_date, VisitRequest.expected_arrival)
    else:
        q = q.filter(VisitRequest.approval_status.in_(["approved", "rejected"])).order_by(VisitRequest.updated_at.desc())
    pg = q.paginate(page=page, per_page=10, error_out=False)
    return render_template("approvals/inbox.html", pg=pg, tab=tab)


@bp.route("/<int:req_id>/decide", methods=["POST"])
@roles_required("host", "admin")
def decide(req_id):
    req = db.get_or_404(VisitRequest, req_id)
    if current_user.role == "host" and req.host_id != current_user.id:
        abort(403)
    try:
        approval_service.decide(req, current_user, request.form.get("decision"), request.form.get("comments"))
        flash(f"Request {req.request_no} {req.approval_status}.", "success")
    except WorkflowError as e:
        flash(str(e), "danger")
    return redirect(request.form.get("next") if (request.form.get("next") or "").startswith("/") else url_for("approvals.inbox"))
