# FDR SMARTTRACK

> Turning caffeine, chaos, and questionable life choices into something that might actually be useful. Developed for SIH 2026 because apparently solving problems wasn't stressful enough, so we made it a national-level responsibility. Welcome to FDR Smart Track. 💀

FDR SMARTTRACK is a Flask application for institutional fixed deposit receipt (FDR) tracking. It includes authenticated finance workspaces, database-backed FDR records, private document uploads, maturity reminders, CSV/PDF reports, audit events, and synthetic demo records.

The project is a functional prototype, not a banking system. Dates, simple-interest estimates, and user-entered records are for operational reference and must be reconciled with official bank documents.

## Requirements

- Python 3.10 or later (tested locally with Python 3.13)
- Visual Studio Code (recommended on Windows)
- Git is optional

The Python dependencies are listed in `requirements.txt`. Flask, Flask-Login, Flask-SQLAlchemy, Flask-WTF, python-dotenv, ReportLab, and Waitress are included.

## Windows setup with VS Code

Open the project folder in VS Code, then open **Terminal → New Terminal** (PowerShell):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks activation, use this for the current terminal only, then activate the environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Generate and set a private `SECRET_KEY` in `.env`. For example:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the printed value into `.env`; do not commit `.env` or share its contents. Configure a stable secret before using the application. Without one, a random process key is generated, which invalidates sessions on restart.

## Initialize the database and administrator

The default SQLite database is created in the Flask `instance` folder, outside the static web root. Create its tables without deleting existing data:

```powershell
flask --app run.py init-db
flask --app run.py create-admin
```

`create-admin` securely prompts for username, email, and a password of at least 12 characters. Passwords are stored as Werkzeug password hashes. There are no default login credentials.

## Seed synthetic demonstration records

After creating an administrator, run:

```powershell
flask --app run.py seed-demo
```

This inserts 16 fictional records for **Northstar Institute of Technology (Demo)** with varied maturity dates and principal amounts. Records are individually marked as demo data. Seeding is idempotent: a second invocation does not create duplicates. The demo records do not include purported receipt scans or real financial information. To reset demo records, archive or remove those records through a deliberate database maintenance operation after taking a backup; the app does not expose a destructive reset command.

For a local judge/demo login instead of creating an administrator interactively, configure `FLASK_DEBUG=1`, `DEMO_MODE=1`, and a unique `DEMO_PASSWORD` of at least 16 characters in `.env`, then run:

```powershell
flask --app run.py init-db
flask --app run.py create-demo-user
flask --app run.py seed-demo
```

The command never prints the password and refuses to create the account unless Flask debug mode and the explicit demo flag are both enabled. Do not enable either setting or provision demo accounts in production; unset the demo password and disable debug/demo mode before deployment.

## Run locally

In the activated virtual environment:

```powershell
flask --app run.py run --debug
```

Then open `http://127.0.0.1:5000` in a browser. Sign in with the account created above. The dashboard reads current values from the database. The basic SIH flow is: add an FDR, upload a sample PDF/PNG/JPG receipt on its details page, inspect the maturity timeline, generate reminders in Notifications, filter the register, export CSV/PDF, toggle the theme, and inspect the administrator audit trail.

To run tests:

```powershell
python -m unittest discover -s tests -v
```

Tests use a temporary SQLite database and temporary upload directory. They cover authentication and password hashing, authorization, FDR creation and duplicate handling, reminder deduplication, private upload/download, and CSV export.

## Application features and current boundaries

- Two backend-enforced roles: administrator and finance officer. Administrators can archive records, manage users, and inspect audit logs; finance users can manage FDRs, upload documents, view alerts, and report on records.
- FDR dates and status are derived from saved dates. The maturity estimate is clearly labelled as an indicative simple-interest calculation and is not the bank's official maturity value.
- In-app reminders use `REMINDER_THRESHOLDS` (default `30,7,1`) and are generated on demand from the Notification Center or CLI. Repeated generation is deduplicated by record, maturity date, reminder window, and recipient.
- Optional scheduling is intentionally not started inside the Flask web process. In a single-instance host, schedule `flask --app run.py generate-reminders` through the host's scheduler. In multi-worker hosting, use one external scheduler/worker only; do not start a scheduler in every web worker.
- File access requires authentication. Accepted file types are PDF, PNG, JPG, and JPEG; content signatures are checked, names are randomized, and files are stored outside `static`. The request limit defaults to 10 MB.
- CSV output prefixes formula-leading text values to mitigate spreadsheet formula injection. PDF and CSV use filtered live database records.
- Login, record creation/update/archive, upload, user provisioning, and report generation create audit entries. Audit history has no editing route.
- SMTP delivery, calendar-grid view (maturity is currently a sorted list), amount-range filters, dedicated missing-document/incomplete-record alerts and reports, scheduled reminder worker, database schema migrations, password reset/MFA, configurable institution settings UI, automatic file replacement, and permanent deletion are not implemented. Records can be archived by administrators. Email is never reported as delivered. For schema evolution, introduce and test Flask-Migrate/Alembic migrations before changing a deployed database.

## Configuration

Copy `.env.example` to `.env` for development and review each setting:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Stable, high-entropy Flask session and CSRF secret. Required operationally for production. |
| `DATABASE_URL` | SQLAlchemy URL; defaults to a SQLite file in `instance`. |
| `UPLOAD_FOLDER` | Private upload directory; defaults to `instance/uploads`. |
| `MAX_CONTENT_LENGTH` | Maximum request size in bytes (default 10 MiB). |
| `ALLOWED_EXTENSIONS` | Accepted upload extensions. |
| `REMINDER_THRESHOLDS` | Comma-separated days-before-maturity windows. |
| `APP_TIMEZONE` | IANA timezone used for maturity-date calculations (default `Asia/Kolkata`). |
| `INSTITUTION_NAME` | Institution label on generated reports. |
| `COOKIE_SECURE` | Set to `1` when HTTPS terminates in front of the app. |

Set environment variables through the hosting provider's secret/configuration UI rather than committing a populated `.env`.

## Production and deployment

The Flask development server (`flask run`) is for local development only. On a single Windows server or local institutional host, install dependencies and run Waitress:

```powershell
waitress-serve --host=127.0.0.1 --port=8000 --call app:create_app
```

Place a properly configured HTTPS reverse proxy (for example IIS with a supported reverse-proxy setup) in front of Waitress. Set `COOKIE_SECURE=1`, configure a stable secret, restrict inbound access to the application service, and run under a dedicated low-privilege service account. For Linux/container WSGI platforms, use the platform's supported WSGI server; for example, install Gunicorn in that deployment environment and target `app:create_app()`.

### Persistence limitations

The default SQLite database and uploaded files are local filesystem assets. **Ephemeral hosting filesystems may erase both on restart, redeploy, reschedule, or instance replacement.** Do not deploy the defaults to ephemeral storage and assume records or documents will persist.

For a demonstration deployment, use a host with a persistent mounted volume, store the SQLite database and upload directory on that volume, and back both up. SQLite is intended here for a single application instance and modest prototype traffic; do not share one SQLite file across multiple web replicas or network filesystems. For production or multiple application instances, configure a managed PostgreSQL database and durable private object/file storage, then install the relevant SQLAlchemy database driver and implement/test the storage adapter before switching from local files. Back up the database and documents together, restrict access, define retention and restore procedures, and validate a restore before relying on the service.

Use the host's scheduler or a single external worker for `generate-reminders`. Configure HTTPS, production secrets, allowed origins/hostnames at the proxy, secure cookies, dependency updates, application logging, and monitoring. The prototype does not include automatic migrations, production email delivery, a scheduler, malware scanning, or cloud object-storage integration; these must be addressed and tested before handling real financial records.

## Project layout

```text
app/
  __init__.py          Flask factory, extensions, CLI commands
  models.py            SQLAlchemy models
  routes.py            Authenticated application workflows
  reminders.py         Idempotent in-app reminder generation
  seed.py              Synthetic demonstration records
  templates/           Server-rendered pages
  static/css/          Responsive dark/light design system
  static/js/           Theme and instant maturity estimate
tests/
  test_app.py
run.py
requirements.txt
```
