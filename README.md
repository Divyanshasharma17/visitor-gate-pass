# GateFlow 

A digital visitor register for offices, factories and campuses: visitor registration, host approval,
QR gate passes, gate check-in/check-out, dashboards, reports, watchlist and audit logging.

## Features
- **Roles** (server-side RBAC + object-level checks): Administrator, Receptionist, Host, Security Guard
- **Registration**: pre-registered, walk-in and group visits, photo upload (validated), duplicate-booking check, consent notice
- **Workflow**: Draft → Pending → Approved / Rejected / Cancelled; approval, visit and pass statuses are stored separately;
  atomic transitions prevent duplicate approvals; configurable approval policy (Settings)
- **Gate pass**: HMAC-derived random token, only its SHA-256 hash is stored, QR contains no personal data,
  print-friendly page, revoke / reissue / email, expiry
- **Gate**: camera QR scanner (BarcodeDetector, jsQR fallback) + manual lookup, atomic check-in/out (conditional UPDATE +
  unique visit log), duplicate/reuse rejection, open-visit handling, corrections with mandatory reason, suspicious-activity reports
- **Dashboard** per role with Chart.js trends, **notifications** (in-app, optional SMTP), **reports** (7 types, filters, CSV/Excel/print)
- **Watchlist**: warnings only (never auto-deny), review/expiry dates, override note + audit log
- **Audit log** for logins, edits, approvals, passes, gate events, exports, permission changes (no passwords/QR secrets)
- **Security**: CSRF, hashed passwords, rate limiting (login, reset, gate), secure cookies in production, upload validation,
  CSV-injection-safe exports, security headers, retention/anonymisation command

## Quick start
```bash
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # edit SECRET_KEY and DATABASE_URL
createdb visitor_gate_pass                             # PostgreSQL
flask db upgrade                                       # apply migrations
python seed.py                                         # sample data (or: flask seed)
flask run                                              # http://127.0.0.1:5000
```

### Sample accounts (seed)
| Role | Email | Password |
|---|---|---|
| Admin | admin@vgp-demo.com | Admin@123 |
| Receptionist | reception@vgp-demo.com | Recept@123 |
| Host | host1@vgp-demo.com (also host2, host3) | Host@1234 |
| Guard | guard@vgp-demo.com | Guard@123 |
