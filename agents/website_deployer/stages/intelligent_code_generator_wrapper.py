#!/usr/bin/env python3
"""
Intelligent Code Generator Wrapper
===================================

Wrapper to make IntelligentCodeGenerator compatible with the 
legacy CodeGenerator interface expected by full_deployment_demo.py.

This translates between:
- Input: (requirements, architecture) from legacy pipeline
- Output: CodeGenerationResult expected by deployment orchestrator
"""

import logging
from typing import Dict, Any
from pathlib import Path
from dataclasses import dataclass
from .intelligent_code_generator import IntelligentCodeGenerator

logger = logging.getLogger(__name__)


@dataclass
class CodeGenerationResult:
    """Result compatible with legacy interface."""
    success: bool
    output_directory: Path = None
    files_generated: list = None
    generation_summary: Dict[str, Any] = None
    error_message: str = None


class IntelligentCodeGeneratorWrapper:
    """
    Wrapper around IntelligentCodeGenerator to match legacy interface.
    
    Accepts requirements and architecture from the legacy pipeline,
    extracts the specification, and runs the intelligent pipeline.
    """
    
    def __init__(self, output_base_dir: Path = Path("generated_projects"), response_cache_path: str = None):
        """Initialize wrapper with output directory and optional response cache."""
        self.output_base_dir = output_base_dir
        self.response_cache_path = response_cache_path
        
        # Load response cache if provided
        response_cache = None
        if response_cache_path:
            from stages.response_cache import ResponseCache
            if Path(response_cache_path).exists():
                response_cache = ResponseCache.load_from_file(response_cache_path)
                logger.info(f"Loaded response cache from {response_cache_path}")
            else:
                response_cache = ResponseCache(mode="record")
                logger.info(f"Created new response cache for recording to {response_cache_path}")
        
        self.generator = IntelligentCodeGenerator(response_cache=response_cache)
        self.response_cache = response_cache
        logger.info(f"IntelligentCodeGeneratorWrapper initialized (output: {output_base_dir})")
    
    def generate(
        self,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any]
    ) -> CodeGenerationResult:
        """
        Generate code using intelligent pipeline.
        
        Args:
            requirements: Requirements from Phase 2 (legacy)
            architecture: Architecture from Phase 3 (legacy)
        
        Returns:
            CodeGenerationResult compatible with deployment orchestrator
        """
        try:
            # Extract the original user specification
            # The requirements dict should contain the original spec
            user_prompt = requirements.get("original_specification") or requirements.get("description", "")
            
            if not user_prompt:
                # Fallback: reconstruct from requirements
                user_prompt = self._reconstruct_prompt(requirements)
            
            logger.info("Running Intelligent Code Generator...")
            logger.info(f"User prompt: {user_prompt[:200]}...")
            
            # Run intelligent generation (non-interactive for automation)
            result = self.generator.generate(user_prompt, interactive=False)
            
            # Save response cache if recording
            if self.response_cache and self.response_cache.mode == "record":
                self.response_cache.save_to_file(self.response_cache_path)
                logger.info(f"Saved response cache to {self.response_cache_path}")
            
            if not result.success:
                return CodeGenerationResult(
                    success=False,
                    error_message=result.message
                )
            
            # Convert to legacy format
            project_path = Path(result.project_path)
            
            # Create generation summary compatible with deployment
            summary = {
                "project_name": architecture.get("project_name", "app"),
                "output_directory": str(project_path),
                "files_generated": len(list(project_path.rglob("*"))),
                "components": {
                    "api_endpoints": len(architecture.get("api_endpoints", [])),
                    "database_tables": len(architecture.get("database_schema", {}).get("tables", [])),
                    "workers": 0,
                    "frontend_pages": 1,  # Intelligent generator creates frontend
                }
            }
            
            return CodeGenerationResult(
                success=True,
                output_directory=project_path,
                files_generated=list(project_path.rglob("*")),
                generation_summary=summary
            )
            
        except Exception as e:
            logger.error(f"Intelligent code generation failed: {e}", exc_info=True)
            return CodeGenerationResult(
                success=False,
                error_message=f"Code generation failed: {str(e)}"
            )
    
    def _reconstruct_prompt(self, requirements: Dict[str, Any]) -> str:
        """Reconstruct user prompt from requirements (fallback)."""
        parts = []
        
        if requirements.get("project_name"):
            parts.append(f"Create a {requirements['project_name']}")
        
        if requirements.get("description"):
            parts.append(requirements["description"])
        
        features = requirements.get("features", {})
        if features:
            parts.append("Features:")
            if features.get("authentication", {}).get("enabled"):
                parts.append("- User authentication")
            if features.get("llm_chat", {}).get("enabled"):
                parts.append("- LLM chat interface")
        
        return " ".join(parts) if parts else "Create a web application"
