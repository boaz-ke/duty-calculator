"""Vehicle Duty Calculator Flask application."""

import os
from pathlib import Path

from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOOK = PROJECT_ROOT / "New-CRSP---July-2025.xlsx"
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"


def _db_path() -> Path:
    return Path(os.environ.get("VDC_DB", DATA_DIR / "vdc.sqlite3"))


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("VDC_SECRET", "dev-only-change-me"),
        DB_PATH=str(_db_path()),
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        ADMIN_USER=os.environ.get("VDC_ADMIN_USER", "admin"),
        ADMIN_PASSWORD=os.environ.get("VDC_ADMIN_PASSWORD", "admin123"),
    )
    if test_config:
        app.config.update(test_config)

    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)

    @app.template_filter("formatnumber")
    def format_number(value):
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)

    from . import db

    db.init_db(app.config["DB_PATH"])
    db.ensure_admin_user(
        app.config["DB_PATH"],
        app.config["ADMIN_USER"],
        app.config["ADMIN_PASSWORD"],
    )
    db.seed_default_release(app.config["DB_PATH"], DEFAULT_WORKBOOK)

    from . import views

    app.register_blueprint(views.bp)

    return app
