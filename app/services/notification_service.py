from flask import current_app
from flask_mail import Message
from ..extensions import db, mail
from ..models import Notification, User


def notify(user, message, link=None, email=True):
    u = user if hasattr(user, "id") else db.session.get(User, user)
    if not u:
        return
    db.session.add(Notification(user_id=u.id, message=message[:255], link=link))
    if email and current_app.config.get("MAIL_SERVER") and u.email:
        try:
            mail.send(Message(subject="Visitor & Gate Pass: notification", recipients=[u.email], body=message))
        except Exception as exc:  # email is optional; never break the workflow
            current_app.logger.warning("Email send failed: %s", exc)


def notify_roles(roles, message, link=None):
    for u in User.query.filter(User.role.in_(roles), User.active.is_(True)).all():
        notify(u, message, link)
