
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# Mock environment
sys.path.append('/home/sabawi/Development/RAICA/agents/coding_agent')
from services.patch_applier import PatchApplier

def test_smart_indentation():
    print("Testing Smart Indentation...")
    
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        applier = PatchApplier(tmp_path)
        
        # Setup File
        file_path = tmp_path / "test_indent.py"
        file_content = """
class MyClass:
    def method_one(self):
        print("One")
        return 1

    def method_two(self):
        print("Two")
        return 2
"""
        file_path.write_text(file_content)
        
        # Test Case: Replace method_one with Unindented replacement
        # Search is also unindented (common LLM behavior)
        search = """def method_one(self):
    print("One")
    return 1"""
    
        replace = """def method_one(self):
    print("One Modified")
    return 100"""
    
        print("\nApplying Unindented Patch...")
        result = applier.apply_patches([{'file': "test_indent.py", 'search': search, 'replace': replace}])
        
        if result.success:
            print("✅ Patch Success")
            new_content = file_path.read_text()
            print("-" * 20)
            print(new_content)
            print("-" * 20)
            
            # Verify Indentation
            if "    def method_one(self):" in new_content:
                print("✅ Correctly Indented")
            else:
                print("❌ Incorrect Indentation")
        else:
            print(f"❌ Patch Failed: {result.error}")

def test_syntax_validation():
    print("\nTesting Syntax Validation...")
    
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        applier = PatchApplier(tmp_path)
        
        # Setup File
        file_path = tmp_path / "test_syntax.py"
        file_content = "def foo():\n    pass\n"
        file_path.write_text(file_content)
        
        search = "pass"
        replace = "if True  # Missing colon syntax error"
        
        print("\nApplying Broken Syntax Patch...")
        result = applier.apply_patches([{'file': "test_syntax.py", 'search': search, 'replace': replace}])
        
        if not result.success and "Syntax Error" in result.error:
            print(f"✅ Syntax Error Caught: {result.error}")
        else:
            print(f"❌ Failed to catch syntax error. Result: {result}")

if __name__ == "__main__":
    test_smart_indentation()
    test_syntax_validation()
