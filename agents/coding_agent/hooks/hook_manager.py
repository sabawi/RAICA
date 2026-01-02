"""
Hook Manager Module
===================

Central orchestration system for latent hooks that execute at various points
during code generation and debugging.

Hook Triggers (Code Generation):
- PHASE_START, PHASE_END: Before/after development phases
- STEP_START, STEP_END: Before/after individual steps
- FILE_GENERATED: After a file is generated
- TEST_PASSED, TEST_FAILED: After test execution
- ERROR: When an error occurs

Hook Triggers (Code Debug - DO NO HARM mode):
- DEBUG_START: Debug workflow initiated
- DEBUG_BASELINE: Baseline snapshot captured before changes
- DEBUG_FIX_APPLIED: A fix was applied to the codebase
- DEBUG_REGRESSION: Regression detected after applying fix
- DEBUG_ROLLBACK: Changes being rolled back to baseline
- DEBUG_COMPLETE: Debug workflow completed (success or failure)
"""

import asyncio
import logging
import yaml
from pathlib import Path
from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Any, Awaitable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class HookTrigger(Enum):
    """Events that can trigger hooks."""
    # Standard development triggers
    PHASE_START = auto()
    PHASE_END = auto()
    STEP_START = auto()
    STEP_END = auto()
    FILE_GENERATED = auto()
    TEST_PASSED = auto()
    TEST_FAILED = auto()
    ERROR = auto()

    # CODE_DEBUG specific triggers (for debugging existing projects)
    DEBUG_START = auto()        # Debug workflow started
    DEBUG_BASELINE = auto()     # Baseline snapshot captured
    DEBUG_FIX_APPLIED = auto()  # A fix was applied to the code
    DEBUG_REGRESSION = auto()   # Regression detected after fix
    DEBUG_ROLLBACK = auto()     # Changes being rolled back
    DEBUG_COMPLETE = auto()     # Debug workflow completed


@dataclass
class HookResult:
    """Result from executing a hook."""
    hook_name: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class HookDefinition:
    """Definition of a hook."""
    name: str
    trigger: HookTrigger
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    enabled: bool = True
    phases: Optional[List[str]] = None  # None = all phases
    priority: int = 100  # Lower = runs first
    description: str = ""
    timeout_seconds: float = 30.0

    def should_run(self, context: Dict[str, Any]) -> bool:
        """Check if this hook should run given the context."""
        if not self.enabled:
            return False

        # Check phase filter
        if self.phases:
            current_phase = context.get('phase')
            if current_phase and current_phase not in self.phases:
                return False

        return True


class HookManager:
    """
    Central hook orchestration system.

    Manages registration and execution of hooks at various trigger points
    during the code generation process.
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the hook manager.

        Args:
            config_path: Optional path to hooks configuration YAML file
        """
        self.hooks: Dict[HookTrigger, List[HookDefinition]] = {
            trigger: [] for trigger in HookTrigger
        }
        self._config_path = config_path
        self._load_config()

        logger.debug("HookManager initialized")

    def _load_config(self):
        """Load hook configuration from YAML file if provided."""
        if not self._config_path or not self._config_path.exists():
            return

        try:
            with open(self._config_path, 'r') as f:
                config = yaml.safe_load(f)

            if config and 'hooks' in config:
                for hook_name, hook_config in config['hooks'].items():
                    enabled = hook_config.get('enabled', True)
                    # Update existing hooks or store config for later
                    self._hook_configs = getattr(self, '_hook_configs', {})
                    self._hook_configs[hook_name] = hook_config

            logger.info(f"Loaded hook configuration from {self._config_path}")

        except Exception as e:
            logger.warning(f"Failed to load hook config: {e}")

    def register(self, hook: HookDefinition) -> None:
        """
        Register a hook.

        Args:
            hook: HookDefinition to register
        """
        # Check if hook with same name already exists
        existing = [h for h in self.hooks[hook.trigger] if h.name == hook.name]
        if existing:
            # Replace existing
            self.hooks[hook.trigger].remove(existing[0])
            logger.debug(f"Replacing existing hook: {hook.name}")

        self.hooks[hook.trigger].append(hook)

        # Sort by priority (lower = runs first)
        self.hooks[hook.trigger].sort(key=lambda h: h.priority)

        logger.debug(f"Registered hook: {hook.name} on {hook.trigger.name}")

    def unregister(self, name: str) -> bool:
        """
        Unregister a hook by name.

        Args:
            name: Name of hook to unregister

        Returns:
            True if hook was found and removed
        """
        found = False
        for trigger in HookTrigger:
            for hook in self.hooks[trigger][:]:
                if hook.name == name:
                    self.hooks[trigger].remove(hook)
                    found = True
                    logger.debug(f"Unregistered hook: {name}")

        return found

    def enable(self, name: str) -> bool:
        """Enable a hook by name."""
        for trigger in HookTrigger:
            for hook in self.hooks[trigger]:
                if hook.name == name:
                    hook.enabled = True
                    logger.debug(f"Enabled hook: {name}")
                    return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a hook by name."""
        for trigger in HookTrigger:
            for hook in self.hooks[trigger]:
                if hook.name == name:
                    hook.enabled = False
                    logger.debug(f"Disabled hook: {name}")
                    return True
        return False

    async def trigger(
        self,
        trigger: HookTrigger,
        context: Dict[str, Any]
    ) -> List[HookResult]:
        """
        Trigger all hooks for an event.

        Args:
            trigger: The trigger event
            context: Context dict with relevant data (phase, files, etc.)

        Returns:
            List of HookResult from each executed hook
        """
        results = []
        hooks_to_run = [h for h in self.hooks[trigger] if h.should_run(context)]

        if not hooks_to_run:
            logger.debug(f"No hooks to run for {trigger.name}")
            return results

        logger.info(f"Triggering {len(hooks_to_run)} hooks for {trigger.name}")

        for hook in hooks_to_run:
            result = await self._execute_hook(hook, context)
            results.append(result)

            # Log result
            if result.success:
                logger.debug(f"Hook {hook.name} succeeded ({result.duration_ms:.0f}ms)")
            else:
                logger.warning(f"Hook {hook.name} failed: {result.error}")

        return results

    async def _execute_hook(
        self,
        hook: HookDefinition,
        context: Dict[str, Any]
    ) -> HookResult:
        """Execute a single hook with timeout."""
        import time
        start_time = time.time()

        try:
            # Run with timeout
            result = await asyncio.wait_for(
                hook.handler(context),
                timeout=hook.timeout_seconds
            )

            duration_ms = (time.time() - start_time) * 1000

            return HookResult(
                hook_name=hook.name,
                success=True,
                result=result,
                duration_ms=duration_ms
            )

        except asyncio.TimeoutError:
            duration_ms = (time.time() - start_time) * 1000
            return HookResult(
                hook_name=hook.name,
                success=False,
                error=f"Hook timed out after {hook.timeout_seconds}s",
                duration_ms=duration_ms
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return HookResult(
                hook_name=hook.name,
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )

    def list_hooks(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        List all registered hooks.

        Returns:
            Dict mapping trigger names to list of hook info
        """
        result = {}
        for trigger in HookTrigger:
            hooks = self.hooks[trigger]
            if hooks:
                result[trigger.name] = [
                    {
                        'name': h.name,
                        'enabled': h.enabled,
                        'priority': h.priority,
                        'phases': h.phases,
                        'description': h.description
                    }
                    for h in hooks
                ]
        return result

    def get_hook(self, name: str) -> Optional[HookDefinition]:
        """Get a hook by name."""
        for trigger in HookTrigger:
            for hook in self.hooks[trigger]:
                if hook.name == name:
                    return hook
        return None


# Singleton instance for convenience
_default_manager: Optional[HookManager] = None


def get_hook_manager(config_path: Optional[Path] = None) -> HookManager:
    """Get or create the default hook manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = HookManager(config_path)
    return _default_manager


def register_hook(
    name: str,
    trigger: HookTrigger,
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
    priority: int = 100,
    phases: Optional[List[str]] = None,
    description: str = ""
) -> None:
    """Convenience function to register a hook with the default manager."""
    hook = HookDefinition(
        name=name,
        trigger=trigger,
        handler=handler,
        priority=priority,
        phases=phases,
        description=description
    )
    get_hook_manager().register(hook)
