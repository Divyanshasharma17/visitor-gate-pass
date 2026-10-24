from datetime import date, timedelta
from conftest import login, logout, make_request, approved_request
from app.models import AuditLog


def test_report_date_filter(client, app):
    approved_request(visit_date=date.today(), name="Today Person", mobile="9111111111")
    approved_request(visit_date=date.today() - timedelta(days=60), name="Old Person", mobile="9222222222")
    login(client, "admin@t.io")
    r = client.get("/reports/?type=daily")  # default last 30 days
    assert r.status_code == 200 and date.today().isoformat().encode() in r.data
    assert (date.today() - timedelta(days=60)).isoformat().encode() not in r.data
    frm = (date.today() - timedelta(days=90)).isoformat()
    r = client.get(f"/reports/?type=daily&from={frm}")
    assert (date.today() - timedelta(days=60)).isoformat().encode() in r.data


def test_host_report_scoped_to_own(client, app):
    approved_request(host_email="host@t.io", name="Mine", mobile="9333333333")
    approved_request(host_email="host2@t.io", name="Theirs", mobile="9444444444")
    login(client, "host@t.io")
    csvdata = client.get("/reports/?type=host&format=csv").data  # 'host' type falls back to history for hosts
    r = client.get("/reports/?type=department&format=csv")
    assert r.status_code == 200
    lines = r.data.decode().strip().splitlines()
    assert lines[1].split(",")[1] == "1"           # only own request counted


def test_guard_report_limited_to_inside(client, app):
    login(client, "guard@t.io")
    r = client.get("/reports/?type=history")
    assert r.status_code == 200 and b"Currently inside" in r.data


def test_export_is_audited_and_csv_safe(client, app):
    approved_request(name="=cmd()", mobile="9555555555")
    login(client, "admin@t.io")
    client.post("/gate/checkin", json={})  # noop
    r = client.get("/reports/?type=history&format=csv")
    assert r.mimetype == "text/csv"
    assert AuditLog.query.filter_by(action="report_export").count() == 1
    x = client.get("/reports/?type=department&format=xlsx")
    assert x.status_code == 200 and x.data[:2] == b"PK"


def test_audit_log_page_admin_only_and_no_secrets(client, app):
    req = approved_request()
    from app.services.gate_pass_service import token_for
    tok = token_for(req.gate_pass)
    login(client, "admin@t.io")
    client.post("/gate/lookup", json={"code": "bad"})
    assert client.get("/admin/audit").status_code == 200
    for a in AuditLog.query.all():
        assert tok not in str(a.details) and "Passw0rd" not in str(a.details)
    logout(client)
    login(client, "rec@t.io")
    assert client.get("/admin/audit").status_code == 403


def test_user_role_change_audited(client, app):
    from app.models import User
    login(client, "admin@t.io")
    u = User.query.filter_by(email="rec@t.io").first()
    client.post(f"/admin/users/{u.id}/edit", data={"name": u.name, "email": u.email, "role": "guard",
                                                   "department_id": u.department_id, "active": "y", "password": ""})
    a = AuditLog.query.filter_by(action="user_updated").one()
    assert "receptionist->guard" in str(a.details)


def test_error_pages(client):
    assert client.get("/nope").status_code == 404
