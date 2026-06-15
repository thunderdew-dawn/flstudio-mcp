import json
import subprocess
import sys
from pathlib import Path


def parse_labels(filepath):
    """
    Parses the simple .github/labels.yml format.
    Expects format:
      - name: <label>
        color: <color>
        description: <desc>
    """
    with open(filepath) as f:
        content = f.read()

    labels = []
    # match each block starting with `- name:`
    blocks = content.split("- name:")[1:]
    for block in blocks:
        lines = block.strip().split("\n")
        name = lines[0].strip().strip("'\"")
        color = ""
        desc = ""
        for line in lines[1:]:
            if line.strip().startswith("color:"):
                color = line.strip()[6:].strip().strip("'\"")
            elif line.strip().startswith("description:"):
                desc = line.strip()[12:].strip().strip("'\"")

        if name and name != "*":
            labels.append({"name": name, "color": color, "description": desc})
    return labels


def get_existing_labels():
    """
    Uses gh cli to get existing labels.
    """
    try:
        result = subprocess.run(
            ["gh", "label", "list", "--json", "name,color,description", "--limit", "500"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching existing labels: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: GitHub CLI (gh) is not installed or not in PATH.")
        sys.exit(1)


def main():
    root_dir = Path(__file__).parent.parent
    labels_file = root_dir / ".github" / "labels.yml"

    if not labels_file.exists():
        print("Error: .github/labels.yml not found.")
        sys.exit(1)

    desired_labels = parse_labels(labels_file)
    existing_labels_list = get_existing_labels()

    existing_labels_map = {lbl["name"]: lbl for lbl in existing_labels_list}

    print(f"Found {len(desired_labels)} desired labels in taxonomy.")
    print(f"Found {len(existing_labels_list)} existing labels on GitHub.")

    success = True

    for desired in desired_labels:
        name = desired["name"]
        color = desired.get("color", "ededed")
        desc = desired.get("description", "")

        if name in existing_labels_map:
            existing = existing_labels_map[name]
            # Check if color or description needs update
            if existing.get("color") != color or existing.get("description") != desc:
                print(f"Updating label: '{name}'")
                try:
                    subprocess.run(
                        ["gh", "label", "edit", name, "--color", color, "--description", desc],
                        check=True,
                        capture_output=True,
                    )
                except subprocess.CalledProcessError as e:
                    print(f"Failed to update label '{name}': {e}")
                    success = False
            else:
                print(f"Label '{name}' is up to date.")
        else:
            print(f"Creating label: '{name}'")
            try:
                subprocess.run(
                    ["gh", "label", "create", name, "--color", color, "--description", desc],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"Failed to create label '{name}': {e}")
                success = False

    if not success:
        print("Some labels failed to sync.")
        sys.exit(1)

    print("Label sync complete.")


if __name__ == "__main__":
    main()
