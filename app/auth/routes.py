from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask_mail import Message
from ..extensions import db, limiter, mail
from ..models import User
from ..services import audit_service
from ..utils import safe_next
from .forms import LoginForm, ForgotForm, ResetForm, ChangePasswordForm

bp = Blueprint("auth", __name__)


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def make_reset_token(user):
    # includes a slice of the current hash so the link is single-use
    return _serializer().dumps({"id": user.id, "h": user.password_hash[-12:]})


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user and user.check_password(form.password.data) and user.active:
            login_user(user, remember=form.remember.data)
            user.last_login_at = datetime.now()
            audit_service.log("login", "User", user.id, actor=user)
            db.session.commit()
            return redirect(safe_next(request.args.get("next")) or url_for("dashboard.index"))
        audit_service.log("login_failed", "User", user.id if user else None, actor=None)
        db.session.commit()
        flash("Invalid credentials or inactive account.", "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    audit_service.log("logout", "User", current_user.id)
    db.session.commit()
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def forgot():
    form = ForgotForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower(), active=True).first()
        if user:
            link = url_for("auth.reset", token=make_reset_token(user), _external=True)
            audit_service.log("password_reset_requested", "User", user.id, actor=user)
            db.session.commit()
            if current_app.config.get("MAIL_SERVER"):
                try:
                    mail.send(Message("Password reset", recipients=[user.email],
                                      body=f"Use this link within 1 hour to reset your password:\n{link}"))
                except Exception as exc:
                    current_app.logger.warning("Reset email failed: %s", exc)
            else:
                current_app.logger.warning("MAIL not configured. Reset link (dev only): %s", link)
                if current_app.debug:
                    flash(f"Dev mode - reset link: {link}", "info")
        flash("If that account exists, a reset link has been sent.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=form)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset(token):
    try:
        data = _serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        flash("Reset link is invalid or expired.", "danger")
        return redirect(url_for("auth.forgot"))
    user = db.session.get(User, data["id"])
    if not user or not user.active or user.password_hash[-12:] != data["h"]:
        flash("Reset link is invalid or already used.", "danger")
        return redirect(url_for("auth.forgot"))
    form = ResetForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        audit_service.log("password_reset", "User", user.id, actor=user)
        db.session.commit()
        flash("Password updated. Please sign in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current.data):
            form.current.errors.append("Current password is incorrect.")
        else:
            current_user.set_password(form.password.data)
            audit_service.log("password_changed", "User", current_user.id)
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html", form=form)
