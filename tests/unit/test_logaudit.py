# WIMS — WSJT-X Instance Management System
# Copyright (C) 2026 Jeff Millar, WA1HCO
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Log audit: match, only-in, grid disagreement, duplicate, exit codes."""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wims.logaudit.check import compare, load_adif_source, render_text, to_json  # noqa: E402
from wims.logaudit.cli import main  # noqa: E402
from wims.logaudit.files import Candidate, probe_path, run_audit  # noqa: E402
from wims.logaudit.page import PAGE  # noqa: E402


def _adi(rows: list[str]) -> str:
    return "<eoh>\n" + "\n".join(rows) + "\n"


def _row(call, band, mode, hhmmss, grid=""):
    grid_f = f" <gridsquare:{len(grid)}>{grid}" if grid else ""
    return (
        f"<call:{len(call)}>{call}{grid_f} <mode:{len(mode)}>{mode} "
        f"<band:{len(band)}>{band} <qso_date:8>20260912 <time_on:6>{hhmmss} <eor>"
    )


def test_match_only_and_grid_clash():
    root = Path(tempfile.mkdtemp())
    a = root / "wsjtx.adi"
    b = root / "other.adi"
    a.write_text(_adi([
        _row("K1ABC", "6m", "FT8", "140200", "FN42"),
        _row("W2XYZ", "2m", "FT8", "151000", "FN31"),
        _row("N1ONLY", "6m", "FT8", "160000", "FN20"),
    ]), encoding="utf-8")
    b.write_text(_adi([
        _row("K1ABC", "6m", "FT8", "140230", "FN42"),
        _row("W2XYZ", "2m", "FT8", "151100", "FN32"),
        _row("W1AW", "6m", "USB", "164000", "FN31"),
    ]), encoding="utf-8")
    ga, ra = load_adif_source(a, "WSJT-X 6m")
    gb, rb = load_adif_source(b, "N1MM")
    report = compare([(ga, ra), (gb, rb)], lotw_names=set())
    text = render_text(report)
    assert report.exit_code() == 1
    assert len(report.matched) == 1
    assert len(report.disagreements) == 1
    assert any(row["call"] == "N1ONLY" for row in report.only)
    assert any(row["call"] == "W1AW" for row in report.only)
    assert "WIMS log check" in text
    assert "Disagreements" in text
    assert "[OK]" in text
    blob = to_json(report)
    assert blob["matched"] and blob["disagreements"]


def test_duplicate_inside_one_file_and_missing_path():
    root = Path(tempfile.mkdtemp())
    path = root / "one.adi"
    path.write_text(_adi([
        _row("K1ABC", "6m", "FT8", "140200", "FN42"),
        _row("K1ABC", "6m", "FT8", "140230", "FN42"),
    ]), encoding="utf-8")
    info, rows = load_adif_source(path, "WSJT-X")
    report = compare([(info, rows)], lotw_names=set())
    assert report.duplicates
    assert report.exit_code() == 1
    missing, none_rows = load_adif_source(root / "nope.adi", "ADIF nope.adi")
    bad = compare([(missing, none_rows)], lotw_names=set())
    assert bad.exit_code() == 2
    assert bad.unreadable is True


def test_cli_json_on_two_files():
    root = Path(tempfile.mkdtemp())
    a = root / "a.adi"
    b = root / "b.adi"
    # Different headers so the files are not byte-identical copies of one log.
    a.write_text("WSJT-X\n" + _adi([_row("K1ABC", "6m", "FT8", "140200", "FN42")]), encoding="utf-8")
    b.write_text("N1MM export\n" + _adi([_row("K1ABC", "6m", "FT8", "140200", "FN42")]), encoding="utf-8")
    out = root / "report.json"
    os.environ["WIMS_LOGCHECK_CACHE"] = str(root / "cache.json")
    try:
        code = main(["--adif", str(a), "--adif", str(b), "--json", str(out)])
    finally:
        os.environ.pop("WIMS_LOGCHECK_CACHE", None)
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["matched"]
    assert data["disagreements"] == []


def _adi_file(path: Path, rows: list[str], header: str = "") -> None:
    path.write_text(header + _adi(rows), encoding="utf-8")


def test_shared_path_inode_and_hash_are_one_log():
    root = Path(tempfile.mkdtemp())
    body = _adi([
        _row("K1ABC", "6m", "FT8", "140200", "FN42"),
        _row("W2XYZ", "2m", "FT8", "151000", "FN31"),
    ])
    shared = root / "wsjtx_log.adi"
    shared.write_text(body, encoding="utf-8")
    linked = root / "link.adi"
    try:
        os.link(shared, linked)
    except OSError:
        linked = None
    copy = root / "copy.adi"
    copy.write_text(body, encoding="utf-8")
    other = root / "n1mm.adi"
    # Same contacts except the last one is absent, plus a header so the bytes differ.
    other.write_text("N1MM\n" + _adi([
        _row("K1ABC", "6m", "FT8", "140200", "FN42"),
    ]), encoding="utf-8")
    third = root / "gt.adi"
    third.write_text("GridTracker\n" + body, encoding="utf-8")
    cands = [
        Candidate("WSJT-X 6m", str(shared)),
        Candidate("WSJT-X 2m", str(shared)),
        Candidate("N1MM", str(other)),
        Candidate("GridTracker log.adi", str(third)),
    ]
    if linked is not None:
        cands.append(Candidate("WSJT-X 222", str(linked)))
    cands.append(Candidate("WSJT-X backup", str(copy)))
    report = run_audit(cands, cache_path=root / "cache.json")
    text = render_text(report)
    assert report.shared_count == 1
    assert report.logs_read == 3
    assert not report.duplicates
    assert "1 shared file" in report.summary
    assert "3 logs read" in report.summary
    assert "1 contact missing from N1MM" in report.summary
    assert "W2XYZ" in text
    # The shared copies are not listed as a second WSJT-X log.
    names = [src.name for src in report.sources if src.status == "ok"]
    assert names.count("WSJT-X") == 1
    assert "duplicate" not in report.summary.lower()


def test_summary_lists_missing_contacts_not_matches():
    root = Path(tempfile.mkdtemp())
    a = root / "wsjtx.adi"
    b = root / "n1mm.adi"
    _adi_file(a, [
        _row("K1ABC", "6m", "FT8", "140200", "FN42"),
        _row("N1ONLY", "6m", "FT8", "160000", "FN20"),
    ], header="WSJT-X\n")
    _adi_file(b, [
        _row("K1ABC", "6m", "FT8", "140200", "FN42"),
    ], header="N1MM\n")
    report = run_audit(
        [Candidate("WSJT-X", str(a)), Candidate("N1MM", str(b))],
        cache_path=root / "cache.json",
    )
    assert report.summary.startswith("2 logs read, 1 contact missing from N1MM")
    text = render_text(report)
    assert text.splitlines()[2] == report.summary
    assert "N1ONLY" in text
    assert "Missing from N1MM" in text
    # The contact present in both logs is a count, not a dumped row.
    assert "K1ABC" not in text
    payload = to_json(report)
    assert payload["matched_count"] == 1
    assert payload["matched"]
    assert "K1ABC" not in payload["summary"]
    assert "Show details" in PAGE


def test_unchanged_file_is_not_read_again():
    root = Path(tempfile.mkdtemp())
    path = root / "wsjtx.adi"
    path.write_text(_adi([_row("K1ABC", "6m", "FT8", "140200", "FN42")]), encoding="utf-8")
    reads = {"n": 0}

    def counting(file_path):
        reads["n"] += 1
        return Path(file_path).read_bytes()

    cache = root / "cache.json"
    messages = []
    run_audit([Candidate("WSJT-X", str(path))], cache_path=cache,
              read_bytes=counting, progress=messages.append)
    assert reads["n"] == 1
    messages.clear()
    report = run_audit([Candidate("WSJT-X", str(path))], cache_path=cache,
                       read_bytes=counting, progress=messages.append)
    assert reads["n"] == 1
    assert report.sources[0].cached is True
    assert any("not read again" in msg for msg in messages)


def test_dead_path_times_out():
    def slow_stat(_path):
        time.sleep(2)
        return os.stat(".")

    started = time.perf_counter()
    probe = probe_path(r"\\server\share\wsjtx_log.adi", timeout=0.2, stat_fn=slow_stat)
    elapsed = time.perf_counter() - started
    assert probe.status == "timeout"
    assert elapsed < 1.0
    messages = []
    started = time.perf_counter()
    report = run_audit(
        [Candidate(f"WSJT-X {i}", r"\\dead\share\wsjtx_log.adi") for i in range(4)],
        cache_path=None,
        stat_timeout=0.2,
        stat_fn=slow_stat,
        progress=messages.append,
    )
    elapsed = time.perf_counter() - started
    # Four labels, one path: one timed stat, not four.
    assert elapsed < 0.7, elapsed
    assert report.exit_code() == 2
    assert len(report.sources) == 1
    assert report.sources[0].status == "timeout"
    assert len(report.sources[0].shared_by) == 4
    assert "did not answer" in report.summary.lower()
    assert any("did not answer" in msg.lower() or "Checking" in msg for msg in messages)


def test_large_synthetic_log_compares_quickly():
    """20k contacts x 2 logs. The old all-pairs compare took ~20s at 15k."""
    root = Path(tempfile.mkdtemp())
    n = 20000

    def write(path: Path, count: int, header: str) -> None:
        lines = [header, "<eoh>"]
        for i in range(count):
            call = f"K{i % 9000:04d}"
            sec = (i * 30) % 86400
            hhmmss = f"{sec // 3600:02d}{(sec % 3600) // 60:02d}{sec % 60:02d}"
            band = "6m" if i % 2 == 0 else "2m"
            lines.append(
                f"<call:{len(call)}>{call} <gridsquare:4>FN42 <mode:3>FT8 "
                f"<band:{len(band)}>{band} <qso_date:8>20260912 <time_on:6>{hhmmss} <eor>"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    wsjtx = root / "wsjtx.adi"
    n1mm = root / "n1mm.adi"
    write(wsjtx, n, "WSJT-X")
    write(n1mm, n - 50, "N1MM")
    started = time.perf_counter()
    report = run_audit(
        [Candidate("WSJT-X", str(wsjtx)), Candidate("N1MM", str(n1mm))],
        cache_path=None,
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 8.0, elapsed
    assert report.logs_read == 2
    missing = report.missing_from.get("N1MM") or []
    assert len(missing) == 50
    assert "50 contacts missing from N1MM" in report.summary
    text = render_text(report)
    assert "And 10 more" in text
    assert text.splitlines()[2].startswith("2 logs read")


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
