# GitHub Labels

## Purpose
This repository uses a central label taxonomy to ensure consistent label usage across issue templates, pull requests, release notes, and GitHub automation. By maintaining a single source of truth, we prevent label drift, typos, and obsolete labels from breaking workflows.

## Source of Truth
The canonical taxonomy is defined in `.github/labels.yml`. This file defines the allowed labels, their colors, and descriptions.

All GitHub configuration files (such as `.github/ISSUE_TEMPLATE/*.yml`, `.github/release.yml`, Dependabot configuration, and GitHub workflows) must only reference labels that are defined in this file.

## Updating Labels
If you need to introduce a new label or rename an existing one:
1. Update `.github/labels.yml`.
2. Update any configuration files that reference the label.
3. If renaming a label, ensure the existing GitHub labels are updated to match the new taxonomy.

## Validation
To ensure that all referenced labels are valid, run the validation script locally:

```bash
python scripts/validate_github_labels.py
```

This script will check issue templates, release configuration, and workflows to confirm they only use labels defined in the taxonomy.
