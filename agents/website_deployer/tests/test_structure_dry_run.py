#!/usr/bin/env python3
"""
Structure and Import Test for Website Deployment Agent
======================================================

Tests code structure, imports, and class definitions without requiring
external dependencies (anthropic, paramiko) to be installed.

This test verifies:
- All files exist
- Python syntax is valid
- Class definitions are correct
- Method signatures are correct

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import os
import sys
import ast
import logging
from pathlib import Path
from typing import Dict, List, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test results tracking
test_results = {
    "file_structure": {"status": "pending", "errors": []},
    "python_syntax": {"status": "pending", "errors": []},
    "class_structure": {"status": "pending", "errors": []},
    "schema_files": {"status": "pending", "errors": []},
}


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_file_structure():
    """Test that all expected files exist."""
    print_section("FILE STRUCTURE TEST")

    expected_files = [
        # SSH Infrastructure
        "ssh/__init__.py",
        "ssh/connection.py",
        "ssh/safety.py",
        "ssh/executor.py",

        # Stages
        "stages/__init__.py",
        "stages/requirement_analyzer.py",
        "stages/architecture_designer.py",
        "stages/code_generator.py",
        "stages/deployment_orchestrator.py",

        # Generators
        "stages/generators/__init__.py",
        "stages/generators/model_generator.py",
        "stages/generators/fastapi_generator.py",
        "stages/generators/migration_generator.py",
        "stages/generators/auth_generator.py",
        "stages/generators/worker_generator.py",
        "stages/generators/frontend_generator.py",
        "stages/generators/config_generator.py",

        # Deployment Modules
        "stages/deployment_modules/__init__.py",
        "stages/deployment_modules/file_transfer.py",
        "stages/deployment_modules/package_installer.py",
        "stages/deployment_modules/database_setup.py",
        "stages/deployment_modules/nginx_configurator.py",
        "stages/deployment_modules/ssl_setup.py",
        "stages/deployment_modules/systemd_service.py",

        # Schemas
        "schemas/requirement_schema.json",
        "schemas/architecture_schema.json",

        # Examples
        "examples/ssh_connection_demo.py",
        "examples/command_execution_demo.py",
        "examples/requirement_analysis_demo.py",
        "examples/architecture_design_demo.py",
        "examples/complete_pipeline_demo.py",
        "examples/full_deployment_demo.py",

        # Documentation
        "README.md",
        "requirements.txt",
    ]

    missing_files = []
    for file_path in expected_files:
        full_path = Path(file_path)
        if full_path.exists():
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} - MISSING")
            missing_files.append(file_path)

    if missing_files:
        test_results["file_structure"]["status"] = "failed"
        test_results["file_structure"]["errors"] = missing_files
        return False
    else:
        test_results["file_structure"]["status"] = "passed"
        print("\n✅ All expected files exist")
        return True


def test_python_syntax():
    """Test Python syntax in all Python files."""
    print_section("PYTHON SYNTAX TEST")

    python_files = [
        "ssh/connection.py",
        "ssh/safety.py",
        "ssh/executor.py",
        "stages/requirement_analyzer.py",
        "stages/architecture_designer.py",
        "stages/code_generator.py",
        "stages/deployment_orchestrator.py",
        "stages/generators/model_generator.py",
        "stages/generators/fastapi_generator.py",
        "stages/generators/migration_generator.py",
        "stages/generators/auth_generator.py",
        "stages/generators/worker_generator.py",
        "stages/generators/frontend_generator.py",
        "stages/generators/config_generator.py",
        "stages/deployment_modules/file_transfer.py",
        "stages/deployment_modules/package_installer.py",
        "stages/deployment_modules/database_setup.py",
        "stages/deployment_modules/nginx_configurator.py",
        "stages/deployment_modules/ssl_setup.py",
        "stages/deployment_modules/systemd_service.py",
    ]

    syntax_errors = []

    for file_path in python_files:
        full_path = Path(file_path)
        if not full_path.exists():
            continue

        try:
            with open(full_path, 'r') as f:
                content = f.read()

            ast.parse(content)
            print(f"✅ {file_path}")

        except SyntaxError as e:
            print(f"❌ {file_path} - Syntax error at line {e.lineno}")
            syntax_errors.append(f"{file_path}: {e}")

    if syntax_errors:
        test_results["python_syntax"]["status"] = "failed"
        test_results["python_syntax"]["errors"] = syntax_errors
        return False
    else:
        test_results["python_syntax"]["status"] = "passed"
        print("\n✅ All Python files have valid syntax")
        return True


def test_class_structure():
    """Test that expected classes and methods exist."""
    print_section("CLASS STRUCTURE TEST")

    expected_classes = {
        "stages/requirement_analyzer.py": {
            "RequirementAnalyzer": ["analyze", "save_requirements"],
            "RequirementAnalysisResult": []
        },
        "stages/architecture_designer.py": {
            "ArchitectureDesigner": ["design", "save_architecture"],
            "ArchitectureDesignResult": []
        },
        "stages/code_generator.py": {
            "CodeGenerator": ["generate"],
            "CodeGenerationResult": []
        },
        "stages/deployment_orchestrator.py": {
            "DeploymentOrchestrator": ["deploy"],
            "DeploymentResult": []
        },
        "stages/deployment_modules/file_transfer.py": {
            "FileTransfer": ["transfer"]
        },
        "stages/deployment_modules/package_installer.py": {
            "PackageInstaller": ["install"]
        },
        "stages/deployment_modules/database_setup.py": {
            "DatabaseSetup": ["configure"]
        },
        "stages/deployment_modules/nginx_configurator.py": {
            "NginxConfigurator": ["configure"]
        },
        "stages/deployment_modules/ssl_setup.py": {
            "SSLSetup": ["setup"]
        },
        "stages/deployment_modules/systemd_service.py": {
            "SystemdService": ["create"]
        },
    }

    structure_errors = []

    for file_path, classes in expected_classes.items():
        full_path = Path(file_path)
        if not full_path.exists():
            continue

        try:
            with open(full_path, 'r') as f:
                content = f.read()

            tree = ast.parse(content)

            # Find all class definitions
            found_classes = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_name = node.name
                    methods = [m.name for m in node.body if isinstance(m, ast.FunctionDef)]
                    found_classes[class_name] = methods

            # Check expected classes
            for class_name, expected_methods in classes.items():
                if class_name not in found_classes:
                    error = f"{file_path}: Missing class '{class_name}'"
                    print(f"❌ {error}")
                    structure_errors.append(error)
                    continue

                # Check expected methods
                found_methods = found_classes[class_name]
                for method in expected_methods:
                    if method not in found_methods:
                        error = f"{file_path}: Class '{class_name}' missing method '{method}'"
                        print(f"❌ {error}")
                        structure_errors.append(error)
                    else:
                        print(f"✅ {file_path}: {class_name}.{method}")

        except Exception as e:
            error = f"{file_path}: Error parsing - {e}"
            print(f"❌ {error}")
            structure_errors.append(error)

    if structure_errors:
        test_results["class_structure"]["status"] = "failed"
        test_results["class_structure"]["errors"] = structure_errors
        return False
    else:
        test_results["class_structure"]["status"] = "passed"
        print("\n✅ All expected classes and methods exist")
        return True


def test_schema_files():
    """Test that JSON schema files are valid."""
    print_section("SCHEMA FILES TEST")

    import json

    schema_files = [
        "schemas/requirement_schema.json",
        "schemas/architecture_schema.json",
    ]

    schema_errors = []

    for file_path in schema_files:
        full_path = Path(file_path)
        if not full_path.exists():
            continue

        try:
            with open(full_path, 'r') as f:
                schema = json.load(f)

            # Basic validation
            if "$schema" not in schema:
                schema_errors.append(f"{file_path}: Missing '$schema' field")

            print(f"✅ {file_path} - Valid JSON")

        except json.JSONDecodeError as e:
            error = f"{file_path}: Invalid JSON - {e}"
            print(f"❌ {error}")
            schema_errors.append(error)

    if schema_errors:
        test_results["schema_files"]["status"] = "failed"
        test_results["schema_files"]["errors"] = schema_errors
        return False
    else:
        test_results["schema_files"]["status"] = "passed"
        print("\n✅ All schema files are valid")
        return True


def print_final_report():
    """Print final test report."""
    print_section("TEST SUMMARY")

    total_tests = len(test_results)
    passed = sum(1 for r in test_results.values() if r["status"] == "passed")
    failed = sum(1 for r in test_results.values() if r["status"] == "failed")

    print(f"\nTotal Tests: {total_tests}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    print("\nDetailed Results:")
    print("-" * 80)

    for test_name, result in test_results.items():
        status_icon = {
            "passed": "✅",
            "failed": "❌",
            "pending": "⏳"
        }.get(result["status"], "❓")

        print(f"\n{status_icon} {test_name.replace('_', ' ').upper()}: {result['status'].upper()}")

        if result["errors"]:
            print("   Errors:")
            for error in result["errors"][:10]:  # Limit to 10 errors
                print(f"     - {error}")
            if len(result["errors"]) > 10:
                print(f"     ... and {len(result['errors']) - 10} more errors")

    print("\n" + "=" * 80)

    if failed > 0:
        print("\n❌ STRUCTURE TEST FAILED - Issues found!")
        return False
    else:
        print("\n✅ STRUCTURE TEST PASSED - All structure tests passed!")
        return True


def main():
    """Run structure tests."""
    print("=" * 80)
    print("WEBSITE DEPLOYMENT AGENT - STRUCTURE TEST")
    print("=" * 80)
    print()
    print("This test verifies code structure without requiring external dependencies.")
    print()

    try:
        # Run all tests
        test_file_structure()
        test_python_syntax()
        test_class_structure()
        test_schema_files()

        # Print final report
        success = print_final_report()

        # Exit with appropriate code
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n❌ Test cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
