
import os
import sys
from pathlib import Path
import shutil

# Add RAICA to path
current_file = Path(__file__).resolve()
# Root is /home/sabawi/Development/RAICA
raica_root = current_file.parent.parent.parent
sys.path.insert(0, str(raica_root))

from agents.coding_agent.services.patch_applier import PatchApplier
from agents.coding_agent.services.linter_service import LinterService, LinterResult

def test_patch_application_line_collapse():
    print("\n--- Testing PatchApplier Line Collapse Strategy ---")
    project_dir = Path("temp_verify_project")
    project_dir.mkdir(exist_ok=True)
    
    file_path = project_dir / "app.py"
    original_code = """
def calculate_sum(a, b):
    result = a + b
    return result
"""
    file_path.write_text(original_code)
    
    applier = PatchApplier(project_dir)
    
    # Simulate LLM splitting lines that weren't split
    patches = [{
        'file': 'app.py',
        'search': """result = a +
    b""",  # Split line!
        'replace': """result = a + b + 0  # Fixed"""
    }]
    
    result = applier.apply_patches(patches)
    print(f"Success: {result.success}")
    if result.success:
        print("Final Code:")
        print(file_path.read_text())
    else:
        print(f"Error: {result.error}")
    
    shutil.rmtree(project_dir)

def test_linter_line_agnostic():
    print("\n--- Testing LinterService Line-Agnostic Baseline ---")
    project_dir = Path("temp_verify_project")
    project_dir.mkdir(exist_ok=True)
    
    linter = LinterService(project_dir)
    
    # Create baseline with a lint error
    baseline = LinterResult(False, [
        "app.py:10:5: F841 local variable 'temp' is assigned to but never used"
    ])
    
    # Current result has the SAME error but on a DIFFERENT line
    current = LinterResult(False, [
        "app.py:15:5: F841 local variable 'temp' is assigned to but never used"
    ])
    
    # Manual check of _clean_error
    clean_b = linter._clean_error(baseline.errors[0])
    clean_c = linter._clean_error(current.errors[0])
    print(f"Cleaned Baseline: {clean_b}")
    print(f"Cleaned Current:  {clean_c}")
    
    # Mock check_file logic for filtering
    clean_baseline = {linter._clean_error(e) for e in baseline.errors}
    new_errors = []
    for e in current.errors:
        cleaned = linter._clean_error(e)
        if cleaned not in clean_baseline:
            new_errors.append(e)
            
    print(f"New Errors found: {len(new_errors)}")
    if not new_errors:
        print("Success: Pre-existing error ignored despite line shift.")
    else:
        print("Failure: Error was not ignored.")
        
    shutil.rmtree(project_dir)

if __name__ == "__main__":
    try:
        test_patch_application_line_collapse()
        test_linter_line_agnostic()
    except Exception as e:
        print(f"Verification script failed: {e}")
        import traceback
        traceback.print_exc()
