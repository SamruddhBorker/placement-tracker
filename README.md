# placement-tracker

[![tests](https://github.com/SamruddhBorker/placement-tracker/actions/workflows/tests.yml/badge.svg)](https://github.com/SamruddhBorker/placement-tracker/actions/workflows/tests.yml)

One place for every internship and placement application: deadlines, follow-ups,
interview dates, and how your search is actually going.

**The problem:** during placement season students juggle dozens of applications
across emails, portals and WhatsApp groups. Deadlines get missed and nobody
remembers whom to follow up with.

- Python 3.9+, **standard library only**, SQLite storage
- A daily `digest` tells you exactly what needs attention

## Quick start

```bash
python track.py add --company Infosys --role Intern --deadline 2026-11-30 --link https://example.com/job
python track.py status 1 applied            # wishlist, applied, oa, interview, offer, accepted, rejected, withdrawn
python track.py event 1 interview "2026-11-25 10:00" --note "HR round, Zoom"
python track.py digest                      # run this every morning
python track.py followed-up 1               # you nudged them; ask again in 7 days
python track.py list --status applied
python track.py stats
python track.py export applications.csv
```

## The digest

```
Deadlines coming up:
#2   wishlist  TCS · Digital Intern deadline 2026-11-22
MISSED deadlines (still on wishlist):
#5   wishlist  Wipro · Analyst deadline 2026-11-10
Follow-ups due:
#1   applied   Infosys · Intern follow up 2026-11-17
Coming up:
  2026-11-20 10:00  interview: Infosys · Intern - HR round, Zoom
```

Marking an application *applied* automatically schedules a follow-up in 7 days.
Applications with no response and no follow-up for 14 days show up as *stale*.

## Stats

Response rate (how many applications heard back) and the **median wait**, so you
know when silence probably means "no".

## Safety

- Links must start with `http://` or `https://` (no `javascript:` or `data:` links)
- CSV export neutralises spreadsheet formulas in company, role and notes
- Text is stripped of control characters; all database access uses parameters

## Layout

| File | Role |
|---|---|
| `track.py` | command-line interface |
| `core.py` | storage, digest, stats |

## Tests

```bash
python -m unittest -v
```

## License

MIT
