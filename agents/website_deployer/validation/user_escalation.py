"""
User Escalation and Recovery Module

This module handles user interaction when automatic validation and recovery fails.
It provides clear options for the user to decide how to proceed when deployment
issues are detected.
"""

import logging
from typing import List, Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class RecoveryAction(Enum):
    """Available recovery actions when validation fails."""
    REGENERATE_ALL = "regenerate_all"
    REGENERATE_FAILED = "regenerate_failed"
    FIX_MANUALLY = "fix_manually"
    CREATE_STUBS = "create_stubs"
    ABORT = "abort"


@dataclass
class ValidationFailure:
    """Represents a validation failure with details."""
    component: str
    error_type: str
    error_message: str
    severity: str  # "critical", "warning", "info"
    can_auto_fix: bool = False
    suggested_action: Optional[str] = None


class UserEscalationHandler:
    """
    Handles user interaction when automatic recovery fails.

    This class presents validation failures to the user and guides them
    through recovery options.
    """

    def __init__(self, max_auto_retries: int = 3):
        """
        Initialize the escalation handler.

        Args:
            max_auto_retries: Maximum number of automatic retry attempts
        """
        self.max_auto_retries = max_auto_retries
        self.retry_count = 0
        self.failures: List[ValidationFailure] = []

    def handle_validation_failure(
        self,
        validation_errors: List[str],
        context: Dict[str, Any]
    ) -> RecoveryAction:
        """
        Handle a validation failure by presenting options to the user.

        Args:
            validation_errors: List of validation error messages
            context: Additional context about the failure

        Returns:
            RecoveryAction chosen by the user
        """
        self.retry_count += 1

        # Convert validation errors to structured failures
        self.failures = self._parse_validation_errors(validation_errors)

        # Check if we should escalate to user
        if self.retry_count <= self.max_auto_retries:
            logger.info(
                f"Automatic retry {self.retry_count}/{self.max_auto_retries} - "
                "attempting to regenerate failed components"
            )
            return RecoveryAction.REGENERATE_FAILED

        # Escalate to user after max retries
        logger.warning(
            f"Maximum automatic retries ({self.max_auto_retries}) exceeded - "
            "escalating to user"
        )

        return self._prompt_user_for_action(context)

    def _parse_validation_errors(
        self,
        validation_errors: List[str]
    ) -> List[ValidationFailure]:
        """Parse raw validation errors into structured failures."""
        failures = []

        for error in validation_errors:
            # Determine component from error message
            component = "unknown"
            if "import" in error.lower():
                component = "imports"
            elif "schema" in error.lower():
                component = "schemas"
            elif "service" in error.lower():
                component = "services"
            elif "dependency" in error.lower():
                component = "dependencies"
            elif "cache" in error.lower():
                component = "cache"

            # Determine severity
            severity = "critical"
            if "warning" in error.lower():
                severity = "warning"
            elif "missing" in error.lower():
                severity = "critical"

            # Determine if auto-fixable
            can_auto_fix = any([
                "dependency" in error.lower(),
                "import" in error.lower(),
            ])

            failure = ValidationFailure(
                component=component,
                error_type="validation_error",
                error_message=error,
                severity=severity,
                can_auto_fix=can_auto_fix,
                suggested_action=self._suggest_action(error)
            )

            failures.append(failure)

        return failures

    def _suggest_action(self, error: str) -> str:
        """Suggest an action based on the error message."""
        if "missing import" in error.lower():
            return "Regenerate the file with missing imports"
        elif "missing dependency" in error.lower():
            return "Add missing package to requirements.txt"
        elif "incomplete module" in error.lower():
            return "Regenerate the incomplete module"
        elif "cache" in error.lower():
            return "Clear cache and regenerate all files"
        else:
            return "Regenerate all affected files"

    def _prompt_user_for_action(self, context: Dict[str, Any]) -> RecoveryAction:
        """
        Prompt the user to choose a recovery action.

        Args:
            context: Additional context about the failure

        Returns:
            RecoveryAction chosen by the user
        """
        logger.info("\n" + "=" * 80)
        logger.info("DEPLOYMENT VALIDATION FAILED")
        logger.info("=" * 80)

        # Display summary
        critical_count = sum(1 for f in self.failures if f.severity == "critical")
        warning_count = sum(1 for f in self.failures if f.severity == "warning")

        logger.info(f"\n📊 Validation Summary:")
        logger.info(f"  🔴 Critical issues: {critical_count}")
        logger.info(f"  ⚠️  Warnings: {warning_count}")
        logger.info(f"  🔄 Retry attempts: {self.retry_count}")

        # Display failures by component
        failures_by_component = {}
        for failure in self.failures:
            if failure.component not in failures_by_component:
                failures_by_component[failure.component] = []
            failures_by_component[failure.component].append(failure)

        logger.info("\n📋 Issues by Component:")
        for component, component_failures in failures_by_component.items():
            logger.info(f"\n  {component.upper()} ({len(component_failures)} issues):")
            for failure in component_failures[:3]:  # Show first 3
                severity_icon = "🔴" if failure.severity == "critical" else "⚠️"
                logger.info(f"    {severity_icon} {failure.error_message[:80]}...")
            if len(component_failures) > 3:
                logger.info(f"    ... and {len(component_failures) - 3} more")

        # Display recovery options
        logger.info("\n🔧 Recovery Options:")
        logger.info("  1. Regenerate All - Start fresh with new LLM generation (RECOMMENDED)")
        logger.info("  2. Regenerate Failed - Only regenerate components that failed validation")
        logger.info("  3. Fix Manually - Pause deployment and fix issues manually")
        logger.info("  4. Create Stubs - Create stub implementations to continue (DEV ONLY)")
        logger.info("  5. Abort - Cancel deployment")

        # Display context if available
        if context:
            logger.info("\n📝 Additional Context:")
            if "model" in context:
                logger.info(f"  Current LLM: {context['model']}")
            if "cache_file" in context:
                logger.info(f"  Cache file: {context['cache_file']}")
            if "phase" in context:
                logger.info(f"  Failed phase: {context['phase']}")

        # Get user input
        logger.info("\n" + "=" * 80)

        # In non-interactive mode, return default action
        # This will be overridden when integrated with the actual deployment script
        return self._get_default_action()

    def _get_default_action(self) -> RecoveryAction:
        """
        Get the default recovery action based on failure analysis.

        This is used when running in non-interactive mode or when
        the user doesn't provide input.
        """
        # If all failures are auto-fixable, try regenerating failed components
        if all(f.can_auto_fix for f in self.failures):
            return RecoveryAction.REGENERATE_FAILED

        # If there are critical failures, regenerate all
        if any(f.severity == "critical" for f in self.failures):
            return RecoveryAction.REGENERATE_ALL

        # Otherwise, let user fix manually
        return RecoveryAction.FIX_MANUALLY

    def get_failure_report(self) -> Dict[str, Any]:
        """
        Get a detailed failure report for logging or debugging.

        Returns:
            Dict containing detailed failure information
        """
        return {
            'retry_count': self.retry_count,
            'total_failures': len(self.failures),
            'critical_failures': sum(1 for f in self.failures if f.severity == "critical"),
            'warnings': sum(1 for f in self.failures if f.severity == "warning"),
            'auto_fixable': sum(1 for f in self.failures if f.can_auto_fix),
            'failures_by_component': self._group_failures_by_component(),
            'failures': [
                {
                    'component': f.component,
                    'error_type': f.error_type,
                    'error_message': f.error_message,
                    'severity': f.severity,
                    'can_auto_fix': f.can_auto_fix,
                    'suggested_action': f.suggested_action,
                }
                for f in self.failures
            ]
        }

    def _group_failures_by_component(self) -> Dict[str, int]:
        """Group failures by component for summary."""
        grouped = {}
        for failure in self.failures:
            if failure.component not in grouped:
                grouped[failure.component] = 0
            grouped[failure.component] += 1
        return grouped


def prompt_user_for_recovery(
    validation_errors: List[str],
    context: Optional[Dict[str, Any]] = None,
    max_auto_retries: int = 3
) -> RecoveryAction:
    """
    Convenience function to prompt user for recovery action.

    Args:
        validation_errors: List of validation error messages
        context: Additional context about the failure
        max_auto_retries: Maximum number of automatic retry attempts

    Returns:
        RecoveryAction chosen by the user
    """
    handler = UserEscalationHandler(max_auto_retries=max_auto_retries)
    return handler.handle_validation_failure(
        validation_errors,
        context or {}
    )
