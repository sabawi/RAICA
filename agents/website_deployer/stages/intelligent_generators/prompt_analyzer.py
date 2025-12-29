#!/usr/bin/env python3
"""
Prompt Analyzer - Stage 1 of Intelligent Code Generation
==========================================================

Dissects user prompts into structured requirements and identifies ambiguities.

This stage:
1. Parses user prompt into semantic units
2. Identifies UI components, features, data flows
3. Detects ambiguities and missing details
4. Generates clarifying questions
5. Expands shorthand into explicit requirements
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class ClarificationQuestion:
    """A question to clarify ambiguous requirements."""
    question: str
    options: List[str]
    context: str
    importance: str = "medium"  # low, medium, high, critical
    answered: bool = False
    answer: Optional[str] = None


@dataclass
class ComponentSpec:
    """Specification for a UI or backend component."""
    name: str
    type: str  # "ui", "api", "database", "worker"
    description: str
    requirements: List[str]
    ambiguities: List[str] = field(default_factory=list)
    missing_details: List[str] = field(default_factory=list)


@dataclass
class PromptAnalysis:
    """Result of prompt analysis."""
    project_name: str
    project_type: str
    description: str
    components: List[ComponentSpec]
    features: Dict[str, Any]
    integrations: List[Dict[str, str]]
    clarifications_needed: List[ClarificationQuestion]
    technical_constraints: Dict[str, Any]
    raw_prompt: str

    def has_clarifications(self) -> bool:
        """Check if clarifications are needed."""
        return len(self.clarifications_needed) > 0

    def get_unanswered_questions(self) -> List[ClarificationQuestion]:
        """Get questions that haven't been answered."""
        return [q for q in self.clarifications_needed if not q.answered]


class PromptAnalyzer:
    """
    Analyzes user prompts and extracts structured requirements.

    Uses LLM to intelligently parse prompts, identify components,
    detect ambiguities, and generate clarifying questions.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        Initialize prompt analyzer.

        Args:
            llm_client: LLM client for analysis (creates new if not provided)
        """
        self.llm = llm_client or LLMClient()
        logger.info("PromptAnalyzer initialized")

    def analyze(self, user_prompt: str) -> PromptAnalysis:
        """
        Analyze user prompt and extract structured requirements.

        Args:
            user_prompt: Raw user description of desired application

        Returns:
            PromptAnalysis with structured requirements and clarifications
        """
        logger.info("=" * 60)
        logger.info("PROMPT ANALYSIS STARTED")
        logger.info("=" * 60)

        # Build analysis prompt
        analysis_prompt = self._build_analysis_prompt(user_prompt)

        # Call LLM for analysis
        logger.info("Calling LLM for analysis...")
        response_obj = self.llm.generate(analysis_prompt)
        response = response_obj.content if hasattr(response_obj, 'content') else str(response_obj)

        # Parse response
        try:
            analysis_data = self._parse_analysis_response(response)
            logger.info("✅ Successfully parsed analysis response")
        except Exception as e:
            logger.error(f"❌ Failed to parse analysis: {e}")
            # Return minimal analysis on failure
            return self._create_fallback_analysis(user_prompt)

        # Create PromptAnalysis object
        analysis = self._create_analysis_object(analysis_data, user_prompt)

        # Log summary
        self._log_analysis_summary(analysis)

        logger.info("=" * 60)
        logger.info("PROMPT ANALYSIS COMPLETE")
        logger.info("=" * 60)

        return analysis

    def _build_analysis_prompt(self, user_prompt: str) -> str:
        """Build LLM prompt for analyzing user's description."""

        return f"""# Task: Analyze Web Application Requirements

You are an expert system architect analyzing a user's description of a web application.
Your goal is to extract structured requirements and identify ANY ambiguities or missing details.

## User's Description
{user_prompt}

## Your Task
Analyze the description and output a JSON object with the following structure:

```json
{{
  "project_name": "Extracted or inferred project name",
  "project_type": "Type of application (e.g., 'chat_interface', 'e-commerce', 'task_manager')",
  "description": "Clean, concise description of the application",

  "components": [
    {{
      "name": "component_name",
      "type": "ui|api|database|worker",
      "description": "What this component does",
      "requirements": ["specific requirement 1", "requirement 2"],
      "ambiguities": ["What's ambiguous or unclear"],
      "missing_details": ["What details are not specified"]
    }}
  ],

  "features": {{
    "authentication": {{
      "enabled": true|false,
      "method": "specified method or 'AMBIGUOUS'"
    }},
    "chat": {{
      "enabled": true|false,
      "streaming": "specified method or 'AMBIGUOUS'",
      "file_upload": "specified types or 'AMBIGUOUS'"
    }},
    "agents": {{
      "enabled": true|false,
      "integration_method": "specified or 'AMBIGUOUS'"
    }}
  }},

  "integrations": [
    {{
      "name": "External system name",
      "purpose": "Why integrating",
      "details": "How to integrate or 'AMBIGUOUS'"
    }}
  ],

  "clarifications_needed": [
    {{
      "question": "Clear, specific question to ask user",
      "options": ["Option 1", "Option 2", "Option 3"],
      "context": "Why this matters for implementation",
      "importance": "low|medium|high|critical"
    }}
  ],

  "technical_constraints": {{
    "backend_language": "specified (e.g., 'python', 'php', 'nodejs', 'ruby', 'java') or 'UNSPECIFIED'",
    "backend_framework": "specified (e.g., 'flask', 'fastapi', 'laravel', 'express', 'rails') or 'UNSPECIFIED'",
    "frontend_framework": "specified (e.g., 'alpine_tailwind', 'react', 'vue', 'vanilla_js') or 'UNSPECIFIED'",
    "web_server": "specified (e.g., 'apache2', 'nginx', 'builtin') or 'UNSPECIFIED'",
    "database": "specified (e.g., 'postgresql', 'mysql', 'sqlite', 'mongodb') or 'UNSPECIFIED'",
    "deployment_target": "specified or 'UNSPECIFIED'"
  }}
}}
```

## Analysis Guidelines

1. **Be Thorough**: Extract every component, feature, and requirement mentioned
2. **Identify Ambiguities**: If something is mentioned but not clearly specified, flag it
3. **Find Missing Details**: Identify what's needed but not provided
4. **Generate Smart Questions**: Ask about ambiguities that significantly impact architecture
5. **Prioritize Questions**: Mark critical questions that must be answered vs. nice-to-knows
6. **Infer Wisely**: Make reasonable inferences but flag them as assumptions

## Examples of Good Questions

- "For streaming chat responses, should we use Server-Sent Events (simpler, one-way) or WebSocket (bidirectional, more complex)?"
- "What file types should users be able to upload? (Images only, Documents, Any file)"
- "Should the agent forms appear inline in the main pane or as modal dialogs?"
- "For conversation history, should we show just titles or preview first messages?"

## CRITICAL: Technology Extraction Guidelines

**Extract backend_language CAREFULLY from user descriptions:**
- "PHP backend" → backend_language: "php"
- "Apache2 with PHP" → backend_language: "php", web_server: "apache2"
- "Python backend" → backend_language: "python"
- "FastAPI" → backend_language: "python", backend_framework: "fastapi"
- "Laravel" → backend_language: "php", backend_framework: "laravel"
- "Node.js" or "Express" → backend_language: "nodejs"
- "Flask" → backend_language: "python", backend_framework: "flask"

**DO NOT confuse web servers with backend languages:**
- Apache2 is a **web_server**, NOT a backend_language
- Nginx is a **web_server**, NOT a backend_language
- If user says "Apache2 with PHP backend", extract: backend_language="php", web_server="apache2"

**Always prioritize explicit language mentions:**
- "PHP backend" clearly means backend_language: "php"
- "Python/FastAPI" clearly means backend_language: "python"
- "Node.js Express" clearly means backend_language: "nodejs"

## Return ONLY valid JSON
No explanations, no markdown formatting, just the JSON object.
"""

    def _parse_analysis_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into structured data."""
        # Try to extract JSON from response
        json_str = response.strip()

        # Remove markdown code blocks if present
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        if json_str.startswith("```"):
            json_str = json_str[3:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]

        json_str = json_str.strip()

        # Parse JSON
        return json.loads(json_str)

    def _create_analysis_object(self, data: Dict[str, Any], raw_prompt: str) -> PromptAnalysis:
        """Create PromptAnalysis object from parsed data."""

        # Create component specs
        components = []
        for comp_data in data.get("components", []):
            component = ComponentSpec(
                name=comp_data["name"],
                type=comp_data["type"],
                description=comp_data["description"],
                requirements=comp_data.get("requirements", []),
                ambiguities=comp_data.get("ambiguities", []),
                missing_details=comp_data.get("missing_details", [])
            )
            components.append(component)

        # Create clarification questions
        clarifications = []
        for q_data in data.get("clarifications_needed", []):
            question = ClarificationQuestion(
                question=q_data["question"],
                options=q_data.get("options", []),
                context=q_data.get("context", ""),
                importance=q_data.get("importance", "medium")
            )
            clarifications.append(question)

        # Create analysis
        analysis = PromptAnalysis(
            project_name=data.get("project_name", "Web Application"),
            project_type=data.get("project_type", "web_application"),
            description=data.get("description", ""),
            components=components,
            features=data.get("features", {}),
            integrations=data.get("integrations", []),
            clarifications_needed=clarifications,
            technical_constraints=data.get("technical_constraints", {}),
            raw_prompt=raw_prompt
        )

        return analysis

    def _create_fallback_analysis(self, user_prompt: str) -> PromptAnalysis:
        """Create minimal analysis if LLM parsing fails."""
        logger.warning("Creating fallback analysis")

        return PromptAnalysis(
            project_name="Web Application",
            project_type="web_application",
            description=user_prompt[:200],
            components=[],
            features={},
            integrations=[],
            clarifications_needed=[],
            technical_constraints={},
            raw_prompt=user_prompt
        )

    def _log_analysis_summary(self, analysis: PromptAnalysis):
        """Log summary of analysis."""
        logger.info(f"\n📊 Analysis Summary:")
        logger.info(f"  Project: {analysis.project_name}")
        logger.info(f"  Type: {analysis.project_type}")
        logger.info(f"  Components: {len(analysis.components)}")

        for comp in analysis.components:
            logger.info(f"    - {comp.name} ({comp.type})")
            if comp.ambiguities:
                logger.info(f"      ⚠️  Ambiguities: {len(comp.ambiguities)}")

        if analysis.clarifications_needed:
            logger.info(f"  ❓ Clarifications needed: {len(analysis.clarifications_needed)}")
            for q in analysis.clarifications_needed:
                logger.info(f"    [{q.importance}] {q.question}")

    def ask_clarifications(self, analysis: PromptAnalysis) -> PromptAnalysis:
        """
        Interactively ask user clarifying questions.

        Args:
            analysis: PromptAnalysis with unanswered questions

        Returns:
            Updated PromptAnalysis with answers
        """
        if not analysis.has_clarifications():
            return analysis

        logger.info("\n" + "=" * 60)
        logger.info("CLARIFICATION QUESTIONS")
        logger.info("=" * 60)

        unanswered = analysis.get_unanswered_questions()

        # Sort by importance
        importance_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        unanswered.sort(key=lambda q: importance_order.get(q.importance, 99))

        for i, question in enumerate(unanswered, 1):
            print(f"\n[Question {i}/{len(unanswered)}] [{question.importance.upper()}]")
            print(f"❓ {question.question}")
            print(f"\n📝 Context: {question.context}")

            if question.options:
                print("\nOptions:")
                for j, option in enumerate(question.options, 1):
                    print(f"  {j}. {option}")
                print(f"  {len(question.options) + 1}. Other (specify)")

                while True:
                    try:
                        choice = input(f"\nYour choice (1-{len(question.options) + 1}): ").strip()
                        choice_num = int(choice)

                        if 1 <= choice_num <= len(question.options):
                            question.answer = question.options[choice_num - 1]
                            question.answered = True
                            break
                        elif choice_num == len(question.options) + 1:
                            custom = input("Please specify: ").strip()
                            if custom:
                                question.answer = custom
                                question.answered = True
                                break
                    except (ValueError, IndexError):
                        print("Invalid choice, please try again.")
            else:
                answer = input("\nYour answer: ").strip()
                if answer:
                    question.answer = answer
                    question.answered = True

        logger.info("\n✅ All clarifications answered")
        return analysis
