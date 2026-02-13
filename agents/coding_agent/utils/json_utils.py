"""
JSON Utilities for RAICA Coding Agent
=====================================

Handles common JSON parsing issues from LLM responses:
- Control characters inside strings
- Trailing commas
- Unescaped special characters
"""

import json
import re
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def sanitize_json(json_str: str) -> str:
    """
    Sanitize JSON string to handle common LLM output issues.

    Fixes:
    - Control characters inside strings (newlines, tabs, etc.)
    - Trailing commas before ] or }
    - Other invalid escape sequences

    Args:
        json_str: Raw JSON string from LLM

    Returns:
        Sanitized JSON string
    """
    if not json_str:
        return json_str

    # Replace actual control characters that should be escaped in JSON
    def escape_control_chars(s):
        result = []
        in_string = False
        escape_next = False
        i = 0
        while i < len(s):
            char = s[i]

            if escape_next:
                result.append(char)
                escape_next = False
                i += 1
                continue

            if char == '\\':
                escape_next = True
                result.append(char)
                i += 1
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                result.append(char)
                i += 1
                continue

            if in_string:
                # Inside a string - escape control characters
                if char == '\n':
                    result.append('\\n')
                elif char == '\r':
                    result.append('\\r')
                elif char == '\t':
                    result.append('\\t')
                elif ord(char) < 32:
                    # Other control characters - escape as unicode
                    result.append(f'\\u{ord(char):04x}')
                else:
                    result.append(char)
            else:
                # Outside string - keep as is
                result.append(char)

            i += 1

        return ''.join(result)

    # Apply control character escaping
    sanitized = escape_control_chars(json_str)

    # Remove trailing commas before ] or } (common LLM mistake)
    sanitized = re.sub(r',\s*([}\]])', r'\1', sanitized)

    # Add missing commas between strings (e.g. ["a" "b"] or {"k": "v" "k": "v"})
    # Matches: Unescaped Quote, Whitespace, Quote
    sanitized = re.sub(r'(?<!\\)"\s+"', '", "', sanitized)

    # Fix missing commas between JSON object properties
    # Matches: value (string, number, bool, null, or closing bracket/brace) followed by a newline/space and a quote (next key)
    # Pattern: matches situations like: "value"\n  "key" or }\n  "key" or ]\n  "key"
    sanitized = re.sub(
        r'(?<=["\}\]0-9truefalsenull])\s*\n\s*(?=")',
        ',\n  ',
        sanitized
    )

    # Also fix missing commas on same line: "value"  "key" → "value", "key"
    sanitized = re.sub(
        r'(?<=["\}\]0-9])\s{2,}(?=")',
        ', ',
        sanitized
    )

    return sanitized


def safe_json_loads(content: str, default: Any = None) -> Any:
    """
    Safely parse JSON with sanitization and fallback.

    Args:
        content: String containing JSON
        default: Default value if parsing fails

    Returns:
        Parsed JSON or default value
    """
    if not content:
        return default

    try:
        # First try direct parsing
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try with sanitization
    try:
        sanitized = sanitize_json(content)
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON object/array
    try:
        # Find first { or [
        obj_start = content.find('{')
        arr_start = content.find('[')

        if obj_start == -1 and arr_start == -1:
            return default

        start = min(x for x in [obj_start, arr_start] if x >= 0)
        is_object = content[start] == '{'

        # Extract balanced JSON
        bracket_open = '{' if is_object else '['
        bracket_close = '}' if is_object else ']'

        count = 0
        end = start
        for i, char in enumerate(content[start:], start):
            if char == bracket_open:
                count += 1
            elif char == bracket_close:
                count -= 1
                if count == 0:
                    end = i + 1
                    break

        if end > start:
            extracted = content[start:end]
            sanitized = sanitize_json(extracted)
            return json.loads(sanitized)

    except (json.JSONDecodeError, ValueError) as e:
        logger.debug(f"JSON extraction failed: {e}")

    return default


def extract_json_from_llm_response(content: str) -> Optional[dict]:
    """
    Extract JSON object from an LLM response that may contain
    additional text before/after the JSON.

    Args:
        content: LLM response text

    Returns:
        Extracted JSON dict or None
    """
    if not content:
        return None

    # 1. Try to extract from Markdown code blocks first (highest reliability)
    import re
    code_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    match = re.search(code_block_pattern, content, re.DOTALL)
    if match:
        try:
            json_str = match.group(1)
            return json.loads(sanitize_json(json_str))
        except json.JSONDecodeError:
            pass  # Fallthrough to other methods

    # 2. Try strict tokenizer/decoder from the first brace
    first_brace = content.find('{')
    if first_brace != -1:
        try:
            json_portion = sanitize_json(content[first_brace:])
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(json_portion)
            return data
        except json.JSONDecodeError:
            pass

    # 3. Fallback: Find outermost balanced braces
    # This handles cases where raw_decode fails due to internal syntax errors 
    # that sanitize_json might help with if we isolate the block first.
    try:
        start = content.find('{')
        if start != -1:
            count = 0
            for i, char in enumerate(content[start:], start):
                if char == '{':
                    count += 1
                elif char == '}':
                    count -= 1
                    if count == 0:
                        # Found matching matching brace
                        json_str = content[start:i+1]
                        return json.loads(sanitize_json(json_str))
    except Exception:
        pass

    return None
