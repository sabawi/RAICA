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

from ..utils.json_utils import extract_json_from_llm_response

logger = logging.getLogger(__name__)


class RequestType(Enum):
    """Types of requests the agent can handle."""
    SYSTEM_QUERY = auto()      # Read-only system checks (what's installed, status)
    SYSTEM_TASK = auto()       # System modifications (install, configure, start/stop)
    CODE_GENERATION = auto()   # Write code, create projects
    CODE_DEBUG = auto()        # Debug/fix bugs, add enhancements to existing projects
    WEB_SEARCH = auto()        # Web searches, news lookups, online research
    HYBRID = auto()            # Mix of system tasks and code generation
    CONVERSATION = auto()      # General questions, help, explanations
    SOCIAL_MEDIA = auto()      # Social media operations (Twitter, etc.) via Communication Hub


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

    def __init__(self, llm_client: Optional[Any] = None):
        """
        Initialize the classifier.

        Args:
            llm_client: Optional LLM client for semantic analysis
        """
        self.llm_client = llm_client

    def classify(self, request: str, context: str = "") -> ClassificationResult:
        """
        Classify a user request with optional context.

        Args:
            request: The user's request text
            context: Additional context (conversation history, project state)

        Returns:
            ClassificationResult with type and metadata
        """
        # Strictly use LLM for classification as per design requirements
        # No hardcoded keyword biasing allowed.
        if self.llm_client:
             llm_result = self._llm_classify(request, context)
             if llm_result:
                 return llm_result
        
        # Fallback if LLM is unavailable or fails (should be rare)
        logger.warning(f"LLM classification unavailable for request: {request[:50]}...")
        return ClassificationResult(
            primary_type=RequestType.CONVERSATION,
            confidence=0.0,
            reasoning="LLM unavailable, default handling"
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

    def _llm_classify(self, request: str, context: str = "") -> Optional[ClassificationResult]:
        """Use LLM for semantic classification with context."""
        if not self.llm_client:
            return None

        prompt = f"""Analyze this user request and classify it based on INTENT, not keywords.

CONTEXT:
{context}

REQUEST: {request}

⚠️⚠️⚠️ CRITICAL - READ THE CONTEXT FIRST! ⚠️⚠️⚠️
Look at the CONTEXT section above. It tells you the project state:

- If CONTEXT says "NO EXISTING CODE FILES" → MUST use CODE_GENERATION (this is a NEW project!)
- If CONTEXT says "EXISTING PROJECT DETECTED" → use CODE_DEBUG for modifications

DO NOT assume there is existing code if the context says there isn't!
The reasoning you provide must match the actual project state from the context.

⚠️⚠️⚠️ FIRST: CHECK IF REQUEST NEEDS MULTIPLE TASK TYPES ⚠️⚠️⚠️

Does the request require 2+ DIFFERENT types of operations?
- "create game in new directory" → YES (mkdir + codegen) → Use HYBRID
- "install package and write config" → YES (install + codegen) → Use HYBRID
- "create a game" → NO (just codegen, directory is implicit) → Use CODE_GENERATION
- "install nginx" → NO (just install) → Use SYSTEM_TASK

If YES (multiple types), set primary_type="HYBRID" and list types in secondary_types.
If NO (single type), use the appropriate single category below.

CATEGORIES (choose the one that best matches the user's INTENT):

1. SYSTEM_QUERY - User wants to READ/VIEW/CHECK information (READ-ONLY operations)
   Examples:
   - "what version of Python?", "is nginx running?", "show disk space"
   - "list all files", "show me files in this directory", "find files by name"
   - "what's the largest file?", "how many files are there?", "check status"
   - "tree", "ls", "du -sh", "df -h", "find ... -name ..."
   KEY: Any operation that READS or DISPLAYS without MODIFYING is SYSTEM_QUERY

2. SYSTEM_TASK - User wants to MODIFY/CHANGE/CREATE/DELETE or EXECUTE/RUN (WRITE operations or script execution)
   Examples:
   - File/directory MODIFICATIONS: "create a directory", "delete the file", "move file to..."
   - Package management: "install nodejs", "update pip packages", "uninstall X"
   - Service control: "start nginx", "restart the database", "stop the service"
   - User/permission management: "add user", "change permissions", "chmod"
   - System configuration: "set environment variable", "configure firewall"
   - EXECUTING EXISTING SCRIPTS: "run the script", "check my email", "execute find_bills.py"
   - SENDING/TRANSMITTING DATA: "send email to...", "email John", "mail this to...", "download file from...", "upload file to..."
   KEY: Any operation that CHANGES the system state OR RUNS AN EXISTING SCRIPT OR TRANSMITS/SENDS DATA is SYSTEM_TASK

   🚨 CRITICAL - EMAIL REQUESTS:
   - "Write an email... and SEND it to..." → SYSTEM_TASK (action: actually send the email!)
   - "Email John saying..." → SYSTEM_TASK (implied send action)
   - "Send email to X" → SYSTEM_TASK (explicit send action)
   - "Draft an email" / "Write an email" WITHOUT "send" → CONVERSATION (just text generation)

   🚨 CRITICAL - EXECUTE vs MODIFY:
   - "check my email" / "run the script" / "execute X" → SYSTEM_TASK (execute existing code!)
   - "fix the email script" / "improve the code" → CODE_DEBUG (modify code)
   - "check" / "run" / "execute" / "use" WITHOUT modification intent → SYSTEM_TASK
   - "fix" / "improve" / "enhance" / "add feature" → CODE_DEBUG

   CRITICAL DISTINCTION:
   - "list files" / "show files" / "find files" → SYSTEM_QUERY (read-only)
   - "create file" / "delete file" / "move file" → SYSTEM_TASK (modification)
   - "run the script" / "check my email" / "execute the tool" → SYSTEM_TASK (execution)

3. CODE_GENERATION - User wants to CREATE a NEW PROJECT from scratch
   ONLY use this when there is NO existing project or user explicitly wants a NEW project
   Examples: "create a snake game", "build a new web app", "write a new Python script"
   KEY: This creates NEW files from scratch - use ONLY for new projects!

4. CODE_DEBUG - User wants to MODIFY an EXISTING project (fixes, enhancements, changes)
   Use this for ANY modification to an existing codebase:
   - FIXES: "there is a problem with X", "X is broken", "fix the bug"
   - ENHANCEMENTS: "make X better", "improve the layout", "add dark mode"
   - CHANGES: "make the buttons smaller", "change the color", "resize the plot"
   KEY: If there's an EXISTING project with code files, use CODE_DEBUG for MODIFICATIONS or ADDITIONS.
   HOWEVER, if the user explicitly wants to "Create a NEW project" or "Build X from scratch",
   you can use CODE_GENERATION *even if some files exist* (assuming they will be overwritten or ignored).

   🚨 DO NOT USE CODE_DEBUG FOR EXECUTION REQUESTS:
   - "check my email" → SYSTEM_TASK (run existing script, don't modify it!)
   - "run the bill checker" → SYSTEM_TASK (execute, don't modify!)
   - "use the tool to scan files" → SYSTEM_TASK (execute, don't modify!)
   These are EXECUTION requests - use SYSTEM_TASK to run the existing scripts!

   CRITICAL RULE FOR EXISTING PROJECTS:
   - "fix", "debug", "improve", "enhance", "change" → CODE_DEBUG
   - "add a feature", "add a module" → CODE_DEBUG
   - "check", "run", "execute", "use", "scan" (WITHOUT modify intent) → SYSTEM_TASK
   - "create a NEW app", "generate a NEW project" → CODE_GENERATION
   - "create a game" (ambiguous) → CODE_DEBUG (treat as adding to repo) unless context implies empty dir.

   Examples when existing project detected:
   - "make the keypads more compact" → CODE_DEBUG (modify existing UI code)
   - "add a high score feature" → CODE_DEBUG (add to existing codebase)
   - "improve the layout" → CODE_DEBUG (change existing layout code)
   - "fix the button" → CODE_DEBUG (fix existing code)
   - "check my email for bills" → SYSTEM_TASK (execute existing script!)
   - "run the email scanner" → SYSTEM_TASK (execute existing script!)

5. WEB_SEARCH - User wants to SEARCH THE INTERNET for information
   Examples:
   - News/current events: "what are the latest headlines about X", "latest news on Y"
   - Research: "search the web for...", "find information online about...", "google for..."
   - Documentation: "look up the docs for React hooks", "find the API reference for..."
   - Tutorials: "find tutorials on how to...", "search for examples of..."
   - General queries: "what's the weather in...", "what time is it in Tokyo"
   - Financial: "what's the stock price of...", "latest financial news"
   KEY: This is for fetching EXTERNAL information from the internet, not local system info.
   NOTE: If user wants to read LOCAL files or check LOCAL system, use SYSTEM_QUERY instead.

6. HYBRID - Request combines multiple task types that require different handlers:
   Combinations that require HYBRID:
   - SYSTEM_TASK + CODE_GENERATION: "install Python and create a script that..."
   - WEB_SEARCH + CODE_GENERATION: "research X online and create a file with the results"
   - WEB_SEARCH + SYSTEM_TASK: "search for config examples and save to a config file"

   Examples:
   - "research top AI developers and list them in a text file" → HYBRID (WEB_SEARCH + CODE_GENERATION)
   - "search for Python best practices and create a guide.md" → HYBRID (WEB_SEARCH + CODE_GENERATION)
   - "install nginx and write a config file" → HYBRID (SYSTEM_TASK + CODE_GENERATION)

7. CONVERSATION - General questions, explanations, help, TEXT GENERATION WITHOUT actions
   Examples:
   - Questions: "what is Docker?", "explain async/await", "help me understand"
   - Text generation: "draft an email", "write a message", "compose a letter" (WITHOUT sending)
   - Help: "how do I...", "what's the best way to...", "can you explain..."

   🚨 CRITICAL DISTINCTION - Text Generation vs Action:
   - "Write an email" / "Draft a message" (NO send/transmit) → CONVERSATION (just generate text)
   - "Write an email... and SEND it" / "Email John" → SYSTEM_TASK (action!)

   KEY: If user wants you to GENERATE TEXT ONLY (no execution, no sending, no file creation), use CONVERSATION.
   If user wants text PLUS an ACTION (send, save, execute), use the appropriate action category (SYSTEM_TASK, CODE_GENERATION, etc.)

   NOTE: If user asks to "review" but also lists CHANGES they want made,
   that is CODE_GENERATION or CODE_DEBUG, not CONVERSATION

8. SOCIAL_MEDIA - Operations on social media platforms (Twitter/X, etc.)
   Examples:
   - "list my last 10 tweets on Twitter" → SOCIAL_MEDIA
   - "get replies to my posts on Twitter" → SOCIAL_MEDIA
   - "read my Twitter mentions" → SOCIAL_MEDIA
   - "post a tweet saying..." → SOCIAL_MEDIA
   - "check my Twitter notifications" → SOCIAL_MEDIA
   KEY: Any request involving social media platforms (Twitter, X, etc.) should use SOCIAL_MEDIA
   NOTE: This uses the Communication Hub tools to interact with social media APIs

EXAMPLE OUTPUT - Simple request (single task type):
{{
    "primary_type": "SYSTEM_TASK",
    "secondary_types": [],
    "intent": "Install nginx package",
    "requires_sudo": true,
    "is_destructive": false,
    "complexity": "simple",
    "confidence": 0.95,
    "reasoning": "Single task: install a package"
}}

EXAMPLE OUTPUT - Email ACTION request (send email):
{{
    "primary_type": "SYSTEM_TASK",
    "secondary_types": [],
    "intent": "Send email to John about lunch cancellation",
    "requires_sudo": false,
    "is_destructive": false,
    "complexity": "simple",
    "confidence": 0.95,
    "reasoning": "User wants to SEND an email (action), not just draft text. Request includes 'send it to...' which indicates execution."
}}

EXAMPLE OUTPUT - Email TEXT request (draft only):
{{
    "primary_type": "CONVERSATION",
    "secondary_types": [],
    "intent": "Draft email text for user to copy",
    "requires_sudo": false,
    "is_destructive": false,
    "complexity": "simple",
    "confidence": 0.90,
    "reasoning": "User wants to DRAFT email text only, no sending action mentioned. Just text generation."
}}

EXAMPLE OUTPUT - Social media request:
{{
    "primary_type": "SOCIAL_MEDIA",
    "secondary_types": [],
    "intent": "Get replies to user's Twitter posts",
    "requires_sudo": false,
    "is_destructive": false,
    "complexity": "simple",
    "confidence": 0.95,
    "reasoning": "Social media read operation - fetching Twitter replies via Communication Hub"
}}

EXAMPLE OUTPUT - Hybrid request (SYSTEM_TASK + CODE_GENERATION):
{{
    "primary_type": "HYBRID",
    "secondary_types": ["SYSTEM_TASK", "CODE_GENERATION"],
    "intent": "Create directory and generate game code",
    "requires_sudo": false,
    "is_destructive": false,
    "complexity": "moderate",
    "confidence": 0.95,
    "reasoning": "Two distinct tasks: (1) create directory via mkdir, (2) generate PyQt game code"
}}

EXAMPLE OUTPUT - Hybrid request (WEB_SEARCH + CODE_GENERATION):
{{
    "primary_type": "HYBRID",
    "secondary_types": ["WEB_SEARCH", "CODE_GENERATION"],
    "intent": "Research AI developers online and create a file listing them",
    "requires_sudo": false,
    "is_destructive": false,
    "complexity": "moderate",
    "confidence": 0.95,
    "reasoning": "Two distinct tasks: (1) web search for information, (2) create output file with results"
}}

KEY DISTINCTIONS:

1. "create" doesn't always mean CODE_GENERATION:
   - "create a directory/folder" → SYSTEM_TASK (file system operation)
   - "create a game/app/website" → CODE_GENERATION (writing software)
   - "create a user account" → SYSTEM_TASK (system administration)

2. "review" with CHANGES is CODE_GENERATION, not CONVERSATION:
   - "review the project and explain it" → CONVERSATION (analysis only)
   - "review the project and redesign the UI" → CODE_GENERATION (wants code changes!)
   - "review and improve the look and feel" → CODE_GENERATION (wants modifications!)

3. CODE_DEBUG vs CODE_GENERATION - Based on PROJECT STATE (not keywords!):
   EXISTING PROJECT (files exist):
   - "there is a problem/issue with X" → CODE_DEBUG (fixing)
   - "X is wrong/broken/incorrect" → CODE_DEBUG (fixing)
   - "I want to add/improve/enhance X" → CODE_DEBUG (modifying existing)
   - "add a new feature" → CODE_DEBUG (extending existing)

   NO PROJECT (empty directory or explicit "new"):
   - "create a new app" → CODE_GENERATION (from scratch)
   - "build X from scratch" → CODE_GENERATION (new project)
   - "make X" (where nothing exists) → CODE_GENERATION (new project)

4. DIRECTORY CREATION vs PROJECT CREATION:
   - "create a directory called foo" → SYSTEM_TASK (just a folder)
   - "create a NEW project in directory foo" → CODE_GENERATION (project creation)
   - "create a game in a new folder" → CODE_GENERATION (the GOAL is the game, not the folder!)
   - "make a subdirectory for the app" → CODE_GENERATION (if part of app creation)

Focus on the END GOAL: Does the user want CODE CHANGES, A NEW APP, or just a FILE SYSTEM CHANGE?
If they want code changed or a software project built, it's CODE_GENERATION or CODE_DEBUG.
Creating a folder is just a step in building an app - so classify as CODE_GENERATION.

5. COMPLEXITY DETERMINATION (CRITICAL FOR TASK DECOMPOSITION):
   - "simple": SINGLE atomic action (e.g., "install nginx", "list files", "check status")
   - "moderate": 2-3 distinct tasks (e.g., "create directory AND generate code", "install AND configure")
   - "complex": 4+ steps or dependencies (e.g., "setup LAMP stack", "build and deploy app")

   ⚠️ IF REQUEST CONTAINS MULTIPLE ACTIONS (create X and Y, install then configure, etc.),
   USE "moderate" or "complex" complexity so proper task decomposition happens!

   Examples:
   - "install nginx" → "simple" (one task)
   - "create directory and generate PyQt game" → "moderate" (two tasks: mkdir + codegen)
   - "install LAMP stack and deploy PHP app" → "complex" (many steps)
   - "create web app with database" → "moderate" (setup + codegen)

6. HYBRID vs SINGLE TYPE:
   ⚠️ CRITICAL: Use HYBRID as primary_type when request involves MULTIPLE distinct task types!

   HYBRID requests (set primary_type = "HYBRID"):
   - "create directory and generate game" → HYBRID (SYSTEM_TASK + CODE_GENERATION)
   - "install nginx and write config files" → HYBRID (SYSTEM_TASK + CODE_GENERATION)
   - "setup environment and build app" → HYBRID (SYSTEM_TASK + CODE_GENERATION)
   - "research X and save to a file" → HYBRID (WEB_SEARCH + CODE_GENERATION)
   - "search online for Y and create a report" → HYBRID (WEB_SEARCH + CODE_GENERATION)
   - "look up Z and list them in output.txt" → HYBRID (WEB_SEARCH + CODE_GENERATION)

   ⚠️ KEY: If request mentions BOTH internet research AND creating/saving to a file, it's HYBRID!

   SINGLE type requests:
   - "install nginx" → SYSTEM_TASK (only one type of work)
   - "create a game" → CODE_GENERATION (only code generation, directory creation is implicit)
   - "fix the bug in login.py" → CODE_DEBUG (only code modification)
   - "search for latest news on AI" → WEB_SEARCH (only search, no file output)

   When using HYBRID, list the component types in secondary_types array.
   Example: {{"primary_type": "HYBRID", "secondary_types": ["SYSTEM_TASK", "CODE_GENERATION"]}}
   Example: {{"primary_type": "HYBRID", "secondary_types": ["WEB_SEARCH", "CODE_GENERATION"]}}
"""

        # System prompt to enforce JSON-only output
        system_prompt = """You are a request classifier. You MUST respond with ONLY valid JSON, no additional text, explanations, or commentary.

Your response must be a single JSON object with this exact structure:
{
    "primary_type": "SYSTEM_TASK",
    "secondary_types": [],
    "intent": "Brief description",
    "requires_sudo": false,
    "is_destructive": false,
    "complexity": "simple",
    "confidence": 0.95,
    "reasoning": "Brief explanation"
}

Do not include any text before or after the JSON object. Return ONLY the JSON."""

        try:
            # Use generate_for_classification if available (uses classification model override)
            if hasattr(self.llm_client, 'generate_for_classification'):
                response = self.llm_client.generate_for_classification(prompt, max_tokens=1000, system_prompt=system_prompt)
            else:
                response = self.llm_client.generate(prompt, max_tokens=1000, system_prompt=system_prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # DEBUG: Log which model was actually used
            if hasattr(response, 'provider') and hasattr(response, 'model'):
                logger.info(f"🔍 CLASSIFICATION USED: {response.provider}/{response.model}")
                print(f"🔍 CLASSIFICATION USED: {response.provider}/{response.model}")

            # Debug: log the raw content when JSON extraction fails
            data = extract_json_from_llm_response(content)
            if not data:
                # Log the problematic content for debugging
                content_preview = content[:500].replace('\\n', '\\\\n').replace('\\r', '\\\\r')
                logger.warning(f"No valid JSON found in LLM classification response")
                logger.debug(f"Raw content preview: {content_preview}...")
                # Print actual response for debugging
                print(f"\n❌ RAW LLM RESPONSE (first 1000 chars):\n{content[:1000]}\n")

                # Try to extract JSON more aggressively with relaxed parsing
                # Look for JSON-like patterns even if malformed
                import re
                json_like = re.search(r'\\{[^{}]*\\}', content, re.DOTALL)
                if json_like:
                    logger.debug(f"Found JSON-like pattern: {json_like.group()[:200]}...")
                return None

            if data:
                # Map string to enum
                type_map = {
                    'SYSTEM_QUERY': RequestType.SYSTEM_QUERY,
                    'SYSTEM_TASK': RequestType.SYSTEM_TASK,
                    'CODE_GENERATION': RequestType.CODE_GENERATION,
                    'CODE_DEBUG': RequestType.CODE_DEBUG,
                    'WEB_SEARCH': RequestType.WEB_SEARCH,
                    'HYBRID': RequestType.HYBRID,
                    'CONVERSATION': RequestType.CONVERSATION,
                    'SOCIAL_MEDIA': RequestType.SOCIAL_MEDIA
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
