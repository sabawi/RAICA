"""
Request Classifier
==================

Semantically classifies user requests to determine the appropriate handling mode.
Uses LLM for intelligent classification of complex or ambiguous requests.
"""

import re
import json
import logging
from enum import Enum, auto
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class RequestType(Enum):
    """Types of requests the agent can handle."""
    SYSTEM_QUERY = auto()      # Read-only system checks (what's installed, status)
    SYSTEM_TASK = auto()       # System modifications (install, configure, start/stop)
    CODE_GENERATION = auto()   # Write code, create projects
    CODE_DEBUG = auto()        # Debug/fix bugs, add enhancements to existing projects
    HYBRID = auto()            # Mix of system tasks and code generation
    CONVERSATION = auto()      # General questions, help, explanations


@dataclass
class ClassificationResult:
    """Result of request classification."""
    primary_type: RequestType
    secondary_types: List[RequestType] = field(default_factory=list)
    intent: str = ""                    # What user wants to achieve
    requires_sudo: bool = False         # Needs root privileges
    is_destructive: bool = False        # Could cause data loss
    complexity: str = "simple"          # simple, moderate, complex
    keywords_found: List[str] = field(default_factory=list)
    confidence: float = 0.0             # 0.0 to 1.0
    reasoning: str = ""                 # Why this classification

    def to_dict(self) -> Dict[str, Any]:
        return {
            'primary_type': self.primary_type.name,
            'secondary_types': [t.name for t in self.secondary_types],
            'intent': self.intent,
            'requires_sudo': self.requires_sudo,
            'is_destructive': self.is_destructive,
            'complexity': self.complexity,
            'keywords_found': self.keywords_found,
            'confidence': self.confidence,
            'reasoning': self.reasoning
        }


class RequestClassifier:
    """
    Classifies user requests into appropriate handling modes.

    Uses a combination of:
    1. Keyword matching for common patterns (fast path)
    2. LLM-based semantic analysis for complex requests
    """

    # Keywords indicating system queries (read-only)
    SYSTEM_QUERY_KEYWORDS = [
        'check', 'is installed', 'what version', 'show', 'list', 'status',
        'which', 'where is', 'find', 'locate', 'display', 'get info',
        'what is', 'how much', 'disk space', 'memory', 'cpu', 'running',
        'configured', 'enabled', 'active', 'listening', 'ports',
        'show me', 'files in', 'folder', 'directory', 'largest', 'oldest',
        'biggest', 'newest', 'how many', 'count', 'size of', 'du -', 'df -',
        'ls', 'tree', 'analyze', 'what are', 'tell me',
        'installed', 'version', 'have', 'exists', 'is there', 'do i have',
        'is my', 'does my', 'is the'
    ]

    # Keywords indicating system tasks (modifications)
    SYSTEM_TASK_KEYWORDS = [
        'install', 'uninstall', 'remove', 'update', 'upgrade', 'configure',
        'setup', 'set up', 'start', 'stop', 'restart', 'enable', 'disable',
        'create user', 'add user', 'delete', 'modify', 'change', 'edit config',
        'download', 'mount', 'unmount', 'chmod', 'chown', 'systemctl',
        'apt', 'yum', 'dnf', 'brew', 'pip install', 'npm install'
    ]

    # Keywords indicating code generation
    CODE_GEN_KEYWORDS = [
        'create', 'build', 'write', 'generate', 'make', 'develop',
        'implement', 'code', 'script', 'program', 'application', 'app',
        'website', 'web page', 'html', 'css', 'javascript', 'python',
        'function', 'class', 'api', 'endpoint', 'database schema',
        'frontend', 'backend', 'fullstack'
    ]

    # Keywords indicating code debug/fix (existing project modifications)
    CODE_DEBUG_KEYWORDS = [
        'fix', 'debug', 'bug', 'error', 'broken', 'not working',
        'fails', 'failing', 'crash', 'crashed', 'exception', 'issue',
        'enhance', 'add feature', 'extend', 'modify existing',
        'improve', 'refactor', 'update', 'existing project',
        'existing code', 'current code', 'my project', 'this project',
        'broken code', 'fix this', 'debug this', 'patch', 'hotfix',
        'regression', 'wrong behavior', 'unexpected', 'incorrect',
        'add to existing', 'modify this', 'change this'
    ]

    # Keywords indicating hybrid requests
    HYBRID_INDICATORS = [
        'and then', 'after that', 'once installed', 'then create',
        'set up and', 'install and create', 'configure and write'
    ]

    # Keywords requiring sudo
    SUDO_KEYWORDS = [
        'install', 'apt', 'yum', 'dnf', 'systemctl', 'service',
        'chmod', 'chown', 'mount', 'umount', 'fdisk', 'mkfs',
        'useradd', 'userdel', 'groupadd', 'passwd', 'visudo',
        '/etc/', 'nginx', 'apache', 'mysql', 'postgresql'
    ]

    # Destructive operation keywords
    DESTRUCTIVE_KEYWORDS = [
        'delete', 'remove', 'uninstall', 'drop', 'truncate', 'format',
        'rm -rf', 'purge', 'wipe', 'destroy', 'reset'
    ]

    def __init__(self, llm_client: Optional[Any] = None):
        """
        Initialize the classifier.

        Args:
            llm_client: Optional LLM client for semantic analysis
        """
        self.llm_client = llm_client

    def classify(self, request: str) -> ClassificationResult:
        """
        Classify a user request.

        Args:
            request: The user's request text

        Returns:
            ClassificationResult with type and metadata
        """
        request_lower = request.lower()

        # Quick keyword-based classification
        result = self._keyword_classify(request_lower)

        # If confidence is low or request is complex, use LLM
        if result.confidence < 0.7 or result.complexity == "complex":
            if self.llm_client:
                llm_result = self._llm_classify(request)
                if llm_result and llm_result.confidence > result.confidence:
                    result = llm_result

        return result

    def _keyword_classify(self, request: str) -> ClassificationResult:
        """Fast keyword-based classification."""
        keywords_found = []
        scores = {
            RequestType.SYSTEM_QUERY: 0,
            RequestType.SYSTEM_TASK: 0,
            RequestType.CODE_GENERATION: 0,
            RequestType.CODE_DEBUG: 0,
            RequestType.CONVERSATION: 0
        }

        def match_keyword(kw: str, text: str) -> bool:
            """Match keyword with word boundary awareness."""
            # Multi-word phrases: simple substring match
            if ' ' in kw:
                return kw in text
            # Single words: use word boundary regex
            pattern = r'\b' + re.escape(kw) + r'\b'
            return bool(re.search(pattern, text))

        # Check for system query keywords FIRST (higher priority for query patterns)
        for kw in self.SYSTEM_QUERY_KEYWORDS:
            if match_keyword(kw, request):
                scores[RequestType.SYSTEM_QUERY] += 2  # Higher weight for query patterns
                keywords_found.append(f"query:{kw}")

        # Check for system task keywords
        for kw in self.SYSTEM_TASK_KEYWORDS:
            if match_keyword(kw, request):
                scores[RequestType.SYSTEM_TASK] += 1
                keywords_found.append(f"task:{kw}")

        # Check for code generation keywords
        for kw in self.CODE_GEN_KEYWORDS:
            if match_keyword(kw, request):
                scores[RequestType.CODE_GENERATION] += 1
                keywords_found.append(f"code:{kw}")

        # Check for code debug keywords (existing project modifications)
        for kw in self.CODE_DEBUG_KEYWORDS:
            if match_keyword(kw, request):
                scores[RequestType.CODE_DEBUG] += 2  # Higher weight for debug patterns
                keywords_found.append(f"debug:{kw}")

        # Check for hybrid indicators
        is_hybrid = any(ind in request for ind in self.HYBRID_INDICATORS)

        # Check for sudo requirements
        requires_sudo = any(kw in request for kw in self.SUDO_KEYWORDS)

        # Check for destructive operations
        is_destructive = any(kw in request for kw in self.DESTRUCTIVE_KEYWORDS)

        # Determine primary type
        max_score = max(scores.values())
        if max_score == 0:
            primary_type = RequestType.CONVERSATION
            confidence = 0.5
        else:
            primary_type = max(scores, key=scores.get)
            # Calculate confidence based on score dominance
            total_score = sum(scores.values())
            confidence = scores[primary_type] / total_score if total_score > 0 else 0.5

        # Check for hybrid
        secondary_types = []
        if is_hybrid or sum(1 for s in scores.values() if s > 0) > 1:
            # Multiple types detected
            for rtype, score in scores.items():
                if score > 0 and rtype != primary_type:
                    secondary_types.append(rtype)
            if secondary_types:
                primary_type = RequestType.HYBRID

        # Determine complexity
        word_count = len(request.split())
        if word_count > 50 or is_hybrid:
            complexity = "complex"
        elif word_count > 20:
            complexity = "moderate"
        else:
            complexity = "simple"

        return ClassificationResult(
            primary_type=primary_type,
            secondary_types=secondary_types,
            intent=self._extract_intent(request),
            requires_sudo=requires_sudo,
            is_destructive=is_destructive,
            complexity=complexity,
            keywords_found=keywords_found,
            confidence=min(confidence, 0.85),  # Cap at 0.85 for keyword-only
            reasoning="Keyword-based classification"
        )

    def _extract_intent(self, request: str) -> str:
        """Extract the main intent from the request."""
        # Simple extraction - first sentence or up to 100 chars
        sentences = request.split('.')
        if sentences:
            intent = sentences[0].strip()
            if len(intent) > 100:
                intent = intent[:100] + "..."
            return intent
        return request[:100]

    def _llm_classify(self, request: str) -> Optional[ClassificationResult]:
        """Use LLM for semantic classification."""
        if not self.llm_client:
            return None

        prompt = f"""Analyze this user request and classify it.

REQUEST: {request}

Classify into one of these types:
- SYSTEM_QUERY: Read-only system checks (what's installed, status, info)
- SYSTEM_TASK: System modifications (install, configure, start/stop services)
- CODE_GENERATION: Write code, create NEW applications, scripts from scratch
- CODE_DEBUG: Fix bugs, debug issues, add enhancements to EXISTING projects
- HYBRID: Combination of system tasks AND code generation
- CONVERSATION: General questions, explanations, help

Output as JSON:
{{
    "primary_type": "CODE_DEBUG",
    "secondary_types": [],
    "intent": "Fix authentication bug in existing login system",
    "requires_sudo": false,
    "is_destructive": false,
    "complexity": "moderate",
    "confidence": 0.95,
    "reasoning": "Request involves fixing bugs in existing code, not creating new project"
}}

IMPORTANT:
- CODE_DEBUG is for fixing/enhancing EXISTING code (bug fixes, enhancements, refactoring)
- CODE_GENERATION is for creating NEW projects from scratch
- HYBRID means the request needs BOTH system operations AND code generation
- requires_sudo is true if the task needs root/admin privileges
- is_destructive is true if the task could cause data loss
- complexity: simple (1-2 steps), moderate (3-5 steps), complex (6+ steps)
"""

        try:
            response = self.llm_client.generate(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())

                # Map string to enum
                type_map = {
                    'SYSTEM_QUERY': RequestType.SYSTEM_QUERY,
                    'SYSTEM_TASK': RequestType.SYSTEM_TASK,
                    'CODE_GENERATION': RequestType.CODE_GENERATION,
                    'CODE_DEBUG': RequestType.CODE_DEBUG,
                    'HYBRID': RequestType.HYBRID,
                    'CONVERSATION': RequestType.CONVERSATION
                }

                primary = type_map.get(data.get('primary_type', ''), RequestType.CONVERSATION)
                secondary = [type_map[t] for t in data.get('secondary_types', []) if t in type_map]

                return ClassificationResult(
                    primary_type=primary,
                    secondary_types=secondary,
                    intent=data.get('intent', ''),
                    requires_sudo=data.get('requires_sudo', False),
                    is_destructive=data.get('is_destructive', False),
                    complexity=data.get('complexity', 'moderate'),
                    keywords_found=[],
                    confidence=float(data.get('confidence', 0.8)),
                    reasoning=data.get('reasoning', 'LLM classification')
                )

        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")

        return None

    def is_safe_to_auto_execute(self, result: ClassificationResult) -> bool:
        """
        Check if the request is safe to execute without explicit approval.

        Args:
            result: Classification result

        Returns:
            True if safe for auto-execution
        """
        # Never auto-execute destructive operations
        if result.is_destructive:
            return False

        # Never auto-execute sudo operations
        if result.requires_sudo:
            return False

        # Only auto-execute simple system queries
        if result.primary_type == RequestType.SYSTEM_QUERY:
            return result.complexity == "simple"

        # Code generation in isolated directory is generally safe
        if result.primary_type == RequestType.CODE_GENERATION:
            return True

        # CODE_DEBUG should never auto-execute - it modifies existing code
        # and requires user oversight for safety
        if result.primary_type == RequestType.CODE_DEBUG:
            return False

        return False
