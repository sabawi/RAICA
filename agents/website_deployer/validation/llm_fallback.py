"""
LLM Fallback Handler - Multi-model resilience for code generation

This module implements automatic fallback between different LLM models when
token limits are exceeded or generation fails. It ensures that code generation
can complete even when a single model fails.

Fallback order: Gemini Pro -> Claude Opus -> GPT-4
"""

import logging
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TokenLimitExceeded(Exception):
    """Exception raised when an LLM exceeds its token limit."""
    pass


class LLMModel(Enum):
    """Available LLM models for code generation."""
    GEMINI_PRO = "gemini-pro"
    CLAUDE_OPUS = "claude-3-opus-20240229"
    GPT4 = "gpt-4"


@dataclass
class LLMResponse:
    """Response from an LLM with metadata."""
    content: str
    model: LLMModel
    tokens_used: Optional[int] = None
    success: bool = True
    error: Optional[str] = None


class LLMFallbackHandler:
    """
    Handles automatic fallback between LLM models on failure.

    This class manages a chain of LLM models and automatically switches to
    the next model when the current one fails due to token limits or other errors.
    """

    def __init__(self, llm_interface, max_retries: int = 3):
        """
        Initialize the fallback handler.

        Args:
            llm_interface: The LLM interface instance to use for generation
            max_retries: Maximum number of retry attempts per model
        """
        self.llm_interface = llm_interface
        self.max_retries = max_retries
        self.current_model_index = 0
        self.models = [
            LLMModel.GEMINI_PRO,
            LLMModel.CLAUDE_OPUS,
            LLMModel.GPT4,
        ]
        self.attempt_log: List[Dict[str, Any]] = []

    def generate_with_fallback(
        self,
        prompt: str,
        validation_type: str = "code"
    ) -> LLMResponse:
        """
        Generate response with automatic fallback to different models on failure.

        Args:
            prompt: The prompt to send to the LLM
            validation_type: Type of validation to perform ("code", "json", "text")

        Returns:
            LLMResponse containing the generated content and metadata

        Raises:
            AllModelsFailedError: If all models fail to generate valid output
        """
        logger.info(f"Starting LLM generation with fallback (type: {validation_type})")

        for model_idx, model in enumerate(self.models):
            logger.info(f"Attempting with model {model.value} (attempt {model_idx + 1}/{len(self.models)})")

            for retry in range(self.max_retries):
                try:
                    # Switch to the current model
                    self._switch_model(model)

                    # Generate response
                    response_content = self.llm_interface.generate(prompt)

                    # Validate the response
                    is_valid, error = self._validate_llm_response(
                        response_content,
                        validation_type
                    )

                    if not is_valid:
                        logger.warning(
                            f"Model {model.value} generated invalid response "
                            f"(retry {retry + 1}/{self.max_retries}): {error}"
                        )
                        self._log_attempt(model, success=False, error=error)

                        if retry < self.max_retries - 1:
                            continue  # Retry with same model
                        else:
                            break  # Move to next model

                    # Success!
                    logger.info(f"Model {model.value} generated valid response")
                    self._log_attempt(model, success=True)

                    return LLMResponse(
                        content=response_content,
                        model=model,
                        success=True
                    )

                except TokenLimitExceeded as e:
                    logger.warning(
                        f"Model {model.value} exceeded token limit: {e}"
                    )
                    self._log_attempt(model, success=False, error=str(e))
                    break  # Token limit exceeded, move to next model immediately

                except Exception as e:
                    logger.error(
                        f"Error with model {model.value} "
                        f"(retry {retry + 1}/{self.max_retries}): {e}"
                    )
                    self._log_attempt(model, success=False, error=str(e))

                    if retry < self.max_retries - 1:
                        continue  # Retry with same model
                    else:
                        break  # Move to next model

        # All models failed
        error_msg = self._generate_failure_summary()
        logger.error(f"All models failed: {error_msg}")
        raise AllModelsFailedError(error_msg, self.attempt_log)

    def _switch_model(self, model: LLMModel):
        """Switch the LLM interface to use a different model."""
        logger.info(f"Switching to model: {model.value}")

        # Update the model in the LLM interface
        if hasattr(self.llm_interface, 'set_model'):
            self.llm_interface.set_model(model.value)
        elif hasattr(self.llm_interface, 'model'):
            self.llm_interface.model = model.value
        else:
            logger.warning(
                "LLM interface doesn't support model switching, "
                "fallback may not work as expected"
            )

    def _validate_llm_response(
        self,
        response: str,
        validation_type: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate an LLM response based on the expected type.

        Args:
            response: The response content to validate
            validation_type: Type of validation ("code", "json", "text")

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not response or not response.strip():
            return False, "Empty response"

        if validation_type == "code":
            return self._validate_code_response(response)
        elif validation_type == "json":
            return self._validate_json_response(response)
        elif validation_type == "text":
            return True, None  # Text responses are always valid if non-empty
        else:
            logger.warning(f"Unknown validation type: {validation_type}")
            return True, None

    def _validate_code_response(self, response: str) -> Tuple[bool, Optional[str]]:
        """Validate that the response looks like valid code."""
        # Check for minimum length
        if len(response) < 50:
            return False, "Response too short for code"

        # Check for common code indicators
        code_indicators = ['def ', 'class ', 'import ', 'from ', 'async ', 'return']
        if not any(indicator in response for indicator in code_indicators):
            return False, "Response doesn't contain code indicators"

        # Check if response was truncated (common sign of token limit)
        truncation_indicators = [
            'TRUNCATED',
            'token limit',
            'maximum length',
            '...[truncated]',
        ]
        if any(indicator.lower() in response.lower() for indicator in truncation_indicators):
            return False, "Response appears to be truncated"

        # Check for incomplete code patterns
        if response.count('{') != response.count('}'):
            return False, "Mismatched braces in code"

        if response.count('(') != response.count(')'):
            return False, "Mismatched parentheses in code"

        return True, None

    def _validate_json_response(self, response: str) -> Tuple[bool, Optional[str]]:
        """Validate that the response is valid JSON."""
        import json

        try:
            json.loads(response)
            return True, None
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}"

    def _log_attempt(self, model: LLMModel, success: bool, error: Optional[str] = None):
        """Log an attempt for later analysis."""
        self.attempt_log.append({
            'model': model.value,
            'success': success,
            'error': error,
        })

    def _generate_failure_summary(self) -> str:
        """Generate a summary of all failed attempts."""
        summary = ["All LLM models failed to generate valid output:"]

        for idx, attempt in enumerate(self.attempt_log, 1):
            status = "✓" if attempt['success'] else "✗"
            error = f" - {attempt['error']}" if attempt['error'] else ""
            summary.append(f"  {idx}. {status} {attempt['model']}{error}")

        return "\n".join(summary)

    def get_attempt_summary(self) -> Dict[str, Any]:
        """Get a summary of all attempts made."""
        return {
            'total_attempts': len(self.attempt_log),
            'successful_attempts': sum(1 for a in self.attempt_log if a['success']),
            'failed_attempts': sum(1 for a in self.attempt_log if not a['success']),
            'attempts': self.attempt_log,
        }


class AllModelsFailedError(Exception):
    """Exception raised when all LLM models fail to generate valid output."""

    def __init__(self, message: str, attempt_log: List[Dict[str, Any]]):
        super().__init__(message)
        self.attempt_log = attempt_log
