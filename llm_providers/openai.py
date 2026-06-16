"""
OpenAI Provider Implementation

Handles OpenAI GPT-4+ API interactions for both streaming and tool calling.
"""

import asyncio
import aiohttp
import json
import logging
from typing import AsyncIterator, List, Dict, Any, Optional
from .base import LLMProvider

logger = logging.getLogger(__name__)

class OpenAIProvider(LLMProvider):
    """OpenAI provider for GPT-4+ models"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize OpenAI provider
        
        Args:
            config: Configuration dictionary with api_key, base_url, model, etc.
        """
        super().__init__(config)
        self.api_key = config.get('api_key')
        self.base_url = config.get('base_url', 'https://api.openai.com/v1')
        self.organization = config.get('organization')
        self.session = None
        
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with auth headers"""
        if self.session is None:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            if self.organization:
                headers["OpenAI-Organization"] = self.organization

            # Support custom headers from config (e.g., for OpenRouter)
            # Filter out None values to prevent serialization errors
            custom_headers = self.config.get('headers', {})
            if custom_headers:
                # Only add headers with non-None values
                filtered_headers = {k: v for k, v in custom_headers.items() if v is not None}
                if filtered_headers:
                    headers.update(filtered_headers)
                    logger.info(f"🔧 Added custom headers: {list(filtered_headers.keys())}")

            timeout = aiohttp.ClientTimeout(total=self.get_timeout())
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=timeout
            )
        return self.session
    
    async def generate_stream(self, prompt: str, model: str, **kwargs) -> AsyncIterator[str]:
        """Generate streaming response from OpenAI
        
        Args:
            prompt: Input prompt
            model: Model name (gpt-4-turbo-preview, etc.)
            **kwargs: Additional parameters
            
        Yields:
            str: Response chunks
        """
        session = await self._get_session()
        
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "temperature": kwargs.get('temperature', self.get_temperature()),
            "max_tokens": kwargs.get('max_tokens', self.get_max_tokens())
        }
        
        logger.info(f"🤖 OpenAI streaming request: model={model}, prompt_len={len(prompt)}")
        
        try:
            async with session.post(
                f"{self.base_url}/chat/completions",
                json=payload
            ) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"❌ OpenAI API error {response.status}: {error_text}")
                    raise Exception(f"OpenAI API error: {response.status} - {error_text}")
                
                async for line in response.content:
                    line_str = line.decode('utf-8').strip()
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]  # Remove 'data: ' prefix
                        if data_str == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get('choices', [])
                            if choices:
                                delta = choices[0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue  # Skip invalid JSON
                            
        except asyncio.TimeoutError:
            logger.error("⏰ OpenAI request timeout")
            raise Exception("OpenAI request timed out")
        except Exception as e:
            logger.error(f"❌ OpenAI streaming error: {e}")
            raise
    
    async def generate_tools(self, prompt: str, model: str, tools: List[Dict], **kwargs) -> Dict[str, Any]:
        """Generate tool calls from OpenAI
        
        Args:
            prompt: Input prompt
            model: Model name
            tools: List of tool definitions
            **kwargs: Additional parameters
            
        Returns:
            Dict with tool calls and/or response text
        """
        session = await self._get_session()
        
        # Format tools for OpenAI API
        formatted_tools = []
        # logger.info(f"🔍 OPENAI TRACE TOOLS: Received {len(tools)} tools")
        for i, tool in enumerate(tools):
            # logger.info(f"🔍 OPENAI TRACE TOOL {i}: {tool}")
            
            # Check if tool is already in OpenAI format (has 'type' and 'function' keys)
            if isinstance(tool, dict) and 'type' in tool and 'function' in tool:
                # Tool is already in correct OpenAI format, use as-is
                formatted_tools.append(tool)
                # logger.info(f"🔍 OPENAI TRACE: Tool {i} already in OpenAI format")
            else:
                # Tool is in raw format, wrap it
                formatted_tools.append({
                    "type": "function",
                    "function": tool
                })
                # logger.info(f"🔍 OPENAI TRACE: Tool {i} wrapped in OpenAI format")
        
        # logger.info(f"🔍 OPENAI TRACE FORMATTED: {formatted_tools[:2] if formatted_tools else 'EMPTY'}")
        # logger.info(f"🔍 OPENAI TRACE 1: Received model parameter = {model}")
        # logger.info(f"🔍 OPENAI TRACE 2: self.config model = {self.config.get('model', 'NOT_SET')}")
        
        # Get system prompt for tool calling
        system_prompt = kwargs.get('system_prompt', '')
        
        # CRITICAL DEBUGGING: Log system prompt investigation
        logger.info(f"🚨 SYSTEM PROMPT DEBUG: Received kwargs keys = {list(kwargs.keys())}")
        logger.info(f"🚨 SYSTEM PROMPT DEBUG: system_prompt length = {len(system_prompt)} chars")
        if system_prompt:
            logger.info(f"🚨 SYSTEM PROMPT DEBUG: First 200 chars = {system_prompt[:200]}")
        else:
            logger.info(f"🚨 SYSTEM PROMPT DEBUG: NO SYSTEM PROMPT RECEIVED!")
        
        # Build messages array with system prompt if provided
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
            logger.info(f"🚨 SYSTEM PROMPT DEBUG: Added system message to payload")
        else:
            logger.info(f"🚨 SYSTEM PROMPT DEBUG: NO SYSTEM MESSAGE ADDED - CRITICAL ISSUE!")
        messages.append({"role": "user", "content": prompt})
        
        logger.info(f"🚨 SYSTEM PROMPT DEBUG: Final messages array length = {len(messages)}")
        logger.info(f"🚨 SYSTEM PROMPT DEBUG: Messages roles = {[msg['role'] for msg in messages]}")
        
        payload = {
            "model": model,
            "messages": messages,
            "tools": formatted_tools,
            "tool_choice": "auto",
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 2048)
        }
        
        logger.info(f"🔧 OpenAI tool request: model={model}, tools={len(tools)}")
        # logger.info(f"🔍 OPENAI PAYLOAD SIMULATION: {json.dumps(payload, indent=2)[:500]}...")
        
        # Transient-error resilience: the cloud tool endpoint (e.g. *:cloud via the Ollama OpenAI proxy)
        # intermittently returns 5xx. Without a retry, one brief blip silently degrades to "no tool calls"
        # → no evidence gathered → e.g. autonomous news posts get discarded for missing citations. Retry
        # 5xx and timeouts with linear backoff (config-driven). NEVER retry 4xx (client errors won't fix).
        retry_attempts = max(1, int(self.config.get('retry_attempts', 3)))
        retry_delay = float(self.config.get('retry_delay', 1))
        last_error = None

        for attempt in range(1, retry_attempts + 1):
            try:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload
                ) as response:

                    if response.status >= 500:
                        # Transient server error — retry with backoff.
                        error_text = await response.text()
                        last_error = Exception(f"OpenAI tool API error: {response.status} - {error_text[:300]}")
                        logger.warning(
                            f"⚠️ OpenAI tool API {response.status} (attempt {attempt}/{retry_attempts}) — "
                            f"transient: {error_text[:150]}"
                        )
                    elif response.status != 200:
                        # Client error (4xx) — not retryable.
                        error_text = await response.text()
                        logger.error(f"❌ OpenAI tool API error {response.status}: {error_text}")
                        raise Exception(f"OpenAI tool API error: {response.status} - {error_text}")
                    else:
                        response_data = await response.json()

                        # Extract tool calls and content
                        choices = response_data.get('choices', [])
                        if not choices:
                            raise Exception("No choices in OpenAI response")

                        message = choices[0].get('message', {})
                        tool_calls = message.get('tool_calls', [])
                        content = message.get('content', '')

                        # Convert OpenAI format to our standard format
                        formatted_tool_calls = []
                        for tool_call in tool_calls:
                            function = tool_call.get('function', {})
                            formatted_tool_calls.append({
                                'id': tool_call.get('id'),
                                'type': 'function',
                                'function': {
                                    'name': function.get('name'),
                                    'arguments': function.get('arguments')
                                }
                            })

                        if attempt > 1:
                            logger.info(f"✅ OpenAI tool API recovered on attempt {attempt}/{retry_attempts}")
                        return {
                            'tool_calls': formatted_tool_calls,
                            'content': content,
                            'usage': response_data.get('usage', {}),
                            'model': model
                        }

            except asyncio.TimeoutError:
                last_error = Exception("OpenAI tool request timed out")
                logger.warning(f"⏰ OpenAI tool request timeout (attempt {attempt}/{retry_attempts})")
            except Exception as e:
                # Non-transient (4xx, no-choices, parse) — do not retry.
                logger.error(f"❌ OpenAI tool calling error: {e}")
                raise

            # Reached only after a transient failure (5xx or timeout): back off before the next attempt.
            if attempt < retry_attempts:
                await asyncio.sleep(retry_delay * attempt)

        logger.error(f"❌ OpenAI tool API failed after {retry_attempts} attempts: {last_error}")
        raise last_error if last_error else Exception("OpenAI tool calling failed")
    
    async def health_check(self) -> bool:
        """Check OpenAI API health
        
        Returns:
            bool: True if healthy, False otherwise
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/models") as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"❌ OpenAI health check failed: {e}")
            return False
    
    def get_available_models(self) -> List[str]:
        """Get available OpenAI models
        
        Returns:
            List[str]: Available model names
        """
        # Common OpenAI models - in practice, would query /models endpoint
        return [
            "gpt-4-turbo-preview",
            "gpt-4-1106-preview", 
            "gpt-4",
            "gpt-3.5-turbo-1106",
            "gpt-3.5-turbo"
        ]
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get OpenAI provider information
        
        Returns:
            Dict with provider metadata
        """
        return {
            'name': 'OpenAI',
            'type': 'openai',
            'base_url': self.base_url,
            'configured_model': self.config.get('model'),
            'organization': self.organization,
            'supports_streaming': True,
            'supports_function_calling': True,
            'timeout': self.get_timeout(),
            'max_tokens': self.get_max_tokens(),
            'temperature': self.get_temperature()
        }
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up session on exit"""
        if self.session:
            await self.session.close()
            self.session = None