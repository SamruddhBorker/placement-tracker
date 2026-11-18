import csv
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import core
import track
from core import Tracker

TODAY = date(2026, 11, 18)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.t = Tracker()

    def test_add_wishlist_and_applied_set_followup(self):
        w = self.t.add("TCS", "Intern", status="wishlist", today=TODAY)
        a = self.t.add("Infosys", "Intern", status="applied", today=TODAY)
        rows = {r["id"]: r for r in self.t.list()}
        self.assertIsNone(rows[w]["applied_on"])
        self.assertEqual(rows[a]["applied_on"], "2026-11-18")
        self.assertEqual(rows[a]["followup_on"], "2026-11-25")

    def test_status_change_sets_applied_date_and_followup(self):
        i = self.t.add("TCS", "Intern", today=TODAY)
        self.assertTrue(self.t.set_status(i, "applied", date(2026, 11, 20)))
        r = self.t.list()[0]
        self.assertEqual((r["applied_on"], r["followup_on"]), ("2026-11-20", "2026-11-27"))
        self.t.set_status(i, "rejected", date(2026, 11, 28))
        self.assertIsNone(self.t.list()[0]["followup_on"])
        self.assertFalse(self.t.set_status(999, "applied"))

    def test_validation(self):
        for kw in ({"company": ""}, {"role": " "}, {"company": "x" * 81}, {"link": "javascript:alert(1)"},
                   {"link": "data:text/html,x"}, {"deadline": "30-11-2026"}, {"status": "dreaming"}):
            args = {"company": "A", "role": "B", **kw}
            with self.assertRaises(ValueError, msg=str(kw)):
                self.t.add(**args)
        self.t.add("A", "B", link="https://example.com/job")   # fine

    def test_events(self):
        i = self.t.add("A", "B", today=TODAY)
        self.t.add_event(i, "interview", "2026-11-25 10:00", "Zoom")
        with self.assertRaises(ValueError):
            self.t.add_event(999, "interview", "2026-11-25 10:00")
        with self.assertRaises(ValueError):
            self.t.add_event(i, "party", "2026-11-25 10:00")
        with self.assertRaises(ValueError):
            self.t.add_event(i, "interview", "soon")

    def test_digest(self):
        soon = self.t.add("Soon", "R", deadline="2026-11-22", today=TODAY)
        late = self.t.add("Late", "R", deadline="2026-11-10", today=TODAY)
        far = self.t.add("Far", "R", deadline="2026-12-30", today=TODAY)
        due = self.t.add("Due", "R", status="applied", applied_on="2026-11-05", today=date(2026, 11, 5))
        self.t.add_event(due, "interview", "2026-11-20 15:00")
        stale = self.t.add("Stale", "R", status="applied", applied_on="2026-10-20", today=date(2026, 10, 20))
        self.t.followed_up(stale, next_in_days=0, today=date(2026, 10, 20))   # then followup cleared below
        self.t.db.execute("UPDATE apps SET followup_on=NULL WHERE id=?", (stale,))
        dg = self.t.digest(TODAY, 7)
        self.assertEqual([a["company"] for a in dg["deadlines"]], ["Soon"])
        self.assertEqual([a["company"] for a in dg["missed_deadlines"]], ["Late"])
        self.assertEqual([a["company"] for a in dg["followups"]], ["Due"])
        self.assertEqual([e["company"] for e in dg["events"]], ["Due"])
        self.assertEqual([a["company"] for a in dg["stale"]], ["Stale"])

    def test_followed_up_pushes_date(self):
        i = self.t.add("A", "B", status="applied", today=TODAY)
        self.t.followed_up(i, 3, today=date(2026, 11, 25))
        self.assertEqual(self.t.list()[0]["followup_on"], "2026-11-28")

    def test_stats(self):
        a = self.t.add("A", "R", status="applied", applied_on="2026-11-01", today=date(2026, 11, 1))
        b = self.t.add("B", "R", status="applied", applied_on="2026-11-01", today=date(2026, 11, 1))
        self.t.add("C", "R", status="applied", applied_on="2026-11-01", today=date(2026, 11, 1))
        self.t.add("W", "R", today=TODAY)   # wishlist: not counted as applied
        self.t.set_status(a, "interview", date(2026, 11, 5))     # 4 days
        self.t.set_status(b, "rejected", date(2026, 11, 11))     # 10 days
        st = self.t.stats()
        self.assertEqual((st["applied"], st["responded"]), (3, 2))
        self.assertAlmostEqual(st["response_rate"], 2 / 3)
        self.assertEqual(st["median_days_to_response"], 7)

    def test_delete_removes_children(self):
        i = self.t.add("A", "B", today=TODAY)
        self.t.add_event(i, "call", "2026-11-25 10:00")
        self.assertTrue(self.t.delete(i))
        self.assertEqual(self.t.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_sql_text_is_inert(self):
        i = self.t.add("x'); DROP TABLE apps;--", "B", today=TODAY)
        self.assertEqual(self.t.list()[0]["company"], "x'); DROP TABLE apps;--")

    def test_csv_safe(self):
        self.assertEqual(core.csv_safe('=HYPERLINK("x")'), "'=HYPERLINK(\"x\")")
        self.assertEqual(core.csv_safe("Normal"), "Normal")


class CliTests(unittest.TestCase):
    def test_flow(self):
        with tempfile.TemporaryDirectory() as d:
            base = ["--db", str(Path(d) / "p.db"), "--today", "2026-11-18"]
            self.assertEqual(track.main(base + ["add", "--company", "=cmd|x", "--role", "Intern", "--deadline", "2026-11-22"]), 0)
            self.assertEqual(track.main(base + ["status", "1", "applied"]), 0)
            self.assertEqual(track.main(base + ["event", "1", "interview", "2026-11-20 10:00"]), 0)
            self.assertEqual(track.main(base + ["digest"]), 0)
            self.assertEqual(track.main(base + ["stats"]), 0)
            self.assertEqual(track.main(base + ["list"]), 0)
            out = Path(d) / "o.csv"
            self.assertEqual(track.main(base + ["export", str(out)]), 0)
            with open(out, newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[1][1], "'=cmd|x")
            self.assertEqual(track.main(base + ["add", "--company", "", "--role", "x"]), 1)
            self.assertEqual(track.main(base + ["event", "1", "interview", "never"]), 1)


if __name__ == "__main__":
    unittest.main()
