from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="finance")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"


class FDR(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fdr_number = db.Column(db.String(100), nullable=False, unique=True, index=True)
    institution = db.Column(db.String(160), nullable=False)
    bank = db.Column(db.String(120), nullable=False, index=True)
    branch = db.Column(db.String(120), nullable=True)
    principal = db.Column(db.Numeric(14, 2), nullable=False)
    interest_rate = db.Column(db.Numeric(5, 2), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    maturity_date = db.Column(db.Date, nullable=False, index=True)
    purpose = db.Column(db.String(200), nullable=True)
    renewal_preference = db.Column(db.String(30), nullable=False, default="review")
    notes = db.Column(db.Text, nullable=True)
    is_demo = db.Column(db.Boolean, nullable=False, default=False, index=True)
    archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    creator = db.relationship("User", backref="fdr_records")
    documents = db.relationship(
        "Document", back_populates="fdr", cascade="all, delete-orphan"
    )

    @property
    def days_remaining(self):
        today = datetime.now(ZoneInfo(current_app.config["APP_TIMEZONE"])).date()
        return (self.maturity_date - today).days

    @property
    def status(self):
        if self.archived:
            return "Archived"
        days = self.days_remaining
        if days < 0:
            return "Matured"
        if days <= 30:
            return "Upcoming"
        return "Active"

    @property
    def estimated_maturity(self):
        years = (self.maturity_date - self.start_date).days / 365.0
        return float(self.principal) * (1 + float(self.interest_rate) / 100 * years)


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fdr_id = db.Column(db.Integer, db.ForeignKey("fdr.id"), nullable=False, index=True)
    stored_name = db.Column(db.String(255), unique=True, nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    document_type = db.Column(db.String(40), nullable=False, default="receipt")
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    uploaded_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    fdr = db.relationship("FDR", back_populates="documents")
    uploader = db.relationship("User")


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    fdr_id = db.Column(db.Integer, db.ForeignKey("fdr.id"), nullable=True, index=True)
    notification_type = db.Column(db.String(40), nullable=False)
    message = db.Column(db.String(300), nullable=False)
    event_key = db.Column(db.String(180), unique=True, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    read_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User")
    fdr = db.relationship("FDR")


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    action = db.Column(db.String(60), nullable=False)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.String(80), nullable=True)
    description = db.Column(db.String(300), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        index=True,
    )

    user = db.relationship("User")
