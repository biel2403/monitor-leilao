from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from auction_monitor.models import RawLot


LOT_FIELDS = [
    "title",
    "description",
    "category",
    "brand",
    "model",
    "year",
    "mileage",
    "city",
    "state",
    "initial_value",
    "current_bid",
    "bid_count",
    "opens_at",
    "closes_at",
    "url",
    "external_id",
    "images",
    "documentation",
    "damages",
    "accident",
    "financing",
    "restrictions",
    "auctioneer",
    "source_site",
    "status",
    "reference_value",
]


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self):
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS lots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    brand TEXT,
                    model TEXT,
                    year INTEGER,
                    mileage INTEGER,
                    city TEXT,
                    state TEXT,
                    initial_value REAL,
                    current_bid REAL,
                    bid_count INTEGER,
                    opens_at TEXT,
                    closes_at TEXT,
                    url TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    images TEXT NOT NULL DEFAULT '[]',
                    documentation TEXT,
                    damages TEXT,
                    accident TEXT,
                    financing TEXT,
                    restrictions TEXT,
                    auctioneer TEXT,
                    source_site TEXT NOT NULL,
                    status TEXT,
                    reference_value REAL,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_site, external_id)
                );

                CREATE TABLE IF NOT EXISTS lot_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lot_id INTEGER NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
                    field_name TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS bid_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lot_id INTEGER NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
                    current_bid REAL,
                    bid_count INTEGER,
                    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    criteria TEXT NOT NULL,
                    channels TEXT NOT NULL DEFAULT '["telegram"]',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lot_id INTEGER NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
                    filter_id INTEGER NOT NULL REFERENCES filters(id) ON DELETE CASCADE,
                    matched_criteria TEXT NOT NULL,
                    discount_percent REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(lot_id, filter_id)
                );

                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    error TEXT,
                    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(opportunity_id, channel)
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lot_details (
                    lot_id INTEGER PRIMARY KEY REFERENCES lots(id) ON DELETE CASCADE,
                    classification TEXT NOT NULL,
                    commission_percent REAL NOT NULL,
                    fixed_fees REAL NOT NULL,
                    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ai_analyses (
                    lot_id INTEGER PRIMARY KEY REFERENCES lots(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ai_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lot_id INTEGER NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS review_criteria (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    criteria_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS valuation_references (
                    lot_id INTEGER PRIMARY KEY REFERENCES lots(id) ON DELETE CASCADE,
                    fipe_value REAL NOT NULL CHECK (fipe_value > 0),
                    model_label TEXT NOT NULL,
                    reference_month TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS market_cache (
                    cache_key TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS market_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS market_references (
                    lot_id INTEGER PRIMARY KEY REFERENCES lots(id) ON DELETE CASCADE,
                    result_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            detail_columns = {row["name"] for row in conn.execute("PRAGMA table_info(lot_details)")}
            for name, definition in (
                ("condition_text", "TEXT"),
                ("image_urls", "TEXT NOT NULL DEFAULT '[]'"),
                ("notice_url", "TEXT"),
            ):
                if name not in detail_columns:
                    conn.execute(f"ALTER TABLE lot_details ADD COLUMN {name} {definition}")
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('source', 'freitas')"
            )

    def selected_source(self) -> str:
        with self.session() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = 'source'").fetchone()
        return str(row["value"]) if row else "freitas"

    def get_market_cache(self, key: str) -> dict | None:
        with self.session() as conn:
            row = conn.execute("SELECT result_json FROM market_cache WHERE cache_key = ? AND collected_at >= datetime('now', '-1 day')", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_market_cache(self, key: str, result: dict) -> None:
        with self.session() as conn:
            conn.execute("INSERT INTO market_cache (cache_key, result_json) VALUES (?, ?) ON CONFLICT(cache_key) DO UPDATE SET result_json=excluded.result_json, collected_at=CURRENT_TIMESTAMP", (key, json.dumps(result, ensure_ascii=False)))

    def reserve_market_request(self, limit: int) -> bool:
        with self.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute("SELECT COUNT(*) FROM market_requests WHERE date(requested_at)=date('now')").fetchone()[0]
            if count >= limit:
                return False
            conn.execute("INSERT INTO market_requests DEFAULT VALUES")
            return True

    def save_market_reference(self, lot_id: int, result: dict) -> None:
        with self.session() as conn:
            conn.execute("INSERT INTO market_references (lot_id, result_json) VALUES (?, ?) ON CONFLICT(lot_id) DO UPDATE SET result_json=excluded.result_json, updated_at=CURRENT_TIMESTAMP", (lot_id, json.dumps(result, ensure_ascii=False)))

    def list_market_references(self) -> dict[int, dict]:
        with self.session() as conn:
            rows = conn.execute("SELECT lot_id, result_json FROM market_references").fetchall()
        return {int(row[0]): json.loads(row[1]) for row in rows}

    def select_source(self, source: str) -> None:
        with self.session() as conn:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES ('source', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (source,),
            )

    def upsert_lot(self, raw: RawLot) -> tuple[int, bool, list[dict[str, Any]]]:
        data = raw.__dict__.copy()
        data["images"] = json.dumps(data.get("images") or [], ensure_ascii=False)
        with self.session() as conn:
            existing = conn.execute(
                "SELECT * FROM lots WHERE source_site = ? AND external_id = ?",
                (raw.source_site, raw.external_id),
            ).fetchone()
            if existing is None:
                columns = ", ".join(LOT_FIELDS)
                placeholders = ", ".join("?" for _ in LOT_FIELDS)
                values = [data[field] for field in LOT_FIELDS]
                cursor = conn.execute(f"INSERT INTO lots ({columns}) VALUES ({placeholders})", values)
                lot_id = int(cursor.lastrowid)
                conn.execute(
                    "INSERT INTO bid_history (lot_id, current_bid, bid_count) VALUES (?, ?, ?)",
                    (lot_id, raw.current_bid, raw.bid_count),
                )
                return lot_id, True, []

            changes: list[dict[str, Any]] = []
            for field in LOT_FIELDS:
                old_value = existing[field]
                new_value = data[field]
                if old_value != new_value:
                    changes.append({"field": field, "old": old_value, "new": new_value})
            if changes:
                assignments = ", ".join(f"{field} = ?" for field in LOT_FIELDS)
                values = [data[field] for field in LOT_FIELDS]
                values.append(existing["id"])
                conn.execute(
                    f"UPDATE lots SET {assignments}, last_seen_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values,
                )
                for change in changes:
                    conn.execute(
                        "INSERT INTO lot_changes (lot_id, field_name, old_value, new_value) VALUES (?, ?, ?, ?)",
                        (existing["id"], change["field"], serialize(change["old"]), serialize(change["new"])),
                    )
                if any(change["field"] in {"current_bid", "bid_count"} for change in changes):
                    conn.execute(
                        "INSERT INTO bid_history (lot_id, current_bid, bid_count) VALUES (?, ?, ?)",
                        (existing["id"], raw.current_bid, raw.bid_count),
                    )
            else:
                conn.execute("UPDATE lots SET last_seen_at = CURRENT_TIMESTAMP WHERE id = ?", (existing["id"],))
            return int(existing["id"]), False, changes

    def list_lots(self) -> list[dict[str, Any]]:
        return self._list("SELECT * FROM lots ORDER BY updated_at DESC")

    def get_lot(self, lot_id: int) -> dict[str, Any] | None:
        rows = self._list("SELECT * FROM lots WHERE id = ?", (lot_id,))
        return rows[0] if rows else None

    def save_lot_detail(
        self,
        lot_id: int,
        classification: str,
        commission_percent: float,
        fixed_fees: float,
        condition_text: str = "",
        image_urls: list[str] | None = None,
        notice_url: str | None = None,
    ) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO lot_details (lot_id, classification, commission_percent, fixed_fees, condition_text, image_urls, notice_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lot_id) DO UPDATE SET
                    classification = excluded.classification,
                    commission_percent = excluded.commission_percent,
                    fixed_fees = excluded.fixed_fees,
                    condition_text = excluded.condition_text,
                    image_urls = excluded.image_urls,
                    notice_url = excluded.notice_url,
                    checked_at = CURRENT_TIMESTAMP
                """,
                (lot_id, classification, commission_percent, fixed_fees, condition_text, json.dumps(image_urls or []), notice_url),
            )

    def list_lot_details(self) -> dict[int, dict[str, Any]]:
        return {int(row["lot_id"]): row for row in self._list("SELECT * FROM lot_details")}

    def get_lot_detail(self, lot_id: int) -> dict[str, Any] | None:
        rows = self._list("SELECT * FROM lot_details WHERE lot_id = ?", (lot_id,))
        return rows[0] if rows else None

    def get_ai_analysis(self, lot_id: int) -> dict[str, Any] | None:
        rows = self._list("SELECT * FROM ai_analyses WHERE lot_id = ?", (lot_id,))
        if not rows:
            return None
        rows[0]["result"] = json.loads(rows[0].pop("result_json"))
        return rows[0]

    def list_ai_analyses(self) -> dict[int, dict[str, Any]]:
        analyses = self._list("SELECT * FROM ai_analyses")
        for item in analyses:
            item["result"] = json.loads(item.pop("result_json"))
        return {int(item["lot_id"]): item for item in analyses}

    def record_ai_analysis(self, lot_id: int, model: str, fingerprint: str, result: dict[str, Any]) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO ai_analyses (lot_id, model, input_fingerprint, result_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(lot_id) DO UPDATE SET
                    model = excluded.model,
                    input_fingerprint = excluded.input_fingerprint,
                    result_json = excluded.result_json,
                    analyzed_at = CURRENT_TIMESTAMP
                """,
                (lot_id, model, fingerprint, json.dumps(result, ensure_ascii=False)),
            )

    def count_ai_requests_today(self) -> int:
        with self.session() as conn:
            row = conn.execute("SELECT COUNT(*) FROM ai_requests WHERE date(requested_at) = date('now')").fetchone()
        return int(row[0])

    def record_ai_request(self, lot_id: int, model: str) -> None:
        with self.session() as conn:
            conn.execute("INSERT INTO ai_requests (lot_id, model) VALUES (?, ?)", (lot_id, model))

    def get_review_criteria(self) -> str | None:
        with self.session() as conn:
            row = conn.execute("SELECT criteria_text FROM review_criteria WHERE id = 1").fetchone()
        return str(row[0]) if row else None

    def save_review_criteria(self, criteria_text: str) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO review_criteria (id, criteria_text) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET criteria_text = excluded.criteria_text, updated_at = CURRENT_TIMESTAMP
                """,
                (criteria_text,),
            )

    def get_valuation_reference(self, lot_id: int) -> dict[str, Any] | None:
        rows = self._list("SELECT * FROM valuation_references WHERE lot_id = ?", (lot_id,))
        return rows[0] if rows else None

    def list_valuation_references(self) -> dict[int, dict[str, Any]]:
        return {int(row["lot_id"]): row for row in self._list("SELECT * FROM valuation_references")}

    def save_valuation_reference(self, lot_id: int, value: float, model_label: str, reference_month: str, source_url: str) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO valuation_references (lot_id, fipe_value, model_label, reference_month, source_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(lot_id) DO UPDATE SET
                    fipe_value = excluded.fipe_value,
                    model_label = excluded.model_label,
                    reference_month = excluded.reference_month,
                    source_url = excluded.source_url,
                    checked_at = CURRENT_TIMESTAMP
                """,
                (lot_id, value, model_label, reference_month, source_url),
            )

    def create_filter(self, name: str, criteria: dict[str, Any], channels: list[str], active: bool = True) -> int:
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO filters (name, criteria, channels, active) VALUES (?, ?, ?, ?)",
                (name, json.dumps(criteria, ensure_ascii=False), json.dumps(channels), 1 if active else 0),
            )
            return int(cursor.lastrowid)

    def update_filter(self, filter_id: int, payload: dict[str, Any]) -> bool:
        current = self.get_filter(filter_id)
        if current is None:
            return False
        name = payload.get("name", current["name"])
        criteria = payload.get("criteria", current["criteria"])
        channels = payload.get("channels", current["channels"])
        active = payload.get("active", current["active"])
        with self.session() as conn:
            conn.execute(
                "UPDATE filters SET name = ?, criteria = ?, channels = ?, active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    name,
                    json.dumps(criteria, ensure_ascii=False),
                    json.dumps(channels),
                    1 if active else 0,
                    filter_id,
                ),
            )
        return True

    def delete_filter(self, filter_id: int) -> bool:
        with self.session() as conn:
            cursor = conn.execute("DELETE FROM filters WHERE id = ?", (filter_id,))
            return cursor.rowcount > 0

    def get_filter(self, filter_id: int) -> dict[str, Any] | None:
        rows = self._list("SELECT * FROM filters WHERE id = ?", (filter_id,))
        return rows[0] if rows else None

    def list_filters(self, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM filters"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY id DESC"
        return self._list(sql)

    def record_opportunity(
        self, lot_id: int, filter_id: int, matched_criteria: list[str], discount_percent: float | None
    ) -> tuple[int, bool]:
        with self.session() as conn:
            existing = conn.execute(
                "SELECT id FROM opportunities WHERE lot_id = ? AND filter_id = ?",
                (lot_id, filter_id),
            ).fetchone()
            if existing:
                return int(existing["id"]), False
            cursor = conn.execute(
                "INSERT INTO opportunities (lot_id, filter_id, matched_criteria, discount_percent) VALUES (?, ?, ?, ?)",
                (lot_id, filter_id, json.dumps(matched_criteria, ensure_ascii=False), discount_percent),
            )
            return int(cursor.lastrowid), True

    def list_opportunities(self) -> list[dict[str, Any]]:
        return self._list(
            """
            SELECT o.*, l.title, l.url, l.current_bid, l.city, l.state, l.closes_at,
                   l.source_site, f.name AS filter_name
            FROM opportunities o
            JOIN lots l ON l.id = o.lot_id
            JOIN filters f ON f.id = o.filter_id
            ORDER BY o.created_at DESC
            """
        )

    def notification_exists(self, opportunity_id: int, channel: str) -> bool:
        with self.session() as conn:
            row = conn.execute(
                "SELECT id FROM notifications WHERE opportunity_id = ? AND channel = ?",
                (opportunity_id, channel),
            ).fetchone()
            return row is not None

    def record_notification(self, opportunity_id: int, channel: str, status: str, message: str, error: str | None = None) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO notifications (opportunity_id, channel, status, message, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (opportunity_id, channel, status, message, error),
            )

    def list_notifications(self) -> list[dict[str, Any]]:
        return self._list(
            """
            SELECT n.*, l.source_site
            FROM notifications n
            JOIN opportunities o ON o.id = n.opportunity_id
            JOIN lots l ON l.id = o.lot_id
            ORDER BY n.sent_at DESC
            """
        )

    def _list(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("images", "image_urls", "criteria", "channels", "matched_criteria"):
                if key in item and isinstance(item[key], str):
                    try:
                        item[key] = json.loads(item[key])
                    except json.JSONDecodeError:
                        pass
            result.append(item)
        return result


def serialize(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
