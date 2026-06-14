import sys
import os
import subprocess
import pytest
from pathlib import Path

def test_validate_github_labels_script():
    """
    Test that the validate_github_labels.py script runs successfully
    and correctly validates the current repository's labels.
    """
    root_dir = Path(__file__).parent.parent
    script_path = root_dir / "scripts" / "validate_github_labels.py"
    
    assert script_path.exists(), "Validation script not found."
    
    # Run the validation script
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=root_dir,
        capture_output=True,
        text=True
    )
    
    # The script should exit with 0 if all labels are valid
    assert result.returncode == 0, f"Script failed with output:\n{result.stdout}\n{result.stderr}"
    assert "Success" in result.stdout
