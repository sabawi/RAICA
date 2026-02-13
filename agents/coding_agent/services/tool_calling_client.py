"""
Tool-Calling LLM Client - Phase 2 of the tool-calling debug architecture.

This module wraps an LLM client to enforce tool-only responses,
with schema validation and structured output parsing.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .debug_toolkit import DebugToolkit, ToolResult
from .tool_executor import ToolExecutor, ToolCall, ExecutionResult
from .tool_usage_examples import TOOL_USAGE_EXAMPLES

logger = logging.getLogger(__name__)


class ToolCallingClient:
    """
    LLM wrapper that enforces tool-only responses.
    
    This client:
    1. Provides tool schemas to the LLM
    2. Enforces JSON-only responses
    3. Validates tool calls against schema
    4. Handles multi-turn tool execution
    
    Usage:
        client = ToolCallingClient(llm_client, toolkit)
        
        # Single turn: get tool calls
        tool_calls = await client.get_tool_calls(
            instruction="Read requirements.txt and check for issues",
            context="Previous tool found an import error"
        )
        
        # Execute and iterate
        results = client.executor.execute_batch(tool_calls)
        next_calls = await client.continue_with_results(results)
    """
    
    # System prompt for TEXT-BASED fallback (when native tool calling unavailable)
    SYSTEM_PROMPT_TEMPLATE = """YOU ARE A TOOL-CALLING AGENT. YOUR ONLY OUTPUT IS JSON TOOL CALLS.

AVAILABLE TOOLS:
{tool_schema}

OUTPUT FORMAT - NOTHING ELSE:
{{"tool_calls": [{{"tool": "TOOL_NAME", "args": {{"param": "value"}}}}]}}

{examples}

DO NOT EXPLAIN. DO NOT DESCRIBE. JUST OUTPUT THE JSON TOOL CALLS.

{context}"""

    # Alternative simpler prompt for retry attempts (text-based fallback)
    SIMPLE_SYSTEM_PROMPT = """OUTPUT JSON TOOL CALLS ONLY. NO TEXT.

FORMAT: {{"tool_calls": [{{"tool": "TOOL_NAME", "args": {{...}}}}]}}

EXAMPLES:
{{"tool_calls": [{{"tool": "read_file", "args": {{"path": "index.html"}}}}]}}
{{"tool_calls": [{{"tool": "write_file", "args": {{"path": "index.html", "content": "..."}}}}]}}"""

    def __init__(self, llm_client, toolkit: DebugToolkit):
        """
        Initialize the tool-calling client.

        Args:
            llm_client: LLM client with generate() method
            toolkit: DebugToolkit with available tools
        """
        self.llm = llm_client
        self.toolkit = toolkit
        self.executor = ToolExecutor(toolkit)
        self._tool_schema = json.dumps(toolkit.get_tool_schema(), indent=2)
        self._conversation_history: List[Dict] = []

        # Log model info
        self._log_model_info()

    def _log_model_info(self):
        """Log which LLM model is being used."""
        try:
            model_name = "unknown"
            provider = "unknown"

            if hasattr(self.llm, 'primary_provider'):
                provider = self.llm.primary_provider
            if hasattr(self.llm, 'primary_model') and self.llm.primary_model:
                model_name = self.llm.primary_model
            elif hasattr(self.llm, '_model_override') and self.llm._model_override:
                model_name = self.llm._model_override
            elif hasattr(self.llm, 'config'):
                providers = self.llm.config.get('providers', {})
                if provider in providers:
                    model_name = providers[provider].get('model', 'default')

            logger.info(f"ToolCallingClient using: {provider}/{model_name}")
        except Exception as e:
            logger.debug(f"Could not get model info: {e}")
    
    def reset_conversation(self):
        """Clear conversation history for new task."""
        self._conversation_history = []
    
    def _build_system_prompt(self, context: str = "") -> str:
        """Build the system prompt with tool schema."""
        # Note: Context is now moved to User Prompt for better adherence
        return self.SYSTEM_PROMPT_TEMPLATE.format(
            tool_schema=self._tool_schema,
            examples=TOOL_USAGE_EXAMPLES,
            context="" # Context removed from system prompt
        )

    def _extract_json_from_response(self, content: str) -> Optional[dict]:
        """
        Extract JSON from LLM response that may contain prose before/after JSON.
        Uses the robust centralized utility.
        """
        from ..utils.json_utils import extract_json_from_llm_response
        return extract_json_from_llm_response(content)

    def _convert_direct_answer_to_tool_calls(self, data: dict) -> List[ToolCall]:
        """
        Convert LLM direct answer formats to tool calls.

        Handles common formats:
        - {'files': {'filename': 'content'}}
        - {'edits': [{'path': '...', 'content': '...'}]}
        - {'edits': [{'file': '...', 'action': 'replace', 'content': '...'}]}

        Returns:
            List of ToolCall objects for file operations (using write_file tool)
        """
        tool_calls = []

        # Format 1: {'files': {'filename': 'content'}}
        if 'files' in data and isinstance(data['files'], dict):
            for filename, content in data['files'].items():
                if isinstance(content, str) and filename:
                    tool_calls.append(ToolCall(
                        tool='write_file',
                        args={'path': filename, 'content': content}
                    ))
                    logger.info(f"Converted direct file: {filename} ({len(content)} chars)")

        # Format 2: {'edits': [{'path': '...', 'content': '...'}]}
        elif 'edits' in data and isinstance(data['edits'], list):
            for edit in data['edits']:
                if isinstance(edit, dict):
                    path = edit.get('path') or edit.get('file')
                    content = edit.get('content') or edit.get('new_content')
                    if path and content:
                        tool_calls.append(ToolCall(
                            tool='write_file',
                            args={'path': path, 'content': content}
                        ))
                        logger.info(f"Converted edit: {path}")

        # Format 3: {'file': 'filename', 'content': '...'} (single file)
        elif 'file' in data and 'content' in data:
            tool_calls.append(ToolCall(
                tool='write_file',
                args={'path': data['file'], 'content': data['content']}
            ))
            logger.info(f"Converted single file: {data['file']}")

        # Format 4: {'path': 'filename', 'content': '...'} (single file alt)
        elif 'path' in data and 'content' in data:
            tool_calls.append(ToolCall(
                tool='write_file',
                args={'path': data['path'], 'content': data['content']}
            ))
            logger.info(f"Converted single file: {data['path']}")

        # Format 5: {'patch': '*** Begin Patch\n*** Update File: filename\n...'} - unified diff format
        elif 'patch' in data and isinstance(data['patch'], str):
            # Parse the patch to extract file and content
            # This is a simplified parser - just extract the filename
            patch_content = data['patch']
            import re
            file_match = re.search(r'\*\*\* Update File:\s*(\S+)', patch_content)
            if file_match:
                filename = file_match.group(1)
                # For patches, we need to read the current file and apply the diff
                # For now, just log that we detected a patch format
                logger.warning(f"Detected patch format for {filename} - patch application not yet implemented")
                # We can't easily convert a diff to write_file, so skip this

        # Format 6: {'filename.ext': 'content'} - filename is the key directly
        # Detect by checking if any key looks like a filename (has extension)
        if not tool_calls:
            import re
            file_pattern = re.compile(r'^[\w\-./]+\.\w+$')  # Matches file paths like index.html, src/main.py
            for key, value in data.items():
                if file_pattern.match(key) and isinstance(value, str) and len(value) > 10:
                    tool_calls.append(ToolCall(
                        tool='write_file',
                        args={'path': key, 'content': value}
                    ))
                    logger.info(f"Converted filename-as-key: {key} ({len(value)} chars)")

        return tool_calls

    async def get_tool_calls(
        self,
        instruction: str,
        context: str = "",
        max_retries: int = 3
    ) -> List[ToolCall]:
        """
        Get tool calls from LLM using NATIVE tool-calling API.

        This uses the provider's built-in tool calling capability (e.g., Ollama /api/chat with tools),
        NOT text generation with JSON parsing. This is the same pattern used by the working
        RAICA server.

        Args:
            instruction: What the LLM should do
            context: Additional context (previous results, etc.)
            max_retries: Number of retries on failure

        Returns:
            List of ToolCall objects
        """
        # Get tool definitions from toolkit
        tools = self.toolkit.get_tool_schema()

        # Build the prompt with context
        prompt = ""
        if context:
            prompt += f"PREVIOUS TOOL RESULTS:\n{context}\n\n"
        prompt += f"TASK:\n{instruction}"

        # Build system prompt for NATIVE tool calling
        # CRITICAL: This prompt must make the LLM CALL TOOLS via the API, not output text
        system_prompt = """YOU MUST CALL TOOLS. DO NOT RESPOND WITH TEXT.

YOUR ONLY ACTION IS TO CALL THE PROVIDED TOOLS.

To fix code:
1. CALL read_file to see current content
2. CALL write_file with the fixed content

CALL TOOLS NOW. NO TEXT RESPONSES.
"""

        for attempt in range(max_retries + 1):
            try:
                logger.info(f"🔧 Native tool-calling request (attempt {attempt + 1}/{max_retries + 1})")

                # Use native tool-calling API (same as working server)
                # This calls Ollama/OpenAI with the 'tools' parameter
                if hasattr(self.llm, 'generate_tools'):
                    result = self.llm.generate_tools(
                        prompt=prompt,
                        tools=tools,
                        system_prompt=system_prompt,
                        temperature=0.1,  # Low temp for deterministic tool calls
                        max_tokens=16000
                    )

                    # DEBUG: Log the raw result from LLM
                    tool_calls_raw = result.get('tool_calls', [])
                    content = result.get('content', '')
                    success = result.get('success', False)
                    error = result.get('error', '')

                    print(f"   🔧 LLM TOOL RESPONSE:")
                    print(f"      success: {success}")
                    print(f"      tool_calls: {len(tool_calls_raw)} calls")
                    for i, tc in enumerate(tool_calls_raw):
                        print(f"         [{i}] {tc.get('tool', 'NO_TOOL')}: {list(tc.get('args', {}).keys())}")
                    if content:
                        print(f"      content: {content[:200]}...")
                    if error:
                        print(f"      error: {error}")

                    if success:
                        # Check if task is complete (no tool calls and content indicates done)
                        if not tool_calls_raw:
                            if content and ('complete' in content.lower() or 'done' in content.lower()):
                                logger.info("LLM indicated task is complete (no more tool calls)")
                                return []
                            # No tool calls but also no completion message - might need retry
                            logger.warning(f"No tool calls returned (attempt {attempt + 1})")
                            print(f"   ⚠ No tool calls in response. Content: {content[:300] if content else 'EMPTY'}")
                            if attempt < max_retries:
                                continue
                            return []

                        # Convert to ToolCall objects
                        tool_calls = []
                        for tc in tool_calls_raw:
                            tool_name = tc.get('tool', '')
                            args = tc.get('args', {})
                            if tool_name:
                                tool_calls.append(ToolCall(tool=tool_name, args=args))
                                logger.info(f"   Tool: {tool_name}({list(args.keys())})")

                        if tool_calls:
                            # Record in history
                            self._conversation_history.append({
                                "role": "user",
                                "content": instruction
                            })
                            self._conversation_history.append({
                                "role": "assistant",
                                "tool_calls": tool_calls_raw
                            })
                            logger.info(f"✅ Native tool calling returned {len(tool_calls)} tool calls")
                            return tool_calls
                    else:
                        error = result.get('error', 'Unknown error')
                        print(f"   ❌ Native tool calling failed: {error}")
                        logger.warning(f"Native tool calling failed: {error}")
                        if attempt < max_retries:
                            continue

                else:
                    # Fallback to text-based tool calling (less reliable)
                    logger.warning("LLM client doesn't support generate_tools(), falling back to text parsing")
                    return await self._get_tool_calls_text_fallback(instruction, context, max_retries - attempt)

            except Exception as e:
                logger.error(f"Error in native tool calling (attempt {attempt + 1}): {e}")
                if attempt < max_retries:
                    continue

        logger.error(f"Failed to get tool calls after {max_retries + 1} attempts")
        return []

    async def _get_tool_calls_text_fallback(
        self,
        instruction: str,
        context: str = "",
        max_retries: int = 2
    ) -> List[ToolCall]:
        """
        Fallback: Get tool calls via text generation with JSON parsing.
        Used when native tool calling is not available.
        """
        system_prompt = self._build_system_prompt()

        prompt = ""
        if context:
            prompt += f"CONTEXT:\n{context}\n\n"
        prompt += f"TASK:\n{instruction}"
        prompt += "\n\nRespond with valid JSON: {\"tool_calls\": [{\"tool\": \"...\", \"args\": {...}}]}"

        for attempt in range(max_retries + 1):
            try:
                logger.info(f"Text-based tool calling (attempt {attempt + 1}/{max_retries + 1})")

                result = self.llm.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0.0,
                    max_tokens=16000
                )

                content = result.content if hasattr(result, 'content') else str(result)

                # Check if complete
                if self._is_complete(content):
                    return []

                # Parse tool calls from text
                tool_calls = self.executor.parse_response(content)

                if tool_calls:
                    logger.info(f"Text parsing returned {len(tool_calls)} tool calls")
                    return tool_calls

                # Try to convert direct answer to tool calls
                data = self._extract_json_from_response(content)
                if data and isinstance(data, dict):
                    converted = self._convert_direct_answer_to_tool_calls(data)
                    if converted:
                        return converted

                logger.warning(f"No tool calls parsed (attempt {attempt + 1})")

            except Exception as e:
                logger.error(f"Text fallback error (attempt {attempt + 1}): {e}")

        return []
    
    def _is_complete(self, content: str) -> bool:
        """Check if LLM response indicates task completion."""
        try:
            # Try to find JSON in content
            import re
            json_match = re.search(r'\{[^{}]*"done"\s*:\s*true[^{}]*\}', content)
            if json_match:
                return True
            
            # Parse full content
            data = json.loads(content.strip())
            return data.get("done", False) == True
        except:
            return False
    
    async def execute_and_continue(
        self,
        instruction: str,
        context: str = "",
        max_iterations: int = 5
    ) -> ExecutionResult:
        """
        Execute tool calls and iterate until done or max iterations.
        
        Preserves base context across iterations.
        """
        all_results: List[ToolResult] = []
        all_errors: List[str] = []
        
        # Keep base context (file structure, read files, etc.)
        base_context = context
        # Cumulative conversation context (tool results)
        running_context = ""
        
        for iteration in range(max_iterations):
            logger.info(f"Tool execution iteration {iteration + 1}/{max_iterations}")
            print(f"   📍 TOOL ITERATION {iteration + 1}/{max_iterations}")
            
            # Combine base context with running context (latest tool results)
            # Put tool results FIRST so they are not buried under static context
            combined_context = ""
            if running_context:
                combined_context = "PREVIOUS TOOL RESULTS:\n" + running_context + "\n\n"
            
            combined_context += "PROJECT CONTEXT:\n" + base_context
            
            # Get tool calls
            # CRITICAL: Continuation must remind LLM of the GOAL and demand ACTION
            if iteration == 0:
                current_instruction = instruction
            else:
                # Include original goal so LLM knows what to do with the data it read
                current_instruction = f"""ORIGINAL TASK: {instruction}

You have read the file. NOW CALL write_file TO APPLY THE FIX.

CALL write_file with the complete fixed content NOW."""

            tool_calls = await self.get_tool_calls(
                instruction=current_instruction,
                context=combined_context
            )
            
            if not tool_calls:
                logger.info("No more tool calls, task complete")
                break
            
            # Execute tool calls
            result = self.executor.execute_batch(tool_calls)
            all_results.extend(result.results)
            all_errors.extend(result.errors)

            # Format results and append to running context
            msg = self.executor.format_results_for_llm(result)
            running_context += f"\nIteration {iteration+1}:\n{msg}\n"

            # Debug: Show what tools executed
            for tr in result.results:
                status = "✅" if tr.success else "❌"
                if tr.success and tr.result:
                    preview = str(tr.result)[:80].replace('\n', ' ')
                    print(f"      {status} Tool result: {preview}...")
                elif tr.error:
                    print(f"      {status} Tool error: {tr.error[:80]}...")
                else:
                    print(f"      {status} Tool executed (no output)")
            
            # Record in history
            self._conversation_history.append({
                "role": "tool",
                "content": msg
            })

            # Check if we should stop
            if self._should_stop(result, iteration):
                logger.info("Stopping: critical error or completion detected")
                break

        return ExecutionResult(
            success=len(all_errors) == 0,
            results=all_results,
            errors=all_errors,
            recovery_suggestions=[]  # Already included per-result
        )
    
    def _should_stop(self, result: ExecutionResult, iteration: int = 0) -> bool:
        """
        Determine if we should stop the execution loop.

        Uses intelligent analysis of errors to distinguish between:
        - Recoverable errors (file not found, timeout) -> continue
        - Fatal errors (permission denied on critical file) -> stop
        - Repeated failures -> stop to prevent infinite loops
        """
        # If there are recovery suggestions and no fatal errors, continue
        if result.has_recoverable_errors() and result.recovery_suggestions:
            logger.info("Recoverable errors with suggestions - continuing")
            return False

        # Count failures by type
        fatal_errors = []
        recoverable_errors = []

        recoverable_patterns = [
            "file not found", "no such file", "does not exist",
            "timeout", "connection", "module not found",
            "import error", "line number", "not unique"
        ]

        fatal_patterns = [
            "permission denied", "access denied", "read-only",
            "disk full", "quota exceeded", "out of memory"
        ]

        for r in result.results:
            if not r.success and r.error:
                error_lower = r.error.lower()

                # Check for fatal patterns
                if any(p in error_lower for p in fatal_patterns):
                    fatal_errors.append(r.error)
                # Check for recoverable patterns
                elif any(p in error_lower for p in recoverable_patterns):
                    recoverable_errors.append(r.error)
                else:
                    # Unknown error type - treat as potentially fatal after iteration 2
                    if iteration >= 2:
                        fatal_errors.append(r.error)
                    else:
                        recoverable_errors.append(r.error)

        # Stop if we have fatal errors
        if fatal_errors:
            logger.warning(f"Fatal errors detected: {fatal_errors}")
            return True

        # Continue if we only have recoverable errors
        if recoverable_errors and not fatal_errors:
            logger.info(f"Only recoverable errors - continuing")
            return False

        # Default: continue if there were any successes
        successes = sum(1 for r in result.results if r.success)
        return successes == 0  # Stop only if ALL calls failed
    
    def get_conversation_summary(self) -> str:
        """Get a summary of the conversation for logging."""
        lines = []
        for msg in self._conversation_history[-10:]:  # Last 10 messages
            role = msg["role"]
            content = msg["content"][:200]
            lines.append(f"[{role}] {content}...")
        return "\n".join(lines)
