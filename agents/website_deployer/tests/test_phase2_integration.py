#!/usr/bin/env python3
"""
Test Phase 2 Integration - TechStackConfig Propagation
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stages.intelligent_generators.tech_stack_config import TechStackConfig
from stages.intelligent_generators.requirement_elaborator import DetailedSpecification
from stages.intelligent_generators.workflow_planner import WorkflowPlanner
from stages.intelligent_generators.llm_code_generator import LLMCodeGenerator
from stages.intelligent_generators.assembly_coordinator import AssemblyCoordinator
from stages.intelligent_generators.consistency_verifier import ConsistencyVerifier

def test_tech_config_creation():
    """Test that TechStackConfig can be created from DetailedSpecification."""
    print("=" * 60)
    print("TEST 1: TechStackConfig Creation")
    print("=" * 60)
    
    # Create a minimal spec
    spec = DetailedSpecification(
        project_name="test_project",
        project_type="web_app",
        description="Test project",
        ui_components=[],
        page_layouts=[],
        frontend_framework="alpine_tailwind",
        state_management={},
        backend_language="python",
        backend_framework="fastapi",
        api_endpoints=[],
        data_models=[],
        authentication={},
        authorization={},
        data_flows=[],
        web_server="uvicorn",
        database_type="postgresql",
        caching_strategy=None,
        background_workers=[],
        external_integrations=[]
    )
    
    # Get tech config
    tech_config = spec.get_tech_config()
    
    print(f"✓ Tech Config Created: {tech_config.tech_key}")
    print(f"  - Backend Language: {tech_config.backend_language}")
    print(f"  - Backend Framework: {tech_config.backend_framework}")
    print(f"  - File Extension: {tech_config.get_file_extension()}")
    print(f"  - Models Dir: {tech_config.get_models_dir()}")
    print(f"  - Controllers Dir: {tech_config.get_controllers_dir()}")
    print()
    
    return tech_config

def test_stage_initialization(tech_config):
    """Test that all stages can be initialized with TechStackConfig."""
    print("=" * 60)
    print("TEST 2: Stage Initialization with TechStackConfig")
    print("=" * 60)
    
    # Initialize all stages
    planner = WorkflowPlanner(tech_config)
    print(f"✓ WorkflowPlanner initialized with tech_config")
    
    generator = LLMCodeGenerator(tech_config=tech_config)
    print(f"✓ LLMCodeGenerator initialized with tech_config")
    
    assembler = AssemblyCoordinator(tech_config=tech_config)
    print(f"✓ AssemblyCoordinator initialized with tech_config")
    
    verifier = ConsistencyVerifier(tech_config)
    print(f"✓ ConsistencyVerifier initialized with tech_config")
    print()
    
    return planner

def test_workflow_planning(planner, tech_config):
    """Test that WorkflowPlanner uses tech_config for file paths."""
    print("=" * 60)
    print("TEST 3: WorkflowPlanner File Path Generation")
    print("=" * 60)
    
    # Create a minimal spec with one model
    from stages.intelligent_generators.requirement_elaborator import DataModel
    
    spec = DetailedSpecification(
        project_name="test_project",
        project_type="web_app",
        description="Test project",
        ui_components=[],
        page_layouts=[],
        frontend_framework="alpine_tailwind",
        state_management={},
        backend_language="python",
        backend_framework="fastapi",
        api_endpoints=[],
        data_models=[
            DataModel(
                name="User",
                table_name="users",
                fields=[
                    {"name": "id", "type": "UUID"},
                    {"name": "email", "type": "String"}
                ],
                relationships=[],
                indexes=[]
            )
        ],
        authentication={},
        authorization={},
        data_flows=[],
        web_server="uvicorn",
        database_type="postgresql",
        caching_strategy=None,
        background_workers=[],
        external_integrations=[]
    )
    
    # Plan workflow
    workflow = planner.plan(spec)
    
    print(f"✓ Workflow created with {workflow.total_files} files")
    print(f"  - Phases: {len(workflow.phases)}")
    
    # Check that files use correct extension
    ext = tech_config.get_file_extension()
    models_dir = tech_config.get_models_dir()
    
    all_files = workflow.get_all_files()
    model_files = [f for f in all_files if f.file_type == "model"]
    
    if model_files:
        sample_model = model_files[0]
        print(f"\n  Sample Model File:")
        print(f"    - Path: {sample_model.path}")
        print(f"    - Expected extension: {ext}")
        print(f"    - Expected directory: {models_dir}")
        
        # Verify
        assert sample_model.path.endswith(ext), f"File should end with {ext}"
        assert models_dir in sample_model.path, f"File should be in {models_dir}"
        print(f"    ✓ Path validation passed")
    
    print()

def test_prompt_templates(tech_config):
    """Test that prompt templates are loaded correctly."""
    print("=" * 60)
    print("TEST 4: Prompt Template Loading")
    print("=" * 60)
    
    # Test various prompt templates
    templates = ['model_prompt', 'api_endpoint_prompt', 'schema_prompt', 'crud_prompt', 'config_prompt']
    
    for template_name in templates:
        template = tech_config.get_prompt_template(template_name)
        if template:
            print(f"✓ {template_name}: Loaded ({len(template)} chars)")
        else:
            print(f"✗ {template_name}: NOT FOUND")
    
    print()

def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "PHASE 2 INTEGRATION TEST SUITE" + " " * 18 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    try:
        # Test 1: Create tech config
        tech_config = test_tech_config_creation()
        
        # Test 2: Initialize stages
        planner = test_stage_initialization(tech_config)
        
        # Test 3: Test workflow planning
        test_workflow_planning(planner, tech_config)
        
        # Test 4: Test prompt templates
        test_prompt_templates(tech_config)
        
        print("=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print()
        
    except Exception as e:
        print("=" * 60)
        print("❌ TEST FAILED")
        print("=" * 60)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
