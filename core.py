"""Storage and logic for the placement/internship tracker. Standard library only."""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import date, datetime, timedelta
from statistics import median
from typing import Optional

STATUSES = ("wishlist", "applied", "oa", "interview", "offer", "accepted", "rejected", "withdrawn")
ACTIVE = ("applied", "oa", "interview")                 # waiting on the company
RESPONDED = ("oa", "interview", "offer", "accepted", "rejected")
EVENT_KINDS = ("oa", "interview", "call", "deadline", "other")
FOLLOWUP_DAYS = 7
STALE_DAYS = 14

SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT NOT NULL, role TEXT NOT NULL, link TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'wishlist',
  applied_on TEXT, deadline TEXT, followup_on TEXT,
  notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (app_id INTEGER NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, app_id INTEGER NOT NULL,
  kind TEXT NOT NULL, at TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
);
"""


def parse_date(s: str) -> date:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"can't read date {s!r}; use YYYY-MM-DD") from None


def parse_dt(s: str) -> datetime:
    t = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            pass
    raise ValueError(f"can't read {s!r}; use 'YYYY-MM-DD HH:MM'")


def clean(s: str, what: str, hi: int, required: bool = False) -> str:
    v = re.sub(r"[\x00-\x1f\x7f]", " ", s or "").strip()
    if required and not v:
        raise ValueError(f"{what} is required")
    if len(v) > hi:
        raise ValueError(f"{what} is too long (max {hi})")
    return v


def clean_link(s: str) -> str:
    v = (s or "").strip()
    if v and not re.fullmatch(r"https?://[^\s<>\"']{3,500}", v, flags=re.I):
        raise ValueError("link must start with http:// or https://")   # blocks javascript: and data: links
    return v


def csv_safe(s: str) -> str:
    """Stop spreadsheet formula injection when exporting."""
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


class Tracker:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # ---- writes
    def add(self, company: str, role: str, link: str = "", deadline: Optional[str] = None,
            status: str = "wishlist", applied_on: Optional[str] = None, notes: str = "",
            today: Optional[date] = None) -> int:
        today = today or date.today()
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        dl = parse_date(deadline).isoformat() if deadline else None
        ap = parse_date(applied_on).isoformat() if applied_on else (today.isoformat() if status != "wishlist" else None)
        follow = (parse_date(ap) + timedelta(days=FOLLOWUP_DAYS)).isoformat() if status == "applied" and ap else None
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO apps(company,role,link,status,applied_on,deadline,followup_on,notes,created) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (clean(company, "company", 80, True), clean(role, "role", 80, True), clean_link(link), status,
                 ap, dl, follow, clean(notes, "notes", 500), today.isoformat()))
            aid = cur.lastrowid
            self.db.execute("INSERT INTO history VALUES(?,?,?)", (aid, status, today.isoformat()))
            return aid

    def set_status(self, aid: int, status: str, on: Optional[date] = None) -> bool:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        on = on or date.today()
        with self.lock:
            row = self.db.execute("SELECT applied_on FROM apps WHERE id=?", (aid,)).fetchone()
            if not row:
                return False
            applied_on = row["applied_on"] or (on.isoformat() if status != "wishlist" else None)
            follow = (on + timedelta(days=FOLLOWUP_DAYS)).isoformat() if status in ACTIVE else None
            self.db.execute("UPDATE apps SET status=?, applied_on=?, followup_on=? WHERE id=?",
                            (status, applied_on, follow, aid))
            self.db.execute("INSERT INTO history VALUES(?,?,?)", (aid, status, on.isoformat()))
            return True

    def add_event(self, aid: int, kind: str, at: str, note: str = "") -> int:
        if kind not in EVENT_KINDS:
            raise ValueError(f"kind must be one of {', '.join(EVENT_KINDS)}")
        when = parse_dt(at).strftime("%Y-%m-%d %H:%M")
        with self.lock:
            if not self.db.execute("SELECT 1 FROM apps WHERE id=?", (aid,)).fetchone():
                raise ValueError("no such application")
            return self.db.execute("INSERT INTO events(app_id,kind,at,note) VALUES(?,?,?,?)",
                                   (aid, kind, when, clean(note, "note", 300))).lastrowid

    def followed_up(self, aid: int, next_in_days: int = FOLLOWUP_DAYS, today: Optional[date] = None) -> bool:
        today = today or date.today()
        with self.lock:
            return self.db.execute("UPDATE apps SET followup_on=? WHERE id=?",
                                   ((today + timedelta(days=next_in_days)).isoformat(), aid)).rowcount == 1

    def note(self, aid: int, text: str) -> bool:
        with self.lock:
            return self.db.execute("UPDATE apps SET notes=? WHERE id=?",
                                   (clean(text, "notes", 500), aid)).rowcount == 1

    def delete(self, aid: int) -> bool:
        with self.lock:
            for t in ("history", "events"):
                self.db.execute(f"DELETE FROM {t} WHERE app_id=?", (aid,))
            return self.db.execute("DELETE FROM apps WHERE id=?", (aid,)).rowcount == 1

    # ---- reads
    def list(self, status: Optional[str] = None):
        with self.lock:
            if status:
                return self.db.execute("SELECT * FROM apps WHERE status=? ORDER BY id", (status,)).fetchall()
            return self.db.execute("SELECT * FROM apps ORDER BY id").fetchall()

    def events(self, start: datetime, end: datetime):
        with self.lock:
            return self.db.execute(
                "SELECT e.*, a.company, a.role FROM events e JOIN apps a ON a.id=e.app_id "
                "WHERE e.at>=? AND e.at<? ORDER BY e.at",
                (start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"))).fetchall()

    def digest(self, today: date, days: int = 7) -> dict:
        end = today + timedelta(days=days)
        apps = self.list()
        open_apps = [a for a in apps if a["status"] in ("wishlist",) + ACTIVE]
        return {
            "deadlines": sorted([a for a in apps if a["status"] == "wishlist" and a["deadline"]
                                 and today <= parse_date(a["deadline"]) <= end], key=lambda a: a["deadline"]),
            "missed_deadlines": [a for a in apps if a["status"] == "wishlist" and a["deadline"]
                                 and parse_date(a["deadline"]) < today],
            "followups": sorted([a for a in apps if a["status"] in ACTIVE and a["followup_on"]
                                 and parse_date(a["followup_on"]) <= today], key=lambda a: a["followup_on"]),
            "events": self.events(datetime.combine(today, datetime.min.time()),
                                  datetime.combine(end, datetime.min.time())),
            "stale": [a for a in open_apps if a["status"] == "applied" and a["applied_on"]
                      and not a["followup_on"] and (today - parse_date(a["applied_on"])).days >= STALE_DAYS],
        }

    def stats(self) -> dict:
        apps = self.list()
        by = {s: 0 for s in STATUSES}
        for a in apps:
            by[a["status"]] += 1
        applied = [a for a in apps if a["applied_on"]]
        waits, responded = [], 0
        for a in applied:
            with self.lock:
                hist = self.db.execute("SELECT status, at FROM history WHERE app_id=? ORDER BY at, rowid",
                                       (a["id"],)).fetchall()
            first = next((h for h in hist if h["status"] in RESPONDED), None)
            if first:
                responded += 1
                waits.append((parse_date(first["at"]) - parse_date(a["applied_on"])).days)
        got_offer = sum(1 for a in apps if a["status"] in ("offer", "accepted"))
        return {"total": len(apps), "by_status": by, "applied": len(applied), "responded": responded,
                "response_rate": responded / len(applied) if applied else None,
                "median_days_to_response": median(waits) if waits else None, "offers": got_offer}
