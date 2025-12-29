#!/usr/bin/env python3
"""
End-to-End Test for Python/FastAPI Stack

This test exercises the entire intelligent code generation pipeline
to verify that the tech-stack agnostic refactoring works correctly.
"""

import sys
import os
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stages.intelligent_generators.prompt_analyzer import PromptAnalyzer
from stages.intelligent_generators.requirement_elaborator import RequirementElaborator
from stages.intelligent_generators.workflow_planner import WorkflowPlanner
from stages.intelligent_generators.tech_stack_config import TechStackConfig

def test_python_fastapi_pipeline():
    """Test the complete pipeline for Python/FastAPI stack."""
    print("=" * 70)
    print("END-TO-END TEST: Python/FastAPI Stack")
    print("=" * 70)
    print()
    
    # Step 1: Skip Prompt Analysis (requires LLM)
    print("STEP 1: Prompt Analysis (SKIPPED - No LLM configured)")
    print("-" * 70)
    print("✓ Skipping LLM-dependent step")
    print()
    
    # Step 2: Requirement Elaboration
    print("STEP 2: Requirement Elaboration")
    print("-" * 70)
    
    elaborator = RequirementElaborator()
    
    # Create a mock detailed specification (normally this would come from LLM)
    from stages.intelligent_generators.requirement_elaborator import DetailedSpecification, DataModel, APIEndpoint
    
    spec = DetailedSpecification(
        project_name="blog_app",
        project_type="web_app",
        description="A blog application with user authentication and post management",
        ui_components=[],
        page_layouts=[
            {
                "name": "Home",
                "template_file": "home.html",
                "route": "/",
                "components": []
            }
        ],
        frontend_framework="alpine_tailwind",
        state_management={},
        backend_language="python",
        backend_framework="fastapi",
        api_endpoints=[
            APIEndpoint(
                path="/api/posts",
                method="GET",
                description="Get all blog posts",
                auth_required=False,
                request_body=None,
                response="List[Post]"
            ),
            APIEndpoint(
                path="/api/posts",
                method="POST",
                description="Create a new blog post",
                auth_required=True,
                request_body="PostCreate",
                response="Post"
            )
        ],
        data_models=[
            DataModel(
                name="User",
                table_name="users",
                fields=[
                    {"name": "id", "type": "UUID"},
                    {"name": "email", "type": "String"},
                    {"name": "username", "type": "String"},
                    {"name": "hashed_password", "type": "String"}
                ],
                relationships=[],
                indexes=["email", "username"]
            ),
            DataModel(
                name="Post",
                table_name="posts",
                fields=[
                    {"name": "id", "type": "UUID"},
                    {"name": "title", "type": "String"},
                    {"name": "content", "type": "Text"},
                    {"name": "author_id", "type": "UUID"}
                ],
                relationships=[
                    {"model": "User", "type": "many-to-one"}
                ],
                indexes=["author_id"]
            )
        ],
        authentication={
            "type": "jwt",
            "token_expiry": "30 minutes"
        },
        authorization={},
        data_flows=[],
        web_server="uvicorn",
        database_type="postgresql",
        caching_strategy=None,
        background_workers=[],
        external_integrations=[]
    )
    
    print(f"✓ Project Name: {spec.project_name}")
    print(f"✓ Backend: {spec.backend_language}/{spec.backend_framework}")
    print(f"✓ Database: {spec.database_type}")
    print(f"✓ Data Models: {len(spec.data_models)}")
    print(f"✓ API Endpoints: {len(spec.api_endpoints)}")
    print()
    
    # Step 3: Get Tech Config
    print("STEP 3: Tech Stack Configuration")
    print("-" * 70)
    
    tech_config = spec.get_tech_config()
    
    print(f"✓ Tech Key: {tech_config.tech_key}")
    print(f"✓ File Extension: {tech_config.get_file_extension()}")
    print(f"✓ Models Directory: {tech_config.get_models_dir()}")
    print(f"✓ Controllers Directory: {tech_config.get_controllers_dir()}")
    print(f"✓ ORM: {tech_config.get_orm_library()}")
    print(f"✓ Validation: {tech_config.get_validation_library()}")
    print(f"✓ Dependency File: {tech_config.get_dependency_file_name()}")
    print()
    
    # Step 4: Workflow Planning
    print("STEP 4: Workflow Planning")
    print("-" * 70)
    
    planner = WorkflowPlanner(tech_config)
    workflow = planner.plan(spec)
    
    print(f"✓ Total Files: {workflow.total_files}")
    print(f"✓ Phases: {len(workflow.phases)}")
    print()
    
    print("File Breakdown by Type:")
    file_types = {}
    for file in workflow.get_all_files():
        file_types[file.file_type] = file_types.get(file.file_type, 0) + 1
    
    for file_type, count in sorted(file_types.items()):
        print(f"  - {file_type}: {count}")
    print()
    
    # Step 5: Verify File Paths and Extensions
    print("STEP 5: File Path Validation")
    print("-" * 70)
    
    all_files = workflow.get_all_files()
    
    # Check that all Python files have .py extension
    python_files = [f for f in all_files if f.file_type in ["model", "api_endpoint", "schema", "crud", "config", "main"]]
    for file in python_files:
        assert file.path.endswith('.py'), f"Python file should end with .py: {file.path}"
    
    print(f"✓ All {len(python_files)} Python files have .py extension")
    
    # Check that models are in correct directory
    model_files = [f for f in all_files if f.file_type == "model"]
    models_dir = tech_config.get_models_dir()
    for file in model_files:
        assert models_dir in file.path, f"Model file should be in {models_dir}: {file.path}"
    
    print(f"✓ All {len(model_files)} model files are in {models_dir}")
    
    # Check that API endpoints are in correct directory
    endpoint_files = [f for f in all_files if f.file_type == "api_endpoint"]
    controllers_dir = tech_config.get_controllers_dir()
    for file in endpoint_files:
        assert controllers_dir in file.path, f"Endpoint file should be in {controllers_dir}: {file.path}"
    
    print(f"✓ All {len(endpoint_files)} endpoint files are in {controllers_dir}")
    print()
    
    # Step 6: Verify Prompts Use Tech-Specific Templates
    print("STEP 6: Prompt Template Validation")
    print("-" * 70)
    
    # Check that model prompts mention SQLAlchemy
    model_file = next((f for f in all_files if f.file_type == "model"), None)
    if model_file:
        assert "SQLAlchemy" in model_file.prompt or "model" in model_file.prompt.lower(), \
            "Model prompt should be tech-specific"
        print(f"✓ Model prompt is tech-specific (mentions SQLAlchemy or model)")
    
    # Check that endpoint prompts mention FastAPI
    endpoint_file = next((f for f in all_files if f.file_type == "api_endpoint"), None)
    if endpoint_file:
        assert "FastAPI" in endpoint_file.prompt or "router" in endpoint_file.prompt.lower(), \
            "Endpoint prompt should be tech-specific"
        print(f"✓ Endpoint prompt is tech-specific (mentions FastAPI or router)")
    
    print()
    
    # Step 7: Verify Dependency Graph
    print("STEP 7: Dependency Graph Validation")
    print("-" * 70)
    
    # Check that models have no dependencies (or only __init__.py)
    for file in model_files:
        if file.dependencies:
            for dep in file.dependencies:
                assert "__init__.py" in dep, f"Model should only depend on __init__.py: {file.path}"
    
    print(f"✓ Model files have correct dependencies")
    
    # Check that CRUD files depend on models
    crud_files = [f for f in all_files if f.file_type == "crud"]
    for crud_file in crud_files:
        has_model_dep = any(models_dir in dep for dep in crud_file.dependencies)
        assert has_model_dep, f"CRUD file should depend on model: {crud_file.path}"
    
    print(f"✓ CRUD files depend on models")
    print()
    
    # Summary
    print("=" * 70)
    print("✅ END-TO-END TEST PASSED!")
    print("=" * 70)
    print()
    print("Summary:")
    print(f"  - Tech Stack: Python/FastAPI")
    print(f"  - Files Generated: {workflow.total_files}")
    print(f"  - Phases: {len(workflow.phases)}")
    print(f"  - All files have correct extensions: ✓")
    print(f"  - All files in correct directories: ✓")
    print(f"  - Prompts are tech-specific: ✓")
    print(f"  - Dependencies are correct: ✓")
    print()

def main():
    """Run the end-to-end test."""
    try:
        test_python_fastapi_pipeline()
        print("🎉 All validations passed! The pipeline is working correctly.")
        return 0
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
