#!/usr/bin/env python3
"""Validate that a release tag matches the package version."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import tomllib

TAG_RE = re.compile(
    r"^v(?P<base>\d+\.\d+\.\d+)(?:(?P<stable>-stable)|-(?P<phase>alpha|beta|rc)\.(?P<n>\d+))?$"
)


def _pep440_from_tag(tag: str) -> str:
    match = TAG_RE.match(tag)
    if not match:
        raise ValueError(
            "release tag must be vX.Y.Z, vX.Y.Z-stable, "
            "vX.Y.Z-alpha.N, vX.Y.Z-beta.N, or vX.Y.Z-rc.N"
        )

    base = match.group("base")
    phase = match.group("phase")
    if not phase or match.group("stable"):
        return base

    marker = {"alpha": "a", "beta": "b", "rc": "rc"}[phase]
    return f"{base}{marker}{match.group('n')}"


def _project_version(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--pyproject", default="pyproject.toml")
    args = parser.parse_args()

    try:
        expected = _pep440_from_tag(args.tag)
    except ValueError as exc:
        print(f"Invalid release tag {args.tag!r}: {exc}", file=sys.stderr)
        return 2

    observed = _project_version(Path(args.pyproject))
    if observed != expected:
        print(
            f"Release tag {args.tag!r} maps to package version {expected!r}, "
            f"but pyproject.toml declares {observed!r}.",
            file=sys.stderr,
        )
        return 1

    print(f"Release tag {args.tag} matches package version {observed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
