from datetime import date
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import (StringField, SelectField, TextAreaField, DateField, TimeField, IntegerField, BooleanField)
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional, Regexp, ValidationError


class VisitRequestForm(FlaskForm):
    full_name = StringField("Visitor full name", validators=[DataRequired(), Length(max=120)])
    mobile = StringField("Mobile number", validators=[DataRequired(), Regexp(
        r"^\+?[0-9\s\-]{7,16}$", message="Enter a valid mobile number")])
    email = StringField("Email (optional)", validators=[Optional(), Email(), Length(max=160)])
    company = StringField("Company / organization", validators=[Optional(), Length(max=120)])
    category = SelectField("Visitor category")
    host_id = SelectField("Person to meet (host)", coerce=int)
    department_id = SelectField("Department", coerce=int)
    purpose = TextAreaField("Purpose of visit", validators=[DataRequired(), Length(min=3, max=500)])
    visit_date = DateField("Visit date", validators=[DataRequired()])
    expected_arrival = TimeField("Expected arrival", validators=[DataRequired()])
    expected_departure = TimeField("Expected departure", validators=[DataRequired()])
    companions = IntegerField("Accompanying visitors", default=0, validators=[Optional(), NumberRange(0, 50)])
    group_members = TextAreaField("Group member names (one per line, optional)", validators=[Optional(), Length(max=1000)])
    vehicle_no = StringField("Vehicle number (optional)", validators=[Optional(), Length(max=20)])
    document_ref = StringField("Document / reference details (only if policy requires)",
                               validators=[Optional(), Length(max=100)])
    photo = FileField("Visitor photograph (optional, JPG/PNG, max 2 MB)")
    consent = BooleanField("The visitor has been informed about how their personal data is collected, used "
                           "and retained for security purposes, and consents to it.",
                           validators=[DataRequired(message="Consent/notice acknowledgement is required.")])

    def validate_visit_date(self, field):
        if field.data and field.data < date.today():
            raise ValidationError("Visit date cannot be in the past.")

    def validate_expected_departure(self, field):
        if field.data and self.expected_arrival.data and field.data <= self.expected_arrival.data:
            raise ValidationError("Departure must be after arrival.")
