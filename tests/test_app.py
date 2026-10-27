import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.models import AuditLog, FDR, Notification, User
from app.reminders import generate_reminders


class FDRSmartTrackTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SECRET_KEY": "test-key-not-for-production",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{root / 'test.db'}",
                "UPLOAD_FOLDER": str(root / "uploads"),
                "REMINDER_THRESHOLDS": (30, 7, 1),
            }
        )
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.admin = User(username="administrator", email="admin@example.test", role="admin")
        self.admin.set_password("long-test-password-1")
        self.finance = User(username="finance", email="finance@example.test", role="finance")
        self.finance.set_password("long-test-password-2")
        db.session.add_all([self.admin, self.finance])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        self.temp_dir.cleanup()

    def login(self, username="finance", password="long-test-password-2"):
        return self.client.post(
            "/login", data={"identity": username, "password": password}, follow_redirects=True
        )

    def add_record(self, number="FDR-TEST-1", maturity=None):
        today = date.today()
        return FDR(
            fdr_number=number,
            institution="Test Institution",
            bank="Test Bank",
            principal=100000,
            interest_rate=6.5,
            start_date=today - timedelta(days=365),
            maturity_date=maturity or today + timedelta(days=7),
            created_by_id=self.admin.id,
        )

    def test_passwords_are_hashed_and_login_logout_work(self):
        self.assertNotEqual(self.admin.password_hash, "long-test-password-1")
        self.assertTrue(self.admin.check_password("long-test-password-1"))
        response = self.login("admin@example.test", "long-test-password-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"FINANCE OVERVIEW", response.data)
        response = self.client.post("/logout", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_fdr_create_and_duplicate_validation(self):
        self.login()
        values = {
            "fdr_number": "fdr-test-new",
            "institution": "Test Institution",
            "bank": "Test Bank",
            "principal": "100000.00",
            "interest_rate": "6.5",
            "start_date": (date.today() - timedelta(days=10)).isoformat(),
            "maturity_date": (date.today() + timedelta(days=90)).isoformat(),
            "renewal_preference": "review",
        }
        response = self.client.post("/fdr/new", data=values, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FDR.query.count(), 1)
        self.assertEqual(FDR.query.first().fdr_number, "FDR-TEST-NEW")
        self.assertEqual(AuditLog.query.filter_by(action="created").count(), 1)
        response = self.client.post("/fdr/new", data=values)
        self.assertIn(b"already registered", response.data)
        self.assertEqual(FDR.query.count(), 1)

    def test_fdr_edit_updates_saved_record(self):
        record = self.add_record()
        db.session.add(record)
        db.session.commit()
        self.login()
        response = self.client.post(
            f"/fdr/{record.id}/edit",
            data={
                "fdr_number": record.fdr_number,
                "institution": record.institution,
                "bank": "Updated Bank",
                "branch": "Central",
                "principal": "125000.00",
                "interest_rate": "7.1",
                "start_date": record.start_date.isoformat(),
                "maturity_date": record.maturity_date.isoformat(),
                "renewal_preference": "payout",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(record.bank, "Updated Bank")
        self.assertEqual(record.principal, 125000)
        self.assertEqual(record.renewal_preference, "payout")

    def test_external_login_redirect_is_rejected(self):
        response = self.client.post(
            "/login?next=https://example.com/",
            data={"identity": "finance", "password": "long-test-password-2"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))

    def test_demo_user_command_requires_explicit_development_configuration(self):
        result = self.app.test_cli_runner().invoke(args=["create-demo-user"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(User.query.count(), 2)

    def test_demo_user_command_uses_configured_password_without_printing_it(self):
        self.app.config.update(DEBUG=True, DEMO_MODE=True)
        password = "local-demo-password-only-123"
        with patch.dict(
            "os.environ",
            {
                "DEMO_USERNAME": "judge-demo",
                "DEMO_EMAIL": "judge@example.test",
                "DEMO_PASSWORD": password,
            },
        ):
            result = self.app.test_cli_runner().invoke(args=["create-demo-user"])
        self.assertEqual(result.exit_code, 0, result.output)
        demo = User.query.filter_by(username="judge-demo").one()
        self.assertTrue(demo.is_admin)
        self.assertTrue(demo.check_password(password))
        self.assertNotIn(password, result.output)

    def test_demo_seed_is_synthetic_and_idempotent(self):
        first = self.app.test_cli_runner().invoke(args=["seed-demo"])
        second = self.app.test_cli_runner().invoke(args=["seed-demo"])
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertEqual(second.exit_code, 0, second.output)
        records = FDR.query.filter_by(is_demo=True).all()
        self.assertEqual(len(records), 16)
        self.assertTrue(all("Demo" in record.institution for record in records))

    def test_primary_navigation_pages_render_for_admin(self):
        record = self.add_record()
        db.session.add(record)
        db.session.commit()
        self.login("administrator", "long-test-password-1")
        paths = [
            "/dashboard",
            "/fdr",
            "/fdr/new",
            f"/fdr/{record.id}",
            f"/fdr/{record.id}/edit",
            "/maturities",
            "/documents",
            "/notifications",
            "/reports",
            "/reports/pdf",
            "/audit",
            "/users",
            "/settings",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, path)
                if path == "/dashboard":
                    self.assertIn("₹100,000".encode("utf-8"), response.data)
                    self.assertIn(b"Test Bank", response.data)

    def test_admin_route_denies_finance_user(self):
        record = self.add_record()
        db.session.add(record)
        db.session.commit()
        self.login()
        response = self.client.get("/audit")
        self.assertEqual(response.status_code, 403)
        archive_response = self.client.post(f"/fdr/{record.id}/archive")
        self.assertEqual(archive_response.status_code, 403)
        self.assertFalse(record.archived)

    def test_reminders_are_created_once_per_occurrence(self):
        db.session.add(self.add_record(maturity=date.today() + timedelta(days=7)))
        db.session.commit()
        first = generate_reminders(date.today())
        second = generate_reminders(date.today())
        self.assertEqual(first, 2)
        self.assertEqual(second, 0)
        self.assertEqual(Notification.query.count(), 2)

    def test_upload_and_authorized_download(self):
        record = self.add_record()
        db.session.add(record)
        db.session.commit()
        self.login()
        response = self.client.post(
            f"/fdr/{record.id}/upload",
            data={
                "document": (io.BytesIO(b"%PDF-1.4\nsample"), "receipt.pdf"),
                "document_type": "receipt",
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(record.documents), 1)
        download = self.client.get(f"/documents/{record.documents[0].id}/download")
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"%PDF-1.4", download.data)
        download.close()
        self.client.post("/logout")
        denied = self.client.get(f"/documents/{record.documents[0].id}/download")
        self.assertEqual(denied.status_code, 302)

    def test_csv_export_uses_current_database_records(self):
        db.session.add(self.add_record())
        db.session.commit()
        self.login()
        response = self.client.post("/reports")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"FDR-TEST-1", response.data)
        self.assertIn(b"100000.00", response.data)

    def test_pdf_report_is_a_real_pdf(self):
        db.session.add(self.add_record())
        db.session.commit()
        self.login()
        response = self.client.get("/reports/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))

    def test_reports_apply_filters_to_exports(self):
        db.session.add_all(
            [
                self.add_record("FDR-KEEP"),
                self.add_record("FDR-OTHER"),
            ]
        )
        db.session.commit()
        self.login()
        response = self.client.post("/reports", data={"q": "FDR-KEEP"})
        self.assertIn(b"FDR-KEEP", response.data)
        self.assertNotIn(b"FDR-OTHER", response.data)


if __name__ == "__main__":
    unittest.main()
