import os
import re
import sys
from pathlib import Path

def parse_simple_labels_yml(filepath):
    """
    Very simple regex-based YAML parser specifically for the known format of .github/labels.yml
    Expects format:
      - name: <label>
        color: <color>
        description: <desc>
    Returns a set of label names.
    """
    with open(filepath, "r") as f:
        content = f.read()

    # Find all occurrences of `- name: label_value`
    labels = set()
    for match in re.finditer(r'-\s+name:\s*(.+)', content):
        name = match.group(1).strip().strip("'\"")
        labels.add(name)
    return labels

def extract_labels_from_yaml(filepath):
    """
    Extracts anything that looks like a label list under a 'labels:' key
    in a typical yaml file, without a full YAML parser.
    """
    with open(filepath, "r") as f:
        lines = f.readlines()
    
    extracted = []
    in_labels_block = False
    indent_level = 0
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
            
        current_indent = len(line) - len(line.lstrip())
        
        if line.lstrip().startswith("labels:"):
            in_labels_block = True
            indent_level = current_indent
            continue
            
        if in_labels_block:
            if current_indent <= indent_level and not line.lstrip().startswith("-"):
                # Exited the block
                in_labels_block = False
            elif line.lstrip().startswith("-") and current_indent > indent_level:
                val = line.lstrip()[1:].strip().strip("'\"")
                if val:
                    # Ignore values that have a colon followed by space (likely another key instead of array item)
                    if not (":" in val and not val.startswith("type:") and not val.startswith("area:") and not val.startswith("priority:") and not val.startswith("status:") and not val.startswith("release:")):
                        extracted.append(val)
            else:
                in_labels_block = False
    return extracted

def main():
    root_dir = Path(__file__).parent.parent
    labels_file = root_dir / ".github" / "labels.yml"

    if not labels_file.exists():
        print("Error: .github/labels.yml not found.")
        sys.exit(1)

    defined_labels = parse_simple_labels_yml(labels_file)

    if not defined_labels:
        print("Error: .github/labels.yml must contain labels.")
        sys.exit(1)
        
    github_dir = root_dir / ".github"
    issues_found = False

    def check_labels(labels_list, filepath, context):
        nonlocal issues_found
        for lbl in labels_list:
            if not isinstance(lbl, str):
                continue
            if lbl.startswith("${{") or lbl.startswith("github."): # Skip dynamic
                continue
            lbl = lbl.strip().strip("'\"")
            if not lbl:
                continue
            
            if lbl not in defined_labels:
                print(f"Error: Unknown label '{lbl}' referenced in {filepath.relative_to(root_dir)} ({context})")
                issues_found = True

    # 1. ISSUE_TEMPLATE and dependabot.yml and release.yml
    yaml_files = list((github_dir / "ISSUE_TEMPLATE").glob("*.yml")) + [
        github_dir / "dependabot.yml",
        github_dir / "release.yml"
    ]

    for yml_file in yaml_files:
        if not yml_file.exists():
            continue
        extracted = extract_labels_from_yaml(yml_file)
        check_labels(extracted, yml_file, "yaml labels array")

    # 2. Workflows (basic string matching)
    workflow_files = list((github_dir / "workflows").glob("*.yml"))
    for wf in workflow_files:
        with open(wf, "r") as f:
            content = f.read()
            for match in re.finditer(r'has_label\s+([\w:\-\*]+)', content):
                lbl = match.group(1).strip().strip("'\"")
                if lbl not in defined_labels:
                    print(f"Error: Unknown label '{lbl}' referenced in {wf.relative_to(root_dir)} (has_label script)")
                    issues_found = True

    if issues_found:
        print("Validation failed: Unknown labels found.")
        sys.exit(1)

    print("Success: All referenced GitHub labels are defined in the taxonomy.")
    sys.exit(0)

if __name__ == "__main__":
    main()
