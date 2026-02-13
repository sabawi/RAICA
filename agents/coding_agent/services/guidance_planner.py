"""
Guidance Planner - Phase 1 of the tool-calling debug architecture.

This module handles the first phase: asking the LLM to provide
a structured diagnosis plan in JSON format.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class DiagnosisStep:
    """A single step in the diagnosis plan."""
    step: int
    action: str
    target: Optional[str] = None
    pattern: Optional[str] = None
    scope: Optional[str] = None
    reason: Optional[str] = None
    # Extended fields for edit operations
    search_text: Optional[str] = None   # For edit_file: exact text to find
    replace_text: Optional[str] = None  # For edit_file: replacement text
    line_number: Optional[int] = None   # For replace_line/insert_line/get_line
    new_content: Optional[str] = None   # For replace_line/insert_line
    packages: Optional[List[str]] = None  # For pip_install: list of packages

    def to_dict(self) -> Dict:
        return {k: v for k, v in {
            "step": self.step,
            "action": self.action,
            "target": self.target,
            "pattern": self.pattern,
            "scope": self.scope,
            "reason": self.reason,
            "search_text": self.search_text,
            "replace_text": self.replace_text,
            "line_number": self.line_number,
            "new_content": self.new_content,
            "packages": self.packages
        }.items() if v is not None}


@dataclass
class DiagnosisPlan:
    """Complete diagnosis plan from the LLM."""
    steps: List[DiagnosisStep]
    raw_response: str
    
    def __len__(self):
        return len(self.steps)
    
    def __iter__(self):
        return iter(self.steps)


class GuidancePlanner:
    """
    Phase 1: Get structured diagnosis plan from LLM.
    
    Prompts the LLM to analyze an issue and return a JSON array
    of diagnosis steps. No free-form text, just structured data.
    
    Usage:
        planner = GuidancePlanner(llm_client)
        plan = await planner.get_diagnosis_plan(
            issue="requirements.txt is malformed",
            error_trace="pip install failed: invalid requirement",
            project_files=["config.py", "main.py", ...]
        )
        
        for step in plan:
            print(f"Step {step.step}: {step.action} - {step.reason}")
    """
    
    # Template for Phase Transition (Diagnosis -> Fix)
    PHASE_TRANSITION_PROMPT = """You are a Senior Technical Lead. Review the diagnosis information and decide if we have enough information to proceed to the FIX phase.

Diagnosis Context:
{context}

OBJECTIVE CRITERIA for proceeding to FIX (ALL must be true):
1. SPECIFIC FILE identified - we know which file(s) need to be modified
2. SPECIFIC LOCATION known - we have line number(s) or function name(s)
3. EXACT CHANGE defined - we know what code to add/remove/modify
4. NO AMBIGUITY - there's only one reasonable interpretation of the fix

CRITERIA for staying in DIAGNOSIS (ANY means stay):
1. Multiple possible root causes - need to narrow down
2. File identified but exact location unknown - need grep/search
3. Error message doesn't point to specific code - need more context
4. Dependencies or imports unclear - need dependency_check
5. File structure unknown - need analyze_project or get_project_tree

CHECKLIST - Can you answer YES to ALL of these?
- [ ] I know the exact file path to modify
- [ ] I know the exact line number or code block
- [ ] I know exactly what the new code should be
- [ ] I'm confident this fix will resolve the issue

DECISION (JSON only):
{{
  "can_proceed": true,
  "file_path": "path/to/file.ext",
  "line_number": 42,
  "fix_type": "replace_line|insert_after|delete_line|search_replace",
  "reason": "Clear explanation"
}}
NOTE: Use actual file extension from the project (.py, .js, .ts, .html, etc.)

OR if not ready:
{{
  "can_proceed": false,
  "reason": "What's still unclear",
  "missing_info": "Specific information needed",
  "suggested_action": "grep_search|read_file|dependency_check|etc"
}}

RESPOND WITH JSON ONLY:"""

    # Template for the diagnosis prompt
    # NOTE: Diagnosis phase is READ-ONLY. Mutations happen in the fix phase.
    PROMPT_TEMPLATE = """You are a debugging expert. Analyze this issue and create a DIAGNOSIS PLAN.
    
ISSUE: {issue}

ERROR TRACE:
{error_trace}

PROJECT FILES:
{file_list}

DIAGNOSIS TOOLS (READ-ONLY - for gathering information):
- read_file: Read contents of a file (target: file path)
- grep_search: Search for patterns in files (pattern: search term, scope: "*.ext" e.g., "*.py", "*.js", "*.ts")
- list_files: List files in a directory (target: directory path)
- validate_syntax: Check file syntax (target: file path) - works for Python, JS, JSON, etc.
- get_symbols: Extract functions/classes from file (target: file path)
- get_lines_range: Get lines around a specific line number (target: file path, line_number: N)
- search_with_context: Search with surrounding lines (target: file path, pattern: search term)
- find_file: Find files by name pattern (pattern: filename pattern)
- sanitize_requirements: Clean dependency files (requirements.txt, package.json)
- analyze_project: Analyze project structure and vital files (no parameters needed)
- dependency_check: Check for missing dependencies (no parameters needed)
- check_lint: Run linter on a file (target: file path)
- get_project_tree: Get hierarchical project view (no parameters needed)
- fetch_url: Fetch web page or documentation (url: full URL)
- fetch_manpage: Get Unix/Linux man page (command: command name, e.g., "grep")
- fetch_documentation: Fetch technical documentation (url: documentation URL)

IMPORTANT: This is the DIAGNOSIS phase. Do NOT include edit/fix operations.
Your job is to gather information to understand the bug, NOT to fix it.

COMMON DIAGNOSIS PATTERNS (adapt to project language):
1. Import/Module Error: dependency_check → read_file (requirements.txt/package.json) → grep_search (import/require statements)
2. Syntax Error: read_file → validate_syntax → get_lines_range (around error line)
3. Runtime Error: read_file (error file) → get_lines_range (error line) → search_with_context
4. Missing Function/Export: grep_search (function name) → get_symbols (found file) → read_file
5. Unknown Error: analyze_project → get_project_tree → read_file (main entry point)

INSTRUCTIONS:
1. Analyze the issue and error trace
2. Create a step-by-step plan to INVESTIGATE the bug
3. Each step should use one of the diagnosis tools above
4. Focus on reading files, searching for patterns, and validating syntax
5. Return ONLY a JSON array, no explanation text
6. Order steps logically - gather broad context first, then narrow down

RESPONSE FORMAT (JSON array only):
[
  {{"step": 1, "action": "read_file", "target": "path/to/file.ext", "reason": "Why this step"}},
  {{"step": 2, "action": "grep_search", "pattern": "search term", "scope": "*.ext", "reason": "Why this step"}},
  {{"step": 3, "action": "get_lines_range", "target": "main.ext", "line_number": 42, "reason": "Get context around error line"}}
]
NOTE: Use actual file extensions from the project (.py, .js, .ts, .html, .jsx, etc.)

RESPOND WITH JSON ONLY, NO TEXT BEFORE OR AFTER:"""

    def __init__(self, llm_client):
        """
        Initialize the planner.
        
        Args:
            llm_client: LLM client with generate() method
        """
        self.llm_client = llm_client
    
    async def get_diagnosis_plan(
        self,
        issue: str,
        error_trace: str = "",
        project_files: List[str] = None,
        max_steps: int = 10
    ) -> DiagnosisPlan:
        """
        Get a structured diagnosis plan from the LLM.
        
        Args:
            issue: Description of the bug/issue
            error_trace: Runtime error output if available
            project_files: List of files in the project
            max_steps: Maximum number of steps to return
            
        Returns:
            DiagnosisPlan with ordered diagnosis steps
        """
        # Build the prompt
        file_list = "\n".join(f"- {f}" for f in (project_files or [])[:30])
        if not file_list:
            file_list = "(No files listed)"
        
        prompt = self.PROMPT_TEMPLATE.format(
            issue=issue,
            error_trace=error_trace or "(No error trace available)",
            file_list=file_list
        )
        
        # Call LLM
        logger.info("Requesting diagnosis plan from LLM...")
        
        try:
            import inspect
            
            result = self.llm_client.generate(
                prompt=prompt,
                temperature=0.0  # Deterministic for JSON output
            )
            
            # If result is a coroutine, await it
            if inspect.iscoroutine(result):
                response = await result
            else:
                response = result
            
            raw_content = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return self._create_fallback_plan(issue, error_trace)
        
        # Parse the response
        steps = self._parse_plan(raw_content, max_steps)
        
        if not steps:
            logger.warning("Failed to parse plan, using fallback")
            return self._create_fallback_plan(issue, error_trace)
        
        return DiagnosisPlan(steps=steps, raw_response=raw_content)
    
    def _parse_plan(self, response: str, max_steps: int) -> List[DiagnosisStep]:
        """Parse JSON response into DiagnosisStep objects."""
        # Extract JSON from response
        json_str = self._extract_json(response)
        if not json_str:
            logger.warning("No JSON found in response")
            return []
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return []
        
        if not isinstance(data, list):
            logger.warning(f"Expected list, got {type(data)}")
            return []
        
        steps = []
        for i, item in enumerate(data[:max_steps]):
            if not isinstance(item, dict):
                continue

            # Parse line_number - handle various formats
            line_num = item.get("line_number") or item.get("line") or item.get("lineno")
            if line_num is not None:
                try:
                    line_num = int(line_num)
                except (ValueError, TypeError):
                    line_num = None

            # Parse packages - handle string or list
            packages = item.get("packages")
            if isinstance(packages, str):
                packages = [p.strip() for p in packages.split(",") if p.strip()]
            elif not isinstance(packages, list):
                packages = None

            step = DiagnosisStep(
                step=item.get("step", i + 1),
                action=item.get("action", "unknown"),
                target=item.get("target") or item.get("path") or item.get("file"),
                pattern=item.get("pattern") or item.get("search"),
                scope=item.get("scope"),
                reason=item.get("reason"),
                # Extended fields
                search_text=item.get("search_text") or item.get("search") or item.get("old_text"),
                replace_text=item.get("replace_text") or item.get("replace") or item.get("new_text"),
                line_number=line_num,
                new_content=item.get("new_content") or item.get("content") or item.get("new_line"),
                packages=packages
            )
            steps.append(step)

        return steps
    
    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON (array or object) from mixed text."""
        import re
        
        text = text.strip()
        
        # Try markdown code block
        code_block = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if code_block:
            return code_block.group(1).strip()
        
        # Find start of JSON
        start_array = text.find('[')
        start_object = text.find('{')
        
        if start_array == -1 and start_object == -1:
            return None
            
        # Determine strict start
        if start_array != -1 and (start_object == -1 or start_array < start_object):
            start = start_array
            open_char, close_char = '[', ']'
        else:
            start = start_object
            open_char, close_char = '{', '}'
        
        # Find matching closing brace
        depth = 0
        in_string = False
        escape = False
        
        for i, char in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
        
        return None
    
    def _create_fallback_plan(self, issue: str, error_trace: str = "") -> DiagnosisPlan:
        """
        ARCHITECTURE: Fail explicitly when LLM fails.

        Per RAICA's LLM-driven architecture, we do NOT use keyword matching
        or hardcoded logic. If LLM cannot provide a diagnosis plan, we fail
        with a minimal generic exploration plan that lets the LLM retry
        with more context.

        This returns a minimal plan that gathers basic context for a retry,
        NOT keyword-based diagnosis logic.
        """
        logger.warning("LLM failed to generate diagnosis plan - using minimal exploration fallback")

        # MINIMAL exploration plan - just gather basic project info
        # No keyword matching, no case-specific logic
        # LLM will get this context and can retry with better understanding
        steps = [
            DiagnosisStep(
                step=1,
                action="analyze_project",
                reason="Gather project structure and vital files for LLM context"
            ),
            DiagnosisStep(
                step=2,
                action="get_project_tree",
                reason="Get hierarchical view of project files"
            ),
            DiagnosisStep(
                step=3,
                action="dependency_check",
                reason="Check for missing dependencies"
            )
        ]

        return DiagnosisPlan(
            steps=steps,
            raw_response="(minimal exploration fallback - LLM diagnosis failed)"
        )

    async def validate_phase_transition(self, context_summary: str) -> Dict[str, Any]:
        """
        Decide if we can proceed from Diagnosis to Fix phase.
        
        Args:
            context_summary: Summary of diagnosis results
            
        Returns:
            Dict with 'can_proceed', 'reason', and 'missing_info'
        """
        try:
            prompt = self.PHASE_TRANSITION_PROMPT.format(context=context_summary)
            
            import inspect
            result = self.llm_client.generate(prompt=prompt, temperature=0.0)
            
            if inspect.iscoroutine(result):
                response = await result
            else:
                response = result
                
            raw_content = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON
            json_str = self._extract_json(raw_content)
            if json_str:
                return json.loads(json_str)
            else:
                logger.warning("Failed to parse phase transition response")
                return {"can_proceed": False, "reason": "Failed to parse LLM response"}
                
        except Exception as e:
            logger.error(f"Phase transition validation failed: {e}")
            return {"can_proceed": False, "reason": f"Error: {e}"}
