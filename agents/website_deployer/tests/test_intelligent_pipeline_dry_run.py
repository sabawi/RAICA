#!/usr/bin/env python3
"""
Test Intelligent Pipeline Dry Run
=================================

Runs the full intelligent code generation pipeline with mocked LLM responses.
Verifies that all stages connect correctly and produce expected output.
"""

import os
import sys
import shutil
import logging
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stages.intelligent_code_generator import IntelligentCodeGenerator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class MockLLMResponse:
    content: str
    success: bool = True
    error: str = None

def mock_llm_generate(prompt, temperature=0.7):
    """Mock LLM response based on prompt content."""
    
    # Debug: Print prompt to see what we are matching against
    if "Generate" in prompt:
        print(f"DEBUG PROMPT: {prompt[:200]}...")
    
    content = ""
    
    # Stage 1: Analysis
    if "Analyze Web Application Requirements" in prompt:
        content = """
        ```json
        {
          "project_name": "Test App",
          "project_type": "todo_app",
          "description": "A simple todo app",
          "components": [
            {
              "name": "todo_list",
              "type": "ui",
              "description": "List of todos",
              "requirements": ["show items", "add item"]
            }
          ],
          "features": {},
          "integrations": [],
          "clarifications_needed": [],
          "technical_constraints": {}
        }
        ```
        """
    
    # Stage 2: Elaboration
    elif "Elaborate Requirements" in prompt:
        content = """
        ```json
        {
          "project_name": "Test App",
          "project_type": "todo_app",
          "description": "A simple todo app",
          "ui_components": [
            {
              "name": "todo_list",
              "type": "interactive",
              "description": "List of todos",
              "html_structure": "<div><ul></ul></div>",
              "alpine_js_data": {"todos": []},
              "alpine_js_methods": ["add()"],
              "tailwind_classes": ["p-4"],
              "api_interactions": ["GET /api/todos"]
            }
          ],
          "page_layouts": [
            {
              "name": "Home",
              "route": "/",
              "template_file": "index.html",
              "layout_type": "single",
              "columns": {
                "main": {"components": ["todo_list"]}
              }
            }
          ],
          "api_endpoints": [
            {
              "method": "GET",
              "path": "/api/todos",
              "description": "Get todos",
              "response": {"items": []}
            }
          ],
          "data_models": [
            {
              "name": "Todo",
              "table_name": "todos",
              "fields": [{"name": "id", "type": "Integer"}],
              "relationships": []
            }
          ],
          "data_flows": [],
          "authentication": {},
          "authorization": {}
        }
        ```
        """
    
    # Stage 4: Code Generation
    elif "Generate" in prompt:
        if "Generate production-ready code for: **app/core/config.py**" in prompt:
            content = """
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Test App"
    DATABASE_URL: str = "sqlite:///./test.db"
    
settings = Settings()
"""
        elif "Generate production-ready code for: **app/main.py**" in prompt:
            content = """
from fastapi import FastAPI
from app.core.config import settings
from app.api.endpoints import todos

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(todos.router, prefix="/api/todos", tags=["todos"])

@app.get("/")
def read_root():
    return {"Hello": "World"}
"""
        elif "Generate production-ready code for: **app/models/todo.py**" in prompt:
            content = """
from sqlalchemy import Column, Integer, String
from app.db.base_class import Base

class Todo(Base):
    __tablename__ = "todos"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
"""
        elif "Generate production-ready code for: **app/api/endpoints/todos.py**" in prompt:
            content = """
from fastapi import APIRouter, Depends
from typing import List
from app.models.todo import Todo

router = APIRouter()

@router.get("/api/todos", response_model=List[dict])
def read_todos():
    return [{"id": 1, "title": "Test Todo"}]
"""
        elif "Generate production-ready code for: **app/templates/index.html**" in prompt:
            content = """
<!DOCTYPE html>
<html>
<head>
    <title>Test App</title>
    <script src="https://unpkg.com/alpinejs" defer></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body>
    <div x-data="{ todos: [] }" class="p-4">
        <!-- todo_list component -->
        <ul>
            <template x-for="todo in todos">
                <li x-text="todo.title"></li>
            </template>
        </ul>
    </div>
</body>
</html>
"""
        else:
            content = "# Generated code placeholder"
            
    else:
        content = "Unknown prompt"
        
    return MockLLMResponse(content=content)

def run_test():
    """Run the dry run test."""
    print("Starting dry run test...")
    
    # Clean up previous run
    if os.path.exists("generated_projects/Test App"):
        shutil.rmtree("generated_projects/Test App")
    
    # Mock LLM Client where it is used in intelligent_code_generator
    with patch('stages.intelligent_code_generator.LLMClient') as MockLLM:
        mock_instance = MockLLM.return_value
        mock_instance.generate.side_effect = mock_llm_generate
        
        # Initialize generator
        generator = IntelligentCodeGenerator()
        
        # Run generation
        result = generator.generate("Create a simple todo app", interactive=False)
        
        if result.success:
            print("\n✅ Test Passed!")
            print(f"Project generated at: {result.project_path}")
            
            # Verify file existence
            project_path = result.project_path
            expected_files = [
                "app/main.py",
                "app/core/config.py",
                "README.md",
                "requirements.txt"
            ]
            
            for f in expected_files:
                path = os.path.join(project_path, f)
                if os.path.exists(path):
                    print(f"  ✓ Found {f}")
                else:
                    print(f"  ❌ Missing {f}")
                    
        else:
            print(f"\n❌ Test Failed: {result.message}")
            if result.verification_report:
                print("Verification Report:")
                print(result.verification_report)

if __name__ == "__main__":
    run_test()
