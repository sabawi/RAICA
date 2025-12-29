#!/usr/bin/env python3
"""
Test that researched dependencies are injected into prompts.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from stages.intelligent_generators.workflow_planner import WorkflowPlanner
from stages.intelligent_generators.requirement_elaborator import DetailedSpecification
from stages.intelligent_generators.tech_stack_config import TechStackConfig

# Create tech config
tech_config = TechStackConfig.get_config("python_fastapi")

# Create workflow planner
planner = WorkflowPlanner(tech_config)

print("=" * 80)
print("TESTING DEPENDENCY PROMPT INJECTION")
print("=" * 80)
print()

# Simulate researched dependencies (as if research succeeded)
planner.researched_dependencies = [
    "fastapi==0.104.1",
    "sqlalchemy==2.0.23",
    "python-jose[cryptography]==3.3.0",
    "passlib[bcrypt]==1.7.4",
    "uvicorn==0.24.0"
]

planner.security_patterns = {
    "password_hashing": "from passlib.context import CryptContext\npwd_context = CryptContext(schemes=['bcrypt'])",
    "jwt": "from jose import jwt"
}

print(f"✅ Simulated research: {len(planner.researched_dependencies)} dependencies")
print(f"✅ Simulated research: {len(planner.security_patterns)} security patterns")
print()

# Create a mock spec (simplified)
from dataclasses import dataclass
@dataclass
class MockSpec:
    project_name: str = "test_api"
    description: str = "Test API"
    authentication: dict = None
    def __post_init__(self):
        if self.authentication is None:
            self.authentication = {"method": "jwt", "email_verification": False}

spec = MockSpec()

# Test dependency file prompt creation
print("Testing _create_dependency_file_prompt()...")
print("-" * 80)
prompt = planner._create_dependency_file_prompt("requirements.txt", spec)
print(prompt)
print("-" * 80)
print()

# Check if dependencies are injected
if "fastapi==0.104.1" in prompt:
    print("✅ Dependencies successfully injected into prompt!")
else:
    print("❌ Dependencies NOT found in prompt!")

# Test security prompt creation
print()
print("Testing _create_security_prompt()...")
print("-" * 80)
sec_prompt = planner._create_security_prompt(spec)
if "SECURITY IMPLEMENTATION PATTERNS" in sec_prompt:
    print("✅ Security patterns successfully injected!")
    print(f"   Found {sec_prompt.count('PATTERN:')} patterns in prompt")
else:
    print("⚠️  No security patterns in prompt (may be OK if research failed)")

print()
print("=" * 80)
print("TEST COMPLETE")
print("=" * 80)
