
import asyncio
import sys
from pathlib import Path

# Mocking the environment
# Bootstrap: Add project root to import test helpers
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.utilities.test_helpers import add_to_path

# Add specific subdirectory for LinterService
add_to_path('agents/coding_agent')

from services.linter_service import LinterService

async def test_linter():
    print("Testing LinterService Integration...")
    
    # Create a file with a syntax error
    bad_file = Path("bad_code.py")
    bad_file.write_text("def foo()\n    pass  # Missing colon")
    
    service = LinterService(Path("."))
    
    print("1. Checking Syntax Error...")
    result = await service.check_file(bad_file)
    if not result.valid:
        print(f"✅ Caught Syntax Error: {result.errors}")
    else:
        print("❌ Failed to catch syntax error")
        
    # Create a file with a lint error (unused import)
    lint_file = Path("lint_code.py")
    lint_file.write_text("import os\n\ndef foo():\n    pass")
    
    print("\n2. Checking Lint Error (Unused Import)...")
    result = await service.check_file(lint_file)
    
    # Note: Flake8/Pylint should catch unused import 'os'
    if not result.valid:
         found_unused = any("unused" in e.lower() or "defined" in e.lower() or "F401" in e for e in result.errors)
         if found_unused:
             print(f"✅ Caught Lint Error: {result.errors}")
         else:
             print(f"⚠️ Lint reported errors but maybe not unused import? {result.errors}")
    else:
        print("❌ Failed to catch lint error (Are pylint/flake8 installed?)")

    # Cleanup
    if bad_file.exists(): bad_file.unlink()
    if lint_file.exists(): lint_file.unlink()

if __name__ == "__main__":
    asyncio.run(test_linter())
