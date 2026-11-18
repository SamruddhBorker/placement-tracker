#!/usr/bin/env python3
"""placement-tracker: keep every application, deadline and interview in one place.

    python track.py add --company Infosys --role "Intern" --deadline 2026-11-30 --link https://...
    python track.py status 1 applied              # wishlist/applied/oa/interview/offer/accepted/rejected/withdrawn
    python track.py event 1 interview "2026-11-25 10:00" --note "HR round, Zoom"
    python track.py digest                        # what needs attention in the next 7 days
    python track.py followed-up 1                 # you nudged them; ask again in 7 days
    python track.py list [--status applied]
    python track.py stats                         # response rate and median wait
    python track.py export applications.csv
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

from core import EVENT_KINDS, STATUSES, Tracker, csv_safe, parse_date


def show(rows) -> None:
    if not rows:
        print("(none)")
    for a in rows:
        extra = f" deadline {a['deadline']}" if a["deadline"] else ""
        extra += f" follow up {a['followup_on']}" if a["followup_on"] else ""
        print(f"#{a['id']:<3} {a['status']:<9} {a['company']} · {a['role']}{extra}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # piped output on Windows defaults to cp1252
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="placements.db")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD (testing)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--company", required=True)
    a.add_argument("--role", required=True)
    a.add_argument("--link", default="")
    a.add_argument("--deadline")
    a.add_argument("--status", default="wishlist", choices=STATUSES)
    a.add_argument("--notes", default="")
    s = sub.add_parser("status")
    s.add_argument("id", type=int)
    s.add_argument("status", choices=STATUSES)
    s.add_argument("--on", help="date it happened, default today")
    e = sub.add_parser("event")
    e.add_argument("id", type=int)
    e.add_argument("kind", choices=EVENT_KINDS)
    e.add_argument("at", help="'YYYY-MM-DD HH:MM'")
    e.add_argument("--note", default="")
    f = sub.add_parser("followed-up")
    f.add_argument("id", type=int)
    f.add_argument("--next-in", type=int, default=7)
    n = sub.add_parser("note")
    n.add_argument("id", type=int)
    n.add_argument("text")
    l = sub.add_parser("list")
    l.add_argument("--status", choices=STATUSES)
    d = sub.add_parser("digest")
    d.add_argument("--days", type=int, default=7)
    sub.add_parser("stats")
    x = sub.add_parser("export")
    x.add_argument("file")
    sub.add_parser("delete").add_argument("id", type=int)
    args = ap.parse_args(argv)

    t = Tracker(args.db)
    try:
        today = parse_date(args.today) if args.today else date.today()
        if args.cmd == "add":
            print(f"added #{t.add(args.company, args.role, args.link, args.deadline, args.status, None, args.notes, today)}")
        elif args.cmd == "status":
            ok = t.set_status(args.id, args.status, parse_date(args.on) if args.on else today)
            print("updated" if ok else "no such application")
        elif args.cmd == "event":
            print(f"event #{t.add_event(args.id, args.kind, args.at, args.note)} saved")
        elif args.cmd == "followed-up":
            print("ok" if t.followed_up(args.id, args.next_in, today) else "no such application")
        elif args.cmd == "note":
            print("ok" if t.note(args.id, args.text) else "no such application")
        elif args.cmd == "list":
            show(t.list(args.status))
        elif args.cmd == "digest":
            dg = t.digest(today, args.days)
            sections = [("Deadlines coming up", dg["deadlines"]), ("MISSED deadlines (still on wishlist)", dg["missed_deadlines"]),
                        ("Follow-ups due", dg["followups"]), ("Stale (applied 14+ days, no follow-up set)", dg["stale"])]
            for title, rows in sections:
                if rows:
                    print(f"\n{title}:")
                    show(rows)
            if dg["events"]:
                print("\nComing up:")
                for ev in dg["events"]:
                    print(f"  {ev['at']}  {ev['kind']}: {ev['company']} · {ev['role']} {('- ' + ev['note']) if ev['note'] else ''}")
            if not any(rows for _, rows in sections) and not dg["events"]:
                print("Nothing needs attention. 🎉")
        elif args.cmd == "stats":
            st = t.stats()
            print(f"{st['total']} tracked | " + ", ".join(f"{k} {v}" for k, v in st["by_status"].items() if v))
            rate = f"{st['response_rate']:.0%}" if st["response_rate"] is not None else "n/a"
            wait = f"{st['median_days_to_response']:g} days" if st["median_days_to_response"] is not None else "n/a"
            print(f"applied {st['applied']} | heard back {st['responded']} ({rate}) | median wait {wait} | offers {st['offers']}")
        elif args.cmd == "export":
            with open(args.file, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["id", "company", "role", "status", "applied_on", "deadline", "followup_on", "link", "notes"])
                for r in t.list():
                    w.writerow([r["id"], csv_safe(r["company"]), csv_safe(r["role"]), r["status"], r["applied_on"] or "",
                                r["deadline"] or "", r["followup_on"] or "", csv_safe(r["link"]), csv_safe(r["notes"])])
            print(f"wrote {args.file}")
        elif args.cmd == "delete":
            print("deleted" if t.delete(args.id) else "no such application")
    except (ValueError, OSError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
