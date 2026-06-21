"""Tests for the N1MM log layer: contactinfo parse, DXLOG read, dupe/mult store.

Runs against the real capture in captures/ and the live N1MM .s3db when present
(those tests SKIP if the files are absent, so the suite stays portable).
"""

import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.integrations.n1mm.qso import LoggedQso  # noqa: E402
from wims.integrations.n1mm import logdb  # noqa: E402
from wims.state.logstore import LogStore  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
N1MM_DB_DIR = "c:/Users/wa1hc/Documents/N1MM Logger+/Databases"


class Skip(Exception):
    pass


def _qso(call, band, grid, mult=False, qid=None):
    return LoggedQso(id=qid or f"{call}-{band}-{grid}", call=call, band=band,
                     grid=grid, mode="FT8", points=1, is_mult=mult, contest="VHF",
                     timestamp="2026-06-17 00:00:00", operator="WA1HCO",
                     rover_location=None, source="test")


def test_from_contactinfo_capture():
    caps = sorted(glob.glob(str(REPO / "captures" / "n1mm-*.jsonl")))
    if not caps:
        raise Skip("no n1mm capture")
    rec = next(json.loads(l) for l in open(caps[-1], encoding="utf-8")
               if json.loads(l)["root"] == "contactinfo")
    q = LoggedQso.from_contactinfo(rec["text"])
    assert q.call == "W1XNZ"
    assert q.band == "20m"        # band "14" MHz normalized
    assert q.points == 1
    assert q.source == "live"
    assert len(q.id) == 32        # N1MM hex id


def test_read_dxlog_seed():
    db = logdb.find_contest_db(N1MM_DB_DIR)
    if not db:
        raise Skip("no N1MM contest DB")
    qsos = logdb.read_dxlog(db)
    assert qsos, "DXLOG empty"
    assert all(q.source == "seed" for q in qsos)
    assert all(len(q.id) == 32 for q in qsos)
    # Structural validity against whatever contest DB is loaded — do NOT pin a
    # specific call/band: this reads the operator's *live* N1MM DB, whose contents
    # change every contest. Every seeded row must have a call and a normalized band.
    assert all(q.call for q in qsos)
    assert all(q.band and q.band != "?" for q in qsos)


def test_seed_and_live_dedup_by_id():
    """A QSO present in both the DB seed and a live broadcast must not double."""
    store = LogStore(":memory:")
    same_id = "04acdb5e4f5f452b9eea122cb1d6f164"
    store.upsert(_qso("W1XNZ", "20m", None, qid=same_id))       # seed
    store.upsert(_qso("W1XNZ", "20m", None, qid=same_id))       # live, same id
    assert store.count() == 1


def test_dupe_and_rover_and_mult():
    store = LogStore(":memory:")
    store.upsert(_qso("K1ABC", "6m", "FN42", mult=True))
    # Same call/band/grid -> dupe.
    assert store.is_dupe("K1ABC", "6m", "FN42") is True
    # Rover: same call/band, NEW grid -> not a dupe, and a new mult.
    assert store.is_dupe("K1ABC", "6m", "FN31") is False
    assert store.is_new_mult("FN31", "6m") is True
    # Grid already worked on this band -> not a new mult.
    assert store.is_new_mult("FN42", "6m") is False
    # Same grid, different band -> still a new mult there.
    assert store.is_new_mult("FN42", "2m") is True


def test_reconcile_resync():
    """Operator resync: store follows a fresh DB read incl. a deletion."""
    store = LogStore(":memory:")
    for c in ("AA1A", "BB2B", "CC3C"):
        store.upsert(_qso(c, "6m", "FN42", qid=c))
    assert store.count() == 3
    # N1MM now has BB2B deleted and a new DD4D added.
    fresh = [_qso("AA1A", "6m", "FN42", qid="AA1A"),
             _qso("CC3C", "6m", "FN42", qid="CC3C"),
             _qso("DD4D", "6m", "FN31", qid="DD4D")]
    summary = store.reconcile(fresh)
    assert summary["deleted"] == 1 and store.count() == 3
    assert store.is_dupe("BB2B", "6m", "FN42") is False   # removed
    assert store.is_dupe("DD4D", "6m", "FN31") is True    # added


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = skipped = failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Skip as s:
            print(f"SKIP {t.__name__} ({s})")
            skipped += 1
        except Exception:
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {skipped} skipped, {failed} failed")
    sys.exit(1 if failed else 0)
