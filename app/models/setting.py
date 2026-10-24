from ..extensions import db

DEFAULTS = {
    "org_name": "Acme Corporation",
    "require_approval": "1",          # host approval required
    "walkin_requires_approval": "1",  # walk-ins need host approval
    "host_self_approve": "1",         # host registering own visitor = auto approved
    "receptionist_gate": "1",         # receptionist may record entry/exit
    "categories": "Business,Interview,Vendor,Contractor,Delivery,Guest,Other",
    "retention_days": "365",
    "reminder_minutes": "60",
}


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")

    @staticmethod
    def get(key, default=None):
        row = db.session.get(Setting, key)
        return row.value if row else DEFAULTS.get(key, default)

    @staticmethod
    def flag(key):
        return Setting.get(key) == "1"

    @staticmethod
    def set(key, value):
        row = db.session.get(Setting, key)
        if row:
            row.value = str(value)
        else:
            db.session.add(Setting(key=key, value=str(value)))
