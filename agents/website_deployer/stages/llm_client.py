#!/usr/bin/env python3
"""
Multi-Provider LLM Client for Website Deployment Agent
=======================================================

Unified interface for multiple LLM providers:
- Anthropic Claude
- OpenAI GPT
- Google Gemini
- Qwen
- Local Ollama

Reads configuration from central config/llm_config.yaml (code_generation section)

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import os
import yaml
import time
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
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


class LLMClient:
    """
    Unified LLM client supporting multiple providers with automatic fallback.

    Supports:
    - Anthropic Claude
    - OpenAI GPT
    - Google Gemini
    - Qwen
    - Ollama (local)
    """

    def __init__(self, config_path: Optional[Path] = None, response_cache=None):
        """
        Initialize LLM client.

        Args:
            config_path: Path to llm_config.yaml (defaults to project config)
            response_cache: Optional ResponseCache for caching/replaying responses
        """
        if config_path is None:
            # Default to project's central config
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "llm_config.yaml"

        self.config = self._load_config(config_path)
        self.primary_provider = self.config.get('type', 'anthropic')
        self.fallback_enabled = self.config.get('fallback', {}).get('enabled', True)
        self.fallback_order = self.config.get('fallback', {}).get('order', [self.primary_provider])
        self.response_cache = response_cache

        # Initialize provider clients (lazy loading)
        self._clients = {}

        logger.info(f"LLMClient initialized with primary provider: {self.primary_provider}")
        if self.fallback_enabled:
            logger.info(f"Fallback enabled with order: {self.fallback_order}")
        if self.response_cache:
            logger.info(f"Response caching enabled in '{self.response_cache.mode}' mode")

    def _validate_response(self, response: str, context: str = "code") -> Tuple[bool, Optional[str]]:
        """
        Validate LLM response for completeness and quality.

        This catches:
        - Empty or too-short responses
        - Truncation indicators
        - Incomplete code patterns
        - Token limit errors

        Args:
            response: The LLM response to validate
            context: Type of response ("code", "json", "text")

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not response or not response.strip():
            return False, "Empty response"

        # Minimum length check (context-dependent)
        min_lengths = {"code": 100, "json": 20, "text": 10}
        min_length = min_lengths.get(context, 50)
        if len(response) < min_length:
            return False, f"Response too short ({len(response)} chars, minimum {min_length})"

        # Check for explicit truncation indicators
        truncation_indicators = [
            'TRUNCATED',
            'token limit exceeded',
            'maximum length exceeded',
            '...[truncated]',
            'Response cut off',
            'output limit reached',
        ]
        for indicator in truncation_indicators:
            if indicator.lower() in response.lower():
                return False, f"Response contains truncation indicator: '{indicator}'"

        # For code responses, check for incomplete patterns
        if context == "code":
            # Check for balanced braces/brackets/parentheses
            if response.count('{') != response.count('}'):
                return False, f"Unbalanced braces ({{ {response.count('{')} vs }} {response.count('}')})"

            if response.count('(') != response.count(')'):
                return False, f"Unbalanced parentheses"

            if response.count('[') != response.count(']'):
                return False, f"Unbalanced brackets"

            # Check for common incomplete code endings
            incomplete_endings = [
                r'\.\.\.$',  # Ends with "..."
                r'#\s*TODO:?\s*$',  # Ends with # TODO
                r'#\s*\.\.\.\s*$',  # Ends with # ...
                r'pass\s*#\s*incomplete\s*$',  # pass # incomplete
            ]
            for pattern in incomplete_endings:
                if re.search(pattern, response.strip(), re.IGNORECASE):
                    return False, f"Response ends with incomplete code pattern: {pattern}"

        # For JSON responses, basic validation
        if context == "json":
            import json
            try:
                json.loads(response)
            except json.JSONDecodeError as e:
                return False, f"Invalid JSON: {e}"

        return True, None

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
                    if api_key.startswith('${') and api_key.endswith('}'):
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
            raise ValueError(f"Provider '{provider}' not configured")

        # Import and create client based on provider
        if provider == 'anthropic':
            import anthropic
            api_key = provider_config.get('api_key', '')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set in environment")
            self._clients[provider] = anthropic.Anthropic(api_key=api_key)

        elif provider == 'openai':
            import openai
            api_key = provider_config.get('api_key', '')
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set in environment")
            base_url = provider_config.get('base_url', 'https://api.openai.com/v1')
            self._clients[provider] = openai.OpenAI(api_key=api_key, base_url=base_url)

        elif provider == 'gemini':
            import google.generativeai as genai
            api_key = provider_config.get('api_key', '')
            if not api_key:
                raise ValueError("GEMINI_API_KEY not set in environment")
            genai.configure(api_key=api_key)
            model_name = provider_config.get('model', 'gemini-2.0-flash-exp')
            self._clients[provider] = genai.GenerativeModel(model_name)

        elif provider == 'qwen':
            # Qwen uses OpenAI-compatible API
            import openai
            api_key = provider_config.get('api_key', '')
            if not api_key:
                raise ValueError("QWEN_API_KEY not set in environment")
            base_url = provider_config.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
            self._clients[provider] = openai.OpenAI(api_key=api_key, base_url=base_url)

        elif provider == 'ollama':
            import ollama
            self._clients[provider] = ollama.Client(
                host=provider_config.get('base_url', 'http://127.0.0.1:11434')
            )

        else:
            raise ValueError(f"Unsupported provider: {provider}")

        return self._clients[provider]

    def _call_anthropic(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call Anthropic Claude API."""
        try:
            # Merge config with kwargs (kwargs take precedence)
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 4096))
            
            response = client.messages.create(
                model=config.get('model', 'claude-sonnet-4-20250514'),
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text
            return LLMResponse(
                content=content,
                provider='anthropic',
                model=config.get('model'),
                success=True
            )

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return LLMResponse(
                content='',
                provider='anthropic',
                model=config.get('model'),
                success=False,
                error=str(e)
            )

    def _call_openai(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call OpenAI GPT API."""
        try:
            # Merge config with kwargs
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 4096))
            
            response = client.chat.completions.create(
                model=config.get('model', 'gpt-4o'),
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=config.get('timeout', 120)
            )

            content = response.choices[0].message.content
            return LLMResponse(
                content=content,
                provider='openai',
                model=config.get('model'),
                success=True
            )

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return LLMResponse(
                content='',
                provider='openai',
                model=config.get('model'),
                success=False,
                error=str(e)
            )

    def _call_gemini(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call Google Gemini API."""
        try:
            from google.generativeai.types import HarmCategory, HarmBlockThreshold

            # Merge config with kwargs
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 8192))

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

            # Check if response was blocked
            if not response.parts:
                finish_reason = response.candidates[0].finish_reason if response.candidates else None
                error_msg = f"No content generated (finish_reason: {finish_reason})"
                logger.error(f"Gemini API error: {error_msg}")
                return LLMResponse(
                    content='',
                    provider='gemini',
                    model=config.get('model'),
                    success=False,
                    error=error_msg
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
                model=config.get('model'),
                success=False,
                error=str(e)
            )

    def _call_qwen(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call Qwen API (OpenAI-compatible)."""
        try:
            # Merge config with kwargs
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 6000))
            
            response = client.chat.completions.create(
                model=config.get('model', 'qwen-max'),
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=config.get('timeout', 120)
            )

            content = response.choices[0].message.content
            return LLMResponse(
                content=content,
                provider='qwen',
                model=config.get('model'),
                success=True
            )

        except Exception as e:
            logger.error(f"Qwen API error: {e}")
            return LLMResponse(
                content='',
                provider='qwen',
                model=config.get('model'),
                success=False,
                error=str(e)
            )

    def _call_ollama(self, client, prompt: str, config: Dict[str, Any], **kwargs) -> LLMResponse:
        """Call local Ollama API."""
        try:
            # Merge config with kwargs
            temperature = kwargs.get('temperature', config.get('temperature', 0.0))
            max_tokens = kwargs.get('max_tokens', config.get('max_tokens', 4096))
            
            response = client.chat(
                model=config.get('model', 'qwen2.5:72b'),
                messages=[{"role": "user", "content": prompt}],
                options={
                    'temperature': temperature,
                    'num_predict': max_tokens,
                }
            )

            content = response['message']['content']
            return LLMResponse(
                content=content,
                provider='ollama',
                model=config.get('model'),
                success=True
            )

        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            return LLMResponse(
                content='',
                provider='ollama',
                model=config.get('model'),
                success=False,
                error=str(e)
            )

    def generate(self, prompt: str, provider: Optional[str] = None, **kwargs) -> LLMResponse:
        """
        Generate text using LLM with automatic fallback.

        Args:
            prompt: The prompt to send to the LLM
            provider: Optional specific provider to use (overrides primary)
            **kwargs: Additional arguments passed to provider (e.g., temperature)

        Returns:
            LLMResponse with generated content or error
        """
        # Check cache first (replay mode)
        if self.response_cache:
            cached_response = self.response_cache.get(prompt)
            if cached_response is not None:
                # Return cached response
                return LLMResponse(
                    content=cached_response,
                    provider="cache",
                    model="cached",
                    success=True
                )
        
        # Determine provider order
        if provider:
            # Explicit provider requested
            providers_to_try = [provider]
        else:
            # Always start with primary provider
            providers_to_try = [self.primary_provider]

            # Add fallback providers if enabled (excluding primary to avoid duplication)
            if self.fallback_enabled:
                fallback_providers = [p for p in self.fallback_order if p != self.primary_provider]
                providers_to_try.extend(fallback_providers)

        # Try each provider in order
        for provider_name in providers_to_try:
            logger.info(f"Trying provider: {provider_name}")

            try:
                # Get provider config
                providers_config = self.config.get('providers', {})
                provider_config = providers_config.get(provider_name, {})

                if not provider_config:
                    logger.warning(f"Provider '{provider_name}' not configured, skipping")
                    continue

                # Get or create client
                client = self._get_provider_client(provider_name)

                # Call provider-specific method
                if provider_name == 'anthropic':
                    response = self._call_anthropic(client, prompt, provider_config, **kwargs)
                elif provider_name == 'openai':
                    response = self._call_openai(client, prompt, provider_config, **kwargs)
                elif provider_name == 'gemini':
                    response = self._call_gemini(client, prompt, provider_config, **kwargs)
                elif provider_name == 'qwen':
                    response = self._call_qwen(client, prompt, provider_config, **kwargs)
                elif provider_name == 'ollama':
                    response = self._call_ollama(client, prompt, provider_config, **kwargs)
                else:
                    logger.warning(f"Unsupported provider: {provider_name}")
                    continue

                # Check if successful
                if response.success:
                    # NEW: Validate response before accepting it
                    is_valid, validation_error = self._validate_response(
                        response.content,
                        context="code"  # Assume code generation context
                    )

                    if not is_valid:
                        logger.warning(
                            f"⚠️  {provider_name} generated response failed validation: {validation_error}"
                        )
                        # Mark as failed and continue to next provider
                        response.success = False
                        response.error = f"Response validation failed: {validation_error}"
                        continue

                    logger.info(f"✅ Successfully generated and validated response using {provider_name}")

                    # Save to cache (record mode)
                    if self.response_cache:
                        self.response_cache.save(
                            prompt=prompt,
                            response=response.content,
                            provider=response.provider,
                            model=response.model
                        )

                    return response
                else:
                    logger.warning(f"⚠️  {provider_name} failed: {response.error}")
                    # Continue to next provider in fallback order
                    continue

            except Exception as e:
                logger.error(f"❌ Error with provider {provider_name}: {e}")
                # Continue to next provider
                continue

        # All providers failed
        error_msg = f"All providers failed. Tried: {providers_to_try}"
        logger.error(error_msg)
        return LLMResponse(
            content='',
            provider='none',
            model='none',
            success=False,
            error=error_msg
        )
