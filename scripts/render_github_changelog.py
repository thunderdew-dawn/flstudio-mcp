#!/usr/bin/env python3
"""Render a lightweight GitHub release/changelog snapshot."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def _github_get(path: str, token: str) -> object:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _list(path: str, token: str) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        batch = _github_get(f"{path}{sep}per_page=100&page={page}", token)
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        page += 1
    return rows


def _labels(row: dict) -> set[str]:
    return {str(label.get("name")) for label in row.get("labels", [])}


def _category(labels: set[str]) -> str:
    if "breaking-change" in labels:
        return "Breaking Changes"
    if "type:feature" in labels or "enhancement" in labels:
        return "Features"
    if "type:fix" in labels or "bug" in labels:
        return "Fixes"
    if "documentation" in labels or "area:docs" in labels:
        return "Documentation"
    if "area:safety" in labels or "compatibility" in labels:
        return "Safety and Compatibility"
    return "Other Changes"


def _display_url(url: str | None, repo: str, display_repo: str | None) -> str:
    if not url:
        return "None"
    if not display_repo or display_repo == repo:
        return url
    return url.replace(f"https://github.com/{repo}/", f"https://github.com/{display_repo}/")


def render(repo: str, token: str, display_repo: str | None = None) -> str:
    generated = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    releases = _list(f"/repos/{repo}/releases", token)
    pulls = [pr for pr in _list(f"/repos/{repo}/pulls?state=closed", token) if pr.get("merged_at")]
    pulls.sort(key=lambda row: str(row.get("merged_at")), reverse=True)

    lines = [
        "# GitHub Changelog Snapshot",
        "",
        "<!-- GENERATED FILE. Source of truth: GitHub Releases, tags, PRs, and labels. -->",
        "",
        f"Generated: {generated}",
        f"Repository: `{display_repo or repo}`",
        "",
        "## Releases",
        "",
    ]

    if not releases:
        lines.extend(["No GitHub releases found.", ""])
    for release in releases:
        prerelease = " prerelease" if release.get("prerelease") else ""
        lines.extend(
            [
                f"### {release.get('tag_name', release.get('name', 'untagged'))}{prerelease}",
                "",
                f"- Published: {release.get('published_at') or 'draft/unpublished'}",
                f"- URL: {_display_url(release.get('html_url'), repo, display_repo)}",
                "",
            ]
        )

    lines.extend(["## Recently Merged Pull Requests", ""])
    if not pulls:
        lines.extend(["No merged pull requests found.", ""])
    else:
        by_category: dict[str, list[dict]] = {}
        for pr in pulls[:100]:
            by_category.setdefault(_category(_labels(pr)), []).append(pr)
        for category in sorted(by_category):
            lines.extend([f"### {category}", ""])
            for pr in by_category[category]:
                url = _display_url(pr.get("html_url"), repo, display_repo)
                lines.append(f"- #{pr['number']} [{pr['title']}]({url})")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--display-repo", default=os.environ.get("SNAPSHOT_DISPLAY_REPOSITORY"))
    parser.add_argument("--output", default="-")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GH_TOKEN or GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    if not args.repo:
        print("--repo or GITHUB_REPOSITORY is required", file=sys.stderr)
        return 2

    text = render(args.repo, token, args.display_repo)
    if args.output == "-":
        print(text, end="")
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
