"""HTTP routes for the calculator and the admin upload flow."""

from __future__ import annotations

import hashlib
import io
import json
from functools import wraps
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from . import db, engine, parser
from .__init__ import UPLOAD_DIR


bp = Blueprint("main", __name__)


def _login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Please sign in as an administrator first.", "warning")
            return redirect(url_for("main.admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _live_release():
    return db.live_release(current_app.config["DB_PATH"])


def _row_payload(row: dict) -> dict:
    """Turn a DB catalogue row into a small API payload."""
    config_bits = []
    if row["category"] == "vehicle":
        if row["transmission"]:
            config_bits.append(row["transmission"])
        if row["drive"]:
            config_bits.append(row["drive"])
    elif row["category"] == "motorcycle" and row["transmission"]:
        config_bits.append(row["transmission"])
    return {
        "id": row["id"],
        "category": row["category"],
        "make": row["make"],
        "model": row["model"],
        "model_number": row["model_number"],
        "display": " ".join(
            part
            for part in (row["make"], row["model"], f"({row['model_number']})" if row["model_number"] else "")
            if part
        ),
        "spec": " · ".join(
            part
            for part in (
                row["engine_raw"] or "",
                row["fuel_raw"] or "",
                row["body_raw"] or "",
                f"{row['seating']} seats" if row["seating"] else "",
                " · ".join(config_bits),
            )
            if part
        ),
        "transmission": row["transmission"],
        "drive": row["drive"],
        "engine_cc": row["engine_cc"],
        "engine_kwh": row["engine_kwh"],
        "engine_hp": row["engine_hp"],
        "fuel_class": row["fuel_class"],
        "body_class": row["body_class"],
        "crsp": round(row["crsp"], 2) if row["crsp"] is not None else None,
    }


@bp.get("/")
def index():
    release = _live_release()
    return render_template(
        "index.html",
        release=db.release_summary(release),
        vehicle_types=engine.VEHICLE_TYPES,
        routes=engine.ROUTE_LABELS,
        current_year=engine.current_year(),
    )


@bp.get("/api/release")
def api_release():
    release = _live_release()
    if not release:
        return jsonify({"error": "No active CRSP release has been published."}), 503
    return jsonify({"release": db.release_summary(release)})


@bp.get("/api/search")
def api_search():
    release = _live_release()
    if not release:
        return jsonify({"error": "No active CRSP release."}), 503
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"results": []})
    category = request.args.get("category", "")
    rows = db.search_catalogue(
        current_app.config["DB_PATH"], release["id"], query, category, limit=20
    )
    return jsonify({"results": [_row_payload(row) for row in rows]})


def _required_field(payload: dict, name: str) -> str | None:
    value = payload.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"{name} is required."
    return None


@bp.post("/api/calculate")
def api_calculate():
    release = _live_release()
    if not release:
        return jsonify({"error": "No active CRSP release has been published."}), 503

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON payload."}), 400

    route = (payload.get("route") or "").strip()
    if route not in engine.ROUTE_LABELS:
        return jsonify({"error": "Choose a valid import route."}), 400
    vehicle_type = (payload.get("vehicle_type") or "").strip()
    if vehicle_type not in engine.VEHICLE_TYPES:
        return jsonify({"error": "Choose a valid vehicle type."}), 400
    fuel = (payload.get("fuel") or "").strip().lower()
    engine_cc = payload.get("engine_cc")
    if engine_cc in (None, ""):
        engine_cc = None
    else:
        try:
            engine_cc = float(engine_cc)
        except (TypeError, ValueError):
            return jsonify({"error": "Engine capacity must be a number."}), 400

    try:
        yom = int(payload.get("yom"))
    except (TypeError, ValueError):
        return jsonify({"error": "Year of manufacture is required."}), 400
    if not 1950 <= yom <= engine.current_year():
        return jsonify({"error": f"Year of manufacture must be between 1950 and {engine.current_year()}."}), 400

    try:
        crsp = float(payload.get("crsp"))
    except (TypeError, ValueError):
        return jsonify({"error": "A CRSP value in KES is required."}), 400
    extra_dep = payload.get("extra_depreciation") or 0
    try:
        extra_dep = float(extra_dep)
    except (TypeError, ValueError):
        return jsonify({"error": "Extra depreciation must be a percentage."}), 400
    extra_dep = extra_dep / 100.0

    try:
        block_key, block_reason = engine.classify_block(vehicle_type, fuel, engine_cc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db_path = current_app.config["DB_PATH"]
    blocks = db.get_tax_blocks(db_path, release["id"])
    block = blocks.get(block_key)
    if not block:
        return jsonify({"error": f"The {block_reason} rate block is missing from the active release."}), 503

    dep_rows = db.get_depreciation(db_path, release["id"], route)
    age = engine.years_old(yom)
    depreciation = engine.depreciation_rate(dep_rows, route, age)
    if depreciation is None:
        hint = (
            "Vehicles older than 8 years are normally not importable as direct imports."
            if route == "direct"
            else "No depreciation rate was found for this vehicle age."
        )
        return jsonify({"error": f"No depreciation rate for a {age}-year-old vehicle. {hint}"}), 400

    try:
        result = engine.calculate(block, route, crsp, depreciation, extra_dep)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "release": db.release_summary(release),
            "block_key": block_key,
            "block_title": block["title"],
            "block_reason": block_reason,
            "route_label": engine.ROUTE_LABELS[route],
            "age": age,
            "depreciation_rate": round(depreciation, 4),
            "extra_depreciation": round(extra_dep, 4),
            "result": result,
        }
    )


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if db.verify_admin_password(current_app.config["DB_PATH"], username, password):
            session["is_admin"] = True
            session["admin_username"] = username
            flash("Signed in.", "success")
            return redirect(request.args.get("next") or url_for("main.admin"))
        flash("Invalid credentials.", "error")
    return render_template("login.html")


@bp.post("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    session.pop("admin_username", None)
    flash("Signed out.", "success")
    return redirect(url_for("main.index"))


@bp.get("/admin")
@_login_required
def admin():
    releases = db.list_releases(current_app.config["DB_PATH"])
    return render_template(
        "admin.html",
        releases=releases,
        live_release=db.live_release(current_app.config["DB_PATH"]),
    )


@bp.route("/admin/password", methods=["GET", "POST"])
@_login_required
def change_password():
    username = session.get("admin_username") or current_app.config["ADMIN_USER"]
    if request.method == "POST":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirmation = request.form.get("confirm_password") or ""
        db_path = current_app.config["DB_PATH"]
        if not db.verify_admin_password(db_path, username, current_password):
            flash("Current password is incorrect.", "error")
        elif len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new_password != confirmation:
            flash("New password and confirmation do not match.", "error")
        else:
            db.change_admin_password(db_path, username, new_password)
            flash("Password updated successfully.", "success")
            return redirect(url_for("main.admin"))
    return render_template("password.html", username=username)


@bp.post("/admin/upload")
@_login_required
def admin_upload():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        flash("Choose a CRSP workbook to upload.", "error")
        return redirect(url_for("main.admin"))
    if not uploaded.filename.lower().endswith(".xlsx"):
        flash("Only .xlsx files are accepted.", "error")
        return redirect(url_for("main.admin"))

    raw = uploaded.read()
    try:
        parsed = parser.parse_workbook(io.BytesIO(raw), source_filename=uploaded.filename)
    except Exception as exc:  # noqa: BLE001 - surface any parse failure to the admin
        flash(f"Could not read the workbook: {exc}", "error")
        return redirect(url_for("main.admin"))

    if parsed["errors"]:
        flash("The workbook could not be validated: " + "; ".join(parsed["errors"]), "error")
        return redirect(url_for("main.admin"))

    effective_date = (request.form.get("effective_date") or "").strip() or parsed["effective_date"]
    db_path = current_app.config["DB_PATH"]
    release_id = db.create_release_from_parsed(
        db_path,
        parsed,
        source_filename=uploaded.filename,
        effective_date=effective_date,
        status="draft",
    )

    safe_name = secure_filename(uploaded.filename)
    target = UPLOAD_DIR / f"release-{release_id}-{safe_name}"
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with db.connect(db_path) as conn:
        conn.execute("UPDATE releases SET sha256 = ? WHERE id = ?", (digest, release_id))

    flash("Workbook parsed and saved as a draft release.", "success")
    return redirect(url_for("main.review_release", release_id=release_id))


@bp.get("/admin/releases/<int:release_id>")
@_login_required
def review_release(release_id: int):
    db_path = current_app.config["DB_PATH"]
    release = db.get_release(db_path, release_id)
    if not release:
        flash("Release not found.", "error")
        return redirect(url_for("main.admin"))
    release_data = dict(release)
    try:
        counts = json.loads(release_data.get("counts_json") or "{}")
    except json.JSONDecodeError:
        counts = {}
    try:
        warnings = json.loads(release_data.get("warnings_json") or "[]")
    except json.JSONDecodeError:
        warnings = []
    blocks = db.get_tax_blocks(db_path, release_id)
    return render_template(
        "review.html",
        release=release_data,
        counts=counts,
        warnings=warnings[:30],
        total_warnings=len(warnings),
        blocks=blocks,
    )


@bp.post("/admin/releases/<int:release_id>/publish")
@_login_required
def publish_release(release_id: int):
    db_path = current_app.config["DB_PATH"]
    release = db.get_release(db_path, release_id)
    if not release:
        flash("Release not found.", "error")
    elif release["status"] == "live":
        flash("Release is already live.", "warning")
    else:
        db.set_release_status(db_path, release_id, "live")
        flash(f"{release['label']} is now the live CRSP release.", "success")
    return redirect(url_for("main.admin"))


@bp.post("/admin/releases/<int:release_id>/discard")
@_login_required
def discard_release(release_id: int):
    db_path = current_app.config["DB_PATH"]
    release = db.get_release(db_path, release_id)
    if not release:
        flash("Release not found.", "error")
    elif release["status"] != "draft":
        flash("Only unpublished drafts can be discarded.", "warning")
    else:
        db.delete_draft(db_path, release_id)
        flash("Draft release discarded.", "success")
    return redirect(url_for("main.admin"))


@bp.post("/admin/releases/<int:release_id>/reactivate")
@_login_required
def reactivate_release(release_id: int):
    db_path = current_app.config["DB_PATH"]
    release = db.get_release(db_path, release_id)
    if not release:
        flash("Release not found.", "error")
    else:
        db.set_release_status(db_path, release_id, "live")
        flash(f"{release['label']} re-activated as the live CRSP release.", "success")
    return redirect(url_for("main.admin"))
