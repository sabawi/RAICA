#!/usr/bin/env python3
"""
Test PHP Fix
============

Test that the PHP code generation fix works correctly.
"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stages.intelligent_code_generator import IntelligentCodeGenerator

def test_php_project():
    """Generate a simple PHP project to verify fixes."""

    print("=" * 80)
    print("TESTING PHP CODE GENERATION FIX")
    print("=" * 80)
    print()

    # Simple PHP spec
    spec = """
    Create a simple Hello World PHP web application where users can:
    - See a login page
    - Log in with username/password (admin/admin123)
    - See a welcome page with their username
    - Log out

    Use PHP for the backend, Apache2 as the web server, and SQLite for the database.
    """

    print("📝 Specification:")
    print(spec)
    print()

    # Clean up previous test
    output_dir = Path("test_generated_project")
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # Generate code
    print("🚀 Generating PHP code...")
    generator = IntelligentCodeGenerator()
    result = generator.generate(spec, interactive=False)

    if not result.success:
        print(f"❌ Failed: {result.message}")
        return False

    print("✅ Code generation complete")
    print(f"📁 Project generated at: {result.project_path}")
    print(f"🌐 URL: {result.url}")

    # Verify it's a PHP project
    project_path = Path(result.project_path)
    
    # Check for PHP files
    php_files = list(project_path.rglob("*.php"))
    if not php_files:
        print("❌ No PHP files found - this is not a PHP project!")
        return False
    
    print(f"✅ Found {len(php_files)} PHP files")
    
    # Check for composer.json (PHP dependency file)
    composer_file = project_path / "composer.json"
    if composer_file.exists():
        print("✅ Found composer.json")
    else:
        print("⚠️  No composer.json found")
    
    # Check that there are no Python files
    py_files = list(project_path.rglob("*.py"))
    if py_files:
        print(f"❌ Found {len(py_files)} Python files - this should be a PHP project!")
        return False
    
    print("✅ No Python files found - this is correctly a PHP project")
    
    print("\n" + "=" * 80)
    print("PHP CODE GENERATION FIX VERIFICATION COMPLETE")
    print("=" * 80)
    print("✅ PHP code generation is working correctly!")
    return True

if __name__ == "__main__":
    success = test_php_project()
    sys.exit(0 if success else 1)