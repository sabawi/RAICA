#!/usr/bin/env python3
"""
Test Generator Fixes
====================

Tests the fixed generator templates by creating a simple project.
"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stages import RequirementAnalyzer, ArchitectureDesigner, CodeGenerator

def test_simple_project():
    """Generate a simple test project to verify fixes."""

    print("=" * 80)
    print("TESTING GENERATOR FIXES")
    print("=" * 80)
    print()

    # Simple spec
    spec = """
    Create a simple task manager where users can:
    - Register and log in
    - Create and manage tasks
    - Mark tasks as complete

    Each task has a title and optional description.
    """

    print("📝 Specification:")
    print(spec)
    print()

    # Phase 1: Requirements
    print("Phase 1: Requirements Analysis...")
    analyzer = RequirementAnalyzer()
    req_result = analyzer.analyze(spec)

    if not req_result.success:
        print(f"❌ Failed: {req_result.error_message}")
        return False

    print("✅ Requirements complete")
    requirements = req_result.requirements

    # Phase 2: Architecture
    print("\nPhase 2: Architecture Design...")
    designer = ArchitectureDesigner()
    arch_result = designer.design(requirements)

    if not arch_result.success:
        print(f"❌ Failed: {arch_result.error_message}")
        return False

    print("✅ Architecture complete")
    architecture = arch_result.architecture

    # Phase 3: Code Generation
    print("\nPhase 3: Code Generation...")
    output_dir = Path("test_generated_project")

    # Clean up if exists
    if output_dir.exists():
        shutil.rmtree(output_dir)

    generator = CodeGenerator(output_base_dir=output_dir)
    code_result = generator.generate(requirements, architecture)

    if not code_result.success:
        print(f"❌ Failed: {code_result.error_message}")
        return False

    print("✅ Code generation complete")
    project_path = code_result.output_directory

    # Verify fixes
    print("\n" + "=" * 80)
    print("VERIFYING FIXES")
    print("=" * 80)

    all_good = True

    # Check 1: Alembic env.py uses settings
    env_file = project_path / "alembic" / "env.py"
    with open(env_file) as f:
        env_content = f.read()

    if "from app.core.config import settings" in env_content:
        print("✅ Alembic env.py imports settings")
    else:
        print("❌ Alembic env.py missing settings import")
        all_good = False

    if "config.set_main_option" in env_content:
        print("✅ Alembic env.py overrides DATABASE_URL")
    else:
        print("❌ Alembic env.py doesn't override DATABASE_URL")
        all_good = False

    # Check 2: Config has REDIS_URL
    config_file = project_path / "app" / "core" / "config.py"
    with open(config_file) as f:
        config_content = f.read()

    if "REDIS_URL" in config_content:
        print("✅ Config includes REDIS_URL")
    else:
        print("❌ Config missing REDIS_URL")
        all_good = False

    # Check 3: Config has CORS validator
    if "field_validator" in config_content and "parse_cors_origins" in config_content:
        print("✅ Config has CORS_ORIGINS validator")
    else:
        print("❌ Config missing CORS_ORIGINS validator")
        all_good = False

    # Check 4: Setup script exists and has PostgreSQL user creation
    setup_file = project_path / "setup.sh"
    if setup_file.exists():
        with open(setup_file) as f:
            setup_content = f.read()

        if "createuser" in setup_content:
            print("✅ Setup script creates PostgreSQL user")
        else:
            print("❌ Setup script doesn't create PostgreSQL user")
            all_good = False

        # Check if executable
        import os
        if os.access(setup_file, os.X_OK):
            print("✅ Setup script is executable")
        else:
            print("❌ Setup script is not executable")
            all_good = False
    else:
        print("❌ Setup script missing")
        all_good = False

    # Check 5: requirements.txt has no Redis conflict
    req_file = project_path / "requirements.txt"
    with open(req_file) as f:
        req_content = f.read()

    # Should NOT have standalone redis line if celery[redis] is present
    lines = [l.strip() for l in req_content.split('\n') if l.strip() and not l.startswith('#')]
    has_celery_redis = any('celery[redis]' in line for line in lines)
    has_standalone_redis = any(line.startswith('redis==') for line in lines)

    if has_celery_redis and not has_standalone_redis:
        print("✅ No Redis dependency conflict")
    elif not has_celery_redis and has_standalone_redis:
        print("✅ Standalone Redis (no workers)")
    elif has_celery_redis and has_standalone_redis:
        print("❌ Redis dependency conflict detected")
        all_good = False
    else:
        print("⚠️  No Redis dependency (may be OK)")

    # Check 6: Apache2 configuration exists
    apache2_dir = project_path / "apache2"
    if apache2_dir.exists():
        apache2_configs = list(apache2_dir.glob("*.conf"))
        if apache2_configs:
            print("✅ Apache2 configuration exists")
        else:
            print("❌ Apache2 directory exists but no config files")
            all_good = False
    else:
        print("❌ Apache2 directory missing")
        all_good = False

    # Check 7: Setup script detects web servers
    if setup_file.exists():
        with open(setup_file) as f:
            setup_content = f.read()

        if "Detect web server" in setup_content and "apache2" in setup_content.lower():
            print("✅ Setup script detects Apache2 and Nginx")
        else:
            print("❌ Setup script missing web server detection")
            all_good = False

    print("\n" + "=" * 80)
    if all_good:
        print("🎉 ALL FIXES VERIFIED!")
        print("=" * 80)
        print(f"\nGenerated project: {project_path}")
        print("You can test it with:")
        print(f"  cd {project_path}")
        print(f"  ./setup.sh")
        return True
    else:
        print("❌ SOME FIXES FAILED")
        print("=" * 80)
        return False

if __name__ == "__main__":
    success = test_simple_project()
    sys.exit(0 if success else 1)
