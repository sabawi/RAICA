
import sys
import os
from pathlib import Path
from typing import Dict, List

# Add agent directory to path
sys.path.append('/home/sabawi/Development/flaskserver/agents/coding_agent')

from validation import ConsistencyVerifier, SymbolExtractor, InterfaceDefinition, ExportedSymbol

def test_symbol_extraction():
    print("Testing SymbolExtractor...")
    extractor = SymbolExtractor('python')
    
    code = """
class DisplayManager:
    def __init__(self, width, height):
        self.width = width
    
    def render(self):
        pass

def main():
    pass
"""
    interface = extractor.extract(code, "display.py")
    
    assert len(interface.exports) == 2
    display_class = next(e for e in interface.exports if e.name == "DisplayManager")
    assert display_class.symbol_type == "class"
    assert display_class.param_count == 2
    assert "width" in display_class.params
    assert "height" in display_class.params
    
    print("✅ SymbolExtractor passed")

def test_consistency_verifier_failure():
    print("\nTesting ConsistencyVerifier (Failure Case)...")
    
    files = {
        "display.py": """
class DisplayManager:
    def __init__(self, width, height):
        pass
""",
        "main.py": """
from display import DisplayManager

def main():
    # Error: Missing argument 'height'
    screen = DisplayManager(800)
"""
    }
    
    verifier = ConsistencyVerifier(files, 'python')
    result = verifier.validate()
    
    print(f"Validation result: valid={result.valid}")
    if result.valid:
        print("❌ Verification PASSED but should have FAILED")
        files_keys = list(files.keys())
        print(f"Files: {files_keys}")
        # Debug why it passed
        # e.g., maybe import resolving failed silently
        
    if not result.valid:
        print(f"Errors found: {result.errors}")

    assert not result.valid
    assert any("signature_mismatch" in e for e in result.errors)
    assert any("expected='2'" in e for e in result.errors)
    
    print("✅ ConsistencyVerifier correctly identified errors")

def test_consistency_verifier_success():
    print("\nTesting ConsistencyVerifier (Success Case)...")
    
    files = {
        "display.py": """
class DisplayManager:
    def __init__(self, width, height):
        pass
""",
        "main.py": """
from display import DisplayManager

def main():
    # Correct usage
    screen = DisplayManager(800, 600)
"""
    }
    
    verifier = ConsistencyVerifier(files, 'python')
    result = verifier.validate()
    
    if not result.valid:
        print(f"❌ Verification failed unexpectedly: {result.errors}")
        sys.exit(1)
        
    assert result.valid
    print("✅ ConsistencyVerifier passed")

if __name__ == "__main__":
    try:
        test_symbol_extraction()
        test_consistency_verifier_failure()
        test_consistency_verifier_success()
        print("\n🎉 ALL ARCHITECTURE TESTS PASSED")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ EXECUTION ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
