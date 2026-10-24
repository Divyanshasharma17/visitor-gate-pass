from datetime import date, time, datetime, timedelta
from .extensions import db
from .models import (User, Department, Visitor, VisitRequest, VisitLog, Setting, VisitorRestriction, GatePass)
from .models.visit_request import new_request_no
from .services import gate_pass_service


def seed_data():
    db.create_all()
    if User.query.first():
        print("Database already has data - skipping seed.")
        return
    depts = {n: Department(name=n, code=c) for n, c in
             [("Human Resources", "HR"), ("Information Technology", "IT"), ("Finance", "FIN"),
              ("Operations", "OPS"), ("Administration", "ADM")]}
    db.session.add_all(depts.values())
    db.session.flush()

    def mk(name, email, pw, role, dept):
        u = User(name=name, email=email, role=role, department_id=depts[dept].id if dept else None)
        u.set_password(pw)
        db.session.add(u)
        return u

    admin = mk("Asha Admin", "admin@vgp-demo.com", "Admin@123", "admin", "Administration")
    recep = mk("Ravi Reception", "reception@vgp-demo.com", "Recept@123", "receptionist", "Administration")
    h1 = mk("Neha Sharma", "host1@vgp-demo.com", "Host@1234", "host", "Information Technology")
    h2 = mk("Karan Mehta", "host2@vgp-demo.com", "Host@1234", "host", "Human Resources")
    h3 = mk("Priya Nair", "host3@vgp-demo.com", "Host@1234", "host", "Finance")
    mk("Sunil Guard", "guard@vgp-demo.com", "Guard@123", "guard", None)
    db.session.flush()
    for k in ("org_name",):
        Setting.set(k, "Acme Corporation")

    people = [("Rahul Verma", "9820011111", "Tata Consulting", "Business"),
              ("Anita Desai", "9820022222", "Globex Ltd", "Interview"),
              ("Mohan Patil", "9820033333", "FastFix Services", "Contractor"),
              ("Sara Khan", "9820044444", "Initech", "Vendor"),
              ("Vikram Rao", "9820055555", "Umbrella Corp", "Guest")]
    visitors = []
    for n, m, c, _ in people:
        v = Visitor(full_name=n, mobile=m, company=c)
        db.session.add(v)
        visitors.append(v)
    db.session.flush()

    hosts = [h1, h2, h3]
    today = date.today()

    def add(i, offset, approval, visit, inside=False, done=False, walkin=False):
        v, host = visitors[i % 5], hosts[i % 3]
        r = VisitRequest(request_no=new_request_no(), visitor_id=v.id, host_id=host.id,
                         department_id=host.department_id, created_by_id=recep.id,
                         category=people[i % 5][3], purpose="Meeting / sample visit",
                         visit_date=today + timedelta(days=offset), expected_arrival=time(10, 0),
                         expected_departure=time(12, 0), companions=i % 3, consent=True,
                         approval_status=approval, visit_status=visit, is_walkin=walkin)
        db.session.add(r)
        db.session.flush()
        if approval == "approved":
            gp = gate_pass_service.issue(r)
            if inside or done:
                st = datetime.combine(r.visit_date, time(10, 5))
                db.session.add(VisitLog(request_id=r.id, pass_id=gp.id, entry_time=st,
                                        exit_time=st + timedelta(hours=1, minutes=i * 7) if done else None))
                if done:
                    gp.status = "used"
        return r

    for i, off in enumerate(range(-12, 0)):          # historical, completed
        add(i, off, "approved", "checked_out", done=True)
    add(0, 0, "approved", "checked_in", inside=True)  # currently inside
    add(1, 0, "approved", "scheduled")                # expected today
    add(2, 0, "pending", "scheduled")                 # waiting approval
    add(3, 1, "approved", "scheduled")                # tomorrow
    add(4, 2, "pending", "scheduled")
    add(3, -1, "rejected", "scheduled")
    add(2, 0, "approved", "scheduled", walkin=True)
    db.session.add(VisitorRestriction(full_name="Test Watchlist Person", mobile="9000000000", level="watchlist",
                                      reason="Sample entry: previously escorted out (demo data)",
                                      created_by_id=admin.id, review_date=today + timedelta(days=90)))
    db.session.commit()
    print("Seed complete. Accounts:\n"
          "  admin@vgp-demo.com / Admin@123\n  reception@vgp-demo.com / Recept@123\n"
          "  host1@vgp-demo.com / Host@1234 (also host2, host3)\n  guard@vgp-demo.com / Guard@123")
