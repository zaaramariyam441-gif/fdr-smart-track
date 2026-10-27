import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)
    default_uploads = instance_path / "uploads"

    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=os.getenv(
            "DATABASE_URL", f"sqlite:///{instance_path / 'fdr_smarttrack.db'}"
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_CONTENT_LENGTH", 10 * 1024 * 1024)),
        UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER") or str(default_uploads),
        ALLOWED_EXTENSIONS={
            extension.strip().lower()
            for extension in os.getenv("ALLOWED_EXTENSIONS", "pdf,png,jpg,jpeg").split(",")
            if extension.strip()
        },
        REMINDER_THRESHOLDS=tuple(
            sorted(
                {
                    int(value.strip())
                    for value in os.getenv("REMINDER_THRESHOLDS", "30,7,1").split(",")
                    if value.strip().isdigit()
                },
                reverse=True,
            )
        ),
        APP_TIMEZONE=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
        INSTITUTION_NAME=os.getenv("INSTITUTION_NAME", "Example Institution"),
        DEMO_MODE=os.getenv("DEMO_MODE", "0") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.login"
    login_manager.login_message_category = "warning"
    csrf.init_app(app)

    from app.models import User
    from app.routes import main

    app.register_blueprint(main)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.cli.command("init-db")
    def init_db_command():
        """Create database tables without overwriting existing data."""
        with app.app_context():
            db.create_all()
        print("Database tables are ready.")

    @app.cli.command("create-admin")
    def create_admin_command():
        """Interactively create the first administrator account."""
        import getpass

        from app.models import User

        username = input("Username: ").strip()
        email = input("Email: ").strip().lower()
        password = getpass.getpass("Password (min 12 characters): ")
        if len(password) < 12:
            raise SystemExit("Password must contain at least 12 characters.")
        if User.query.filter(
            (User.username == username) | (User.email == email)
        ).first():
            raise SystemExit("That username or email is already in use.")
        user = User(username=username, email=email, role="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Administrator account created for {email}.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Add clearly identified synthetic FDR records, once."""
        from app.models import FDR, User
        from app.seed import seed_demo

        with app.app_context():
            admin = User.query.filter_by(role="admin", active=True).first()
            if not admin:
                raise SystemExit("Create an administrator first with: flask create-admin")
            added = seed_demo(admin.id)
            print(f"Added {added} synthetic demo records.")

    @app.cli.command("create-demo-user")
    def create_demo_user_command():
        """Create a development-only demo administrator with an environment password."""
        from app.models import User

        with app.app_context():
            if not app.debug or not app.config["DEMO_MODE"]:
                raise SystemExit(
                    "Demo accounts require both FLASK_DEBUG=1 and DEMO_MODE=1."
                )
            username = os.getenv("DEMO_USERNAME", "demo").strip()
            email = os.getenv("DEMO_EMAIL", "demo@example.test").strip().lower()
            password = os.getenv("DEMO_PASSWORD", "")
            if len(password) < 16:
                raise SystemExit("Set DEMO_PASSWORD to a unique password of at least 16 characters.")
            if User.query.filter(
                (User.username == username) | (User.email == email)
            ).first():
                raise SystemExit("The configured demo username or email is already in use.")
            user = User(username=username, email=email, role="admin")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            print(f"Development demo administrator created for {email}; password not displayed.")

    @app.cli.command("generate-reminders")
    def generate_reminders_command():
        """Generate deduplicated in-app maturity reminders."""
        from app.reminders import generate_reminders

        with app.app_context():
            created = generate_reminders()
            print(f"Created {created} reminder(s).")

    @app.errorhandler(413)
    def too_large(_error):
        from flask import flash, redirect, request, url_for

        flash("The upload exceeds the 10 MB limit. Choose a smaller file.", "error")
        return redirect(request.referrer or url_for("main.documents"))

    return app
