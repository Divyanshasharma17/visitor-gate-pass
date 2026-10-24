from datetime import date, timedelta
from conftest import login, logout, make_request, approved_request
from app.extensions import db
from app.models import User, Department, VisitRequest, GatePass, AuditLog, Visitor
from app.services import approval_service
from app.services.approval_service import WorkflowError


def payload(**over):
    host = User.query.filter_by(email="host@t.io").first()
    d = dict(full_name="Jane Doe", mobile="+91 98765 43210", email="jane@x.com", company="X", category="Business",
             host_id=host.id, department_id=host.department_id, purpose="Project discussion",
             visit_date=(date.today() + timedelta(days=1)).isoformat(), expected_arrival="10:00",
             expected_departure="11:00", companions="1", consent="y", action="submit")
    d.update(over)
    return d


def test_registration_creates_pending_request(client):
    login(client, "rec@t.io")
    r = client.post("/visitors/new", data=payload(), follow_redirects=True)
    assert r.status_code == 200
    req = VisitRequest.query.one()
    assert req.approval_status == "pending" and req.request_no.startswith("VR-")
    assert req.visitor.mobile == "+919876543210"
    assert AuditLog.query.filter_by(action="visitor_created").count() == 1


def test_registration_validation(client):
    login(client, "rec@t.io")
    r = client.post("/visitors/new", data=payload(mobile="abc", expected_departure="09:00", consent=""))
    assert b"valid mobile" in r.data and b"after arrival" in r.data and b"required" in r.data
    assert VisitRequest.query.count() == 0


def test_past_date_rejected(client):
    login(client, "rec@t.io")
    r = client.post("/visitors/new", data=payload(visit_date=(date.today() - timedelta(days=1)).isoformat()))
    assert b"cannot be in the past" in r.data


def test_duplicate_booking_blocked(client):
    login(client, "rec@t.io")
    client.post("/visitors/new", data=payload())
    r = client.post("/visitors/new", data=payload(expected_arrival="10:30", expected_departure="11:30"), follow_redirects=True)
    assert b"Duplicate booking" in r.data
    assert VisitRequest.query.count() == 1


def test_walkin_registration(client):
    login(client, "rec@t.io")
    p = payload(action="submit")
    p.pop("visit_date")
    client.post("/visitors/walkin", data=p)
    req = VisitRequest.query.one()
    assert req.is_walkin and req.visit_date == date.today()


def test_host_cannot_view_other_hosts_request(client, app):
    r = make_request(host_email="host2@t.io")
    login(client, "host@t.io")
    assert client.get(f"/visitors/{r.id}").status_code == 403
    assert client.post(f"/visitors/{r.id}/cancel").status_code == 403


def test_approval_creates_pass_and_notifies(client, app):
    req = make_request()
    approval_service.submit(req, User.query.filter_by(email="rec@t.io").first())
    assert req.approval_status == "pending"
    login(client, "host@t.io")
    client.post(f"/approvals/{req.id}/decide", data={"decision": "approved", "comments": "fine"})
    req = db.session.get(VisitRequest, req.id)
    assert req.approval_status == "approved" and req.gate_pass.status == "active"
    assert req.approvals[0].approver.email == "host@t.io"
    assert AuditLog.query.filter_by(action="pass_generated").count() == 1


def test_rejection_requires_reason_and_issues_no_pass(client, app):
    req = make_request()
    approval_service.submit(req, User.query.filter_by(email="rec@t.io").first())
    login(client, "host@t.io")
    r = client.post(f"/approvals/{req.id}/decide", data={"decision": "rejected", "comments": ""}, follow_redirects=True)
    assert b"reason for rejection" in r.data
    client.post(f"/approvals/{req.id}/decide", data={"decision": "rejected", "comments": "Not needed"})
    req = db.session.get(VisitRequest, req.id)
    assert req.approval_status == "rejected" and req.gate_pass is None


def test_duplicate_approval_prevented(app):
    req = make_request()
    host = User.query.filter_by(email="host@t.io").first()
    approval_service.submit(req, User.query.filter_by(email="rec@t.io").first())
    approval_service.decide(req, host, "approved", "")
    try:
        approval_service.decide(req, host, "approved", "")
        assert False, "second approval must fail"
    except WorkflowError:
        pass
    assert GatePass.query.count() == 1


def test_only_assigned_host_can_decide(app):
    req = make_request()
    approval_service.submit(req, User.query.filter_by(email="rec@t.io").first())
    other = User.query.filter_by(email="host2@t.io").first()
    try:
        approval_service.decide(req, other, "approved", "")
        assert False
    except WorkflowError:
        pass


def test_cancellation_revokes_pass(app):
    req = approved_request()
    admin = User.query.filter_by(email="admin@t.io").first()
    approval_service.cancel(req, admin, "no longer needed")
    req = db.session.get(VisitRequest, req.id)
    assert req.approval_status == "cancelled" and req.gate_pass.status == "revoked"


def test_host_self_registered_visit_auto_approved(app):
    host = User.query.filter_by(email="host@t.io").first()
    req = make_request(creator_email="host@t.io")
    approval_service.submit(req, host)
    assert req.approval_status == "approved" and req.gate_pass


def test_file_upload_validation(client):
    import io
    login(client, "rec@t.io")
    p = payload()
    p["photo"] = (io.BytesIO(b"not an image"), "evil.png")
    r = client.post("/visitors/new", data=p, content_type="multipart/form-data")
    assert b"not a valid image" in r.data
    p = payload()
    p["photo"] = (io.BytesIO(b"<?php ?>"), "shell.php")
    r = client.post("/visitors/new", data=p, content_type="multipart/form-data")
    assert b"JPG or PNG" in r.data
