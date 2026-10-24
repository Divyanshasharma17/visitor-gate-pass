import json
from datetime import date, datetime, timedelta
from sqlalchemy import text
from conftest import login, logout, make_request, approved_request
from app.extensions import db
from app.models import User, VisitRequest, GatePass, VisitLog, AuditLog, VisitorRestriction
from app.services import gate_pass_service, gate_service
from app.services.gate_service import GateError


def guard():
    return User.query.filter_by(email="guard@t.io").first()


def test_qr_token_not_personal_and_hashed(app):
    req = approved_request()
    gp = req.gate_pass
    token = gate_pass_service.token_for(gp)
    assert req.visitor.full_name not in token and req.visitor.mobile not in token
    assert gp.token_hash != token and gp.token_hash == gate_pass_service.hash_token(token)
    assert gate_pass_service.find_by_code(token).id == gp.id
    assert gate_pass_service.qr_data_uri(gp).startswith("data:image/png;base64,")


def test_invalid_token_rejected(client, app):
    login(client, "guard@t.io")
    r = client.post("/gate/lookup", json={"code": "totally-bogus-token"})
    assert r.status_code == 404 and not r.get_json()["ok"]


def test_checkin_checkout_flow(client, app):
    req = approved_request()
    token = gate_pass_service.token_for(req.gate_pass)
    login(client, "guard@t.io")
    d = client.post("/gate/lookup", json={"code": token}).get_json()
    assert d["valid"] and d["action"] == "checkin"
    assert client.post("/gate/checkin", json={"pass_no": d["pass_no"]}).get_json()["ok"]
    req = db.session.get(VisitRequest, req.id)
    assert req.visit_status == "checked_in" and req.log.entry_guard.email == "guard@t.io"
    assert client.post("/gate/lookup", json={"code": token}).get_json()["action"] == "checkout"
    assert client.post("/gate/checkout", json={"pass_no": d["pass_no"]}).get_json()["ok"]
    req = db.session.get(VisitRequest, req.id)
    assert req.visit_status == "checked_out" and req.gate_pass.status == "used" and req.log.exit_time
    assert {"gate_entry", "gate_exit"} <= {a.action for a in AuditLog.query.all()}


def test_duplicate_checkin_rejected(client, app):
    req = approved_request()
    no = req.gate_pass.pass_no
    login(client, "guard@t.io")
    assert client.post("/gate/checkin", json={"pass_no": no}).status_code == 200
    r = client.post("/gate/checkin", json={"pass_no": no})
    assert r.status_code == 409 and "Duplicate check-in" in r.get_json()["message"]
    assert VisitLog.query.count() == 1


def test_duplicate_checkout_and_reuse_rejected(client, app):
    req = approved_request()
    no = req.gate_pass.pass_no
    login(client, "guard@t.io")
    assert client.post("/gate/checkout", json={"pass_no": no}).status_code == 409  # never checked in
    client.post("/gate/checkin", json={"pass_no": no})
    client.post("/gate/checkout", json={"pass_no": no})
    r = client.post("/gate/checkout", json={"pass_no": no})
    assert r.status_code == 409 and "already checked out" in r.get_json()["message"]
    r = client.post("/gate/checkin", json={"pass_no": no})   # reuse after completion
    assert r.status_code == 409


def test_concurrent_checkin_atomic_claim(app):
    """A stale in-memory object must not allow a second check-in (conditional UPDATE)."""
    req = approved_request()
    gp = db.session.get(GatePass, req.gate_pass.id)
    assert gp.request.visit_status == "scheduled"
    # another worker checks the visitor in between our read and write
    db.session.execute(text("UPDATE visit_requests SET visit_status='checked_in' WHERE id=:i"), {"i": req.id})
    try:
        gate_service.check_in(gp, guard())
        assert False, "must be rejected"
    except GateError as e:
        assert "concurrent" in str(e) or "Duplicate" in str(e)
    assert VisitLog.query.count() == 0


def test_revoked_pass_rejected(client, app):
    req = approved_request()
    login(client, "admin@t.io")
    client.post(f"/visitors/{req.id}/pass/revoke", data={"reason": "Visitor flagged"})
    logout(client)
    login(client, "guard@t.io")
    r = client.post("/gate/checkin", json={"pass_no": req.gate_pass.pass_no})
    assert r.status_code == 409 and "revoked" in r.get_json()["message"]


def test_expired_pass_rejected(client, app):
    req = approved_request(visit_date=date.today())
    gp = req.gate_pass
    gp.valid_until = datetime.now() - timedelta(minutes=1)
    db.session.commit()
    login(client, "guard@t.io")
    r = client.post("/gate/checkin", json={"pass_no": gp.pass_no})
    assert r.status_code == 409 and "expired" in r.get_json()["message"]


def test_future_pass_not_valid_yet(client, app):
    req = approved_request(visit_date=date.today() + timedelta(days=3))
    login(client, "guard@t.io")
    r = client.post("/gate/checkin", json={"pass_no": req.gate_pass.pass_no})
    assert r.status_code == 409 and "not valid before" in r.get_json()["message"]


def test_rejected_and_cancelled_cannot_enter(client, app):
    req = make_request()
    req.approval_status = "rejected"
    db.session.commit()
    from app.services.gate_pass_service import issue
    gp = issue(req)
    db.session.commit()
    login(client, "guard@t.io")
    r = client.post("/gate/checkin", json={"pass_no": gp.pass_no})
    assert r.status_code == 409 and "rejected" in r.get_json()["message"]


def test_maintenance_marks_missed_and_expires(app):
    from app.services.maintenance_service import run_maintenance
    req = approved_request()
    req.gate_pass.valid_until = datetime.now() - timedelta(hours=1)
    db.session.commit()
    run_maintenance()
    req = db.session.get(VisitRequest, req.id)
    assert req.visit_status == "missed" and req.gate_pass.status == "expired"


def test_watchlist_requires_acknowledgement(client, app):
    req = approved_request(name="Bad Actor", mobile="9000000001")
    admin = User.query.filter_by(email="admin@t.io").first()
    db.session.add(VisitorRestriction(full_name="Bad Actor", mobile="9000000001", reason="Prior incident",
                                      created_by_id=admin.id, review_date=date.today() + timedelta(days=30)))
    db.session.commit()
    login(client, "guard@t.io")
    r = client.post("/gate/checkin", json={"pass_no": req.gate_pass.pass_no})
    assert r.status_code == 428 and r.get_json()["code"] == "ack_required"
    r = client.post("/gate/checkin", json={"pass_no": req.gate_pass.pass_no, "ack_note": "ID verified, different person"})
    assert r.get_json()["ok"]
    assert AuditLog.query.filter_by(action="restriction_override").count() == 1


def test_correction_needs_reason_and_is_audited(client, app):
    req = approved_request()
    login(client, "guard@t.io")
    client.post("/gate/checkin", json={"pass_no": req.gate_pass.pass_no})
    logout(client)
    login(client, "admin@t.io")
    r = client.post(f"/gate/correct/{req.id}", data={"force_checkout": "1", "reason": "x"}, follow_redirects=True)
    assert b"reason" in r.data
    assert db.session.get(VisitRequest, req.id).visit_status == "checked_in"
    client.post(f"/gate/correct/{req.id}", data={"force_checkout": "1", "reason": "Visitor left, guard forgot"})
    req = db.session.get(VisitRequest, req.id)
    assert req.visit_status == "checked_out" and req.log.correction_reason
    assert AuditLog.query.filter_by(action="gate_correction").count() == 1


def test_non_gate_roles_blocked_from_gate_actions(client, app):
    req = approved_request()
    login(client, "host@t.io")
    assert client.post("/gate/checkin", json={"pass_no": req.gate_pass.pass_no}).status_code == 403
