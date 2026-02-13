#!/usr/bin/env python3
"""
Code Generation LLM Client
==========================

Direct LLM client for code generation that reads from the `code_generation`
section of config/llm_config.yaml.

This bypasses the FastAPI server and calls the LLM providers directly,
using the code_generation configuration which may be different from the
server's primary LLM.

Supports:
- Ollama (local)
- OpenAI
- Anthropic Claude
- Google Gemini
- Qwen

Author: RAICA Development Team
Version: 1.0.0
"""

import os
import yaml
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Unified LLM response format."""
    content: str
    provider: str
    model: str
    success: bool
    error: Optional[str] = None
    finish_reason: Optional[str] = None


@dataclass
class FallbackEntry:
    """Represents a provider+model pair in the fallback chain."""
    provider: str
    model: Optional[str] = None  # None means use default from provider config

    def __str__(self):
        if self.model:
            return f"{self.provider}/{self.model}"
        return self.provider


def strip_thinking_content(content: str) -> str:
    """
    Strip thinking/reasoning content from LLM responses.

    Handles various formats from different LLM providers:
    - <thinking>...</thinking> tags
    - <think>...</think> tags
    - <details>...</details> tags (often used for collapsible reasoning)
    - <detail>...</detail> tags
    - <summary>Thought for Xs</summary> tags
    - <reasoning>...</reasoning> tags
    - <reflection>...</reflection> tags
    - <scratchpad>...</scratchpad> tags
    - > **model_name** markers
    - Chain-of-thought prefixes like "Let me think...", "Step 1:", etc.

    Use this to clean documentation files (README.md, etc.) before writing.
    Do NOT use this on code files as it may remove legitimate content.

    Returns the cleaned content with only the final answer/documentation.
    """
    if not content:
        return content

    original_content = content

    # Remove XML-style thinking tags (case-insensitive, handles multiline)
    thinking_patterns = [
        r'<thinking>[\s\S]*?</thinking>',
        r'<think>[\s\S]*?</think>',
        r'<details>[\s\S]*?</details>',
        r'<detail>[\s\S]*?</detail>',
        r'<summary>[\s\S]*?</summary>',
        r'<reasoning>[\s\S]*?</reasoning>',
        r'<reflection>[\s\S]*?</reflection>',
        r'<scratchpad>[\s\S]*?</scratchpad>',
        r'<internal>[\s\S]*?</internal>',
        r'<analysis>[\s\S]*?</analysis>',
        r'<thought>[\s\S]*?</thought>',
        r'<plan>[\s\S]*?</plan>',  # Be careful - only remove if not part of content
    ]

    for pattern in thinking_patterns:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE)

    # Remove model markers like "> **ollama/model:tag**" at start of lines
    content = re.sub(r'^>\s*\*\*[\w\-/:.]+\*\*\s*$', '', content, flags=re.MULTILINE)

    # Remove "Thought for Xs" standalone lines
    content = re.sub(r'^.*Thought for \d+\.?\d*s.*$', '', content, flags=re.MULTILINE)

    # Remove common chain-of-thought prefixes (only at line starts)
    cot_patterns = [
        r"^Let me think[^.]*\.\s*",
        r"^I'll analyze[^.]*\.\s*",
        r"^First,? let me[^.]*\.\s*",
        r"^Okay,? so[^.]*\.\s*",
        r"^Alright,?[^.]*\.\s*",
        r"^Hmm,?[^.]*\.\s*",
        r"^Let's see[^.]*\.\s*",
        r"^I need to[^.]*\.\s*",
    ]

    for pattern in cot_patterns:
        content = re.sub(pattern, '', content, flags=re.MULTILINE | re.IGNORECASE)

    # Remove numbered reasoning steps BEFORE code blocks (not inside them)
    # Find the first code block position
    code_block_match = re.search(r'```', content)
    if code_block_match:
        before_code = content[:code_block_match.start()]
        after_and_including_code = content[code_block_match.start():]

        # Remove numbered steps from the part before code
        before_code = re.sub(r'^\d+\.\s+\*\*[^*]+\*\*:?[^\n]*\n?', '', before_code, flags=re.MULTILINE)
        before_code = re.sub(r'^\*\*\d+\.\s+[^*]+\*\*:?[^\n]*\n?', '', before_code, flags=re.MULTILINE)

        content = before_code + after_and_including_code

    # Clean up excessive whitespace
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = content.strip()

    # Log if significant content was removed
    if len(original_content) - len(content) > 100:
        logger.debug(f"Stripped {len(original_content) - len(content)} bytes of thinking content")

    return content


def extract_best_code_block(content: str, expected_type: str = None) -> str:
    """
    Extract the best/most complete code block from LLM response.

    This is the iron-clad code extraction that handles:
    - Multiple code blocks (picks the largest/most complete)
    - Nested code blocks
    - Code without proper fencing
    - Truncated blocks

    Args:
        content: Raw LLM response
        expected_type: Expected file type (html, py, js, etc.) for validation

    Returns:
        The best extracted code, or empty string if none found
    """
    if not content:
        return ""

    # First, strip thinking content
    content = strip_thinking_content(content)

    # Find ALL code blocks with their language tags
    code_blocks = []

    # Pattern for fenced code blocks with optional language
    pattern = r'```(\w*)\n([\s\S]*?)```'

    for match in re.finditer(pattern, content):
        lang = match.group(1).lower()
        code = match.group(2).strip()

        # Skip empty or trivial blocks
        if not code or len(code) < 10:
            continue

        # Calculate a quality score
        score = len(code)  # Base score is length

        # Bonus for matching expected type
        if expected_type:
            if expected_type.lower() in lang or lang in expected_type.lower():
                score += 1000

        # Bonus for complete-looking code
        if expected_type in ('html', 'htm') or lang == 'html':
            if '<!DOCTYPE' in code or '<html' in code:
                score += 500
            if '</html>' in code:
                score += 500
        elif expected_type == 'py' or lang == 'python':
            if 'def ' in code or 'class ' in code or 'import ' in code:
                score += 200
        elif expected_type in ('js', 'javascript') or lang in ('javascript', 'js'):
            if 'function ' in code or 'const ' in code or 'let ' in code:
                score += 200

        # Penalty for incomplete code (unbalanced brackets)
        open_braces = code.count('{') - code.count('}')
        open_parens = code.count('(') - code.count(')')
        open_brackets = code.count('[') - code.count(']')

        if abs(open_braces) > 0 or abs(open_parens) > 0 or abs(open_brackets) > 0:
            score -= 100 * (abs(open_braces) + abs(open_parens) + abs(open_brackets))

        code_blocks.append((score, lang, code))

    if code_blocks:
        # Sort by score descending and return the best one
        code_blocks.sort(key=lambda x: x[0], reverse=True)
        best_score, best_lang, best_code = code_blocks[0]
        logger.debug(f"Selected code block: lang={best_lang}, score={best_score}, len={len(best_code)}")
        return best_code

    # No fenced code blocks found - try to extract code without fencing
    # Look for code-like content
    lines = content.split('\n')
    code_lines = []
    in_code = False

    for line in lines:
        # Detect start of code-like content
        if not in_code:
            if line.strip().startswith(('<!DOCTYPE', '<html', 'import ', 'from ', 'def ', 'class ',
                                         'function ', 'const ', 'let ', 'var ', '#!', '<?')):
                in_code = True
                code_lines.append(line)
        else:
            # Continue collecting code
            code_lines.append(line)
            # Detect end of code (empty lines followed by non-code text)
            if not line.strip() and len(code_lines) > 5:
                # Check if next non-empty line looks like prose
                remaining = '\n'.join(lines[lines.index(line)+1:]).strip()
                if remaining and not remaining[0] in '<#{[/\\':
                    # Might be end of code, but keep going
                    pass

    if code_lines:
        code = '\n'.join(code_lines).strip()
        if len(code) > 50:  # Minimum viable code length
            logger.debug(f"Extracted unfenced code: len={len(code)}")
            return code

    # Last resort: return the content stripped of thinking
    return content


class CodeGenLLMClient:
    """
    LLM client for code generation using the code_generation config.

    Supports multiple providers with automatic fallback.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
        output_callback: Optional[callable] = None
    ):
        """
        Initialize the code generation LLM client.

        Args:
            config_path: Path to llm_config.yaml (defaults to project config)
            provider_override: Optional provider to use instead of config default
            model_override: Optional model name to use instead of config default
        """
        if config_path is None:
            # Default to project's central config
            config_path = Path(__file__).parent.parent.parent / "config" / "llm_config.yaml"

        self.config_path = config_path
        self.config = self._load_config(config_path)

        # Apply overrides if provided
        self._provider_override = provider_override
        self._model_override = model_override
        self.output = output_callback or (lambda x: None)

        # Always load fallback settings from config
        self.fallback_enabled = self.config.get('fallback', {}).get('enabled', True)
        raw_fallback_order = self.config.get('fallback', {}).get('order', [])

        # Parse fallback order - supports both simple strings and provider+model dicts
        self.fallback_order: List[FallbackEntry] = self._parse_fallback_order(raw_fallback_order)

        if provider_override:
            # Use override as primary, but keep fallback enabled
            self.primary_provider = provider_override
            self.primary_model = model_override  # May be None

            # Create a FallbackEntry for the override and put it first
            override_entry = FallbackEntry(provider=provider_override, model=model_override)

            # Filter out entries that exactly match the override (same provider+model)
            remaining = [
                e for e in self.fallback_order
                if not (e.provider == provider_override and e.model == model_override)
            ]
            self.fallback_order = [override_entry] + remaining
        else:
            # Check for model preset selection (new simplified config)
            selected_model = self.config.get('selected_model')
            model_presets = self.config.get('model_presets', {})

            if selected_model and selected_model in model_presets:
                # Use the preset to determine provider and model
                preset = model_presets[selected_model]
                self.primary_provider = preset.get('provider', 'openai')
                self.primary_model = preset.get('model')
                logger.info(f"Using model preset '{selected_model}' → {self.primary_provider}/{self.primary_model}")

                # Check for classification model override
                classification_model_name = self.config.get('classification_model')
                if classification_model_name:
                    self.classification_provider = 'ollama'  # Default to ollama for simplicity
                    self.classification_model = classification_model_name
                    logger.info(f"Using classification model override: {self.classification_provider}/{self.classification_model}")
                else:
                    # Use same as primary
                    self.classification_provider = self.primary_provider
                    self.classification_model = self.primary_model

                # Put this preset first in the fallback order
                preset_entry = FallbackEntry(provider=self.primary_provider, model=self.primary_model)
                remaining = [
                    e for e in self.fallback_order
                    if not (e.provider == self.primary_provider and e.model == self.primary_model)
                ]
                self.fallback_order = [preset_entry] + remaining
            elif selected_model:
                # selected_model specified but not in presets - warn and use as-is
                logger.warning(f"Model preset '{selected_model}' not found in model_presets, using as provider type")
                self.primary_provider = self.config.get('type', 'ollama')
                self.primary_model = None
            else:
                # Fallback to old-style 'type' config
                self.primary_provider = self.config.get('type', 'ollama')
                self.primary_model = None

        # If model override provided, update the provider config
        if model_override and self.primary_provider in self.config.get('providers', {}):
            self.config['providers'][self.primary_provider]['model'] = model_override

        # Lazy-loaded provider clients
        self._clients: Dict[str, Any] = {}

        # Provider dispatch registry - maps provider names to their call methods
        # This eliminates the need for if-elif chains when calling providers
        self._provider_dispatch: Dict[str, callable] = {
            'ollama': self._call_ollama,
            'openai': self._call_openai,
            'anthropic': self._call_anthropic,
            'gemini': self._call_gemini,
            'qwen': self._call_qwen,
        }

        # Store selected preset name for display
        self._selected_preset = self.config.get('selected_model') if not provider_override else None

        logger.info(f"CodeGenLLMClient initialized")
        if self._selected_preset:
            logger.info(f"  Selected model: {self._selected_preset} → {self.primary_provider}/{self.primary_model}")
        else:
            logger.info(f"  Primary provider: {self.primary_provider}")
            if self.primary_model:
                logger.info(f"  Primary model: {self.primary_model}")
        if provider_override:
            logger.info(f"  Provider override: {provider_override}")
        if model_override:
            logger.info(f"  Model override: {model_override}")
        logger.info(f"  Fallback enabled: {self.fallback_enabled}")
        if self.fallback_enabled:
            fallback_str = ', '.join(str(e) for e in self.fallback_order[:5])  # Show first 5
            logger.info(f"  Fallback order: [{fallback_str}...]")

    def _parse_fallback_order(self, raw_order: List[Union[str, Dict]]) -> List[FallbackEntry]:
        """
        Parse fallback order from config, supporting both formats:
        - Simple: ["ollama", "openai", "gemini"]
        - Detailed: [{"provider": "ollama", "model": "deepseek-v3.2:cloud"}, ...]

        Args:
            raw_order: List of provider names (strings) or provider+model dicts

        Returns:
            List of FallbackEntry objects
        """
        entries = []
        default_order = ['ollama', 'openai', 'anthropic', 'gemini', 'qwen']

        if not raw_order:
            # Use default order with no specific models
            return [FallbackEntry(provider=p) for p in default_order]

        for item in raw_order:
            if isinstance(item, str):
                # Simple format: just provider name
                entries.append(FallbackEntry(provider=item, model=None))
            elif isinstance(item, dict):
                # Detailed format: provider + optional model
                provider = item.get('provider')
                model = item.get('model')
                if provider:
                    entries.append(FallbackEntry(provider=provider, model=model))
                else:
                    logger.warning(f"Invalid fallback entry (missing 'provider'): {item}")
            else:
                logger.warning(f"Invalid fallback entry type: {type(item)}")

        return entries

    def _call_provider(
        self,
        provider_name: str,
        client: Any,
        prompt: str,
        provider_config: Dict[str, Any],
        **kwargs
    ) -> Optional[LLMResponse]:
        """
        Dispatch a call to the appropriate provider using the registry.

        Args:
            provider_name: Name of the provider to call
            client: The provider client instance
            prompt: The prompt to send
            provider_config: Provider configuration
            **kwargs: Additional arguments

        Returns:
            LLMResponse or None if provider not found
        """
        call_method = self._provider_dispatch.get(provider_name)
        if call_method is None:
            logger.warning(f"Unsupported provider: {provider_name}")
            return None
        return call_method(client, prompt, provider_config, **kwargs)

    def _load_config(self, config_path: Path) -> Dict[str, Any]:
        """Load code_generation config from YAML."""
        try:
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f)

            code_gen_config = full_config.get('code_generation', {})
            if not code_gen_config:
                raise ValueError("No 'code_generation' section found in llm_config.yaml")

            # Expand environment variables in API keys
            providers = code_gen_config.get('providers', {})
            for provider_name, provider_config in providers.items():
                if 'api_key' in provider_config:
                    api_key = provider_config['api_key']
                    if isinstance(api_key, str) and api_key.startswith('${') and api_key.endswith('}'):
                        env_var = api_key[2:-1]
                        provider_config['api_key'] = os.getenv(env_var, '')

            return code_gen_config

        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            raise

    def _get_provider_client(self, provider: str):
        """Get or create provider client (lazy loading)."""
        if provider in self._clients:
            return self._clients[provider]

        providers_config = self.config.get('providers', {})
        provider_config = providers_config.get(provider, {})

        if not provider_config:
            raise ValueError(f"Provider '{provider}' not configured in code_generation section")

        # Import and create client based on provider
        if provider == 'ollama':
            import ollama
            self._clients[provider] = ollama.Client(
                host=provider_config.get('base_url', 'http://127.0.0.1:11434')
            )

        elif provider == 'openai':
            import openai
            api_key = provider_config.get('api_key', '')
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set in environment")
            base_url = provider_config.get('base_url', 'https://api.openai.com/v1')
            self._clients[provider] = openai.OpenAI(api_key=api_key, base_url=base_url)

        elif provider == 'anthropic':
            import anthropic
            api_key = provider_config.get('api_key', '')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set in environment")
            self._clients[provider] = anthropic.Anthropic(api_key=api_key)

        elif provider == 'gemini':
            import google.generativeai as genai
            api_key = provider_config.get('api_key', '')
            if not api_key:
                raise ValueError("GEMINI_API_KEY not set in environment")
            genai.configure(api_key=api_key)
            model_name = provider_config.get('model', 'gemini-2.0-flash-exp')
            self._clients[provider] = genai.GenerativeModel(model_name)

        elif provider == 'qwen':
            import openai
            api_key = provider_config.get('api_key', '')
            if not api_key:
                raise ValueError("QWEN_API_KEY not set in environment")
            base_url = provider_config.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
            self._clients[provider] = openai.OpenAI(api_key=api_key, base_url=base_url)

        else:
            raise ValueError(f"Unsupported provider: {provider}")

        return self._clients[provider]

    def _validate_response(self, response: str, context: str = "code") -> Tuple[bool, Optional[str]]:
        """
        Validate LLM response for completeness and structure.

        Args:
            response: The LLM response to validate
            context: Type of response ("code", "json", "text")

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not response or not response.strip():
            return False, "Empty response"

        # Minimum length check for code responses
        # JSON responses are validated separately (if it parses, it's valid)
        min_length = 50 if context == "code" else 10
        if len(response) < min_length:
            return False, f"Response too short ({len(response)} chars)"

        # Check for truncation indicators in text (legacy fallback)
        truncation_indicators = ['TRUNCATED', 'token limit exceeded', '...[truncated]']
        for indicator in truncation_indicators:
            if indicator.lower() in response.lower():
                return False, f"Response truncated: '{indicator}'"

        # Structural validation for SEARCH/REPLACE blocks
        if "<<<<<<< SEARCH" in response:
            search_count = response.count("<<<<<<< SEARCH")
            replace_count = response.count(">>>>>>> REPLACE")
            
            if search_count > replace_count:
                return False, "Response truncated: Unmatched SEARCH block (missing REPLACE tag)"
            
            # Check if the last block is complete (has ======= and >>>>>>> REPLACE)
            last_search_pos = response.rfind("<<<<<<< SEARCH")
            last_replace_pos = response.rfind(">>>>>>> REPLACE")
            
            if last_search_pos > last_replace_pos:
                 return False, "Response truncated: Incomplete SEARCH/REPLACE block at end"
                 
            # Also check if it has the separator
            last_separator_pos = response.rfind("=======")
            if last_separator_pos < last_search_pos:
                 return False, "Response truncated: Missing separator in last block"

        # Structural validation for Python-specific truncation (when context is code)
        if context == "code" and not "<<<<<<< SEARCH" in response:
            # Check for unclosed triple quotes (docstrings)
            for quote in ['"""', "'''"]:
                if response.count(quote) % 2 != 0:
                    return False, f"Response truncated: Unclosed Python docstring ({quote})"
            
            # Check if it ends mid-line or at a colon without body
            lines = response.strip().splitlines()
            if lines:
                raw_last_line = lines[-1]
                last_line = raw_last_line.strip()
                
                if not last_line:
                    return True, None
                
                # If it ends with a colon and common block starter, it's likely truncated
                if last_line.endswith(':') and any(last_line.startswith(w) for w in ['def ', 'class ', 'if ', 'else:', 'elif ', 'for ', 'while ', 'try:', 'except']):
                     return False, "Response truncated: Incomplete Python block (ends at colon)"
                
                # If it ends mid-word (no punctuation, no closing bracket, and last line is indented)
                # But only if it's a reasonably long block where truncation is likely
                if len(last_line) > 0 and last_line[-1].isalnum() and (raw_last_line.startswith(' ') or raw_last_line.startswith('\t')) and len(lines) > 5:
                     return False, "Response truncated: Incomplete Python line at end"

        return True, None

    def _format_thinking(self, content: str, reasoning: str, start_time: float) -> str:
        """
        Format reasoning content into a collapsible details block.
        
        Args:
            content: The main response content
            reasoning: The reasoning/thinking content
            start_time: Timestamp when generation started
            
        Returns:
            Formatted content string
        """
        if not reasoning:
            return content
            
        import time
        elapsed = time.time() - start_time
        thought_header = f"Thought for {elapsed:.1f}s"
        formatted_thinking = f"<details>\n<summary>{thought_header}</summary>\n\n{reasoning}\n</details>\n\n"
        return formatted_thinking + content

    def _call_ollama(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call local Ollama API."""
        import time
        start_time = time.time()
        try:
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 32768))
            model = config.get('model', 'deepseek-v3.2:cloud')

            timeout = config.get('timeout', 300)  # Default 5 minutes
            logger.info(f"🦙 Ollama request: model={model}, temp={temperature}, max_tokens={max_tokens}, timeout={timeout}s")

            # Use httpx timeout for Ollama client (handles long-running requests)
            import httpx

            # Get context window from config (check both naming conventions)
            context_window = config.get('context_window') or config.get('num_ctx', 32768)

            # Get think parameter from config (default False to disable thinking/reasoning output)
            # This matches the server implementation in llm_providers/ollama.py
            think_enabled = config.get('think', False)

            # Log the actual values being used
            think_status = "🧠 THINK ON" if think_enabled else "⚡ THINK OFF"
            logger.debug(f"Ollama options: num_predict={max_tokens}, num_ctx={context_window}, {think_status}")

            response = client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={
                    'temperature': temperature,
                    'num_predict': max_tokens,
                    'num_ctx': context_window,
                },
                think=think_enabled  # Top-level param like server implementation
            )
            # Note: Ollama Python library handles timeout internally via keep_alive
            # For external timeout control, the caller should use asyncio.wait_for or signal

            # Handle different response formats
            # Some models (like DeepSeek) use 'thinking' field, others use 'content'
            message = response.get('message', {})
            content = message.get('content', '')

            # Check specific 'thinking' field from Ollama response (DeepSeek style)
            # Some wrappers might put it in message.thinking, others in message.get('thinking')
            reasoning = ""
            
            # 1. Check top-level message object attributes
            if hasattr(message, 'thinking') and message.thinking:
                reasoning = message.thinking
            
            # 2. Check dictionary access if message is dict
            elif isinstance(message, dict) and message.get('thinking'):
                reasoning = message.get('thinking')
                
            # 3. Fallback: Check if content is empty but thinking is present (edge case)
            if not content and reasoning:
                # If only reasoning exists, treat it as content for now, or keep separate?
                # User wants to capture it. If content is empty, maybe the model only thought?
                pass

            # Format with thinking if present
            content = self._format_thinking(content, reasoning, start_time)

            return LLMResponse(
                content=content,
                provider='ollama',
                model=model,
                success=True,
                finish_reason=response.get('done_reason')
            )

        except Exception as e:
            error_str = str(e)
            logger.error(f"Ollama API error: {error_str}")

            # Provide more helpful error messages for common issues
            hint = ""
            if "context length" in error_str.lower():
                hint = " (prompt exceeds model's context window)"
            elif "max_tokens" in error_str.lower() or "num_predict" in error_str.lower():
                hint = " (response length limit exceeded)"
            elif "model" in error_str.lower() and "not found" in error_str.lower():
                hint = f" (model '{config.get('model')}' may not exist or be pulled)"
            elif "connection" in error_str.lower() or "refused" in error_str.lower():
                hint = " (is Ollama running? Check: ollama serve)"
            elif "timeout" in error_str.lower():
                hint = " (request timed out - model may be loading or overloaded)"

            return LLMResponse(
                content='',
                provider='ollama',
                model=config.get('model', 'unknown'),
                success=False,
                error=f"{error_str}{hint}"
            )

    def _call_openai(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call OpenAI API."""
        try:
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 32768))  # Increased for code gen
            model = config.get('model', 'gpt-4o-mini')

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=config.get('timeout', 300)
            )

            content = response.choices[0].message.content
            return LLMResponse(
                content=content,
                provider='openai',
                model=model,
                success=True,
                finish_reason=response.choices[0].finish_reason
            )

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return LLMResponse(
                content='',
                provider='openai',
                model=config.get('model', 'unknown'),
                success=False,
                error=str(e)
            )

    def _call_anthropic(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call Anthropic Claude API."""
        try:
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 32768))  # Increased for code gen
            model = config.get('model', 'claude-sonnet-4-20250514')

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text
            return LLMResponse(
                content=content,
                provider='anthropic',
                model=model,
                success=True,
                finish_reason=response.stop_reason
            )

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return LLMResponse(
                content='',
                provider='anthropic',
                model=config.get('model', 'unknown'),
                success=False,
                error=str(e)
            )

    def _call_gemini(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call Google Gemini API."""
        try:
            from google.generativeai.types import HarmCategory, HarmBlockThreshold

            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 32768))

            generation_config = {
                'temperature': temperature,
                'max_output_tokens': max_tokens,
            }

            # Disable safety settings for code generation
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE
            }

            response = client.generate_content(
                prompt,
                generation_config=generation_config,
                safety_settings=safety_settings
            )

            if not response.parts:
                # Log detailed error info
                block_reason = None
                try:
                    if hasattr(response, 'prompt_feedback'):
                        block_reason = str(response.prompt_feedback)
                    elif hasattr(response, 'candidates') and response.candidates:
                        block_reason = f"finish_reason={response.candidates[0].finish_reason}, safety={getattr(response.candidates[0], 'safety_ratings', 'unknown')}"
                except Exception:
                    pass
                
                error_detail = f"No content generated. Block reason: {block_reason}" if block_reason else "No content generated (empty response.parts)"
                logger.error(f"Gemini returned empty response for model {config.get('model')}: {error_detail}")
                
                return LLMResponse(
                    content='',
                    provider='gemini',
                    model=config.get('model', 'unknown'),
                    success=False,
                    error=error_detail
                )

            content = response.text
            finish_reason = None
            try:
                # Gemini finish_reason is an enum, 2 usually means length
                fr_val = response.candidates[0].finish_reason
                if fr_val == 2: finish_reason = "length"
                elif fr_val == 1: finish_reason = "stop"
                else: finish_reason = f"enum_{fr_val}"
            except Exception: pass

            return LLMResponse(
                content=content,
                provider='gemini',
                model=config.get('model'),
                success=True,
                finish_reason=finish_reason
            )

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return LLMResponse(
                content='',
                provider='gemini',
                model=config.get('model', 'unknown'),
                success=False,
                error=str(e)
            )

    def _call_qwen(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call Qwen API (OpenAI-compatible)."""
        import time
        start_time = time.time()
        try:
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 32768))  # Increased for code gen
            model = config.get('model', 'qwen-max')

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=config.get('timeout', 300)
            )

            message = response.choices[0].message
            content = message.content
            
            # Capture thinking/reasoning if available
            reasoning = getattr(message, 'reasoning_content', None)
            
            content = self._format_thinking(content, reasoning, start_time)

            return LLMResponse(
                content=content,
                provider='qwen',
                model=model,
                success=True,
                finish_reason=response.choices[0].finish_reason
            )

        except Exception as e:
            logger.error(f"Qwen API error: {e}")
            return LLMResponse(
                content='',
                provider='qwen',
                model=config.get('model', 'unknown'),
                success=False,
                error=str(e)
            )

    def generate(self, prompt: str, provider: Optional[str] = None, model: Optional[str] = None, system_prompt: Optional[str] = None, **kwargs) -> LLMResponse:
        """
        Generate code/text using LLM with automatic fallback.

        Args:
            prompt: The prompt to send to the LLM
            provider: Optional specific provider to use (overrides primary)
            model: Optional specific model to use (overrides config)
            system_prompt: Optional system prompt to set behavior/constraints
            **kwargs: Additional arguments (temperature, max_tokens)

        Returns:
            LLMResponse with generated content or error
        """
        # Build the list of FallbackEntry objects to try
        entries_to_try: List[FallbackEntry] = []

        if provider:
            # Start with the requested provider+model, then add remaining fallbacks
            requested_entry = FallbackEntry(provider=provider, model=model)
            entries_to_try.append(requested_entry)

            if self.fallback_enabled:
                # Add remaining entries that don't exactly match the request
                for entry in self.fallback_order:
                    if not (entry.provider == provider and entry.model == model):
                        entries_to_try.append(entry)
        else:
            # Use the full fallback order (first entry is the primary)
            entries_to_try = list(self.fallback_order)

            # If no fallback order defined, use primary provider
            if not entries_to_try:
                entries_to_try.append(FallbackEntry(provider=self.primary_provider, model=self.primary_model))

        # Try each provider+model combination
        tried_entries = []
        failed_entries = []  # Track failures for user notification
        is_fallback = False  # True if we're not on the first entry

        for idx, entry in enumerate(entries_to_try):
            provider_name = entry.provider
            model_override = entry.model
            is_fallback = idx > 0  # Not the primary provider

            logger.info(f"🤖 LLM CALL: Trying provider={provider_name}, model={model_override or 'default'}")
            tried_entries.append(str(entry))

            try:
                providers_config = self.config.get('providers', {})
                provider_config = providers_config.get(provider_name, {}).copy()  # Copy to avoid modifying original

                # Apply model override if specified in the fallback entry
                if model_override:
                    provider_config['model'] = model_override

                if not provider_config:
                    logger.warning(f"Provider '{provider_name}' not configured, skipping")
                    continue

                client = self._get_provider_client(provider_name)

                # Call provider using registry dispatch
                response = self._call_provider(provider_name, client, prompt, provider_config, **kwargs)
                if response is None:
                    logger.warning(f"Unsupported provider: {provider_name}")
                    continue

                if response.success:
                    # Validate response
                    # If response is valid JSON, accept it (LLM followed instructions)
                    # Only do structural validation for code (SEARCH/REPLACE blocks)
                    content_stripped = response.content.strip() if response.content else ""

                    # JSON responses: if it parses, it's valid
                    if content_stripped.startswith('{') or content_stripped.startswith('['):
                        try:
                            import json
                            json.loads(content_stripped)
                            is_valid, error = True, None  # Valid JSON = success
                        except json.JSONDecodeError:
                            is_valid, error = False, "Invalid JSON"
                    else:
                        # Code responses: check for truncation/structure
                        is_valid, error = self._validate_response(response.content, "code")
                    
                    # Handle truncation with auto-continuation
                    # Triggered if finish_reason is "length" (or variant) OR structural validation failed with "truncated"
                    is_truncated = (
                        (response.finish_reason in ("length", "max_tokens")) or
                        (not is_valid and error and "Response truncated" in error)
                    )

                    if is_truncated:
                        # Check if we already have usable SEARCH/REPLACE blocks
                        # If we have at least one complete block, skip continuation (it often corrupts output)
                        has_complete_block = (
                            "<<<<<<< SEARCH" in response.content and
                            "=======" in response.content and
                            ">>>>>>> REPLACE" in response.content
                        )

                        if has_complete_block:
                            # We have at least one complete block - use it as-is
                            # Continuation often produces garbage (repeated tags, malformed blocks)
                            logger.info(f"⚠️ Response truncated but has complete blocks - skipping continuation")
                            self.output(f"⚠️ Response truncated but has usable content - using as-is")
                            # Clean up any incomplete trailing block
                            content = response.content
                            last_search = content.rfind("<<<<<<< SEARCH")
                            last_replace = content.rfind(">>>>>>> REPLACE")
                            if last_search > last_replace:
                                # Incomplete block at end - remove it
                                content = content[:last_search].rstrip()
                                response.content = content
                                logger.info(f"   Removed incomplete trailing block")
                            return response

                        logger.info(f"⚠️ Truncation detected ({response.finish_reason or 'structural'}), attempting continuation...")
                        self.output(f"⚠️ Response truncated ({response.finish_reason or 'structural'}), attempting continuation...")
                        
                        full_content = response.content
                        
                        # Strip common truncation markers to prevent re-triggering validation failure
                        truncation_indicators = ['TRUNCATED', 'token limit exceeded', '...[truncated]', 'Response truncated:']
                        for indicator in truncation_indicators:
                            if indicator.lower() in full_content.lower():
                                # Case-insensitive replace would be better but let's be pragmatic
                                pattern = re.compile(re.escape(indicator), re.IGNORECASE)
                                full_content = pattern.sub('', full_content)
                        
                        continuation_success = False
                        
                        # Use same client and config for continuation
                        for i in range(3):  # Max 3 continuations
                            # Check for interrupt before each continuation attempt
                            try:
                                from ..tui.agent_runner import _interrupt_requested
                                if _interrupt_requested:
                                    logger.info("   ⚠️ Interrupt requested - aborting continuation")
                                    self.output("   ⚠️ Interrupt requested - aborting continuation")
                                    break
                            except ImportError:
                                pass  # Not running in TUI context

                            # Construct continuation prompt
                            # We take the last 1000 chars for context to ensure LLM knows where it was
                            last_context = full_content[-1000:]
                            cont_prompt = f"""[SYSTEM: CONTINUATION REQUEST]
You were generating a response but were cut off by the output token limit.

PREVIOUS OUTPUT ENDED WITH:
---
{last_context}
---

TASK:
Continue generating the output EXACTLY where you left off.
- Do NOT repeat the previous output.
- Do NOT add explanations or preamble.
- Start IMMEDIATELY with the next character needed to complete the previous block.
- Ensure the syntax (especially SEARCH/REPLACE blocks) is perfectly maintained.
"""

                            logger.info(f"   🔄 Continuation attempt {i+1}/3...")
                            self.output(f"   🔄 Continuation attempt {i+1}/3...")

                            # Call provider again using registry dispatch
                            cont_resp = self._call_provider(provider_name, client, cont_prompt, provider_config, **kwargs)
                            if cont_resp is None:
                                break

                            if cont_resp.success and cont_resp.content:
                                # Check for garbage continuation (repeated tags)
                                cont_content = cont_resp.content
                                if cont_content.count(">>>>>>> REPLACE") > 2:
                                    logger.warning(f"   ❌ Continuation produced garbage (repeated REPLACE tags) - aborting")
                                    self.output(f"   ❌ Continuation corrupted - using original response")
                                    break

                                # Append content
                                full_content += cont_content
                                logger.info(f"   ✅ Appended {len(cont_content)} chars")
                                self.output(f"   ✅ Appended {len(cont_content)} chars")
                                
                                # Validate combined result
                                is_valid, error = self._validate_response(full_content)
                                if is_valid:
                                    response.content = full_content
                                    continuation_success = True
                                    logger.info(f"   ✅ Full response validated ({len(full_content)} chars)")
                                    self.output(f"   ✅ Full response validated ({len(full_content)} chars)")
                                    break
                                
                                # Check if still truncated
                                still_truncated = (
                                    (cont_resp.finish_reason in ("length", "max_tokens")) or
                                    (not is_valid and error and "Response truncated" in error)
                                )
                                
                                if still_truncated:
                                    # Still truncated, continue loop
                                    continue
                                else:
                                    # Other validation error (e.g. syntax broken during stitch)
                                    logger.warning(f"   ❌ Continuation merged invalid: {error}")
                                    break
                            else:
                                logger.warning(f"   ❌ Continuation failed: {cont_resp.error}")
                                break
                        
                        if not continuation_success:
                            logger.warning(f"Failed to resolve truncation for {provider_name}")
                            # We still try to return the partial if it's better than nothing? 
                            # Or skip to next provider? Usually skip to next provider is safer in fallback mode.
                            continue
                            
                    elif not is_valid:
                        logger.warning(f"Response validation failed: {error}")
                        continue

                    # Strip thinking/reasoning content from response
                    # This handles chain-of-thought, <thinking> tags, model markers, etc.
                    original_len = len(response.content)
                    response.content = strip_thinking_content(response.content)
                    if len(response.content) < original_len:
                        logger.info(f"   Stripped {original_len - len(response.content)} bytes of thinking content")

                    # Notify user if we used a fallback provider
                    if is_fallback:
                        fallback_msg = f"⚠️ FALLBACK: Primary failed, using {provider_name}/{response.model}"
                        logger.warning(fallback_msg)
                        self.output(fallback_msg)
                        if failed_entries:
                            failed_msg = f"   Failed providers: {', '.join(failed_entries)}"
                            logger.info(failed_msg)
                            self.output(failed_msg)

                    logger.info(f"✅ Generated {len(response.content)} chars using {provider_name}/{response.model}")
                    return response
                else:
                    error_msg = response.error or "Unknown error"
                    logger.warning(f"Provider {provider_name} failed: {error_msg}")
                    failed_entries.append(f"{entry} ({error_msg[:50]})")
                    # Notify user about the failure and upcoming fallback
                    if idx < len(entries_to_try) - 1:
                        next_entry = entries_to_try[idx + 1]
                        fallback_notice = f"⚠️ {provider_name} failed: {error_msg[:80]}. Trying fallback: {next_entry}"
                        logger.info(fallback_notice)
                        self.output(fallback_notice)

            except Exception as e:
                error_str = str(e)[:80]
                logger.error(f"Error with provider {provider_name}: {e}")
                failed_entries.append(f"{entry} (Exception: {error_str})")
                # Notify user about the exception and upcoming fallback
                if idx < len(entries_to_try) - 1:
                    next_entry = entries_to_try[idx + 1]
                    fallback_notice = f"⚠️ {provider_name} error: {error_str}. Trying fallback: {next_entry}"
                    logger.warning(fallback_notice)
                    self.output(fallback_notice)
                continue

        # All providers failed
        error_msg = f"All providers failed. Tried: {tried_entries}"
        logger.error(error_msg)

        # Notify user about complete failure
        self.output(f"❌ ALL LLM PROVIDERS FAILED")
        for failed in failed_entries:
            self.output(f"   • {failed}")

        return LLMResponse(
            content='',
            provider='none',
            model='none',
            success=False,
            error=error_msg
        )

    def generate_tools(self, prompt: str, tools: List[Dict], system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Generate tool calls using NATIVE LLM tool-calling API.

        This uses the provider's built-in tool calling capability (e.g., Ollama /api/chat with tools),
        NOT text generation with JSON parsing. This is the same pattern used by the working
        RAICA server in fastapi_server_complete.py.

        Args:
            prompt: The user's request/instruction
            tools: List of tool definitions in OpenAI function format:
                   [{"name": "tool_name", "description": "...", "parameters": {...}}, ...]
            system_prompt: Optional system prompt for tool-calling behavior
            **kwargs: Additional arguments (temperature, max_tokens)

        Returns:
            Dict with:
                - tool_calls: List of tool calls from LLM
                - content: Any text content from LLM
                - model: Model used
                - success: Boolean
                - error: Error message if failed
        """
        provider_name = self.primary_provider

        try:
            providers_config = self.config.get('providers', {})
            provider_config = providers_config.get(provider_name, {}).copy()
            model = provider_config.get('model', 'deepseek-v3.2:cloud')

            logger.info(f"🔧 TOOL CALLING: provider={provider_name}, model={model}, tools={len(tools)}")

            if provider_name == 'ollama':
                return self._call_ollama_tools(prompt, tools, provider_config, system_prompt, **kwargs)
            elif provider_name == 'openai':
                return self._call_openai_tools(prompt, tools, provider_config, system_prompt, **kwargs)
            else:
                # Fallback: use text generation with JSON parsing (less reliable)
                logger.warning(f"Provider {provider_name} doesn't have native tool calling, falling back to text generation")
                return self._fallback_text_tool_calling(prompt, tools, system_prompt, **kwargs)

        except Exception as e:
            logger.error(f"Tool calling error: {e}")
            return {
                'tool_calls': [],
                'content': '',
                'model': provider_config.get('model', 'unknown') if 'provider_config' in dir() else 'unknown',
                'success': False,
                'error': str(e)
            }

    def _call_ollama_tools(self, prompt: str, tools: List[Dict], config: Dict[str, Any],
                           system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Call Ollama with native tool calling support.

        Uses Ollama's /api/chat endpoint with the 'tools' parameter - same as
        the working implementation in llm_providers/ollama.py.
        """
        import time
        start_time = time.time()

        try:
            model = config.get('model', 'deepseek-v3.2:cloud')
            temperature = kwargs.get('temperature', 0.1)  # Low temp for tool calling
            context_window = config.get('context_window') or config.get('num_ctx', 32768)
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 16000))

            client = self._get_provider_client('ollama')

            # Format tools for Ollama - handle both wrapped and unwrapped formats
            formatted_tools = []
            for tool in tools:
                # Check if already wrapped in {"type": "function", "function": {...}}
                if tool.get('type') == 'function' and 'function' in tool:
                    formatted_tools.append(tool)  # Already in correct format
                else:
                    # Wrap in function format
                    formatted_tools.append({
                        "type": "function",
                        "function": tool
                    })

            # Build messages with system prompt
            messages = []
            if system_prompt:
                # Add enhanced tool-calling instructions
                # CRITICAL: LLM must CALL TOOLS via API, not respond with text
                enhanced_system = system_prompt + """

EXECUTE TOOLS NOW. DO NOT RESPOND WITH TEXT.
You have tools available. USE THEM. Call the tools to complete the task.
"""
                messages.append({"role": "system", "content": enhanced_system})
            messages.append({"role": "user", "content": prompt})

            # Get think parameter from config (default False for tool calling)
            think_enabled = config.get('think', False)
            think_status = "🧠 THINK ON" if think_enabled else "⚡ THINK OFF"
            logger.info(f"🦙 Ollama TOOL request: model={model}, tools={len(formatted_tools)}, num_ctx={context_window}, {think_status}")

            # Call Ollama with tools parameter
            response = client.chat(
                model=model,
                messages=messages,
                tools=formatted_tools,
                options={
                    'temperature': temperature,
                    'num_predict': max_tokens,
                    'num_ctx': context_window,
                },
                think=think_enabled  # Top-level param like server implementation
            )

            elapsed = time.time() - start_time

            # Extract tool calls from response
            message = response.get('message', {}) or {}
            tool_calls = message.get('tool_calls') or []
            content = message.get('content') or ''

            logger.info(f"🔧 Ollama TOOL response: {len(tool_calls)} tool calls, {len(content)} chars content, {elapsed:.1f}s")

            # DEBUG: Log raw Ollama response
            print(f"   🦙 OLLAMA RAW TOOL CALLS: {tool_calls}")
            if content:
                print(f"   🦙 OLLAMA CONTENT: {content[:300]}...")

            # Normalize tool call format to standard structure
            normalized_calls = []
            for tc in tool_calls:
                func = tc.get('function', {})
                tool_name = func.get('name', '')
                tool_args = func.get('arguments', {})
                print(f"   🦙 Normalizing: {tc} -> tool={tool_name}, args={tool_args}")
                normalized_calls.append({
                    'tool': tool_name,
                    'args': tool_args
                })

            return {
                'tool_calls': normalized_calls,
                'content': content,
                'model': model,
                'success': True,
                'error': None
            }

        except Exception as e:
            logger.error(f"Ollama tool calling error: {e}")
            return {
                'tool_calls': [],
                'content': '',
                'model': config.get('model', 'unknown'),
                'success': False,
                'error': str(e)
            }

    def _call_openai_tools(self, prompt: str, tools: List[Dict], config: Dict[str, Any],
                           system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Call OpenAI with native tool calling support.
        """
        try:
            model = config.get('model', 'gpt-4o-mini')
            temperature = kwargs.get('temperature', 0.1)
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 16000))

            client = self._get_provider_client('openai')

            # Format tools for OpenAI - handle both wrapped and unwrapped formats
            formatted_tools = []
            for tool in tools:
                if tool.get('type') == 'function' and 'function' in tool:
                    formatted_tools.append(tool)  # Already in correct format
                else:
                    formatted_tools.append({"type": "function", "function": tool})

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            logger.info(f"🤖 OpenAI TOOL request: model={model}, tools={len(formatted_tools)}")

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=formatted_tools,
                tool_choice="auto",
                temperature=temperature,
                max_tokens=max_tokens
            )

            # Extract tool calls
            message = response.choices[0].message
            tool_calls = []

            if message.tool_calls:
                for tc in message.tool_calls:
                    import json
                    tool_calls.append({
                        'tool': tc.function.name,
                        'args': json.loads(tc.function.arguments) if tc.function.arguments else {}
                    })

            return {
                'tool_calls': tool_calls,
                'content': message.content or '',
                'model': model,
                'success': True,
                'error': None
            }

        except Exception as e:
            logger.error(f"OpenAI tool calling error: {e}")
            return {
                'tool_calls': [],
                'content': '',
                'model': config.get('model', 'unknown'),
                'success': False,
                'error': str(e)
            }

    def _fallback_text_tool_calling(self, prompt: str, tools: List[Dict],
                                     system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Fallback: Use text generation with JSON parsing for providers without native tool calling.
        This is less reliable than native tool calling.
        """
        import json

        # Build tool schema for prompt
        tool_schema = json.dumps(tools, indent=2)

        full_prompt = f"""You are a tool-calling agent. You MUST respond with JSON only.

AVAILABLE TOOLS:
{tool_schema}

TASK: {prompt}

Respond with ONLY this JSON format (no other text):
{{"tool_calls": [{{"tool": "TOOL_NAME", "args": {{...}}}}]}}
"""

        response = self.generate(full_prompt, system_prompt=system_prompt, **kwargs)

        if not response.success:
            return {
                'tool_calls': [],
                'content': '',
                'model': response.model,
                'success': False,
                'error': response.error
            }

        # Try to parse JSON from response
        content = response.content.strip()
        try:
            # Extract JSON if wrapped in markdown
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()

            data = json.loads(content)
            tool_calls = data.get('tool_calls', [])

            return {
                'tool_calls': tool_calls,
                'content': response.content,
                'model': response.model,
                'success': True,
                'error': None
            }
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool calls from text response: {e}")
            return {
                'tool_calls': [],
                'content': response.content,
                'model': response.model,
                'success': False,
                'error': f"JSON parse error: {e}"
            }

    def generate_for_classification(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> LLMResponse:
        """
        Generate response for classification tasks that require strict JSON output.
        Uses the classification_model override if configured, otherwise uses primary model.

        Args:
            prompt: The classification prompt
            system_prompt: Optional system prompt
            **kwargs: Additional arguments

        Returns:
            LLMResponse with JSON content
        """
        # Use classification model if configured
        if hasattr(self, 'classification_model') and self.classification_model:
            return self.generate(
                prompt,
                provider=self.classification_provider,
                model=self.classification_model,
                system_prompt=system_prompt,
                **kwargs
            )
        else:
            # Fallback to primary model
            return self.generate(prompt, system_prompt=system_prompt, **kwargs)

    def generate_json(
        self,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Generate structured JSON output with optional schema validation.
        
        Uses provider-specific JSON modes where available:
        - OpenAI: response_format={"type": "json_object"}
        - Ollama: format="json"
        - Others: Prompt engineering with JSON extraction
        
        Args:
            prompt: The prompt to send (will be augmented with JSON instructions)
            schema: Optional JSON schema for validation
            provider: Optional specific provider to use
            model: Optional specific model to use
            **kwargs: Additional arguments (temperature, max_tokens)
            
        Returns:
            Tuple of (parsed_json, error_message)
            - On success: (dict, None)
            - On failure: (None, error_string)
        """
        import json
        
        # Augment prompt with JSON instructions
        schema_instruction = ""
        if schema:
            schema_instruction = f"\n\nYour response MUST conform to this JSON schema:\n```json\n{json.dumps(schema, indent=2)}\n```"
        
        json_prompt = f"""{prompt}

CRITICAL: Respond with ONLY valid JSON. No markdown, no explanations, no code fences.
Start your response with {{ and end with }}.{schema_instruction}"""

        # Set JSON mode hints for providers that support it
        json_kwargs = kwargs.copy()
        json_kwargs['_json_mode'] = True  # Internal flag for provider methods
        
        # Generate response
        response = self.generate(json_prompt, provider=provider, model=model, **json_kwargs)
        
        if not response.success:
            return None, response.error or "LLM request failed"
        
        content = response.content.strip()
        
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                content = content[start:end].strip()
        
        # Find JSON object boundaries
        if not content.startswith('{'):
            json_start = content.find('{')
            json_end = content.rfind('}')
            if json_start != -1 and json_end > json_start:
                content = content[json_start:json_end + 1]
        
        # Parse JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e}"
        
        # Validate against schema if provided
        if schema:
            try:
                import jsonschema
                jsonschema.validate(parsed, schema)
            except ImportError:
                logger.warning("jsonschema not installed - skipping schema validation")
            except jsonschema.ValidationError as e:
                return None, f"Schema validation failed: {e.message}"
        
        return parsed, None

    def get_config_info(self) -> Dict[str, Any]:
        """Get configuration information for display."""
        providers_config = self.config.get('providers', {})
        primary_config = providers_config.get(self.primary_provider, {})

        # Use the preset model if selected, otherwise fall back to provider config
        model = self.primary_model or primary_config.get('model', 'unknown')

        info = {
            'primary_provider': self.primary_provider,
            'primary_model': model,
            'fallback_enabled': self.fallback_enabled,
            'fallback_order': self.fallback_order,
            'temperature': primary_config.get('temperature', 0.0),
            'max_tokens': primary_config.get('max_tokens', 32768),
            'config_path': str(self.config_path)
        }

        # Include preset info if using model presets
        if self._selected_preset:
            info['selected_preset'] = self._selected_preset
            info['available_presets'] = list(self.config.get('model_presets', {}).keys())

        return info

    def list_available_presets(self) -> Dict[str, Dict[str, str]]:
        """
        List all available model presets.

        Returns:
            Dict mapping preset names to their provider/model info
        """
        presets = self.config.get('model_presets', {})
        return {
            name: {
                'provider': preset.get('provider', 'unknown'),
                'model': preset.get('model', 'unknown')
            }
            for name, preset in presets.items()
        }

    def test_connection(self) -> Tuple[bool, str]:
        """
        Test connection to the primary provider.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Use a simple test that doesn't trigger validation issues
            providers_config = self.config.get('providers', {})
            provider_config = providers_config.get(self.primary_provider, {})

            if not provider_config:
                return False, f"Primary provider '{self.primary_provider}' not configured"

            client = self._get_provider_client(self.primary_provider)
            # Use the selected preset model (self.primary_model) if set,
            # otherwise fall back to provider's default model
            model = self.primary_model or provider_config.get('model', 'unknown')

            # Make a simple test call
            if self.primary_provider == 'ollama':
                response = client.chat(
                    model=model,
                    messages=[{"role": "user", "content": "Reply with just 'ok'"}],
                    options={'num_predict': 50}
                )
                # Handle different response formats (DeepSeek uses thinking, others use content)
                message = response.get('message', {}) if response else {}
                content = ''
                if hasattr(message, 'content') and message.content:
                    content = message.content
                elif hasattr(message, 'thinking') and message.thinking:
                    content = message.thinking
                elif isinstance(message, dict):
                    content = message.get('content', '') or message.get('thinking', '')

                if content:
                    return True, f"Connected to {self.primary_provider}/{model}"
                else:
                    return False, "Empty response from Ollama"

            elif self.primary_provider == 'openai':
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Reply with just 'ok'"}],
                    max_tokens=10
                )
                if response.choices[0].message.content:
                    return True, f"Connected to {self.primary_provider}/{model}"
                else:
                    return False, "Empty response from OpenAI"

            elif self.primary_provider == 'anthropic':
                response = client.messages.create(
                    model=model,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Reply with just 'ok'"}]
                )
                if response.content[0].text:
                    return True, f"Connected to {self.primary_provider}/{model}"
                else:
                    return False, "Empty response from Anthropic"

            elif self.primary_provider == 'gemini':
                response = client.generate_content("Reply with just 'ok'")
                if response.text:
                    return True, f"Connected to {self.primary_provider}/{model}"
                else:
                    return False, "Empty response from Gemini"

            else:
                # Generic test using the generate method
                response = self.generate("Reply with 'hello'", max_tokens=50)
                if response.success and response.content:
                    return True, f"Connected to {response.provider}/{response.model}"
                else:
                    return False, f"Connection failed: {response.error}"

        except Exception as e:
            return False, f"Connection error: {e}"
