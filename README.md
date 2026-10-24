# Visitor & Gate Pass Management System (Flask)

A digital visitor register for offices, factories and campuses: visitor registration, host approval,
QR gate passes, gate check-in/check-out, dashboards, reports, watchlist and audit logging.

> Screenshots: `docs/screenshots/login.png`, `dashboard.png`, `register.png`, `gate-verify.png`, `pass.png` *(placeholders - add your own)*

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
Changing models later: `flask db migrate -m "msg" && flask db upgrade`.

### Sample accounts (seed)
| Role | Email | Password |
|---|---|---|
| Admin | admin@vgp-demo.com | Admin@123 |
| Receptionist | reception@vgp-demo.com | Recept@123 |
| Host | host1@vgp-demo.com (also host2, host3) | Host@1234 |
| Guard | guard@vgp-demo.com | Guard@123 |

Change or delete these before any real deployment.

## Maintenance commands
- `flask maintenance` – expire passes, mark missed visits, send upcoming-visit reminders (also runs on dashboard load). Schedule via cron every 10 min.
- `flask purge-old-records [--days N]` – anonymise visitors beyond the retention period (default from Settings). Schedule daily.

## Tests
```bash
pytest -q          # uses an isolated in-memory SQLite DB (override with TEST_DATABASE_URL to use a PostgreSQL test DB)
```
Covers auth/permissions, registration, approval/rejection, expiry/revocation, invalid tokens, duplicate check-in/out,
atomic concurrent claim, reports filtering, exports, audit logs.

## Deployment
1. Set `FLASK_CONFIG=production`, a long random `SECRET_KEY`, PostgreSQL `DATABASE_URL`, SMTP variables (optional).
2. Run behind HTTPS (required for camera scanning and secure cookies): `gunicorn -w 3 -b 127.0.0.1:8000 run:app` behind Nginx
   with TLS (Let's Encrypt). Set `RATELIMIT_STORAGE_URI=redis://...` when running several workers.
3. `flask db upgrade`, create the first admin (`python seed.py` on an empty DB then delete demo users, or insert via `flask shell`).
4. Back up the database and `app/uploads/` (visitor photos are served only through authenticated routes).
5. Add cron entries for `flask maintenance` and `flask purge-old-records`.

## Privacy notes
Collect only what policy needs (the "document reference" field is optional - never store full ID numbers unless legally required).
Display a privacy notice to visitors, set the retention period in Settings, and review watchlist entries regularly.

## Structure
`app/` blueprints (`auth, dashboard, visitors, approvals, gate, reports, admin`), `models/`, `services/` (approval, gate pass, gate,
notification, audit, maintenance), `templates/`, `static/`; `migrations/`; `tests/`; `config.py`; `run.py`; `seed.py`.
