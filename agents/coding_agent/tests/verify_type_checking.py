
import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# Mock environment
sys.path.append('/home/sabawi/Development/RAICA/agents/coding_agent')
from services.linter_service import LinterService

async def test_type_checking():
    print("Testing Mypy Integration...")
    
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        linter = LinterService(tmp_path)
        
        if not linter._available_tools['mypy']:
            print("⚠️ Mypy not found in environment. Skipping test.")
            return

        # Setup File with Type Error
        file_path = tmp_path / "test_types.py"
        file_content = """
def add_numbers(a: int, b: int) -> int:
    return a + b

result: int = add_numbers(5, "10") # Type Error
"""
        file_path.write_text(file_content)
        
        print("\nChecking file with Type Error...")
        result = await linter.check_file(file_path)
        
        if not result.valid:
            print("✅ Linter correctly rejected invalid types.")
            print(f"Errors:\n{result.errors[0]}")
        else:
            print("❌ Linter failed to catch type error.")

if __name__ == "__main__":
    asyncio.run(test_type_checking())
