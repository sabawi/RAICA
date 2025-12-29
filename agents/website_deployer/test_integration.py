#!/usr/bin/env python3
"""
Quick test to verify workflow planner integration with Agentic-RAG research.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from stages.intelligent_generators.workflow_planner import WorkflowPlanner
from stages.intelligent_generators.requirement_elaborator import DetailedSpecification
from stages.intelligent_generators.tech_stack_config import TechStackConfig
from dataclasses import dataclass, field
from typing import List, Dict, Any

# Create minimal spec for testing
spec = DetailedSpecification(
    project_name="test_api",
    description="Test API",
    tech_stack="python_fastapi",
    backend_language="python",
    backend_framework="fastapi",
    frontend_framework="alpine.js",
    database_type="postgresql",
    state_management="alpine.js",
    authentication={"method": "jwt", "email_verification": True},
    models=[],
    api_endpoints=[],
    data_models=[],
    ui_components=[],
    page_layouts=[],
    background_workers=[],
    data_flows=[],
    integrations=[]
)

# Create tech config
tech_config = TechStackConfig.get_config("python_fastapi")

print("=" * 80)
print("TESTING WORKFLOW PLANNER INTEGRATION WITH AGENTIC-RAG")
print("=" * 80)
print()

# Create workflow planner
planner = WorkflowPlanner(tech_config)

print("✅ WorkflowPlanner initialized")
print(f"   Has intelligent_resolver: {hasattr(planner, 'intelligent_resolver')}")
print(f"   Has researched_dependencies: {hasattr(planner, 'researched_dependencies')}")
print(f"   Has security_patterns: {hasattr(planner, 'security_patterns')}")
print()

# Test the research method directly
print("Testing _research_dependencies_sync()...")
try:
    planner._research_dependencies_sync(spec)
    print(f"✅ Research completed!")
    print(f"   Researched {len(planner.researched_dependencies)} dependencies")
    print(f"   Extracted {len(planner.security_patterns)} security patterns")
    print()
    if planner.researched_dependencies:
        print("First 5 dependencies:")
        for dep in planner.researched_dependencies[:5]:
            print(f"   - {dep}")
except Exception as e:
    print(f"❌ Research failed: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
print("TEST COMPLETE")
print("=" * 80)
