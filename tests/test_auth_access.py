from conftest import login, logout
from app.models import User, AuditLog
from app.extensions import db
from app.auth.routes import make_reset_token


def test_login_success_and_audit(client, app):
    r = login(client, "admin@t.io")
    assert b"Welcome" in r.data
    assert AuditLog.query.filter_by(action="login").count() == 1


def test_login_wrong_password(client):
    r = login(client, "admin@t.io", "wrong")
    assert b"Invalid credentials" in r.data


def test_inactive_user_cannot_login(client, app):
    u = User.query.filter_by(email="rec@t.io").first()
    u.active = False
    db.session.commit()
    assert b"Invalid credentials" in login(client, "rec@t.io").data


def test_private_routes_require_login(client):
    for url in ("/", "/visitors/", "/gate/verify", "/reports/", "/admin/users"):
        r = client.get(url)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_role_restrictions(client):
    login(client, "guard@t.io")
    assert client.get("/admin/users").status_code == 403
    assert client.get("/visitors/").status_code == 403
    assert client.get("/gate/verify").status_code == 200
    logout(client)
    login(client, "host@t.io")
    assert client.get("/admin/audit").status_code == 403
    assert client.get("/gate/verify").status_code == 403
    assert client.get("/approvals/").status_code == 200


def test_password_reset_flow_single_use(client, app):
    u = User.query.filter_by(email="host@t.io").first()
    tok = make_reset_token(u)
    assert client.get(f"/reset-password/{tok}").status_code == 200
    r = client.post(f"/reset-password/{tok}", data={"password": "NewPass123", "confirm": "NewPass123"}, follow_redirects=True)
    assert b"Password updated" in r.data
    assert login(client, "host@t.io", "NewPass123").status_code == 200
    logout(client)
    r = client.get(f"/reset-password/{tok}", follow_redirects=True)
    assert b"invalid or already used" in r.data


def test_weak_password_rejected_on_reset(client):
    u = User.query.filter_by(email="host@t.io").first()
    tok = make_reset_token(u)
    r = client.post(f"/reset-password/{tok}", data={"password": "short", "confirm": "short"})
    assert b"at least 8" in r.data


def test_admin_cannot_deactivate_self(client):
    login(client, "admin@t.io")
    me = User.query.filter_by(email="admin@t.io").first()
    client.post(f"/admin/users/{me.id}/toggle", follow_redirects=True)
    assert db.session.get(User, me.id).active is True
