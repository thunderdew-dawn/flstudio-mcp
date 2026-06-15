#!/usr/bin/env python3
"""Verify semantic invariants for the canonical GitHub Project."""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from typing import Any

OWNER = "thunderdew-dawn"
PROJECT = "7"
REQUIRED_RELEASE_ITEMS = {59, 60, 61, 62, 63, 64, 65, 66}
REQUIRED_PROJECT_FIELDS = ("status", "roadmap Lane", "priority", "area", "type", "safety")


def _current_repo() -> str:
    if repo := os.environ.get("GITHUB_REPOSITORY"):
        return repo
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _gh_json(*args: str) -> Any:
    result = subprocess.run(
        ["gh", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(result.stdout)


def _project_items() -> list[dict[str, Any]]:
    data = _gh_json(
        "project",
        "item-list",
        PROJECT,
        "--owner",
        OWNER,
        "--limit",
        "200",
        "--format",
        "json",
    )
    return list(data.get("items", []))


def _source_issues() -> list[dict[str, Any]]:
    data = _gh_json(
        "issue",
        "list",
        "--repo",
        _current_repo(),
        "--state",
        "all",
        "--label",
        "github-source-of-truth",
        "--limit",
        "200",
        "--json",
        "number,title,state,stateReason,milestone,labels",
    )
    return list(data)


def _label_names(issue: dict[str, Any]) -> set[str]:
    return {str(label.get("name")) for label in issue.get("labels", [])}


def _item_number(item: dict[str, Any]) -> int | None:
    number = item.get("content", {}).get("number")
    return int(number) if number is not None else None


def _field_counts(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(Counter(str(item.get(field) or "<empty>") for item in items))


def main() -> int:
    items = _project_items()
    by_number = {number: item for item in items if (number := _item_number(item)) is not None}
    source_issues = _source_issues()
    source_numbers = {int(issue["number"]) for issue in source_issues}
    errors: list[str] = []

    missing_from_project = sorted(source_numbers - set(by_number))
    if missing_from_project:
        errors.append(
            f"github-source-of-truth issues missing from Project #{PROJECT}: {missing_from_project}"
        )

    missing_release_items = sorted(REQUIRED_RELEASE_ITEMS - set(by_number))
    if missing_release_items:
        errors.append(
            f"required 3.0 release-train issues missing from Project #{PROJECT}: {missing_release_items}"
        )

    for issue in source_issues:
        number = int(issue["number"])
        item = by_number.get(number)
        labels = _label_names(issue)
        if item is None:
            continue

        missing_fields = [field for field in REQUIRED_PROJECT_FIELDS if not item.get(field)]
        if missing_fields:
            errors.append(f"issue #{number} has empty Project fields: {missing_fields}")

        if issue.get("state") == "CLOSED":
            if item.get("status") != "Done" or item.get("roadmap Lane") != "Done":
                errors.append(
                    f"closed issue #{number} is not marked Done/Done in Project #{PROJECT}"
                )

        if issue.get("state") == "OPEN" and "release-blocker" in labels:
            milestone = issue.get("milestone") or {}
            if not milestone.get("title"):
                errors.append(f"open release blocker #{number} has no milestone")
            if item.get("priority") != "P0":
                errors.append(
                    f"open release blocker #{number} is not marked P0 in Project #{PROJECT}"
                )

    summary = {
        "project": PROJECT,
        "project_items": len(by_number),
        "github_source_of_truth_issues": len(source_issues),
        "release_train_items": sorted(REQUIRED_RELEASE_ITEMS),
        "lanes": _field_counts(items, "roadmap Lane"),
        "statuses": _field_counts(items, "status"),
        "priorities": _field_counts(items, "priority"),
        "errors": errors,
    }
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
