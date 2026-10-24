from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SelectField, BooleanField, TextAreaField, DateField, IntegerField)
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, ValidationError
from ..models import ROLES
from ..utils import password_problem


class UserForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=160)])
    phone = StringField("Phone", validators=[Optional(), Length(max=20)])
    role = SelectField("Role", choices=list(ROLES.items()))
    department_id = SelectField("Department", coerce=int)
    password = PasswordField("Password (leave blank to keep current)", validators=[Optional(), Length(max=128)])
    active = BooleanField("Active", default=True)

    def validate_password(self, field):
        if field.data:
            msg = password_problem(field.data)
            if msg:
                raise ValidationError(msg)


class DepartmentForm(FlaskForm):
    name = StringField("Department name", validators=[DataRequired(), Length(max=100)])
    code = StringField("Code", validators=[Optional(), Length(max=10)])


class RestrictionForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    mobile = StringField("Mobile (optional)", validators=[Optional(), Length(max=20)])
    level = SelectField("Level", choices=[("watchlist", "Watchlist (warn & verify)"), ("blacklist", "Restricted (warn - supervisor review)")])
    reason = TextAreaField("Reason", validators=[DataRequired(), Length(min=5, max=500)])
    review_date = DateField("Review / expiry date", validators=[DataRequired()])


class SettingsForm(FlaskForm):
    org_name = StringField("Organization name", validators=[DataRequired(), Length(max=100)])
    require_approval = BooleanField("Require host approval for visits")
    walkin_requires_approval = BooleanField("Require host approval for walk-ins")
    host_self_approve = BooleanField("Auto-approve when a host registers their own visitor")
    receptionist_gate = BooleanField("Allow receptionists to record entry/exit")
    categories = StringField("Visitor categories (comma separated)", validators=[DataRequired(), Length(max=300)])
    retention_days = IntegerField("Retention period (days) before anonymisation", validators=[DataRequired(), NumberRange(30, 3650)])
    reminder_minutes = IntegerField("Upcoming-visit reminder (minutes before)", validators=[DataRequired(), NumberRange(5, 600)])
