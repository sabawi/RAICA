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


@dataclass
class FallbackEntry:
    """Represents a provider+model pair in the fallback chain."""
    provider: str
    model: Optional[str] = None  # None means use default from provider config

    def __str__(self):
        if self.model:
            return f"{self.provider}/{self.model}"
        return self.provider


class CodeGenLLMClient:
    """
    LLM client for code generation using the code_generation config.

    Supports multiple providers with automatic fallback.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None
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

        logger.info(f"CodeGenLLMClient initialized")
        logger.info(f"  Primary provider: {self.primary_provider}")
        if provider_override:
            logger.info(f"  Provider override: {provider_override}")
        if model_override:
            logger.info(f"  Model override: {model_override}")
        logger.info(f"  Fallback enabled: {self.fallback_enabled}")
        if self.fallback_enabled:
            fallback_str = ', '.join(str(e) for e in self.fallback_order)
            logger.info(f"  Fallback order: [{fallback_str}]")

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
        Validate LLM response for completeness.

        Args:
            response: The LLM response to validate
            context: Type of response ("code", "json", "text")

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not response or not response.strip():
            return False, "Empty response"

        # Minimum length check
        min_lengths = {"code": 50, "json": 20, "text": 10}
        min_length = min_lengths.get(context, 30)
        if len(response) < min_length:
            return False, f"Response too short ({len(response)} chars)"

        # Check for truncation indicators
        truncation_indicators = ['TRUNCATED', 'token limit exceeded', '...[truncated]']
        for indicator in truncation_indicators:
            if indicator.lower() in response.lower():
                return False, f"Response truncated: '{indicator}'"

        return True, None

    def _call_ollama(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call local Ollama API."""
        try:
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 32768))
            model = config.get('model', 'deepseek-v3.2:cloud')

            logger.info(f"🦙 Ollama request: model={model}, temp={temperature}, max_tokens={max_tokens}")

            response = client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={
                    'temperature': temperature,
                    'num_predict': max_tokens,
                    'num_ctx': config.get('context_window', 131072),
                }
            )

            # Handle different response formats
            # Some models (like DeepSeek) use 'thinking' field, others use 'content'
            message = response.get('message', {})
            content = message.get('content', '')

            # If content is empty but thinking exists (DeepSeek format), use thinking
            if not content and hasattr(message, 'thinking') and message.thinking:
                content = message.thinking
            elif not content and isinstance(message, dict) and message.get('thinking'):
                content = message.get('thinking', '')

            # For Message objects that have attributes
            if not content and hasattr(message, 'content'):
                content = message.content or ''
            if not content and hasattr(message, 'thinking'):
                content = message.thinking or ''

            return LLMResponse(
                content=content,
                provider='ollama',
                model=model,
                success=True
            )

        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            return LLMResponse(
                content='',
                provider='ollama',
                model=config.get('model', 'unknown'),
                success=False,
                error=str(e)
            )

    def _call_openai(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call OpenAI API."""
        try:
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 16384))
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
                success=True
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
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 8192))
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
                success=True
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
                return LLMResponse(
                    content='',
                    provider='gemini',
                    model=config.get('model', 'unknown'),
                    success=False,
                    error="No content generated"
                )

            content = response.text
            return LLMResponse(
                content=content,
                provider='gemini',
                model=config.get('model'),
                success=True
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
        try:
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 8000))
            model = config.get('model', 'qwen-max')

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
                provider='qwen',
                model=model,
                success=True
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

    def generate(self, prompt: str, provider: Optional[str] = None, model: Optional[str] = None, **kwargs) -> LLMResponse:
        """
        Generate code/text using LLM with automatic fallback.

        Args:
            prompt: The prompt to send to the LLM
            provider: Optional specific provider to use (overrides primary)
            model: Optional specific model to use (overrides config)
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
        for entry in entries_to_try:
            provider_name = entry.provider
            model_override = entry.model

            logger.info(f"Trying: {entry}")
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
                    is_valid, error = self._validate_response(response.content)
                    
                    # Handle truncation with auto-continuation
                    if not is_valid and error and "Response truncated" in error:
                        logger.info(f"⚠️ Truncation detected from {provider_name}, attempting continuation...")
                        
                        full_content = response.content
                        
                        # Strip common truncation markers to prevent re-triggering validation failure
                        truncation_indicators = ['TRUNCATED', 'token limit exceeded', '...[truncated]']
                        for indicator in truncation_indicators:
                            # Use case-insensitive replacement if possible, but simple string replace for now
                            # The validation uses lower(), so we should be careful.
                            # But usually the LLM outputs it verbatim as prompted or system message.
                            if indicator in full_content:
                                full_content = full_content.replace(indicator, '')
                        
                        continuation_success = False
                        
                        # Use same client and config for continuation
                        for i in range(3):  # Max 3 continuations
                            # Construct continuation prompt
                            last_chars = full_content[-500:] # Context for continuity
                            cont_prompt = f"""You were generating code but hit the output limit. 
The previous output ended with:
```
{last_chars}
```

TASK:
Continue generating the code EXACTLY where you left off. 
- Do NOT repeat the code above.
- Do NOT output any explanation.
- Start immediately with the next character of code.
- Ensure the syntax connects perfectly with the previous output."""

                            logger.info(f"   🔄 Continuation attempt {i+1}/3...")

                            # Call provider again using registry dispatch
                            cont_resp = self._call_provider(provider_name, client, cont_prompt, provider_config, **kwargs)
                            if cont_resp is None:
                                break

                            if cont_resp.success and cont_resp.content:
                                # Append content
                                full_content += cont_resp.content
                                logger.info(f"   ✅ Appended {len(cont_resp.content)} chars")
                                
                                # Validate combined result
                                is_valid, error = self._validate_response(full_content)
                                if is_valid:
                                    response.content = full_content
                                    continuation_success = True
                                    logger.info(f"   ✅ Full response validated ({len(full_content)} chars)")
                                    break
                                elif "Response truncated" in str(error):
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
                            continue
                            
                    elif not is_valid:
                        logger.warning(f"Response validation failed: {error}")
                        continue

                    logger.info(f"✅ Generated {len(response.content)} chars using {provider_name}/{response.model}")
                    return response
                else:
                    logger.warning(f"Provider {provider_name} failed: {response.error}")

            except Exception as e:
                logger.error(f"Error with provider {provider_name}: {e}")
                continue

        # All providers failed
        error_msg = f"All providers failed. Tried: {tried_entries}"
        logger.error(error_msg)
        return LLMResponse(
            content='',
            provider='none',
            model='none',
            success=False,
            error=error_msg
        )

    def get_config_info(self) -> Dict[str, Any]:
        """Get configuration information for display."""
        providers_config = self.config.get('providers', {})
        primary_config = providers_config.get(self.primary_provider, {})

        return {
            'primary_provider': self.primary_provider,
            'primary_model': primary_config.get('model', 'unknown'),
            'fallback_enabled': self.fallback_enabled,
            'fallback_order': self.fallback_order,
            'temperature': primary_config.get('temperature', 0.0),
            'max_tokens': primary_config.get('max_tokens', 32768),
            'config_path': str(self.config_path)
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
            model = provider_config.get('model', 'unknown')

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
