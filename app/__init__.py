import os
import click
from flask import Flask, render_template, request, jsonify
from flask_login import current_user
from config import config_by_name
from .extensions import db, migrate, login_manager, csrf, mail, limiter


def create_app(config_name=None):
    app = Flask(__name__)
    config_name = config_name or os.getenv("FLASK_CONFIG", "development")
    app.config.from_object(config_by_name[config_name])
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from . import models  # noqa: F401
    from .auth.routes import bp as auth_bp
    from .dashboard.routes import bp as dashboard_bp
    from .visitors.routes import bp as visitors_bp
    from .approvals.routes import bp as approvals_bp
    from .gate.routes import bp as gate_bp
    from .reports.routes import bp as reports_bp
    from .admin.routes import bp as admin_bp
    for bp in (auth_bp, dashboard_bp, visitors_bp, approvals_bp, gate_bp, reports_bp, admin_bp):
        app.register_blueprint(bp)

    @app.context_processor
    def inject_globals():
        ctx = {"org_name": models.Setting.get("org_name", "Visitor & Gate Pass"), "unread_count": 0,
               "recent_notifications": [], "gate_allowed": models.Setting.flag("receptionist_gate")}
        if current_user.is_authenticated:
            q = models.Notification.query.filter_by(user_id=current_user.id)
            ctx["unread_count"] = q.filter_by(is_read=False).count()
            ctx["recent_notifications"] = q.order_by(models.Notification.created_at.desc()).limit(6).all()
        return ctx

    @app.template_filter("dt")
    def fmt_dt(v, fmt="%d %b %Y, %H:%M"):
        return v.strftime(fmt) if v else "-"

    @app.template_filter("d")
    def fmt_d(v):
        return v.strftime("%d %b %Y") if v else "-"

    @app.template_filter("t")
    def fmt_t(v):
        return v.strftime("%H:%M") if v else "-"

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(self)")
        if request.endpoint and request.endpoint != "static" and current_user.is_authenticated:
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def _err(code, title):
        def handler(e):
            if request.path.startswith("/gate/") and request.method == "POST":
                return jsonify(ok=False, message=title), code
            return render_template(f"errors/{code}.html"), code
        return handler

    app.register_error_handler(403, _err(403, "Forbidden"))
    app.register_error_handler(404, _err(404, "Not found"))
    app.register_error_handler(500, _err(500, "Server error"))
    app.register_error_handler(413, lambda e: (render_template("errors/403.html", message="Upload too large (max 2 MB)."), 413))

    @app.cli.command("seed")
    def seed_cmd():
        """Load sample development data."""
        from .seed import seed_data
        seed_data()

    @app.cli.command("maintenance")
    def maintenance_cmd():
        """Expire passes, mark missed visits, send reminders."""
        from .services.maintenance_service import run_maintenance
        run_maintenance()
        click.echo("Maintenance complete.")

    @app.cli.command("purge-old-records")
    @click.option("--days", type=int, default=None)
    def purge_cmd(days):
        """Anonymise visitor records past the retention period."""
        from .services.maintenance_service import purge_old_records
        click.echo(f"Anonymised {purge_old_records(days)} visitor(s).")

    return app
