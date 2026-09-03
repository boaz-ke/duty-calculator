"""SQLite persistence for CRSP releases, catalogues and rate plans."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from . import parser


SCHEMA = """
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    counts_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS catalogue_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    make TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    model_number TEXT NOT NULL DEFAULT '',
    transmission TEXT NOT NULL DEFAULT '',
    drive TEXT NOT NULL DEFAULT '',
    engine_raw TEXT NOT NULL DEFAULT '',
    engine_cc REAL,
    engine_hp REAL,
    engine_kwh REAL,
    engine_kw REAL,
    body_raw TEXT NOT NULL DEFAULT '',
    body_class TEXT NOT NULL DEFAULT '',
    gvw_raw TEXT NOT NULL DEFAULT '',
    gvw_kg REAL,
    seating INTEGER,
    fuel_raw TEXT NOT NULL DEFAULT '',
    fuel_class TEXT NOT NULL DEFAULT '',
    crsp REAL,
    source_row INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_catalogue_release
    ON catalogue_rows(release_id, category);
CREATE INDEX IF NOT EXISTS idx_catalogue_search
    ON catalogue_rows(release_id, make, model);

CREATE TABLE IF NOT EXISTS tax_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    block_key TEXT NOT NULL,
    title TEXT NOT NULL,
    duty_rate REAL,
    excise_rate REAL,
    excise_fixed REAL,
    vat_rate REAL,
    rdl_rate REAL,
    idf_rate REAL,
    initial_divisor REAL NOT NULL,
    backout_divisors_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(release_id, block_key)
);

CREATE TABLE IF NOT EXISTS depreciation_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    route TEXT NOT NULL,
    low REAL,
    high REAL,
    rate REAL NOT NULL,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def ensure_admin_user(db_path: str | Path, username: str, password: str) -> None:
    """Create the first admin account from app configuration if none exists."""
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        if row["c"]:
            return
        now = _now()
        conn.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (username, generate_password_hash(password), now, now),
        )


def verify_admin_password(db_path: str | Path, username: str, password: str) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_admin = 1", (username,)
        ).fetchone()
    if row is None:
        return False
    return check_password_hash(row["password_hash"], password)


def change_admin_password(db_path: str | Path, username: str, new_password: str) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE users SET password_hash = ?, updated_at = ?
            WHERE username = ? AND is_admin = 1
            """,
            (generate_password_hash(new_password), _now(), username),
        )
        return cur.rowcount > 0


def seed_default_release(db_path: str | Path, workbook_path: Path) -> None:
    if not workbook_path.exists():
        return
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM releases").fetchone()
        if row["c"]:
            return
    parsed = parser.parse_workbook(workbook_path, workbook_path.name)
    if parsed["errors"]:
        # Do not silently ship a broken default; surface the parse errors to the log.
        raise RuntimeError("Could not parse default workbook: " + "; ".join(parsed["errors"]))
    create_release_from_parsed(
        db_path,
        parsed,
        source_filename=workbook_path.name,
        status="live",
    )


def create_release_from_parsed(
    db_path: str | Path,
    parsed: dict[str, Any],
    source_filename: str,
    effective_date: str | None = None,
    status: str = "draft",
) -> int:
    release_id: int
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO releases
                (label, source_filename, effective_date, status,
                 counts_json, warnings_json, created_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed["release_label"],
                source_filename,
                effective_date or parsed["effective_date"],
                status,
                json.dumps(parsed["counts"]),
                json.dumps(parsed["warnings"]),
                _now(),
                _now() if status == "live" else None,
            ),
        )
        release_id = cur.lastrowid

        for block in parsed["blocks"]:
            conn.execute(
                """
                INSERT INTO tax_blocks
                    (release_id, block_key, title, duty_rate, excise_rate,
                     excise_fixed, vat_rate, rdl_rate, idf_rate,
                     initial_divisor, backout_divisors_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release_id,
                    block["key"],
                    block["title"],
                    block["duty_rate"],
                    block["excise_rate"],
                    block["excise_fixed"],
                    block["vat_rate"],
                    block["rdl_rate"],
                    block["idf_rate"],
                    block["initial_divisor"],
                    json.dumps(block["backout_divisors"]),
                ),
            )

        for route_key, rows in parsed["depreciation"].items():
            for item in rows:
                conn.execute(
                    """
                    INSERT INTO depreciation_rows
                        (release_id, route, low, high, rate, label)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_id,
                        route_key,
                        item.get("low", item.get("age")),
                        item.get("high", item.get("age")),
                        item["rate"],
                        item["label"],
                    ),
                )

        for category_rows in (
            parsed["vehicles"],
            parsed["motorcycles"],
            parsed["machinery"],
        ):
            conn.executemany(
                """
                INSERT INTO catalogue_rows
                    (release_id, category, make, model, model_number,
                     transmission, drive, engine_raw, engine_cc, engine_hp,
                     engine_kwh, engine_kw, body_raw, body_class, gvw_raw,
                     gvw_kg, seating, fuel_raw, fuel_class, crsp, source_row)
                VALUES
                    (:release_id, :category, :make, :model, :model_number,
                     :transmission, :drive, :engine_raw, :engine_cc, :engine_hp,
                     :engine_kwh, :engine_kw, :body_raw, :body_class, :gvw_raw,
                     :gvw_kg, :seating, :fuel_raw, :fuel_class, :crsp, :source_row)
                """,
                [{**row, "release_id": release_id} for row in category_rows],
            )
    return release_id


def set_release_status(db_path: str | Path, release_id: int, status: str) -> None:
    with connect(db_path) as conn:
        now = _now()
        if status == "live":
            conn.execute("UPDATE releases SET status = 'archived' WHERE status = 'live'")
            conn.execute(
                "UPDATE releases SET status = ?, published_at = ? WHERE id = ?",
                (status, now, release_id),
            )
        else:
            conn.execute(
                "UPDATE releases SET status = ?, published_at = NULL WHERE id = ?",
                (status, release_id),
            )


def delete_draft(db_path: str | Path, release_id: int) -> None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT status FROM releases WHERE id = ?", (release_id,)).fetchone()
        if row and row["status"] == "draft":
            conn.execute("DELETE FROM releases WHERE id = ?", (release_id,))


def live_release(db_path: str | Path) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM releases WHERE status = 'live' ORDER BY id DESC LIMIT 1"
        ).fetchone()


def get_release(db_path: str | Path, release_id: int) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute("SELECT * FROM releases WHERE id = ?", (release_id,)).fetchone()


def list_releases(db_path: str | Path) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT r.*,
                   COUNT(c.id) AS catalogue_count
            FROM releases r
            LEFT JOIN catalogue_rows c ON c.release_id = r.id
            GROUP BY r.id
            ORDER BY r.created_at DESC, r.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_tax_blocks(db_path: str | Path, release_id: int) -> dict[str, dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM tax_blocks WHERE release_id = ? ORDER BY id", (release_id,)
        ).fetchall()
    blocks: dict[str, dict[str, Any]] = {}
    for row in rows:
        data = dict(row)
        data["backout_divisors"] = json.loads(data.pop("backout_divisors_json"))
        blocks[data["block_key"]] = data
    return blocks


def get_depreciation(
    db_path: str | Path, release_id: int, route: str
) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM depreciation_rows
            WHERE release_id = ? AND route = ?
            ORDER BY COALESCE(low, 999), id
            """,
            (release_id, route),
        ).fetchall()
    return [dict(row) for row in rows]


def search_catalogue(
    db_path: str | Path,
    release_id: int,
    query: str,
    category: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    where = ["release_id = ?"]
    params: list[Any] = [release_id]
    if category:
        where.append("category = ?")
        params.append(category)
    if query:
        tokens = query.strip().split()
        token_conditions = []
        for token in tokens:
            pattern = f"%{token}%"
            token_conditions.append("(make LIKE ? OR model LIKE ? OR model_number LIKE ?)")
            params.extend([pattern, pattern, pattern])
        where.append("(" + " AND ".join(token_conditions) + ")")
    sql = f"""
        SELECT * FROM catalogue_rows
        WHERE id IN (
            SELECT MIN(id) FROM catalogue_rows
            WHERE {' AND '.join(where)}
            GROUP BY category, make, model, model_number, transmission, drive,
                     engine_raw, engine_cc, engine_hp, engine_kwh, engine_kw,
                     body_raw, body_class, fuel_raw, fuel_class, seating, crsp
        )
        ORDER BY CASE WHEN make LIKE ? THEN 0 ELSE 1 END, make, model, model_number
        LIMIT ?
    """
    if query:
        first_token = query.strip().split()[0]
        params.append(f"{first_token}%")
    params.append(limit)
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def release_summary(release: dict[str, Any] | sqlite3.Row | None) -> dict[str, Any] | None:
    if release is None:
        return None
    data = dict(release)
    try:
        counts = json.loads(data.get("counts_json") or "{}")
    except json.JSONDecodeError:
        counts = {}
    return {
        "id": data["id"],
        "label": data["label"],
        "source_filename": data["source_filename"],
        "effective_date": data["effective_date"],
        "status": data["status"],
        "created_at": data["created_at"],
        "published_at": data.get("published_at"),
        "counts": counts,
    }
