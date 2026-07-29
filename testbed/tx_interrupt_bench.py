"""TX-interrupt bench: how much does a brief mid-transmission mute hurt FT8 decode?

Supports the WIMS SSB/CW-priority design (wims_design.md §3.4.1): when a priority
phone/CW transmission needs the antenna, the FT8 TX audio is muted with a short
raised-cosine ramp (2-5 ms) and later restored. This bench measures the decode
cost of that gap at the far end:

  1. Generate N noisy FT8 realizations per SNR with ft8sim (WSJT-X tool).
  2. Puncture each wav — zero a window with raised-cosine edges (the fast-mute
     actuator model) — at early/middle/late positions in the transmission.
  3. Decode with jt9 and compare decode probability + reported SNR against the
     unpunctured control.

Usage:
  python testbed/tx_interrupt_bench.py            # full sweep (a few minutes)
  python testbed/tx_interrupt_bench.py --quick    # small matrix, sanity check

All wav/CSV output lands under scratch/tx_interrupt/ (gitignored). Exits with
status 2 and a SKIP message if ft8sim/jt9 are not available (same spirit as the
capture-based tests that skip when captures/ is absent).

Fidelity caveat: puncturing the composite wav removes the receiver noise inside
the gap as well as the signal. In a real halt the RX band noise continues; only
the transmitted signal disappears. The dominant effect (missing signal energy)
is modeled correctly; jt9's noise-baseline estimate sees a slightly quieter file.
"""

from __future__ import annotations

import argparse
import array
import csv
import math
import shutil
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# FT8 timing (WSJT-X constants): 79 symbols x 1920/12000 s, starting 0.5 s
# into the 15 s file (DT = 0). Costas sync blocks occupy symbols 0-6, 36-42,
# 72-78 -> 0.00-1.12 s, 5.76-6.88 s, 11.52-12.64 s into the transmission.
# ---------------------------------------------------------------------------
TX_START_S = 0.5
TX_LEN_S = 79 * 1920 / 12000.0          # 12.64 s

MESSAGE = "K1ABC W9XYZ EN37"
F0_HZ = 1500.0

DEFAULT_FT8SIM = "/usr/local/bin/ft8sim"
DEFAULT_JT9 = "/usr/local/bin/jt9"
FALLBACK_JT9 = ("/home/jeff/ham/wsjtx-3.1.0_improved_PLUS_260228/wsjtx-3.1.0/"
                "build/wsjtx-prefix/src/wsjtx-build/jt9")

# Full sweep matrix
SNRS_DB = [-5, -10, -13, -15, -17]
GAP_LENS_S = [0.16, 0.32, 0.5, 0.8, 1.2, 1.6, 2.4, 3.2]
# Gap CENTER, in seconds after the start of the transmission.
POSITIONS_S = {"early": 1.5, "middle": 6.0, "late": 10.5}

# Quick matrix (sanity / smoke)
QUICK_SNRS_DB = [-10, -15]
QUICK_GAP_LENS_S = [0.5, 1.6]
QUICK_POSITIONS_S = {"middle": 6.0}


# ---------------------------------------------------------------------------
# Pure helper: the fast-mute actuator model
# ---------------------------------------------------------------------------

def puncture(samples, sample_rate_hz, gap_start_s, gap_len_s, ramp_s=0.003):
    """Zero out [gap_start_s, gap_start_s + gap_len_s) of int16 PCM samples,
    with raised-cosine gain ramps of ramp_s on either side of the gap.

    Gain profile (t in seconds):
        t <  gap_start - ramp          : 1                (untouched)
        gap_start - ramp <= t < start  : 0.5*(1+cos(pi*u)) ramp 1 -> 0
        start <= t < end               : 0                (fully muted)
        end <= t < end + ramp          : 0.5*(1-cos(pi*u)) ramp 0 -> 1
        t >= end + ramp                : 1                (untouched)

    Pure function: returns a new list; the input sequence is not modified.
    Windows partly or wholly outside the file are clamped; a non-positive
    gap length returns a copy of the input unchanged. Boundaries are resolved
    to integer sample indices (round) so edges are deterministic and free of
    floating-point drift.
    """
    out = list(samples)
    n = len(out)
    if gap_len_s <= 0 or n == 0:
        return out
    fs = float(sample_rate_hz)
    i_gap_start = int(round(gap_start_s * fs))
    i_gap_end = int(round((gap_start_s + gap_len_s) * fs))
    if i_gap_start >= n or i_gap_end <= 0:
        return out                       # gap entirely outside the file
    n_ramp = max(0, int(round(ramp_s * fs)))
    i_down_start = i_gap_start - n_ramp  # gain 1 here, 0 at i_gap_start
    i_up_end = i_gap_end + n_ramp        # gain 0 at i_gap_end, 1 here
    for i in range(max(0, i_down_start), min(n, i_up_end)):
        if i < i_gap_start:              # ramp down 1 -> 0
            u = (i - i_down_start) / n_ramp
            gain = 0.5 * (1.0 + math.cos(math.pi * u))
        elif i < i_gap_end:              # fully muted
            gain = 0.0
        else:                            # ramp up 0 -> 1
            u = (i - i_gap_end) / n_ramp
            gain = 0.5 * (1.0 - math.cos(math.pi * u))
        out[i] = int(round(samples[i] * gain))
    return out


# ---------------------------------------------------------------------------
# WAV I/O (stdlib wave; 16-bit mono)
# ---------------------------------------------------------------------------

def read_wav_mono16(path):
    """Return (samples as list of int, sample_rate_hz) from a 16-bit mono wav."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit mono wav")
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    pcm = array.array("h")
    pcm.frombytes(raw)
    if sys.byteorder == "big":
        pcm.byteswap()
    return list(pcm), rate


def write_wav_mono16(path, samples, sample_rate_hz):
    pcm = array.array("h", (max(-32768, min(32767, int(s))) for s in samples))
    if sys.byteorder == "big":
        pcm.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------------------
# ft8sim / jt9 drivers
# ---------------------------------------------------------------------------

def generate_base_files(ft8sim, out_dir, snr_db, nfiles):
    """Run ft8sim in out_dir; returns the sorted list of generated wav paths.

    ft8sim usage: ft8sim "message" f0 DT fdop del nfiles snr
    Each of the nfiles gets an independent noise realization scaled so the
    per-file SNR (2500 Hz reference bandwidth) hits the target exactly.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [ft8sim, MESSAGE, str(F0_HZ), "0.0", "0.0", "1.0",
           str(nfiles), str(snr_db)]
    subprocess.run(cmd, cwd=out_dir, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wavs = sorted(out_dir.glob("*.wav"))
    if len(wavs) != nfiles:
        raise RuntimeError(f"ft8sim produced {len(wavs)} files, expected {nfiles}")
    return wavs


def run_jt9(jt9, cond_dir, wav_names, depth=3):
    """Decode wav_names (basenames, cwd=cond_dir) with jt9 FT8 mode.

    Returns one entry per file, in order: (decoded: bool, reported_snr_db or None).
    jt9 emits each file's decode lines followed by a <DecodeFinished> marker.
    """
    cmd = [jt9, "-8", "-d", str(depth)] + list(wav_names)
    proc = subprocess.run(cmd, cwd=cond_dir, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True)
    results = []
    decoded, snr = False, None
    for line in proc.stdout.splitlines():
        if "<DecodeFinished>" in line:
            results.append((decoded, snr))
            decoded, snr = False, None
            continue
        # decode line: HHMMSS SNR DT FREQ ~ MESSAGE...
        parts = line.split()
        if len(parts) >= 6 and MESSAGE in line:
            try:
                snr = int(parts[1])
                decoded = True
            except ValueError:
                pass
    while len(results) < len(wav_names):     # jt9 died mid-run: count as fails
        results.append((False, None))
    return results[:len(wav_names)]


# ---------------------------------------------------------------------------
# Sweep driver
# ---------------------------------------------------------------------------

def build_conditions(gap_lens_s, positions_s):
    """Control plus every (gap length x position) combination."""
    conds = [("control", 0.0, None)]
    for pos_name, pos_s in positions_s.items():
        for gap in gap_lens_s:
            conds.append((pos_name, gap, pos_s))
    return conds


def gap_window(gap_len_s, pos_center_in_tx_s):
    """Absolute (start, len) in file seconds for a gap centered at
    pos_center_in_tx_s seconds after the start of the transmission."""
    start = TX_START_S + pos_center_in_tx_s - gap_len_s / 2.0
    return max(0.0, start), gap_len_s


def run_sweep(args):
    run_dir = ROOT / "scratch" / "tx_interrupt" / time.strftime("run_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True)
    if args.snrs:
        snrs = [int(s) for s in args.snrs.split(",")]
    else:
        snrs = QUICK_SNRS_DB if args.quick else SNRS_DB
    gaps = QUICK_GAP_LENS_S if args.quick else GAP_LENS_S
    positions = QUICK_POSITIONS_S if args.quick else POSITIONS_S
    nfiles = args.nfiles if args.nfiles else (3 if args.quick else 8)
    conditions = build_conditions(gaps, positions)

    print(f"tx_interrupt bench: {len(snrs)} SNRs x {len(conditions)} conditions "
          f"x {nfiles} files = {len(snrs)*len(conditions)*nfiles} decodes")
    print(f"output: {run_dir}\n")

    # 1) Generate base realizations and punctured variants.
    jobs = []          # (snr_db, cond_name, gap_len, pos_s, cond_dir, wav_names)
    for snr in snrs:
        base_dir = run_dir / f"snr{snr:+d}" / "base"
        base_wavs = generate_base_files(args.ft8sim, base_dir, snr, nfiles)
        names = [w.name for w in base_wavs]
        cached = [read_wav_mono16(w) for w in base_wavs]
        for cond_name, gap_len, pos_s in conditions:
            if cond_name == "control":
                jobs.append((snr, cond_name, 0.0, None, base_dir, names))
                continue
            cond_dir = run_dir / f"snr{snr:+d}" / f"gap{gap_len:.2f}_{cond_name}"
            cond_dir.mkdir(parents=True, exist_ok=True)
            g_start, g_len = gap_window(gap_len, pos_s)
            for (samples, rate), name in zip(cached, names):
                write_wav_mono16(cond_dir / name,
                                 puncture(samples, rate, g_start, g_len,
                                          ramp_s=args.ramp_ms / 1000.0), rate)
            jobs.append((snr, cond_name, gap_len, pos_s, cond_dir, names))

    # 2) Decode every condition (parallel jt9 processes, one cwd each).
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_jt9, args.jt9, j[4], j[5], args.depth)
                   for j in jobs]
        outcomes = [f.result() for f in futures]
    print(f"decoded {sum(len(o) for o in outcomes)} files "
          f"in {time.time()-t0:.1f} s ({args.workers} workers)\n")

    # 3) Aggregate.
    rows = []          # per-condition dicts
    control_snr = {}   # snr_set -> mean reported snr of decoded controls
    for (snr, cond, gap_len, pos_s, _d, names), res in zip(jobs, outcomes):
        n_dec = sum(1 for ok, _ in res if ok)
        snrs_rep = [s for ok, s in res if ok and s is not None]
        mean_rep = sum(snrs_rep) / len(snrs_rep) if snrs_rep else None
        if cond == "control":
            control_snr[snr] = mean_rep
        rows.append({"snr_set_db": snr, "position": cond,
                     "gap_len_s": gap_len,
                     "gap_center_in_tx_s": pos_s if pos_s is not None else "",
                     "n_files": len(names), "n_decoded": n_dec,
                     "decode_prob": round(n_dec / len(names), 3),
                     "mean_reported_snr_db":
                         round(mean_rep, 1) if mean_rep is not None else ""})
    for r in rows:
        ctl = control_snr.get(r["snr_set_db"])
        rep = r["mean_reported_snr_db"]
        r["snr_delta_vs_control_db"] = (
            round(rep - ctl, 1) if rep != "" and ctl is not None else "")

    # 4) CSV + table.
    csv_path = run_dir.parent / f"results_{run_dir.name}.csv"
    with open(csv_path, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(rows)
    print_table(rows, snrs, gaps, positions)
    print(f"\nCSV: {csv_path}")
    return 0


def print_table(rows, snrs, gaps, positions):
    by_key = {(r["snr_set_db"], r["position"], r["gap_len_s"]): r for r in rows}
    pos_names = list(positions.keys())
    for snr in snrs:
        ctl = by_key[(snr, "control", 0.0)]
        print(f"SNR {snr:+d} dB   control: P={ctl['decode_prob']:.2f} "
              f"mean rpt {ctl['mean_reported_snr_db'] or 'n/a'} dB "
              f"(n={ctl['n_files']})")
        hdr = "  gap_s " + "".join(f"{p:>22}" for p in pos_names)
        print(hdr)
        for gap in gaps:
            cells = []
            for p in pos_names:
                r = by_key.get((snr, p, gap))
                if r is None:
                    cells.append(f"{'-':>22}")
                    continue
                d = r["snr_delta_vs_control_db"]
                d_txt = f"{d:+.1f}dB" if d != "" else "  n/a "
                cells.append(f"{r['decode_prob']:>10.2f} {d_txt:>10}")
            print(f"  {gap:5.2f} " + "".join(cells))
        print()


# ---------------------------------------------------------------------------

def resolve_binaries(args):
    """Fill in ft8sim/jt9 paths; return an error string if unusable."""
    if not (Path(args.ft8sim).is_file() or shutil.which(args.ft8sim)):
        return f"ft8sim not found at {args.ft8sim}"
    if not (Path(args.jt9).is_file() or shutil.which(args.jt9)):
        if Path(FALLBACK_JT9).is_file():
            args.jt9 = FALLBACK_JT9
        else:
            return f"jt9 not found at {args.jt9} (or fallback {FALLBACK_JT9})"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true",
                    help="small matrix (2 SNRs x 2 gaps x 1 position x 3 files)")
    ap.add_argument("--snrs", default="",
                    help="comma-separated SNR list override, e.g. -18,-19,-20")
    ap.add_argument("--nfiles", type=int, default=0,
                    help="realizations per point (default 8 full / 3 quick)")
    ap.add_argument("--ramp-ms", type=float, default=3.0,
                    help="raised-cosine mute ramp, ms (default 3, design 2-5)")
    ap.add_argument("--depth", type=int, default=3, help="jt9 -d depth (default 3)")
    ap.add_argument("--workers", type=int, default=8,
                    help="parallel jt9 processes (default 8)")
    ap.add_argument("--ft8sim", default=DEFAULT_FT8SIM)
    ap.add_argument("--jt9", default=DEFAULT_JT9)
    args = ap.parse_args(argv)

    err = resolve_binaries(args)
    if err:
        print(f"SKIP tx_interrupt bench: {err}\n"
              "Install WSJT-X command-line tools (ft8sim, jt9) or pass "
              "--ft8sim/--jt9. Exit status 2 = skipped, not failed.")
        return 2
    return run_sweep(args)


if __name__ == "__main__":
    sys.exit(main())
