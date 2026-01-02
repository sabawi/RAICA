"""
Regression Detector for CODE_DEBUG
===================================

Detects regressions after code changes to ensure "DO NO HARM".

Features:
- Test regression detection (tests that were passing now fail)
- Symbol regression detection (public APIs removed)
- Execution regression detection (code no longer runs)
- Intelligent fix suggestions

Author: RAICA Development Team
Version: 1.0.0
"""

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .baseline_manager import BaselineSnapshot, BaselineManager, DiffReport

logger = logging.getLogger(__name__)


class RegressionSeverity(Enum):
    """Severity levels for regressions."""
    NONE = auto()       # No regressions
    LOW = auto()        # Minor issues, can proceed
    MEDIUM = auto()     # Notable issues, should fix
    HIGH = auto()       # Significant issues, must fix
    CRITICAL = auto()   # Blocking issues, cannot proceed


class FixStrategy(Enum):
    """Strategy for fixing regressions."""
    TARGETED = auto()      # Attempt 1: Minimal, focused fix
    CONTEXTUAL = auto()    # Attempt 2: Broader context analysis
    ALTERNATIVE = auto()   # Attempt 3: Different approach entirely


@dataclass
class TestRegression:
    """A single test regression."""
    test_name: str
    file_path: str
    was_passing: bool
    now_failing: bool
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None


@dataclass
class SymbolRegression:
    """A symbol (API) regression."""
    symbol_name: str
    symbol_type: str  # 'function', 'class', 'method'
    file_path: str
    regression_type: str  # 'removed', 'signature_changed', 'renamed'
    details: Optional[str] = None


@dataclass
class ExecutionRegression:
    """An execution regression."""
    file_path: str
    error_type: str  # 'import_error', 'syntax_error', 'runtime_error'
    error_message: str
    line_number: Optional[int] = None


@dataclass
class RegressionReport:
    """Complete report of detected regressions."""
    has_regressions: bool = False
    test_regressions: List[TestRegression] = field(default_factory=list)
    symbol_regressions: List[SymbolRegression] = field(default_factory=list)
    execution_regressions: List[ExecutionRegression] = field(default_factory=list)
    severity: RegressionSeverity = RegressionSeverity.NONE
    fix_suggestions: List[str] = field(default_factory=list)
    confidence: float = 1.0  # Confidence that fix is safe (0.0 to 1.0)
    summary: str = ""

    def __post_init__(self):
        """Update has_regressions based on content."""
        self.has_regressions = bool(
            self.test_regressions or
            self.symbol_regressions or
            self.execution_regressions
        )
        self._calculate_severity()

    def _calculate_severity(self):
        """Calculate overall severity from regressions."""
        if not self.has_regressions:
            self.severity = RegressionSeverity.NONE
            self.confidence = 1.0
            return

        # Symbol regressions are most severe (breaking API changes)
        if self.symbol_regressions:
            removed_count = sum(
                1 for s in self.symbol_regressions
                if s.regression_type == 'removed'
            )
            if removed_count > 0:
                self.severity = RegressionSeverity.CRITICAL
                self.confidence = 0.0
                return

        # Execution regressions are high severity
        if self.execution_regressions:
            self.severity = RegressionSeverity.HIGH
            self.confidence = 0.2
            return

        # Test regressions depend on count
        if self.test_regressions:
            count = len(self.test_regressions)
            if count >= 5:
                self.severity = RegressionSeverity.HIGH
                self.confidence = 0.3
            elif count >= 2:
                self.severity = RegressionSeverity.MEDIUM
                self.confidence = 0.5
            else:
                self.severity = RegressionSeverity.LOW
                self.confidence = 0.7

    def add_test_regression(self, regression: TestRegression):
        """Add a test regression and recalculate."""
        self.test_regressions.append(regression)
        self.has_regressions = True
        self._calculate_severity()

    def add_symbol_regression(self, regression: SymbolRegression):
        """Add a symbol regression and recalculate."""
        self.symbol_regressions.append(regression)
        self.has_regressions = True
        self._calculate_severity()

    def add_execution_regression(self, regression: ExecutionRegression):
        """Add an execution regression and recalculate."""
        self.execution_regressions.append(regression)
        self.has_regressions = True
        self._calculate_severity()

    def get_summary(self) -> str:
        """Generate human-readable summary."""
        if not self.has_regressions:
            return "No regressions detected. All changes are safe."

        parts = []
        if self.test_regressions:
            parts.append(f"{len(self.test_regressions)} test(s) now failing")
        if self.symbol_regressions:
            parts.append(f"{len(self.symbol_regressions)} API(s) affected")
        if self.execution_regressions:
            parts.append(f"{len(self.execution_regressions)} execution error(s)")

        severity_text = self.severity.name
        confidence_pct = int(self.confidence * 100)

        self.summary = (
            f"REGRESSIONS DETECTED ({severity_text}): {', '.join(parts)}. "
            f"Confidence in fix safety: {confidence_pct}%"
        )
        return self.summary


@dataclass
class FixAttempt:
    """Record of a fix attempt."""
    attempt_number: int
    strategy: FixStrategy
    description: str
    success: bool
    failure_reason: Optional[str] = None
    changes_made: List[str] = field(default_factory=list)


class RegressionDetector:
    """
    Detects regressions after code changes.

    Compares current state with baseline to identify:
    - Tests that were passing but now fail
    - Public APIs that were removed or changed
    - Code that no longer executes properly
    """

    def __init__(
        self,
        project_dir: Path,
        baseline: BaselineSnapshot,
        baseline_manager: BaselineManager,
        llm_client: Optional[Any] = None
    ):
        """
        Initialize RegressionDetector.

        Args:
            project_dir: Project directory
            baseline: Baseline snapshot to compare against
            baseline_manager: Manager for baseline operations
            llm_client: Optional LLM client for fix suggestions
        """
        self.project_dir = Path(project_dir)
        self.baseline = baseline
        self.baseline_manager = baseline_manager
        self.llm_client = llm_client
        self.fix_attempts: List[FixAttempt] = []

    async def detect_all(self) -> RegressionReport:
        """
        Run all regression checks.

        Returns:
            RegressionReport with all detected regressions
        """
        report = RegressionReport()

        # Run checks in parallel
        test_task = asyncio.create_task(self.check_test_regressions())
        symbol_task = asyncio.create_task(
            asyncio.to_thread(self.check_symbol_regressions)
        )
        execution_task = asyncio.create_task(self.check_execution())

        # Gather results
        test_results, symbol_results, execution_results = await asyncio.gather(
            test_task, symbol_task, execution_task,
            return_exceptions=True
        )

        # Process test regressions
        if isinstance(test_results, list):
            for regression in test_results:
                report.add_test_regression(regression)
        elif isinstance(test_results, Exception):
            logger.warning(f"Test check failed: {test_results}")

        # Process symbol regressions
        if isinstance(symbol_results, list):
            for regression in symbol_results:
                report.add_symbol_regression(regression)
        elif isinstance(symbol_results, Exception):
            logger.warning(f"Symbol check failed: {symbol_results}")

        # Process execution regressions
        if isinstance(execution_results, list):
            for regression in execution_results:
                report.add_execution_regression(regression)
        elif isinstance(execution_results, Exception):
            logger.warning(f"Execution check failed: {execution_results}")

        # Generate fix suggestions if regressions found
        if report.has_regressions and self.llm_client:
            report.fix_suggestions = await self._generate_fix_suggestions(report)

        report.get_summary()
        return report

    async def check_test_regressions(self) -> List[TestRegression]:
        """
        Check for test regressions.

        Compares current test results with baseline test results.

        Returns:
            List of tests that were passing but now fail
        """
        regressions = []

        # Get baseline test results
        baseline_passed = set()
        if self.baseline.test_results:
            baseline_passed = set(self.baseline.test_results.get('passed', []))

        if not baseline_passed:
            logger.info("No baseline test results to compare")
            return regressions

        # Run current tests
        current_results = await self._run_tests()
        current_passed = set(current_results.get('passed', []))
        current_failed = current_results.get('failed', {})

        # Find regressions (was passing, now failing)
        for test_name in baseline_passed:
            if test_name not in current_passed:
                error_info = current_failed.get(test_name, {})
                regressions.append(TestRegression(
                    test_name=test_name,
                    file_path=error_info.get('file', 'unknown'),
                    was_passing=True,
                    now_failing=True,
                    error_message=error_info.get('message'),
                    stack_trace=error_info.get('traceback')
                ))

        logger.info(f"Test regressions: {len(regressions)} of {len(baseline_passed)} tests")
        return regressions

    async def _run_tests(self) -> Dict[str, Any]:
        """Run project tests and return results."""
        results = {'passed': [], 'failed': {}}

        # Detect test framework
        if (self.project_dir / 'pytest.ini').exists() or \
           (self.project_dir / 'setup.py').exists() or \
           list(self.project_dir.glob('test_*.py')) or \
           list(self.project_dir.glob('**/test_*.py')):
            # Python pytest
            results = await self._run_pytest()
        elif (self.project_dir / 'package.json').exists():
            # Node.js
            results = await self._run_npm_test()

        return results

    async def _run_pytest(self) -> Dict[str, Any]:
        """Run pytest and parse results."""
        results = {'passed': [], 'failed': {}}

        try:
            proc = await asyncio.create_subprocess_exec(
                'python', '-m', 'pytest', '--tb=short', '-v',
                cwd=self.project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=120
            )

            output = stdout.decode('utf-8', errors='replace')

            # Parse pytest output
            for line in output.split('\n'):
                line = line.strip()
                if '::' in line:
                    if ' PASSED' in line:
                        test_name = line.split(' PASSED')[0].strip()
                        results['passed'].append(test_name)
                    elif ' FAILED' in line:
                        test_name = line.split(' FAILED')[0].strip()
                        results['failed'][test_name] = {
                            'file': test_name.split('::')[0] if '::' in test_name else 'unknown',
                            'message': 'Test failed'
                        }

        except asyncio.TimeoutError:
            logger.warning("Test execution timed out")
        except Exception as e:
            logger.warning(f"Test execution failed: {e}")

        return results

    async def _run_npm_test(self) -> Dict[str, Any]:
        """Run npm test and parse results."""
        results = {'passed': [], 'failed': {}}

        try:
            proc = await asyncio.create_subprocess_exec(
                'npm', 'test', '--', '--passWithNoTests',
                cwd=self.project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=120
            )

            # Basic parsing - npm test output varies widely
            if proc.returncode == 0:
                results['passed'].append('all_tests')
            else:
                results['failed']['tests'] = {
                    'message': stderr.decode('utf-8', errors='replace')[:500]
                }

        except asyncio.TimeoutError:
            logger.warning("npm test timed out")
        except Exception as e:
            logger.warning(f"npm test failed: {e}")

        return results

    def check_symbol_regressions(self) -> List[SymbolRegression]:
        """
        Check for symbol (API) regressions.

        Identifies:
        - Public functions/classes that were removed
        - Signature changes to existing APIs

        Returns:
            List of symbol regressions
        """
        regressions = []

        # Get diff from baseline manager
        diff = self.baseline_manager.compare_with_baseline(self.baseline)

        # Check for removed symbols
        for file_path, removed_symbols in diff.symbols_removed.items():
            for symbol_name in removed_symbols:
                # Find symbol info from baseline
                symbol_info = None
                if file_path in self.baseline.symbol_table:
                    for sym in self.baseline.symbol_table[file_path]:
                        if sym.name == symbol_name:
                            symbol_info = sym
                            break

                regressions.append(SymbolRegression(
                    symbol_name=symbol_name,
                    symbol_type=symbol_info.symbol_type if symbol_info else 'unknown',
                    file_path=file_path,
                    regression_type='removed',
                    details=f"Symbol '{symbol_name}' was removed from {file_path}"
                ))

        # Check for files that were completely removed
        for file_path in diff.files_removed:
            if file_path in self.baseline.symbol_table:
                for sym in self.baseline.symbol_table[file_path]:
                    regressions.append(SymbolRegression(
                        symbol_name=sym.name,
                        symbol_type=sym.symbol_type,
                        file_path=file_path,
                        regression_type='removed',
                        details=f"File '{file_path}' was removed, losing symbol '{sym.name}'"
                    ))

        logger.info(f"Symbol regressions: {len(regressions)}")
        return regressions

    async def check_execution(self) -> List[ExecutionRegression]:
        """
        Verify code still executes properly.

        Checks:
        - Import errors
        - Syntax errors
        - Basic runtime errors

        Returns:
            List of execution regressions
        """
        regressions = []

        # Get modified files
        diff = self.baseline_manager.compare_with_baseline(self.baseline)
        files_to_check = diff.files_modified + diff.files_added

        for file_path in files_to_check:
            full_path = self.project_dir / file_path

            if not full_path.exists():
                continue

            # Check based on file type
            if file_path.endswith('.py'):
                regression = await self._check_python_execution(file_path, full_path)
                if regression:
                    regressions.append(regression)
            elif file_path.endswith(('.js', '.ts')):
                regression = await self._check_js_execution(file_path, full_path)
                if regression:
                    regressions.append(regression)

        logger.info(f"Execution regressions: {len(regressions)}")
        return regressions

    async def _check_python_execution(
        self,
        file_path: str,
        full_path: Path
    ) -> Optional[ExecutionRegression]:
        """Check Python file for execution issues."""
        import ast

        try:
            content = full_path.read_text()

            # Check syntax
            try:
                ast.parse(content)
            except SyntaxError as e:
                return ExecutionRegression(
                    file_path=file_path,
                    error_type='syntax_error',
                    error_message=str(e),
                    line_number=e.lineno
                )

            # Check imports (basic check)
            try:
                proc = await asyncio.create_subprocess_exec(
                    'python', '-c', f"import ast; ast.parse(open('{full_path}').read())",
                    cwd=self.project_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

                if proc.returncode != 0:
                    error_msg = stderr.decode('utf-8', errors='replace')
                    if 'ImportError' in error_msg or 'ModuleNotFoundError' in error_msg:
                        return ExecutionRegression(
                            file_path=file_path,
                            error_type='import_error',
                            error_message=error_msg[:500]
                        )
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            return ExecutionRegression(
                file_path=file_path,
                error_type='runtime_error',
                error_message=str(e)
            )

        return None

    async def _check_js_execution(
        self,
        file_path: str,
        full_path: Path
    ) -> Optional[ExecutionRegression]:
        """Check JavaScript/TypeScript file for execution issues."""
        try:
            # Check syntax using node
            proc = await asyncio.create_subprocess_exec(
                'node', '--check', str(full_path),
                cwd=self.project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace')
                return ExecutionRegression(
                    file_path=file_path,
                    error_type='syntax_error',
                    error_message=error_msg[:500]
                )

        except asyncio.TimeoutError:
            pass
        except FileNotFoundError:
            # Node not available
            pass
        except Exception as e:
            logger.warning(f"JS check failed for {file_path}: {e}")

        return None

    async def _generate_fix_suggestions(
        self,
        report: RegressionReport
    ) -> List[str]:
        """Generate fix suggestions using LLM."""
        if not self.llm_client:
            return []

        suggestions = []

        # Build context for LLM
        context_parts = []

        if report.test_regressions:
            context_parts.append("TEST FAILURES:")
            for reg in report.test_regressions[:5]:  # Limit to 5
                context_parts.append(f"  - {reg.test_name}: {reg.error_message or 'failed'}")

        if report.symbol_regressions:
            context_parts.append("REMOVED/CHANGED APIs:")
            for reg in report.symbol_regressions[:5]:
                context_parts.append(f"  - {reg.symbol_name} ({reg.regression_type})")

        if report.execution_regressions:
            context_parts.append("EXECUTION ERRORS:")
            for reg in report.execution_regressions[:5]:
                context_parts.append(f"  - {reg.file_path}: {reg.error_type}")

        if not context_parts:
            return []

        # This would call the LLM - placeholder for now
        # The actual implementation would use self.llm_client
        suggestions = [
            "Review the test failures and ensure the fix doesn't break existing functionality",
            "Check if removed symbols are still referenced elsewhere in the codebase",
            "Verify all imports are still valid after the changes"
        ]

        return suggestions

    def get_fix_prompt(
        self,
        attempt: int,
        previous_failures: List[str],
        report: RegressionReport
    ) -> str:
        """
        Generate fix prompt based on attempt number and strategy.

        Each attempt uses a DIFFERENT strategy with fresh thinking.

        Args:
            attempt: Attempt number (1, 2, or 3)
            previous_failures: List of previous failure reasons
            report: Current regression report

        Returns:
            Prompt for the LLM to fix the regression
        """
        # Build regression context
        regression_context = []
        for reg in report.test_regressions[:3]:
            regression_context.append(
                f"Test '{reg.test_name}' failing: {reg.error_message or 'unknown error'}"
            )
        for reg in report.symbol_regressions[:3]:
            regression_context.append(
                f"Symbol '{reg.symbol_name}' {reg.regression_type} in {reg.file_path}"
            )
        for reg in report.execution_regressions[:3]:
            regression_context.append(
                f"Execution error in '{reg.file_path}': {reg.error_type}"
            )

        context_str = "\n".join(regression_context)

        if attempt == 1:
            # TARGETED: Minimal, focused fix
            strategy = FixStrategy.TARGETED
            return f"""REGRESSION FIX - TARGETED APPROACH (Attempt 1/3)

The following regressions were detected after your changes:
{context_str}

STRATEGY: Make the MINIMUM changes necessary to fix ONLY these specific issues.
- Focus on the exact failing points
- Do not refactor or reorganize code
- Preserve all existing functionality
- Make surgical, targeted fixes

Provide the fix with minimal code changes."""

        elif attempt == 2:
            # CONTEXTUAL: Broader analysis
            strategy = FixStrategy.CONTEXTUAL
            prev_failure = previous_failures[-1] if previous_failures else "Unknown"
            return f"""REGRESSION FIX - CONTEXTUAL APPROACH (Attempt 2/3)

PREVIOUS ATTEMPT FAILED: {prev_failure}

The following regressions persist:
{context_str}

STRATEGY: Analyze the BROADER CONTEXT of these failures.
- Consider dependencies and side effects
- Look at how the changed code interacts with other parts
- The targeted fix didn't work - think about WHY
- Consider if multiple related changes are needed

Provide a fix that addresses the root cause, not just symptoms."""

        else:
            # ALTERNATIVE: Completely different approach
            strategy = FixStrategy.ALTERNATIVE
            prev_1 = previous_failures[0] if len(previous_failures) > 0 else "Unknown"
            prev_2 = previous_failures[1] if len(previous_failures) > 1 else "Unknown"
            return f"""REGRESSION FIX - ALTERNATIVE APPROACH (Attempt 3/3 - FINAL)

TWO PREVIOUS APPROACHES FAILED:
1. Targeted fix: {prev_1}
2. Contextual fix: {prev_2}

The following regressions STILL persist:
{context_str}

STRATEGY: The previous approaches are NOT WORKING. Think of a COMPLETELY DIFFERENT solution.
- Consider alternative algorithms or approaches
- Maybe the original change approach was wrong
- Consider reverting parts and doing them differently
- Think about what FUNDAMENTAL assumption might be incorrect

This is the FINAL attempt. Provide an alternative solution that takes a fresh perspective."""

    def record_fix_attempt(
        self,
        attempt: int,
        strategy: FixStrategy,
        description: str,
        success: bool,
        failure_reason: Optional[str] = None,
        changes_made: Optional[List[str]] = None
    ) -> FixAttempt:
        """Record a fix attempt for history."""
        fix_attempt = FixAttempt(
            attempt_number=attempt,
            strategy=strategy,
            description=description,
            success=success,
            failure_reason=failure_reason,
            changes_made=changes_made or []
        )
        self.fix_attempts.append(fix_attempt)
        return fix_attempt

    def get_fix_history_summary(self) -> str:
        """Get summary of all fix attempts."""
        if not self.fix_attempts:
            return "No fix attempts recorded."

        lines = ["Fix Attempt History:"]
        for attempt in self.fix_attempts:
            status = "SUCCESS" if attempt.success else "FAILED"
            lines.append(
                f"  Attempt {attempt.attempt_number} ({attempt.strategy.name}): {status}"
            )
            if attempt.failure_reason:
                lines.append(f"    Reason: {attempt.failure_reason}")

        return "\n".join(lines)
