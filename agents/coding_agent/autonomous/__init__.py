"""
Autonomous Debug Loop Module
=============================

Provides autonomous debugging capabilities for RAICA:
- ProjectDebugContext: Persistent project-local context
- BugTestGenerator: Generate bug-specific tests
- AutonomousDebugController: Main debug loop controller

Design Principles:
1. Project Context is King - All context saved IN the project directory
2. No Approvals Until Stuck - Work autonomously, ask only when genuinely blocked
3. Iterate Until Fixed - Not a 1-shot, loop until bug eliminated
4. Test-Driven Verification - Generate bug-specific test, use it to verify fix
5. Minimal Changes - Fix the bug, don't refactor the world
"""

from .project_context import ProjectDebugContext, DebugSession, DebugIteration
from .bug_test_generator import BugTestGenerator
from .debug_controller import AutonomousDebugController, DebugResult, DebugStatus, DebugOutcome

__all__ = [
    'ProjectDebugContext',
    'DebugSession',
    'DebugIteration',
    'BugTestGenerator',
    'AutonomousDebugController',
    'DebugResult',
    'DebugStatus',
    'DebugOutcome',
]
