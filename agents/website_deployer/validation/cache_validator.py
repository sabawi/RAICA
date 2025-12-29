"""
Cache Validation Module

This module validates cached LLM responses to ensure they are complete and
haven't been corrupted by token limits or other failures. It prevents the
replay of incomplete or corrupted cached code.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CacheValidationResult:
    """Result of cache validation."""
    is_valid: bool = True
    errors: List[str] = None
    warnings: List[str] = None
    total_responses: int = 0
    validated_responses: int = 0
    invalid_responses: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.invalid_responses is None:
            self.invalid_responses = []

    def add_error(self, error: str):
        """Add an error and mark validation as invalid."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str):
        """Add a warning without invalidating."""
        self.warnings.append(warning)

    def get_summary(self) -> str:
        """Get a human-readable summary."""
        if self.is_valid:
            return (
                f"✅ Cache validation PASSED\n"
                f"  Total responses: {self.total_responses}\n"
                f"  Validated: {self.validated_responses}"
            )

        summary = [
            f"❌ Cache validation FAILED",
            f"  Total responses: {self.total_responses}",
            f"  Validated: {self.validated_responses}",
            f"  Invalid: {len(self.invalid_responses)}",
        ]

        if self.errors:
            summary.append(f"\n🔴 Errors ({len(self.errors)}):")
            for error in self.errors[:5]:
                summary.append(f"  - {error}")
            if len(self.errors) > 5:
                summary.append(f"  ... and {len(self.errors) - 5} more")

        if self.warnings:
            summary.append(f"\n⚠️  Warnings ({len(self.warnings)}):")
            for warning in self.warnings[:3]:
                summary.append(f"  - {warning}")

        return "\n".join(summary)


class CacheValidator:
    """Validates cached LLM responses for completeness and correctness."""

    # Expected phases that should have cached responses
    EXPECTED_PHASES = {
        'requirement_analysis',
        'architecture_design',
        'code_generation',
        'database_schema',
        'deployment_config',
    }

    # Minimum response length for code generation (characters)
    MIN_CODE_RESPONSE_LENGTH = 100

    # Truncation indicators that suggest incomplete generation
    TRUNCATION_INDICATORS = [
        'TRUNCATED',
        'token limit exceeded',
        'maximum length',
        '...[truncated]',
        'Response cut off',
    ]

    def __init__(self, cache_file_path: str):
        """
        Initialize the cache validator.

        Args:
            cache_file_path: Path to the cache JSON file
        """
        self.cache_file_path = Path(cache_file_path)
        self.result = CacheValidationResult()

    def validate_cache(self) -> CacheValidationResult:
        """
        Validate the cache file for completeness and integrity.

        Returns:
            CacheValidationResult with detailed validation information
        """
        logger.info(f"Validating cache file: {self.cache_file_path}")
        self.result = CacheValidationResult()

        # Check if cache file exists
        if not self.cache_file_path.exists():
            self.result.add_error(f"Cache file not found: {self.cache_file_path}")
            return self.result

        # Load cache file
        try:
            with open(self.cache_file_path, 'r') as f:
                cache_data = json.load(f)
        except json.JSONDecodeError as e:
            self.result.add_error(f"Invalid JSON in cache file: {e}")
            return self.result
        except Exception as e:
            self.result.add_error(f"Error reading cache file: {e}")
            return self.result

        # Validate cache structure
        if not isinstance(cache_data, dict):
            self.result.add_error("Cache file must contain a JSON object")
            return self.result

        # Count total responses
        self.result.total_responses = len(cache_data)

        if self.result.total_responses == 0:
            self.result.add_error("Cache file is empty - no responses cached")
            return self.result

        # Validate each cached response
        for key, response_data in cache_data.items():
            is_valid = self._validate_response(key, response_data)
            if is_valid:
                self.result.validated_responses += 1
            else:
                self.result.invalid_responses.append(key)

        # Check if we have responses for expected phases
        self._validate_expected_phases(cache_data)

        # Check for suspicious patterns
        self._check_suspicious_patterns(cache_data)

        logger.info(
            f"Cache validation complete: {self.result.validated_responses}/"
            f"{self.result.total_responses} responses valid"
        )

        return self.result

    def _validate_response(self, key: str, response_data: Any) -> bool:
        """
        Validate a single cached response.

        Args:
            key: Cache key
            response_data: The cached response data

        Returns:
            True if valid, False otherwise
        """
        # Response should be a string
        if not isinstance(response_data, str):
            self.result.add_error(
                f"Response '{key}' is not a string (type: {type(response_data).__name__})"
            )
            return False

        # Response should not be empty
        if not response_data.strip():
            self.result.add_error(f"Response '{key}' is empty")
            return False

        # Check for truncation indicators
        for indicator in self.TRUNCATION_INDICATORS:
            if indicator.lower() in response_data.lower():
                self.result.add_error(
                    f"Response '{key}' contains truncation indicator: '{indicator}'"
                )
                return False

        # For code generation responses, check minimum length
        if 'code' in key.lower() or 'generate' in key.lower():
            if len(response_data) < self.MIN_CODE_RESPONSE_LENGTH:
                self.result.add_error(
                    f"Code response '{key}' is suspiciously short ({len(response_data)} chars)"
                )
                return False

        return True

    def _validate_expected_phases(self, cache_data: Dict[str, Any]):
        """Check if all expected phases have cached responses."""
        cached_phases = set()

        for key in cache_data.keys():
            key_lower = key.lower()
            for phase in self.EXPECTED_PHASES:
                if phase in key_lower:
                    cached_phases.add(phase)
                    break

        missing_phases = self.EXPECTED_PHASES - cached_phases
        if missing_phases:
            self.result.add_warning(
                f"Missing cached responses for phases: {', '.join(missing_phases)}"
            )

    def _check_suspicious_patterns(self, cache_data: Dict[str, Any]):
        """Check for suspicious patterns that might indicate incomplete generation."""
        # Check if number of responses is suspiciously low
        # For a full deployment, we expect 30+ cached responses
        if self.result.total_responses < 10:
            self.result.add_warning(
                f"Only {self.result.total_responses} cached responses found. "
                "This might indicate incomplete generation."
            )

        # Check if many responses are very similar in length (might indicate copy-paste errors)
        lengths = [len(str(v)) for v in cache_data.values()]
        if len(set(lengths)) < len(lengths) * 0.5:
            self.result.add_warning(
                "Many cached responses have identical lengths - might indicate duplication"
            )

        # Check for responses that reference "previous" content (indicates generation dependency)
        dependency_keywords = [
            'as mentioned above',
            'as shown previously',
            'from the previous',
            'continuing from',
        ]
        dependent_responses = []
        for key, response in cache_data.items():
            if isinstance(response, str):
                if any(keyword in response.lower() for keyword in dependency_keywords):
                    dependent_responses.append(key)

        if dependent_responses:
            self.result.add_warning(
                f"{len(dependent_responses)} responses reference previous content - "
                "cache may not be replayable in isolation"
            )


def validate_cache(cache_file_path: str) -> CacheValidationResult:
    """
    Convenience function to validate a cache file.

    Args:
        cache_file_path: Path to the cache JSON file

    Returns:
        CacheValidationResult with detailed validation information
    """
    validator = CacheValidator(cache_file_path)
    return validator.validate_cache()
