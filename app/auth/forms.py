from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
from ..utils import password_problem


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Keep me signed in")


class ForgotForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])


class ResetForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(), Length(max=128)])
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", "Passwords must match")])

    def validate_password(self, field):
        msg = password_problem(field.data)
        if msg:
            raise ValidationError(msg)


class ChangePasswordForm(ResetForm):
    current = PasswordField("Current password", validators=[DataRequired()])
