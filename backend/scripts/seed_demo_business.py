"""Insert a demo user + business so /api/audits has something to audit.

Usage:
    .venv/bin/python -m scripts.seed_demo_business
Prints the business_id to stdout.
"""
from app.db import SessionLocal
from app.models import Business, User


def main() -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email="demo@example.com").one_or_none()
        if user is None:
            user = User(email="demo@example.com")
            db.add(user)
            db.commit()
            db.refresh(user)

        business = (
            db.query(Business)
            .filter_by(user_id=user.id, name="Brewmorphia Cafe")
            .one_or_none()
        )
        if business is None:
            business = Business(
                user_id=user.id,
                name="Brewmorphia Cafe",
                city="Calicut",
                country="India",
                website="https://cafficana.com",
                ig_handle="brewmorphia",
            )
            db.add(business)
            db.commit()
            db.refresh(business)

        print(business.id)
        return business.id
    finally:
        db.close()


if __name__ == "__main__":
    main()
