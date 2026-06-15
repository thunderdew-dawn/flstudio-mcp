#!/usr/bin/env python3
"""Render a GitHub issue roadmap snapshot."""

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


def _list_issues(repo: str, token: str) -> list[dict]:
    issues: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"state": "all", "per_page": 100, "page": page})
        batch = _github_get(f"/repos/{repo}/issues?{query}", token)
        if not isinstance(batch, list) or not batch:
            break
        issues.extend([row for row in batch if "pull_request" not in row])
        page += 1
    return issues


def _labels(issue: dict) -> set[str]:
    return {str(label.get("name")) for label in issue.get("labels", [])}


def _priority(labels: set[str]) -> str:
    for value in ("p0", "p1", "p2", "p3"):
        if f"priority:{value}" in labels:
            return value.upper()
    return "Unprioritized"


def _milestone(issue: dict) -> str:
    milestone = issue.get("milestone") or {}
    return str(milestone.get("title") or "No milestone")


def _display_url(url: str, repo: str, display_repo: str | None) -> str:
    if not display_repo or display_repo == repo:
        return url
    return url.replace(f"https://github.com/{repo}/", f"https://github.com/{display_repo}/")


def _render_issue(issue: dict, repo: str, display_repo: str | None) -> str:
    labels = _labels(issue)
    priority = _priority(labels)
    safety = ", ".join(
        sorted(labels & {"read-only", "write-safe-required", "api-dependent", "transient"})
    )
    suffix = f" - {safety}" if safety else ""
    url = _display_url(str(issue["html_url"]), repo, display_repo)
    return f"- [{priority}] #{issue['number']} [{issue['title']}]({url}){suffix}"


def render(repo: str, token: str, display_repo: str | None = None) -> str:
    all_issues = [
        issue for issue in _list_issues(repo, token) if "github-source-of-truth" in _labels(issue)
    ]
    all_issues.sort(key=lambda item: int(item["number"]))
    open_issues = [issue for issue in all_issues if issue.get("state") == "open"]
    closed_issues = [issue for issue in all_issues if issue.get("state") == "closed"]
    generated = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    lines = [
        "# GitHub Roadmap Snapshot",
        "",
        "<!-- GENERATED FILE. Source of truth: GitHub Issues/Milestones/Project #7. -->",
        "",
        f"Generated: {generated}",
        f"Repository: `{display_repo or repo}`",
        "",
        "## Open Roadmap",
        "",
    ]

    for milestone in sorted({_milestone(issue) for issue in open_issues}):
        group = [issue for issue in open_issues if _milestone(issue) == milestone]
        lines.extend([f"### {milestone}", ""])
        for issue in sorted(
            group, key=lambda item: (_priority(_labels(item)), int(item["number"]))
        ):
            lines.append(_render_issue(issue, repo, display_repo))
        lines.append("")

    if closed_issues:
        lines.extend(["## Closed / Not Planned", ""])
        for issue in closed_issues:
            reason = issue.get("state_reason") or "closed"
            url = _display_url(str(issue["html_url"]), repo, display_repo)
            lines.append(f"- #{issue['number']} [{issue['title']}]({url}) - {reason}")
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
