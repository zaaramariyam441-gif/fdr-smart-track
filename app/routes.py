import csv
import io
import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from app import db
from app.models import AuditLog, Document, FDR, Notification, User
from app.reminders import generate_reminders

main = Blueprint("main", __name__)


def today():
    return datetime.now(ZoneInfo(current_app.config["APP_TIMEZONE"])).date()


def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_safe_redirect(target):
    base = urlsplit(request.host_url)
    candidate = urlsplit(urljoin(request.host_url, target))
    return candidate.scheme in {"http", "https"} and base.netloc == candidate.netloc


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def audit(action, entity_type, entity_id, description):
    db.session.add(
        AuditLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            description=description[:300],
        )
    )


def parse_fdr_form(existing=None):
    data = {
        "fdr_number": request.form.get("fdr_number", "").strip().upper(),
        "institution": request.form.get("institution", "").strip(),
        "bank": request.form.get("bank", "").strip(),
        "branch": request.form.get("branch", "").strip(),
        "purpose": request.form.get("purpose", "").strip(),
        "renewal_preference": request.form.get("renewal_preference", "review"),
        "notes": request.form.get("notes", "").strip(),
        "principal": request.form.get("principal", "").strip(),
        "interest_rate": request.form.get("interest_rate", "").strip(),
        "start_date": request.form.get("start_date", "").strip(),
        "maturity_date": request.form.get("maturity_date", "").strip(),
    }
    errors = []
    for field in ("fdr_number", "institution", "bank", "principal", "interest_rate", "start_date", "maturity_date"):
        if not data[field]:
            errors.append(f"{field.replace('_', ' ').title()} is required.")
    try:
        principal = Decimal(data["principal"])
        if principal <= 0 or principal > Decimal("999999999999.99"):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        principal = None
        if data["principal"]:
            errors.append("Principal must be a positive amount.")
    try:
        rate = Decimal(data["interest_rate"])
        if rate < 0 or rate > 100:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        rate = None
        if data["interest_rate"]:
            errors.append("Interest rate must be between 0 and 100.")
    try:
        start = date.fromisoformat(data["start_date"])
        maturity = date.fromisoformat(data["maturity_date"])
        if start > maturity:
            errors.append("Start date cannot be after maturity date.")
    except ValueError:
        start, maturity = None, None
        if data["start_date"] and data["maturity_date"]:
            errors.append("Enter valid start and maturity dates.")
    duplicate = FDR.query.filter_by(fdr_number=data["fdr_number"]).first()
    if duplicate and (existing is None or duplicate.id != existing.id):
        errors.append("That FDR number is already registered.")
    if data["renewal_preference"] not in {"review", "renew", "payout"}:
        errors.append("Choose a valid renewal preference.")
    return data, errors, principal, rate, start, maturity


def filtered_records():
    query = FDR.query.filter_by(archived=False)
    search = request.values.get("q", "").strip()
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                FDR.fdr_number.ilike(term),
                FDR.bank.ilike(term),
                FDR.institution.ilike(term),
            )
        )
    bank = request.values.get("bank", "").strip()
    if bank:
        query = query.filter(FDR.bank == bank)
    status = request.values.get("status", "").strip()
    if status == "Matured":
        query = query.filter(FDR.maturity_date < today())
    elif status == "Upcoming":
        query = query.filter(FDR.maturity_date.between(today(), date.fromordinal(today().toordinal() + 30)))
    elif status == "Active":
        query = query.filter(FDR.maturity_date > date.fromordinal(today().toordinal() + 30))
    start = request.values.get("from", "").strip()
    end = request.values.get("to", "").strip()
    try:
        if start:
            query = query.filter(FDR.maturity_date >= date.fromisoformat(start))
        if end:
            query = query.filter(FDR.maturity_date <= date.fromisoformat(end))
    except ValueError:
        flash("Invalid date filter was ignored.", "warning")
    return query.order_by(FDR.maturity_date.asc()), search, bank, status


@main.app_context_processor
def shared_template_values():
    if current_user.is_authenticated:
        unread_count = Notification.query.filter_by(user_id=current_user.id, read_at=None).count()
    else:
        unread_count = 0
    return {
        "unread_count": unread_count,
        "today": today(),
        "institution_name": current_app.config["INSTITUTION_NAME"],
    }


@main.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("landing.html")


@main.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        user = User.query.filter(
            or_(User.email == identity, User.username == identity)
        ).first()
        if user and user.active and user.check_password(request.form.get("password", "")):
            login_user(user, remember=request.form.get("remember") == "on")
            audit("login", "user", user.id, "User signed in.")
            db.session.commit()
            next_url = request.args.get("next", "")
            return redirect(next_url if next_url and is_safe_redirect(next_url) else url_for("main.dashboard"))
        flash("Sign-in failed. Check your username/email and password.", "error")
    return render_template("login.html")


@main.route("/logout", methods=["POST"])
@login_required
def logout():
    audit("logout", "user", current_user.id, "User signed out.")
    db.session.commit()
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("main.home"))


@main.route("/dashboard")
@login_required
def dashboard():
    records = FDR.query.filter_by(archived=False).all()
    total_principal = sum((record.principal for record in records), Decimal("0"))
    upcoming = sorted((record for record in records if 0 <= record.days_remaining <= 30), key=lambda x: x.days_remaining)[:6]
    recent = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(5).all()
    bank_totals = {}
    for record in records:
        bank_totals[record.bank] = bank_totals.get(record.bank, Decimal("0")) + record.principal
    return render_template(
        "dashboard.html",
        records=records,
        total_principal=total_principal,
        upcoming=upcoming,
        recent=recent,
        bank_totals=bank_totals,
    )


@main.route("/fdr")
@login_required
def fdr_list():
    query, search, bank, status = filtered_records()
    page = max(request.args.get("page", 1, type=int), 1)
    pagination = query.paginate(page=page, per_page=12, error_out=False)
    banks = [row[0] for row in db.session.query(FDR.bank).distinct().order_by(FDR.bank).all()]
    return render_template(
        "fdr_list.html",
        records=pagination.items,
        pagination=pagination,
        banks=banks,
        search=search,
        selected_bank=bank,
        selected_status=status,
    )


@main.route("/fdr/new", methods=["GET", "POST"])
@login_required
def fdr_new():
    data = {}
    if request.method == "POST":
        data, errors, principal, rate, start, maturity = parse_fdr_form()
        if not errors:
            record = FDR(
                fdr_number=data["fdr_number"],
                institution=data["institution"],
                bank=data["bank"],
                branch=data["branch"] or None,
                purpose=data["purpose"] or None,
                renewal_preference=data["renewal_preference"],
                notes=data["notes"] or None,
                principal=principal,
                interest_rate=rate,
                start_date=start,
                maturity_date=maturity,
                created_by_id=current_user.id,
            )
            try:
                db.session.add(record)
                db.session.flush()
                audit("created", "fdr", record.id, f"Created FDR {record.fdr_number}.")
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Unable to create FDR record.")
                flash("The FDR could not be saved. Your entered details are still available; please retry.", "error")
                return render_template("fdr_form.html", record=None, data=data), 503
            flash("FDR record saved.", "success")
            return redirect(url_for("main.fdr_detail", fdr_id=record.id))
        for error in errors:
            flash(error, "error")
    return render_template("fdr_form.html", record=None, data=data)


@main.route("/fdr/<int:fdr_id>")
@login_required
def fdr_detail(fdr_id):
    record = db.get_or_404(FDR, fdr_id)
    return render_template("fdr_detail.html", record=record)


@main.route("/fdr/<int:fdr_id>/edit", methods=["GET", "POST"])
@login_required
def fdr_edit(fdr_id):
    record = db.get_or_404(FDR, fdr_id)
    if record.archived:
        abort(404)
    data = {}
    if request.method == "POST":
        data, errors, principal, rate, start, maturity = parse_fdr_form(record)
        if not errors:
            for key in ("fdr_number", "institution", "bank", "branch", "purpose", "renewal_preference", "notes"):
                setattr(record, key, data[key] or None if key in {"branch", "purpose", "notes"} else data[key])
            record.principal, record.interest_rate = principal, rate
            record.start_date, record.maturity_date = start, maturity
            try:
                audit("updated", "fdr", record.id, f"Updated FDR {record.fdr_number}.")
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception("Unable to update FDR record %s.", record.id)
                flash("The FDR could not be updated. Your entered details are still available; please retry.", "error")
                return render_template("fdr_form.html", record=record, data=data), 503
            flash("FDR record updated.", "success")
            return redirect(url_for("main.fdr_detail", fdr_id=record.id))
        for error in errors:
            flash(error, "error")
    return render_template("fdr_form.html", record=record, data=data)


@main.route("/fdr/<int:fdr_id>/archive", methods=["POST"])
@admin_required
def fdr_archive(fdr_id):
    record = db.get_or_404(FDR, fdr_id)
    record.archived = True
    audit("archived", "fdr", record.id, f"Archived FDR {record.fdr_number}.")
    db.session.commit()
    flash("FDR record archived.", "success")
    return redirect(url_for("main.fdr_list"))


@main.route("/fdr/<int:fdr_id>/upload", methods=["POST"])
@login_required
def upload_document(fdr_id):
    record = db.get_or_404(FDR, fdr_id)
    uploaded = request.files.get("document")
    if not uploaded or not uploaded.filename:
        flash("Select a receipt or supporting document to upload.", "error")
        return redirect(url_for("main.fdr_detail", fdr_id=record.id))
    safe_original = secure_filename(uploaded.filename)
    extension = Path(safe_original).suffix.lower().lstrip(".")
    if not safe_original or extension not in current_app.config["ALLOWED_EXTENSIONS"]:
        flash("Unsupported file type. Use PDF, PNG, JPG, or JPEG.", "error")
        return redirect(url_for("main.fdr_detail", fdr_id=record.id))
    signature = uploaded.stream.read(8)
    uploaded.stream.seek(0)
    signatures = {
        "pdf": signature.startswith(b"%PDF-"),
        "png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": signature.startswith(b"\xff\xd8\xff"),
        "jpeg": signature.startswith(b"\xff\xd8\xff"),
    }
    if not signatures.get(extension, False):
        flash("The file content does not match its allowed file type.", "error")
        return redirect(url_for("main.fdr_detail", fdr_id=record.id))
    stored_name = f"{secrets.token_hex(24)}.{extension}"
    destination = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name
    try:
        uploaded.save(destination)
        document = Document(
            fdr_id=record.id,
            stored_name=stored_name,
            original_name=safe_original[:255],
            document_type=request.form.get("document_type", "receipt"),
            uploaded_by_id=current_user.id,
        )
        if document.document_type not in {"receipt", "supporting"}:
            document.document_type = "supporting"
        db.session.add(document)
        db.session.flush()
        audit("uploaded", "document", document.id, f"Uploaded document for {record.fdr_number}.")
        db.session.commit()
    except (OSError, SQLAlchemyError):
        db.session.rollback()
        destination.unlink(missing_ok=True)
        current_app.logger.exception("Document upload failed for FDR %s.", record.id)
        flash("The document could not be saved. Check storage availability and try again.", "error")
        return redirect(url_for("main.fdr_detail", fdr_id=record.id))
    flash("Document uploaded and linked to this FDR.", "success")
    return redirect(url_for("main.fdr_detail", fdr_id=record.id))


@main.route("/documents")
@login_required
def documents():
    query = Document.query.join(FDR)
    search = request.args.get("q", "").strip()
    if search:
        term = f"%{search}%"
        query = query.filter(or_(Document.original_name.ilike(term), FDR.fdr_number.ilike(term), FDR.bank.ilike(term)))
    return render_template("documents.html", documents=query.order_by(Document.uploaded_at.desc()).all(), search=search)


@main.route("/documents/<int:document_id>/download")
@login_required
def download_document(document_id):
    document = db.get_or_404(Document, document_id)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        document.stored_name,
        as_attachment=True,
        download_name=document.original_name,
    )


@main.route("/maturities")
@login_required
def maturities():
    records = FDR.query.filter_by(archived=False).order_by(FDR.maturity_date.asc()).all()
    return render_template("maturities.html", records=records)


@main.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "generate":
            count = generate_reminders(today())
            flash(f"Generated {count} new maturity reminder(s).", "success")
        elif action == "read":
            notification = Notification.query.filter_by(id=request.form.get("notification_id", type=int), user_id=current_user.id).first_or_404()
            notification.read_at = utc_now_naive()
            db.session.commit()
            flash("Notification marked as read.", "success")
        return redirect(url_for("main.notifications"))
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template("notifications.html", notifications=items)


@main.route("/reports", methods=["GET", "POST"])
@login_required
def reports():
    query, _, _, _ = filtered_records()
    records = query.all()
    if request.method == "POST":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["FDR number", "Institution", "Bank", "Principal (INR)", "Rate (%)", "Start date", "Maturity date", "Status"])
        for record in records:
            values = [record.fdr_number, record.institution, record.bank, f"{record.principal:.2f}", f"{record.interest_rate:.2f}", record.start_date.isoformat(), record.maturity_date.isoformat(), record.status]
            writer.writerow(
                [
                    f"'{value}"
                    if isinstance(value, str)
                    and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                    else value
                    for value in values
                ]
            )
        response = make_response("\ufeff" + output.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = 'attachment; filename="fdr-report.csv"'
        audit("generated", "report", None, f"Generated CSV report with {len(records)} records.")
        db.session.commit()
        return response
    return render_template("reports.html", records=records)


@main.route("/reports/pdf")
@login_required
def report_pdf():
    records, _, _, _ = filtered_records()
    records = records.all()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), title="FDR SMARTTRACK Report")
    styles = getSampleStyleSheet()
    content = [
        Paragraph("FDR SMARTTRACK — Deposit Register", styles["Title"]),
        Paragraph(f"{current_app.config['INSTITUTION_NAME']} · Generated {datetime.now().strftime('%d %b %Y, %H:%M')}", styles["Normal"]),
        Spacer(1, 16),
    ]
    rows = [["FDR number", "Bank", "Principal (INR)", "Rate", "Maturity", "Status"]]
    rows.extend([[r.fdr_number, r.bank, f"{r.principal:,.2f}", f"{r.interest_rate}%", r.maturity_date.strftime("%d %b %Y"), r.status] for r in records])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14213d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8deea")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fb")]),
        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    content.extend([table, Spacer(1, 12), Paragraph(f"Records: {len(records)} · Principal total: ₹{sum((r.principal for r in records), Decimal('0')):,.2f}", styles["Normal"])])
    def draw_page_number(canvas, page_doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#687890"))
        canvas.drawRightString(
            page_doc.pagesize[0] - 28,
            18,
            f"Page {page_doc.page}",
        )
        canvas.restoreState()

    doc.build(content, onFirstPage=draw_page_number, onLaterPages=draw_page_number)
    audit("generated", "report", None, f"Generated PDF report with {len(records)} records.")
    db.session.commit()
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = 'attachment; filename="fdr-report.pdf"'
    return response


@main.route("/audit")
@admin_required
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(250).all()
    return render_template("audit.html", logs=logs)


@main.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "finance")
        if not username or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a username and valid email address.", "error")
        elif len(password) < 12:
            flash("Password must contain at least 12 characters.", "error")
        elif role not in {"admin", "finance"}:
            flash("Choose a valid role.", "error")
        elif User.query.filter(or_(User.username == username, User.email == email)).first():
            flash("That username or email is already registered.", "error")
        else:
            user = User(username=username, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            audit("created", "user", user.id, f"Created {role} account {email}.")
            db.session.commit()
            flash("User account created.", "success")
            return redirect(url_for("main.users"))
    return render_template("users.html", users=User.query.order_by(User.created_at.desc()).all())


@main.route("/settings")
@login_required
def settings():
    return render_template("settings.html")
