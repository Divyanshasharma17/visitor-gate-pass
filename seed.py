"""Run: python seed.py  (creates tables if missing and loads sample data)."""
from app import create_app
from app.seed import seed_data

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed_data()
