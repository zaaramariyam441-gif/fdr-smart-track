from datetime import date, timedelta
from decimal import Decimal

from app import db
from app.models import FDR


def seed_demo(user_id):
    if FDR.query.filter_by(is_demo=True).first():
        return 0
    today = date.today()
    banks = ["SBI", "Canara Bank", "HDFC Bank", "Bank of Baroda", "ICICI Bank"]
    offsets = [-35, -8, -1, 0, 3, 7, 14, 22, 30, 45, 70, 95, 120, 180, 240, 330]
    for index, offset in enumerate(offsets, start=1):
        maturity = today + timedelta(days=offset)
        start = maturity - timedelta(days=365 + index * 11)
        fdr = FDR(
            fdr_number=f"DEMO-FDR-{index:03d}",
            institution="Northstar Institute of Technology (Demo)",
            bank=banks[(index - 1) % len(banks)],
            branch=f"Campus Branch {1 + (index - 1) % 3}",
            principal=Decimal(250000 + index * 137500),
            interest_rate=Decimal("6.50") + Decimal(index % 5) * Decimal("0.20"),
            start_date=start,
            maturity_date=maturity,
            purpose=["Student scholarship corpus", "Library security deposit", "Utility guarantee"][
                (index - 1) % 3
            ],
            renewal_preference="review",
            notes="Synthetic demonstration record; not real institutional financial data.",
            is_demo=True,
            created_by_id=user_id,
        )
        db.session.add(fdr)
    db.session.commit()
    return len(offsets)
