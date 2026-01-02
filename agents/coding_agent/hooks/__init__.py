"""
Hooks Module - Latent hook system for automated actions per step.

Components:
- hook_manager.py: Central hook orchestration with triggers
- builtin_hooks.py: Built-in hooks (doc_update, run_tests, git_commit)

Hook Triggers:
- PHASE_START, PHASE_END
- STEP_START, STEP_END
- FILE_GENERATED
- TEST_PASSED, TEST_FAILED
- ERROR
"""

from .hook_manager import HookManager, HookTrigger, HookDefinition
from .builtin_hooks import doc_update_hook, run_tests_hook, git_commit_hook

__all__ = [
    'HookManager', 'HookTrigger', 'HookDefinition',
    'doc_update_hook', 'run_tests_hook', 'git_commit_hook'
]
