"""
Request Interpreter Module
==========================

Centralized user request interpretation with validation and iterative refinement.

Features:
- LLM-driven intent analysis and TO-DO list generation
- User feedback loop for validation
- Iterative refinement until user confirms understanding
- Confidence scoring and risk assessment

Usage:
    interpreter = RequestInterpreter(llm_client, feedback_handler)
    result = await interpreter.interpret_with_feedback(
        user_request="Create a web scraper",
        project_context={...}
    )
    # Result includes validated interpretation with user confirmation

Author: RAICA Development Team
Version: 1.0.0
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class UserFeedback:
    """Captures user's validation of interpretation."""

    is_accurate: bool = False
    confidence: int = 0  # 1-5 scale
    missing_items: List[str] = field(default_factory=list)
    incorrect_items: List[str] = field(default_factory=list)
    additional_requirements: List[str] = field(default_factory=list)
    priority_override: Optional[str] = None
    clarifications: str = ""
    iteration: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_accurate': self.is_accurate,
            'confidence': self.confidence,
            'missing_items': self.missing_items,
            'incorrect_items': self.incorrect_items,
            'additional_requirements': self.additional_requirements,
            'priority_override': self.priority_override,
            'clarifications': self.clarifications,
            'iteration': self.iteration,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class TodoItem:
    """A single TODO item in the interpretation."""

    step_number: int
    task: str
    tool_suggestions: List[str] = field(default_factory=list)
    depends_on: List[int] = field(default_factory=list)
    verification_criteria: str = ""
    estimated_effort: str = "medium"  # low, medium, high
    priority: str = "medium"  # low, medium, high, critical

    def to_dict(self) -> Dict[str, Any]:
        return {
            'step_number': self.step_number,
            'task': self.task,
            'tool_suggestions': self.tool_suggestions,
            'depends_on': self.depends_on,
            'verification_criteria': self.verification_criteria,
            'estimated_effort': self.estimated_effort,
            'priority': self.priority
        }


@dataclass
class ContextMatch:
    """Analysis of how well the request matches current project context."""

    matches_current_project: bool = False
    target_files_exist: List[str] = field(default_factory=list)
    target_files_missing: List[str] = field(default_factory=list)
    ambiguous_terms: List[str] = field(default_factory=list)
    similar_projects_detected: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'matches_current_project': self.matches_current_project,
            'target_files_exist': self.target_files_exist,
            'target_files_missing': self.target_files_missing,
            'ambiguous_terms': self.ambiguous_terms,
            'similar_projects_detected': self.similar_projects_detected
        }


@dataclass
class ClarificationNeeded:
    """Information about what needs clarification from user."""

    needs_confirmation: bool = False
    questions: List[str] = field(default_factory=list)
    warning_message: str = ""
    suggested_action: str = ""  # "proceed", "ask_user", "change_project"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'needs_confirmation': self.needs_confirmation,
            'questions': self.questions,
            'warning_message': self.warning_message,
            'suggested_action': self.suggested_action
        }


@dataclass
class InterpretationResult:
    """Complete interpretation result."""

    # Core interpretation
    primary_intent: str = ""
    request_type: str = ""  # CODE_DEBUG, CODE_GENERATION, SYSTEM_TASK, etc.
    confidence: float = 0.0  # 0.0-1.0
    complexity: str = "medium"  # simple, medium, complex

    # Project classification (NEW - Critical for safety)
    project_classification: str = ""  # NEW_PROJECT, EXISTING_MODIFICATION, EXTERNAL_REFERENCE, AMBIGUOUS
    context_match: ContextMatch = field(default_factory=ContextMatch)
    clarification_needed: ClarificationNeeded = field(default_factory=ClarificationNeeded)

    # Detailed breakdown
    todo_list: List[TodoItem] = field(default_factory=list)
    context_needs: List[str] = field(default_factory=list)

    # Risk assessment
    potential_issues: List[str] = field(default_factory=list)
    mitigation_strategies: List[str] = field(default_factory=list)

    # User validation
    user_confirmed: bool = False
    user_confidence: int = 0
    feedback_history: List[UserFeedback] = field(default_factory=list)

    # Metadata
    raw_llm_response: str = ""
    iteration_count: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'primary_intent': self.primary_intent,
            'request_type': self.request_type,
            'confidence': self.confidence,
            'complexity': self.complexity,
            'project_classification': self.project_classification,
            'context_match': self.context_match.to_dict(),
            'clarification_needed': self.clarification_needed.to_dict(),
            'todo_list': [item.to_dict() for item in self.todo_list],
            'context_needs': self.context_needs,
            'potential_issues': self.potential_issues,
            'mitigation_strategies': self.mitigation_strategies,
            'user_confirmed': self.user_confirmed,
            'user_confidence': self.user_confidence,
            'feedback_history': [f.to_dict() for f in self.feedback_history],
            'iteration_count': self.iteration_count,
            'timestamp': self.timestamp.isoformat()
        }

    def get_summary(self) -> str:
        """Get a concise summary for display."""
        lines = [
            f"🎯 Intent: {self.primary_intent[:60]}{'...' if len(self.primary_intent) > 60 else ''}",
            f"📊 Confidence: {self.confidence:.0%}",
            f"📋 Tasks: {len(self.todo_list)} items",
            f"✅ User Confirmed: {'Yes' if self.user_confirmed else 'No'}"
        ]
        return "\n".join(lines)


class MaxIterationsExceeded(Exception):
    """Raised when max interpretation iterations reached without user confirmation."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════

# System prompt for initial request interpretation
# This prompt instructs the LLM to analyze user requests and produce structured JSON output
REQUEST_INTERPRETER_PROMPT = """You are a Request Interpreter. Your job is to analyze user requests and convert them into structured, actionable TO-DO lists.

## YOUR TASK
1. **Intent Analysis**: What does the user want to achieve?
2. **Project Classification** (CRITICAL): Determine if this is NEW project or EXISTING modification
3. **Context Matching**: Check if targets exist in current project
4. **Requirement Extraction**: What are the explicit and implicit requirements?
5. **Constraint Identification**: What limitations or constraints exist?
6. **Dependency Mapping**: What must be done before other steps?
7. **Tool Mapping**: Which tools should be used for each step?

## INPUT
User Request: {user_request}
Current Project Directory: {project_dir}
Project Context: {project_context}
Existing Files in Project: {existing_files}
Available Tools: {available_tools}

## ⚠️ PROJECT CLASSIFICATION RULES (CRITICAL - FOLLOW EXACTLY)

Before interpreting, classify the request:

**1. NEW_PROJECT**: Use when:
   - User explicitly says "create a NEW project", "build from scratch", "start fresh"
   - No mention of existing code or specific files in current project
   - Request implies independent deliverable

**2. EXISTING_MODIFICATION**: Use when:
   - User mentions files/tools that EXIST in current project
   - Request is "fix", "add", "improve", "change", "update"
   - User references existing functionality

**3. EXTERNAL_REFERENCE**: Use when:
   - User mentions files/tools NOT in current project
   - Request targets something outside current directory
   - User refers to "the other project", "my other app"

**4. AMBIGUOUS**: Use when:
   - Cannot determine target from context
   - Request could apply to multiple projects
   - Missing critical context

**Context Matching:**
- List ALL files mentioned in request that exist in current project
- List ALL files mentioned that are MISSING
- Flag any AMBIGUOUS terms (e.g., "the database" when multiple exist)

## OUTPUT FORMAT
Return ONLY valid JSON in this exact structure:

```json
{
  "interpretation": {
    "primary_intent": "clear, concise description of main goal",
    "request_type": "CODE_DEBUG|CODE_GENERATION|SYSTEM_TASK|SYSTEM_QUERY|WEB_SEARCH|HYBRID|CONVERSATION",
    "project_classification": "NEW_PROJECT|EXISTING_MODIFICATION|EXTERNAL_REFERENCE|AMBIGUOUS",
    "confidence": 0.95,
    "complexity": "simple|medium|complex",
    "context_match": {
      "matches_current_project": true|false,
      "target_files_exist": ["file1.py", "file2.js"],
      "target_files_missing": ["file3.py"],
      "ambiguous_terms": ["the database", "the API"],
      "similar_projects_detected": []
    }
  },
  "clarification_needed": {
    "needs_confirmation": false,
    "questions": ["Is this about the current project?", "Which file specifically?"],
    "warning_message": "",
    "suggested_action": "proceed|ask_user|change_project"
  },
  "todo_list": [
    {
      "step_number": 1,
      "task": "clear, actionable description",
      "tool_suggestions": ["tool_name_1", "tool_name_2"],
      "depends_on": [],
      "verification_criteria": "how to know this is done",
      "estimated_effort": "low|medium|high",
      "priority": "low|medium|high|critical"
    }
  ],
  "context_needs": [
    "what files need to be read",
    "what info needs to be gathered"
  ],
  "risk_assessment": {
    "potential_issues": ["list of possible problems"],
    "mitigation_strategies": ["how to avoid issues"]
  },
  "reasoning": "step-by-step thinking about how you interpreted this request"
}
```

## RULES
- Break down every request into at least 3 concrete steps
- Each step must be actionable and specific
- Include verification criteria for each step
- Consider edge cases and failure modes
- If the request is ambiguous, note what clarification would help
- For code requests, identify the language/framework
- For debug requests, identify what needs investigation

## REASONING REQUIREMENT
Before providing your final JSON, think step-by-step:
1. What is the user really asking for?
2. What are the hidden requirements?
3. What could go wrong?
4. How should this be broken down?

Put your reasoning in the "reasoning" field.

Respond with JSON only, no text before or after.
"""

# Prompt template for refining interpretation based on user feedback
# Used when user indicates the initial interpretation needs corrections
ITERATION_PROMPT_TEMPLATE = """You are refining an interpretation based on user feedback.

## ORIGINAL REQUEST
{original_request}

## YOUR PREVIOUS INTERPRETATION
{previous_interpretation}

## USER FEEDBACK
- Accurate: {is_accurate}
- Confidence: {confidence}/5
- Missing Items: {missing_items}
- Incorrect Items: {incorrect_items}
- Additional Requirements: {additional_requirements}
- Clarifications: {clarifications}

## YOUR TASK
Revise your interpretation based on the feedback:
1. Keep what was correct
2. Fix what was wrong (incorrect_items)
3. Add what was missing (missing_items)
4. Include new requirements (additional_requirements)
5. Apply clarifications to improve understanding

## OUTPUT
Return updated JSON in the same format as before, with a revised:
- primary_intent (if needed)
- todo_list (updated based on feedback)
- context_needs (updated)
- risk_assessment (updated if needed)
- reasoning (explain what you changed and why)

Respond with JSON only.
"""


# ═══════════════════════════════════════════════════════════════════════════
# USER FEEDBACK HANDLER
# ═══════════════════════════════════════════════════════════════════════════

class UserFeedbackHandler:
    """Handles presentation and capture of user feedback."""

    def __init__(self, ui_callback: Optional[Callable[[str], str]] = None):
        """
        Initialize the feedback handler.

        Args:
            ui_callback: Function to send message to user and get response.
                        Signature: (prompt: str) -> str (user response)
                        If None, uses CLI mode.
        """
        self.ui_callback = ui_callback or self._cli_callback
        self.max_iterations = self._get_default_max_iterations()

    def _cli_callback(self, prompt: str) -> str:
        """Fallback CLI callback for non-interactive mode."""
        print(f"\n{prompt}")
        return input("> ")

    def _get_default_max_iterations(self) -> int:
        """Get default max iterations from config or fallback to 10."""
        try:
            from ..config_accessor import get_max_iterations
            return get_max_iterations()
        except ImportError:
            # Fallback when imported directly (not as part of package)
            return 10

    def present_interpretation(self, interpretation: InterpretationResult) -> str:
        """
        Format interpretation for user review.

        Returns formatted string suitable for display.
        """
        lines = [
            "",
            "═" * 70,
            "📋 INTERPRETATION OF YOUR REQUEST",
            "═" * 70,
            "",
            f"🎯 INTENT: {interpretation.primary_intent}",
            "",
            f"Request Type: {interpretation.request_type}",
            f"Complexity: {interpretation.complexity.upper()}",
            f"Confidence: {interpretation.confidence:.0%}",
            "",
            "📋 TO-DO LIST:",
        ]

        for item in interpretation.todo_list:
            priority_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🟢"
            }.get(item.priority, "⚪")

            effort_emoji = {
                "high": "🏋️",
                "medium": "⚡",
                "low": "🍃"
            }.get(item.estimated_effort, "⚡")

            lines.append(f"  {priority_emoji} Step {item.step_number}: {item.task}")
            lines.append(f"     Effort: {effort_emoji} {item.estimated_effort}")

            if item.tool_suggestions:
                lines.append(f"     Tools: {', '.join(item.tool_suggestions)}")

            if item.depends_on:
                deps = ', '.join(f"Step {d}" for d in item.depends_on)
                lines.append(f"     Depends on: {deps}")

            if item.verification_criteria:
                lines.append(f"     ✓ Verify: {item.verification_criteria}")

            lines.append("")

        if interpretation.context_needs:
            lines.extend([
                "📁 CONTEXT NEEDED:",
                *[f"  • {need}" for need in interpretation.context_needs],
                ""
            ])

        if interpretation.potential_issues:
            lines.extend([
                "⚠️  POTENTIAL ISSUES:",
                *[f"  • {issue}" for issue in interpretation.potential_issues],
                ""
            ])

            if interpretation.mitigation_strategies:
                lines.extend([
                    "🛡️  MITIGATION STRATEGIES:",
                    *[f"  • {strategy}" for strategy in interpretation.mitigation_strategies],
                    ""
                ])

        lines.extend([
            "═" * 70,
            "Is this interpretation accurate? (yes/no/partly)",
            "═" * 70,
            ""
        ])

        return "\n".join(lines)

    def capture_feedback(self, interpretation: InterpretationResult) -> UserFeedback:
        """
        Interactive questionnaire to capture user feedback.

        Returns UserFeedback object with user's responses.
        """
        feedback = UserFeedback()

        # Question 1: Overall accuracy
        response = self.ui_callback(
            self.present_interpretation(interpretation)
        ).lower().strip()

        if response in ('yes', 'y', 'correct', 'accurate', 'right'):
            feedback.is_accurate = True

            # Get confidence level
            confidence_str = self.ui_callback(
                "How confident are you in this interpretation? (1-5, where 5 is exactly right)"
            ).strip()

            try:
                feedback.confidence = max(1, min(5, int(confidence_str)))
            except ValueError:
                feedback.confidence = 4  # Default to high confidence if they said yes

        elif response in ('no', 'n', 'wrong', 'incorrect'):
            feedback.is_accurate = False
            feedback.confidence = 1

        elif response in ('partly', 'partial', 'partially', 'somewhat', 'kind of', 'kinda'):
            feedback.is_accurate = False
            feedback.confidence = 2

        else:
            # Treat unclear response as needing refinement
            feedback.is_accurate = False
            feedback.confidence = 2
            feedback.clarifications = f"Unclear response: '{response}'"

        # If not fully accurate, ask for specifics
        if not feedback.is_accurate or feedback.confidence < 4:
            # Question 2: What's missing?
            missing = self.ui_callback(
                "What's missing from this interpretation? (comma-separated list, or 'nothing')"
            ).strip()

            if missing and missing.lower() not in ('nothing', 'none', 'n/a', ''):
                feedback.missing_items = [item.strip() for item in missing.split(',') if item.strip()]

            # Question 3: What's incorrect?
            incorrect = self.ui_callback(
                "What's incorrect or misunderstood? (comma-separated list, or 'nothing')"
            ).strip()

            if incorrect and incorrect.lower() not in ('nothing', 'none', 'n/a', ''):
                feedback.incorrect_items = [item.strip() for item in incorrect.split(',') if item.strip()]

            # Question 4: Additional requirements
            additional = self.ui_callback(
                "Any additional requirements not captured? (comma-separated, or 'none')"
            ).strip()

            if additional and additional.lower() not in ('none', 'n/a', 'nothing', ''):
                feedback.additional_requirements = [item.strip() for item in additional.split(',') if item.strip()]

        # Question 5: Priority override
        priority = self.ui_callback(
            "Priority level? (high/medium/low, or press Enter to keep as interpreted)"
        ).lower().strip()

        if priority in ('high', 'medium', 'low'):
            feedback.priority_override = priority

        # Question 6: Free-form clarifications
        clarification = self.ui_callback(
            "Any other clarifications? (or press Enter if none)"
        ).strip()

        if clarification:
            feedback.clarifications = clarification

        return feedback

    def should_iterate(self, feedback: UserFeedback, iteration: int) -> bool:
        """
        Determine if we need another iteration.

        Returns True if refinement is needed, False if we should proceed.
        """
        # Check iteration limit
        if iteration >= self.max_iterations:
            logger.warning(f"Max iterations ({self.max_iterations}) reached")
            return False

        # If there are missing items or incorrect items, we MUST iterate
        if feedback.missing_items or feedback.incorrect_items:
            return True

        # If user said it's not accurate, we need to iterate
        if not feedback.is_accurate:
            return True

        # If confidence is low (even if they said accurate), iterate
        if feedback.confidence < 4:
            return True

        # User confirmed with high confidence and no issues - we're done
        return False

    def build_iteration_prompt(self, original_request: str,
                               current_interpretation: InterpretationResult,
                               feedback: UserFeedback) -> str:
        """
        Build prompt for LLM to revise interpretation based on feedback.
        """
        # Format previous interpretation for the prompt
        prev_json = json.dumps({
            'primary_intent': current_interpretation.primary_intent,
            'request_type': current_interpretation.request_type,
            'todo_list': [item.to_dict() for item in current_interpretation.todo_list],
            'potential_issues': current_interpretation.potential_issues,
            'mitigation_strategies': current_interpretation.mitigation_strategies
        }, indent=2)

        # Format feedback items
        def format_list(items: List[str]) -> str:
            if not items:
                return "None"
            return "\n  - " + "\n  - ".join(items)

        return ITERATION_PROMPT_TEMPLATE.format(
            original_request=original_request,
            previous_interpretation=prev_json,
            is_accurate=feedback.is_accurate,
            confidence=feedback.confidence,
            missing_items=format_list(feedback.missing_items),
            incorrect_items=format_list(feedback.incorrect_items),
            additional_requirements=format_list(feedback.additional_requirements),
            clarifications=feedback.clarifications or "None provided"
        )


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST INTERPRETER
# ═══════════════════════════════════════════════════════════════════════════

class RequestInterpreter:
    """
    Main interpreter that converts user requests to structured plans.

    Features user feedback loop for validation.
    """

    # Default available tools list
    DEFAULT_TOOLS = [
        "read_file", "write_file", "edit_file",
        "grep_search", "list_files", "find_file",
        "run_command", "pip_install", "validate_syntax",
        "run_python", "get_symbols", "sanitize_requirements",
        "get_line", "get_lines_range", "replace_line", "insert_line",
        "search_with_context", "copy_file", "move_file", "delete_file"
    ]

    def __init__(self, llm_client,
                 feedback_handler: Optional[UserFeedbackHandler] = None,
                 output_callback: Optional[Callable[[str], None]] = None):
        """
        Initialize the request interpreter.

        Args:
            llm_client: LLM client with generate() method
            feedback_handler: Handler for user feedback (creates default if None)
            output_callback: Optional callback for status messages
        """
        self.llm_client = llm_client
        self.feedback_handler = feedback_handler or UserFeedbackHandler()
        self.output = output_callback or (lambda x: logger.info(x))

    def _parse_interpretation(self, llm_response: str) -> Optional[InterpretationResult]:
        """Parse LLM response into InterpretationResult."""
        try:
            # Extract JSON from response
            text = llm_response.strip()

            # Try to find JSON block
            if "```json" in text:
                start = text.find("```json") + 7
                end = text.find("```", start)
                if end > start:
                    text = text[start:end].strip()
            elif "```" in text:
                start = text.find("```") + 3
                end = text.find("```", start)
                if end > start:
                    text = text[start:end].strip()

            # Find JSON object
            start_idx = text.find('{')
            if start_idx == -1:
                logger.error("No JSON object found in response")
                return None

            # Find matching closing brace
            brace_count = 0
            in_string = False
            escape = False
            end_idx = start_idx

            for i, char in enumerate(text[start_idx:], start_idx):
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
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break

            json_str = text[start_idx:end_idx]
            data = json.loads(json_str)

            # Parse interpretation section
            interp = data.get('interpretation', {})

            # Parse todo list
            todo_items = []
            for item_data in data.get('todo_list', []):
                todo_items.append(TodoItem(
                    step_number=item_data.get('step_number', len(todo_items) + 1),
                    task=item_data.get('task', ''),
                    tool_suggestions=item_data.get('tool_suggestions', []),
                    depends_on=item_data.get('depends_on', []),
                    verification_criteria=item_data.get('verification_criteria', ''),
                    estimated_effort=item_data.get('estimated_effort', 'medium'),
                    priority=item_data.get('priority', 'medium')
                ))

            # Parse risk assessment
            risk = data.get('risk_assessment', {})

            # Parse project classification (NEW)
            context_match_data = interp.get('context_match', {})
            context_match = ContextMatch(
                matches_current_project=context_match_data.get('matches_current_project', False),
                target_files_exist=context_match_data.get('target_files_exist', []),
                target_files_missing=context_match_data.get('target_files_missing', []),
                ambiguous_terms=context_match_data.get('ambiguous_terms', []),
                similar_projects_detected=context_match_data.get('similar_projects_detected', [])
            )

            clarification_data = data.get('clarification_needed', {})
            clarification = ClarificationNeeded(
                needs_confirmation=clarification_data.get('needs_confirmation', False),
                questions=clarification_data.get('questions', []),
                warning_message=clarification_data.get('warning_message', ''),
                suggested_action=clarification_data.get('suggested_action', 'proceed')
            )

            return InterpretationResult(
                primary_intent=interp.get('primary_intent', ''),
                request_type=interp.get('request_type', ''),
                confidence=interp.get('confidence', 0.0),
                complexity=interp.get('complexity', 'medium'),
                project_classification=interp.get('project_classification', 'AMBIGUOUS'),
                context_match=context_match,
                clarification_needed=clarification,
                todo_list=todo_items,
                context_needs=data.get('context_needs', []),
                potential_issues=risk.get('potential_issues', []),
                mitigation_strategies=risk.get('mitigation_strategies', []),
                raw_llm_response=llm_response
            )

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing interpretation: {e}")
            return None

    async def interpret_request(self, user_request: str,
                                project_context: Dict[str, Any],
                                is_revision: bool = False) -> Optional[InterpretationResult]:
        """
        Get interpretation from LLM.

        Args:
            user_request: Original user request text
            project_context: Project structure and available files
            is_revision: True if this is a revision based on feedback

        Returns:
            InterpretationResult or None if failed
        """
        # Build prompt using safe replacement (not .format() which interprets all braces)
        prompt = REQUEST_INTERPRETER_PROMPT
        prompt = prompt.replace("{user_request}", user_request)
        prompt = prompt.replace("{project_context}", json.dumps(project_context, indent=2))
        prompt = prompt.replace("{available_tools}", ", ".join(self.DEFAULT_TOOLS))

        # Call LLM
        self.output("🤖 Asking LLM to interpret request...")

        try:
            import inspect

            result = self.llm_client.generate(
                prompt=prompt,
                temperature=0.3,  # Slightly creative but mostly deterministic
                max_tokens=4000
            )

            # Handle async
            if inspect.iscoroutine(result):
                response = await result
            else:
                response = result

            content = response.content if hasattr(response, 'content') else str(response)

            # Parse response
            interpretation = self._parse_interpretation(content)

            if interpretation:
                self.output(f"✓ Got interpretation: {interpretation.primary_intent[:50]}...")
                return interpretation
            else:
                self.output("✗ Failed to parse interpretation")
                return None

        except Exception as e:
            logger.error(f"LLM interpretation failed: {e}")
            self.output(f"✗ Interpretation failed: {e}")
            return None

    async def interpret_with_feedback(self,
                                      user_request: str,
                                      project_context: Dict[str, Any],
                                      max_iterations: int = 3) -> Optional[InterpretationResult]:
        """
        Main method: Interpret request with user feedback loop.

        Args:
            user_request: Original user request
            project_context: Project context dict
            max_iterations: Maximum refinement iterations

        Returns:
            Validated InterpretationResult or None if failed

        Raises:
            MaxIterationsExceeded: If user doesn't confirm after max tries
        """
        iteration = 0
        interpretation = None
        last_feedback = None

        self.output("\n" + "═" * 70)
        self.output("🎯 REQUEST INTERPRETATION WITH FEEDBACK")
        self.output("═" * 70)

        while iteration < max_iterations:
            iteration += 1
            self.output(f"\n[Iteration {iteration}/{max_iterations}]")

            # Step 1: Get interpretation from LLM
            if iteration == 1:
                interpretation = await self.interpret_request(
                    user_request, project_context
                )
            else:
                # Revise based on feedback
                iteration_prompt = self.feedback_handler.build_iteration_prompt(
                    user_request, interpretation, last_feedback
                )

                self.output("🔄 Refining interpretation based on feedback...")

                interpretation = await self.interpret_request(
                    iteration_prompt, project_context, is_revision=True
                )

            if not interpretation:
                self.output("✗ Failed to get interpretation")
                return None

            # Step 2: Present to user and get feedback
            feedback = self.feedback_handler.capture_feedback(interpretation)
            feedback.iteration = iteration
            interpretation.feedback_history.append(feedback)

            # Step 3: Check if user confirmed
            if not self.feedback_handler.should_iterate(feedback, iteration):
                # User confirmed - mark and return
                interpretation.user_confirmed = True
                interpretation.user_confidence = feedback.confidence
                interpretation.iteration_count = iteration

                self.output("\n" + "═" * 70)
                self.output("✅ INTERPRETATION CONFIRMED BY USER")
                self.output(f"   Confidence: {feedback.confidence}/5")
                self.output(f"   Iterations: {iteration}")
                self.output("═" * 70)

                return interpretation

            # Need to iterate - save feedback for next round
            last_feedback = feedback
            self.output(f"\n⚠️  User requested refinements (confidence: {feedback.confidence}/5)")

            if feedback.missing_items:
                self.output(f"   Missing: {', '.join(feedback.missing_items)}")
            if feedback.incorrect_items:
                self.output(f"   Incorrect: {', '.join(feedback.incorrect_items)}")

        # Max iterations reached
        self.output("\n" + "═" * 70)
        self.output(f"⚠️  MAX ITERATIONS ({max_iterations}) REACHED")
        self.output("   Proceeding with best interpretation")
        self.output("═" * 70)

        interpretation.iteration_count = iteration
        raise MaxIterationsExceeded(
            f"User did not confirm interpretation after {max_iterations} attempts"
        )

    def validate_interpretation(self, interpretation: InterpretationResult) -> Tuple[bool, List[str]]:
        """
        Validate interpretation quality.

        Returns:
            Tuple of (is_valid: bool, issues: List[str])
        """
        issues = []

        # Check for empty fields
        if not interpretation.primary_intent:
            issues.append("Missing primary_intent")

        if not interpretation.todo_list:
            issues.append("Empty todo_list")

        # Check confidence level
        if interpretation.confidence < 0.5:
            issues.append(f"Low confidence: {interpretation.confidence:.0%}")

        # Check for minimum steps
        if len(interpretation.todo_list) < 2:
            issues.append(f"Too few steps: {len(interpretation.todo_list)}")

        # Check for step numbering
        step_numbers = [item.step_number for item in interpretation.todo_list]
        if len(step_numbers) != len(set(step_numbers)):
            issues.append("Duplicate step numbers")

        # Check for reasonable task descriptions
        for item in interpretation.todo_list:
            if len(item.task) < 10:
                issues.append(f"Step {item.step_number}: Task description too short")

        return len(issues) == 0, issues
