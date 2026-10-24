from datetime import date, time, timedelta
import pytest
from app import create_app
from app.extensions import db
from app.models import User, Department, Visitor, VisitRequest
from app.models.visit_request import new_request_no


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        d = Department(name="IT", code="IT")
        db.session.add(d)
        db.session.flush()
        for name, email, role in [("Admin", "admin@t.io", "admin"), ("Recep", "rec@t.io", "receptionist"),
                                  ("Host", "host@t.io", "host"), ("Host2", "host2@t.io", "host"),
                                  ("Guard", "guard@t.io", "guard")]:
            u = User(name=name, email=email, role=role, department_id=d.id)
            u.set_password("Passw0rd!")
            db.session.add(u)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, pw="Passw0rd!"):
    return client.post("/login", data={"email": email, "password": pw}, follow_redirects=True)


def logout(client):
    return client.post("/logout", follow_redirects=True)


def make_request(host_email="host@t.io", visit_date=None, approval="draft", name="Vic Visitor", mobile="9876543210",
                 arrival=time(10, 0), departure=time(11, 0), category="Business", creator_email="rec@t.io"):
    host = User.query.filter_by(email=host_email).first()
    creator = User.query.filter_by(email=creator_email).first()
    v = Visitor.query.filter_by(full_name=name, mobile=mobile).first()
    if not v:
        v = Visitor(full_name=name, mobile=mobile)
        db.session.add(v)
        db.session.flush()
    r = VisitRequest(request_no=new_request_no(), visitor_id=v.id, host_id=host.id, department_id=host.department_id,
                     created_by_id=creator.id, category=category, purpose="Meeting",
                     visit_date=visit_date or date.today(), expected_arrival=arrival, expected_departure=departure,
                     consent=True, approval_status="draft")
    db.session.add(r)
    db.session.commit()
    return r


def approved_request(**kw):
    """Create a request and approve it through the real service (issues a pass)."""
    from app.services import approval_service
    r = make_request(**kw)
    host = db.session.get(User, r.host_id)
    admin = User.query.filter_by(email="admin@t.io").first()
    r.approval_status = "pending"
    db.session.commit()
    approval_service.decide(r, host, "approved", "ok")
    return db.session.get(VisitRequest, r.id)
