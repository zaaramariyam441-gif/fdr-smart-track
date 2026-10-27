from datetime import date, timedelta

from app import db
from app.models import FDR, Notification, User


def generate_reminders(today=None):
    today = today or date.today()
    thresholds = current_app_thresholds()
    users = User.query.filter_by(active=True).all()
    created = 0
    records = FDR.query.filter_by(archived=False).all()
    for fdr in records:
        days = (fdr.maturity_date - today).days
        if days < 0:
            kind, label = "overdue", f"matured {abs(days)} day(s) ago"
        elif days == 0:
            kind, label = "maturity_today", "matures today"
        elif days in thresholds:
            kind, label = "upcoming_maturity", f"matures in {days} day(s)"
        else:
            continue
        for user in users:
            occurrence = str(days) if kind == "upcoming_maturity" else kind
            event_key = f"maturity:{fdr.id}:{fdr.maturity_date.isoformat()}:{occurrence}:{user.id}"
            if Notification.query.filter_by(event_key=event_key).first():
                continue
            db.session.add(
                Notification(
                    user_id=user.id,
                    fdr_id=fdr.id,
                    notification_type=kind,
                    message=f"{fdr.fdr_number} at {fdr.bank} {label}.",
                    event_key=event_key,
                )
            )
            created += 1
    db.session.commit()
    return created


def current_app_thresholds():
    from flask import current_app

    return current_app.config["REMINDER_THRESHOLDS"]
