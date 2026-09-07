#!/usr/bin/env python3
# Write release manifest.json (design: docs/plan/wims_release_packages.md).
"""Stamp a WIMS release manifest.

Channel mapping from a release tag (without leading ``v``):

- ``X.Y.Z``           → GA
- ``X.Y.Z-rcN``       → RC   (N ≥ 1)
- ``X.Y.Z-tester``    → tester

The Python package version is the numeric base ``X.Y.Z`` only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_TAG_RE = re.compile(
    r"^(?P<base>\d+\.\d+\.\d+)(?:-(?P<suffix>tester|rc(?P<rc>[1-9]\d*)))?$"
)


def parse_release_tag(tag_or_version: str) -> tuple[str, str, str]:
    """Return (numeric_base, channel, display_version).

    ``display_version`` keeps the suffix when present (for artifact names).
    ``channel`` is GA | RC | tester.
    """
    text = tag_or_version.strip()
    if text.startswith("v"):
        text = text[1:]
    m = _TAG_RE.match(text)
    if not m:
        raise ValueError(
            f"unsupported release version {tag_or_version!r}; "
            "expected X.Y.Z, X.Y.Z-tester, or X.Y.Z-rcN"
        )
    base = m.group("base")
    suffix = m.group("suffix")
    if suffix is None:
        return base, "GA", base
    if suffix == "tester":
        return base, "tester", text
    # rcN
    return base, "RC", text


def read_package_version(repo_root: Path) -> str:
    init_path = repo_root / "src" / "wims" / "__init__.py"
    text = init_path.read_text(encoding="utf-8")
    m = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"', text)
    if not m:
        raise ValueError(f"__version__ not found in {init_path}")
    init_ver = m.group(1)

    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    m2 = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    if not m2:
        raise ValueError("version not found in pyproject.toml")
    py_ver = m2.group(1)
    if init_ver != py_ver:
        raise ValueError(f"version mismatch: __init__={init_ver!r} pyproject={py_ver!r}")
    return init_ver


def git_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_manifest(
    *,
    repo_root: Path,
    tag_or_version: str,
    python_bundled: bool = False,
    name: str = "wims",
) -> dict:
    base, channel, display = parse_release_tag(tag_or_version)
    pkg = read_package_version(repo_root)
    if pkg != base:
        raise ValueError(
            f"tag numeric base {base!r} != package version {pkg!r}; "
            "bump pyproject.toml / __init__.py to the numeric base only"
        )
    return {
        "name": name,
        "version": display,
        "version_base": base,
        "git_sha": git_sha(repo_root),
        "channel": channel,
        "python_bundled": bool(python_bundled),
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "version",
        help="Release version or tag (e.g. 0.1.0-tester or v0.1.0-rc1)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write JSON here (default: stdout)",
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root (default: parent of scripts/)",
    )
    p.add_argument(
        "--python-bundled",
        action="store_true",
        help="Set python_bundled true (Windows runtime overlay present)",
    )
    args = p.parse_args(argv)

    root = args.repo_root
    if root is None:
        root = Path(__file__).resolve().parents[2]
    root = root.resolve()

    try:
        manifest = build_manifest(
            repo_root=root,
            tag_or_version=args.version,
            python_bundled=args.python_bundled,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
