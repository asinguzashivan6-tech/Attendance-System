import argparse
import getpass

from sqlalchemy import text

from app import app, db, User


def ensure_is_active_column():
    with app.app_context():
        db.create_all()
        columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(users)"))]
        if 'is_active' not in columns:
            db.session.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
            db.session.commit()
            print("Migrated: added 'is_active' column to users table")
        else:
            print("Schema OK: 'is_active' already present")


def create_admin(name, email, password):
    with app.app_context():
        email = email.strip().lower()
        existing = User.query.filter_by(email=email).first()
        if existing:
            if existing.role != 'admin':
                existing.role = 'admin'
                existing.is_active = True
                db.session.commit()
                print(f"Promoted existing account to admin: {email}")
            else:
                print(f"Admin already exists: {email}")
            return
        admin = User(name=name, email=email, role='admin', is_active=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f"Admin created: {email}")


def main():
    parser = argparse.ArgumentParser(description="Create the first admin account")
    parser.add_argument('--name', help="Admin full name")
    parser.add_argument('--email', help="Admin email")
    parser.add_argument('--password', help="Admin password (min 6 chars)")
    args = parser.parse_args()

    ensure_is_active_column()

    name = args.name or input("Admin full name: ").strip()
    email = args.email or input("Admin email: ").strip()
    password = args.password or getpass.getpass("Admin password (min 6 chars): ")

    if len(password) < 6:
        print("Password must be at least 6 characters")
        return

    create_admin(name, email, password)


if __name__ == '__main__':
    main()
