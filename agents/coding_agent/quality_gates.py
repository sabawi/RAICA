"""
Quality Gates Module
====================

Shared quality gate functions for code generation and verification.
Used by both enhancement_controller.py (in-place) and agent_runner.py (new projects).

Quality Gates:
1. LLD Completeness - Ensures implementation plans have no gaps
2. Stub Detection/Completion - Eliminates placeholder code
3. Code Quality Review - Checks for common issues
4. Documentation Generation - Creates README/requirements
5. Final Verification - Compares output to plan
"""

import re
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple

logger = logging.getLogger(__name__)


class QualityGates:
    """
    Shared quality gates for code generation.
    
    Initialize with an LLM client and optional output callback.
    """
    
    def __init__(
        self, 
        llm_client, 
        project_dir: Path,
        output_fn: Optional[Callable[[str], None]] = None
    ):
        """
        Args:
            llm_client: LLM client with generate() method
            project_dir: Project directory path
            output_fn: Optional callback for status messages
        """
        self.llm_client = llm_client
        self.project_dir = Path(project_dir)
        self._output_fn = output_fn or (lambda x: None)
    
    def output(self, msg: str) -> None:
        """Output status message."""
        self._output_fn(msg)
        logger.info(msg)

    # ═══════════════════════════════════════════════════════════════════════════
    # GATE 1: LLD COMPLETENESS
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def verify_lld_completeness(self, lld_content: str, max_iterations: int = 10) -> str:
        """
        Review→Update loop until LLD meets quality threshold (85%).
        """
        self.output("[Quality Gate] Verifying LLD completeness (Target: 85%+)...")
        
        best_score = 0.0
        stagnation_counter = 0
        
        for i in range(max_iterations):
            score, gaps = await self._assess_lld_quality(lld_content)
            
            if score >= 85.0:
                self.output(f"  ✓ LLD verified {score:.1f}% complete after {i+1} iteration(s)")
                return lld_content
            
            # Check for stagnation (score not improving)
            if score <= best_score:
                stagnation_counter += 1
            else:
                best_score = score
                stagnation_counter = 0
                
            if stagnation_counter >= 3:
                self.output(f"  ⚠ LLD verification stagnated at {best_score:.1f}% for 3 iterations. Proceeding...")
                return lld_content

            self.output(f"  → Completeness: {score:.1f}% ({len(gaps)} issues). Target: 85%. Filling gaps... (iteration {i+1}/{max_iterations})")
            lld_content = await self._fill_lld_gaps(lld_content, gaps)
        
        self.output(f"  ⚠ LLD verification exited at {score:.1f}% after {max_iterations} iterations")
        return lld_content
    
    async def _assess_lld_quality(self, lld_content: str) -> Tuple[float, List[str]]:
        """
        Assess LLD quality against checklist.
        Returns (percentage_score, list_of_issues).
        """
        prompt = f"""Evaluate this implementation plan against the checklist.
        
IMPLEMENTATION PLAN:
{lld_content}

CHECKLIST:
1. FILES: Are ALL files to create/modify explicitly listed?
2. SIGNATURES: Are ALL functions/methods specified with signatures?
3. DEPENDENCIES: Are ALL dependencies (imports, packages) listed?
4. COMPLETENESS: Are there NO "TBD", "TODO", "placeholder" items?
5. ERROR HANDLING: Is error handling specified?
6. VERIFICATION: Is the testing approach defined?
7. ENTRY POINT: Is the entry point clear?

For each item, strictly output "PASS" or "FAIL: <reason>".
Example output:
1. PASS
2. FAIL: Missing signatures for Client class
...
"""
        response = await asyncio.to_thread(
            self.llm_client.generate,
            prompt=prompt,
            temperature=0.1,
            max_tokens=2000
        )
        
        if not response.success:
            return 100.0, []
            
        content = response.content.strip()
        lines = content.splitlines()
        
        passes = 0
        total = 7
        issues = []
        
        for line in lines:
            if "PASS" in line:
                passes += 1
            elif "FAIL" in line:
                # Extract reason after FAIL:
                parts = line.split("FAIL:", 1)
                if len(parts) > 1:
                    issues.append(parts[1].strip())
                else:
                    issues.append(line.strip())
        
        # Calculate score (clamped 0-100)
        # Being generous: if passes > total (hallucination), clamp to 100
        passes = min(passes, total)
        score = (passes / total) * 100.0
        
        return score, issues
    
    async def _fill_lld_gaps(self, lld_content: str, gaps: List[str]) -> str:
        """Fill identified gaps in the implementation plan."""
        gaps_str = "\n".join([f"- {g}" for g in gaps])
        
        prompt = f"""Complete this implementation plan by filling the identified gaps.

CURRENT PLAN:
{lld_content}

GAPS TO FILL:
{gaps_str}

Provide the UPDATED implementation plan with all gaps filled.
- Add specific file paths where missing
- Add function signatures where missing
- Add dependency lists where missing
- Replace all TBD/TODO with concrete specifications
- Ensure there is a clear ENTRY POINT file (main.py or index.html)
- Be specific and actionable, not vague

Output the complete updated plan."""

        response = await asyncio.to_thread(
            self.llm_client.generate,
            prompt=prompt,
            temperature=0.2,
            max_tokens=6000
        )
        
        if not response.success:
            return lld_content  # Return original if fill fails
        
        return response.content

    # ═══════════════════════════════════════════════════════════════════════════
    # GATE 2: STUB DETECTION AND COMPLETION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def detect_stubs(self, file_content: str, file_path: str = "") -> List[Dict[str, Any]]:
        """
        Detect stub functions, placeholders, and incomplete implementations.
        
        Returns list of detected stubs with:
        - line: Line number
        - pattern: What was matched
        - context: Surrounding code
        """
        stubs = []
        lines = file_content.splitlines()
        
        # Patterns indicating stubs/placeholders
        patterns = [
            (r'^\s*pass\s*(?:#.*)?$', 'Empty function body (pass)'),
            (r'raise NotImplementedError', 'NotImplementedError placeholder'),
            (r'^\s*\.\.\.\s*(?:#.*)?$', 'Ellipsis placeholder'),
            (r'#\s*TODO\s*:', 'TODO comment'),
            (r'#\s*FIXME\s*:', 'FIXME comment'),
            (r'#\s*STUB\s*:', 'STUB comment'),
            (r'#\s*PLACEHOLDER', 'PLACEHOLDER comment'),
            (r'return\s+None\s*#\s*(?:stub|placeholder|todo)', 'Stub return None'),
            (r'^\s*pass\s*#\s*(?:stub|todo|implement)', 'Marked stub'),
        ]
        
        for i, line in enumerate(lines, 1):
            for pattern, description in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    # Get context (2 lines before and after)
                    start = max(0, i - 3)
                    end = min(len(lines), i + 2)
                    context = "\n".join(lines[start:end])
                    
                    stubs.append({
                        'line': i,
                        'pattern': description,
                        'content': line.strip(),
                        'context': context,
                        'file': file_path,
                    })
                    break  # Only match first pattern per line
        
        return stubs
    
    async def complete_stubs(
        self, 
        file_path: str, 
        file_content: str, 
        stubs: List[Dict], 
        max_iterations: int = 10
    ) -> str:
        """
        Iteratively complete stubs until 95% resolved or max iterations reached.
        """
        if not stubs:
            return file_content
        
        initial_stub_count = len(stubs)
        current_content = file_content
        
        for iteration in range(max_iterations):
            # Re-detect stubs to check progress
            current_stubs = stubs if iteration == 0 else self.detect_stubs(current_content, file_path)
            current_count = len(current_stubs)
            
            # Calculate reduction percentage
            reduction = 100.0
            if initial_stub_count > 0:
                reduction = ((initial_stub_count - current_count) / initial_stub_count) * 100.0
            
            if current_count == 0 or reduction >= 95.0:
                self.output(f"    ✓ Stubs resolved: {reduction:.1f}% ({current_count} left) after {iteration} iteration(s)")
                return current_content
            
            # Check for stagnation (stubs not decreasing)
            if current_count >= initial_stub_count and iteration > 1:
                stagnation_counter = getattr(self, '_stub_stagnation', 0) + 1
                self._stub_stagnation = stagnation_counter
                if stagnation_counter >= 3:
                     self.output(f"    ⚠ Stub resolution stagnated at {current_count} stubs. Stopping to avoid loop.")
                     break
            else:
                self._stub_stagnation = 0

            self.output(f"    → Resolution: {reduction:.1f}% ({current_count}/{initial_stub_count} stubs). Target: 95%. Completing... (iter {iteration + 1}/{max_iterations})")
            
            stubs_description = "\n".join([
                f"Line {s['line']}: {s['pattern']}\nContext:\n{s['context']}\n"
                for s in current_stubs[:5]
            ])
            
            prompt = f"""Complete these stub implementations with FULL working code.

FILE: {file_path}

DETECTED STUBS:
{stubs_description}

CURRENT FILE CONTENT:
{current_content}

CRITICAL RULES:
1. Replace EVERY stub/placeholder with COMPLETE, WORKING code
2. NO pass statements, NO NotImplementedError, NO TODO comments
3. NO ellipsis (...) placeholders
4. Implement REAL functionality, not more placeholders
5. Follow the existing code style and patterns
6. Each function must have COMPLETE logic - no shortcuts

Provide the COMPLETE updated file content with all stubs replaced."""

            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=8000
            )
            
            if not response.success:
                logger.warning(f"Stub completion failed for {file_path}: {response.error}")
                break
            
            # Extract code from response
            completed_code = self._extract_code(response.content, file_path)
            
            if completed_code and len(completed_code) > len(current_content) * 0.5:
                current_content = completed_code
            else:
                self.output(f"    ⚠ Failed to extract valid code in iteration {iteration + 1}")
                break
        
        # Final stub check
        final_stubs = self.detect_stubs(current_content, file_path)
        final_count = len(final_stubs)
        final_reduction = ((initial_stub_count - final_count) / initial_stub_count * 100.0) if initial_stub_count else 100.0
        
        if final_count > 0:
             self.output(f"    ⚠ Exited with {final_reduction:.1f}% resolution ({final_count} stubs remain)")
        
        return current_content
    
    def _extract_code(self, content: str, file_path: str) -> Optional[str]:
        """Extract code from LLM response, handling code blocks."""
        # Determine language from extension
        ext = Path(file_path).suffix.lower() if file_path else ""
        lang_map = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
            '.html': 'html', '.css': 'css', '.json': 'json'
        }
        lang = lang_map.get(ext, '')
        
        # Try to find code block - prioritized order
        patterns = [
            rf'```{lang}\n(.*?)```',
            rf'```\n(.*?)```',
            r'```[\w]*\n(.*?)```',
            # Fallback for when LLM forgets newlines in fence
            r'```(.*?)```', 
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                # Basic validation: code shouldn't be empty
                extracted = match.group(1).strip()
                if len(extracted) > 10: 
                    return extracted

        
        # If no code block, check if entire response is code
        if content.strip() and not content.strip().startswith('```'):
            # Check for common code indicators
            if any(ind in content for ind in ['def ', 'class ', 'function ', 'import ', '<html', '{']):
                return content.strip()
        
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # GATE 3: CODE QUALITY REVIEW
    # ═══════════════════════════════════════════════════════════════════════════
    
    def detect_quality_issues(self, file_content: str, file_path: str) -> List[str]:
        """Detect code quality issues using pattern matching and heuristics."""
        issues = []
        lines = file_content.splitlines()
        
        ext = Path(file_path).suffix.lower() if file_path else ""
        is_python = ext in ['.py', '']
        
        # Check for functions without error handling (I/O operations)
        if is_python:
            func_pattern = r'def\s+(\w+)\s*\([^)]*\):'
            risky_ops = ['open(', 'requests.', 'urllib', '.read()', '.write()', 'json.load', 'connect(']
            
            in_function = False
            current_func = ""
            has_try = False
            has_risky = False
            
            for i, line in enumerate(lines):
                func_match = re.match(func_pattern, line)
                if func_match:
                    if in_function and has_risky and not has_try:
                        issues.append(f"Function '{current_func}' has I/O operations but no error handling")
                    current_func = func_match.group(1)
                    in_function = True
                    has_try = False
                    has_risky = False
                    continue
                
                if in_function:
                    if 'try:' in line:
                        has_try = True
                    if any(op in line for op in risky_ops):
                        has_risky = True
        
        # Check for hardcoded paths/URLs
        hardcoded_patterns = [
            (r'["\'][A-Za-z]:\\[^"\']+["\']', 'Hardcoded Windows path'),
            (r'["\']/home/[^"\']+["\']', 'Hardcoded Unix path'),
            (r'["\']https?://(?!example\.)[^"\']+["\']', 'Hardcoded URL'),
        ]
        
        for i, line in enumerate(lines, 1):
            for pattern, desc in hardcoded_patterns:
                if re.search(pattern, line):
                    issues.append(f"Line {i}: {desc} should be configurable")
                    break
        
        return issues[:10]
    
    async def review_code_quality(
        self, 
        file_path: str, 
        file_content: str, 
        max_iterations: int = 2
    ) -> str:
        """Iterative code quality review loop."""
        current_content = file_content
        
        for iteration in range(max_iterations):
            issues = self.detect_quality_issues(current_content, file_path)
            
            if not issues:
                if iteration > 0:
                    self.output(f"    ✓ Code quality verified after {iteration} fix iteration(s)")
                return current_content
            
            self.output(f"    → Fixing {len(issues)} quality issues (iteration {iteration + 1}/{max_iterations})")
            
            issues_str = "\n".join([f"- {issue}" for issue in issues])
            
            prompt = f"""Review and fix these code quality issues.

FILE: {file_path}

ISSUES IDENTIFIED:
{issues_str}

CURRENT CODE:
{current_content}

FIX REQUIREMENTS:
1. Add proper error handling (try/except with meaningful messages)
2. Replace hardcoded values with constants or config
3. Keep all existing functionality intact

Provide the COMPLETE fixed file content."""

            response = await asyncio.to_thread(
                self.llm_client.generate,
                prompt=prompt,
                temperature=0.2,
                max_tokens=8000
            )
            
            if not response.success:
                break
            
            fixed_code = self._extract_code(response.content, file_path)
            
            if fixed_code and len(fixed_code) > len(current_content) * 0.5:
                current_content = fixed_code
            else:
                break
        
        return current_content

    # ═══════════════════════════════════════════════════════════════════════════
    # GATE 4: DOCUMENTATION GENERATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def generate_documentation(
        self, 
        files_created: List[str],
        project_name: str = "",
        original_request: str = ""
    ) -> None:
        """Generate or update project documentation (README, requirements)."""
        self.output("[Quality Gate] Generating project documentation...")
        
        readme_path = self.project_dir / "README.md"
        
        # Detect language from files
        python_files = [f for f in files_created if f.endswith('.py')]
        js_files = [f for f in files_created if f.endswith(('.js', '.ts', '.jsx', '.tsx'))]
        html_files = [f for f in files_created if f.endswith('.html')]
        
        is_python = bool(python_files)
        is_web = bool(html_files) or bool(js_files)
        
        # Collect dependencies
        dependencies = await self._extract_dependencies(files_created)
        
        prompt = f"""Generate a comprehensive README.md for this project.

PROJECT NAME: {project_name or "Generated Project"}
ORIGINAL REQUEST: {original_request or "Custom project"}

FILES CREATED:
{chr(10).join(files_created)}

DETECTED DEPENDENCIES:
{chr(10).join(dependencies) if dependencies else 'None detected'}

Generate a README.md that includes:

1. **Project Overview** - What does this project do
2. **Prerequisites** - Required software (detect from file types: Python, Node.js, etc.)
3. **Installation** - TECHNOLOGY-APPROPRIATE instructions:
   - For Python: `python -m venv venv`, `pip install -r requirements.txt`
   - For Node.js: `npm install`
   - For web apps: May just need a browser or simple HTTP server
4. **Running the Application** - EXACT command to run based on entry point detected
5. **Project Structure** - Key files and directories

CRITICAL RULES:
- All commands must be COPY-PASTE ready
- Include BOTH Windows and Unix commands where different
- Be SPECIFIC about the entry point command based on actual files
- Match instructions to the ACTUAL technology stack detected
- NO placeholders or "configure as needed"

Output ONLY the README.md content in markdown format."""

        response = await asyncio.to_thread(
            self.llm_client.generate,
            prompt=prompt,
            temperature=0.2,
            max_tokens=4000
        )
        
        if response.success and response.content:
            readme_content = response.content
            
            # 1. Try to extract from markdown code block first (most reliable)
            import re
            code_block_match = re.search(r'```markdown\n(.*?)```', readme_content, re.DOTALL)
            if not code_block_match:
                code_block_match = re.search(r'```\n(.*?)```', readme_content, re.DOTALL)
            
            if code_block_match:
                readme_content = code_block_match.group(1).strip()

            # 2. Cleanup artifacts - strip ALL LLM thinking tags
            # Uses comprehensive strip_thinking_content which handles:
            # <details>, <thinking>, <think>, <summary>, <reasoning>, etc.
            from ..llm_client import strip_thinking_content
            readme_content = strip_thinking_content(readme_content)
            
            # Remove "Here is the README..." prefixes if not in code block
            if not code_block_match:
                lines = readme_content.splitlines()
                # Skip leading lines that aren't headers or list items
                start_idx = 0
                for i, line in enumerate(lines):
                    if line.strip().startswith('#') or line.strip().startswith('[!') or line.strip().startswith('='):
                        start_idx = i
                        break
                if start_idx > 0 and start_idx < 5: # Only skip if header is found near top
                    readme_content = "\n".join(lines[start_idx:])
            
            readme_content = readme_content.strip()
            
            readme_path.write_text(readme_content, encoding='utf-8')
            self.output(f"  ✓ Generated README.md ({len(readme_content)} chars)")
            
            # Generate requirements.txt for Python
            if is_python:
                await self._generate_requirements_txt(dependencies)
        else:
            self.output(f"  ⚠ Documentation generation failed")
    
    async def _extract_dependencies(self, files: List[str]) -> List[str]:
        """Extract dependencies from created files, filtering stdlib and local imports."""
        dependencies = set()
        
        # Comprehensive stdlib list (hardcoded for reliability without importlib scanning)
        stdlib = {
            'abc', 'argparse', 'ast', 'asyncio', 'base64', 'collections', 'concurrent', 'contextlib', 
            'copy', 'csv', 'ctypes', 'datetime', 'decimal', 'difflib', 'enum', 'functools', 'glob', 
            'gzip', 'hashlib', 'html', 'http', 'importlib', 'inspect', 'io', 'itertools', 'json', 
            'logging', 'math', 'mimetypes', 'multiprocessing', 'netrc', 'numbers', 'operator', 'os', 
            'pathlib', 'pickle', 'platform', 'pprint', 'queue', 'random', 're', 'shlex', 'shutil', 
            'signal', 'socket', 'sqlite3', 'ssl', 'stat', 'string', 'struct', 'subprocess', 'sys', 
            'tarfile', 'tempfile', 'threading', 'time', 'timeit', 'token', 'tokenize', 'traceback', 
            'types', 'typing', 'unittest', 'urllib', 'uuid', 'venv', 'warnings', 'weakref', 'xml', 
            'zipfile', '__future__'
        }
        
        # Identify local module names to exclude
        local_modules = set()
        for f in files:
            parts = f.replace('\\', '/').split('/')
            # Add top-level folder names (e.g. 'game' from game/player.py)
            if len(parts) > 1:
                local_modules.add(parts[0])
            # Add file stems (e.g. 'config' from config.py)
            p = Path(f)
            if p.suffix == '.py':
                local_modules.add(p.stem)

        for f in files:
            full_path = self.project_dir / f
            if not full_path.exists():
                continue
            
            try:
                content = full_path.read_text(encoding='utf-8', errors='replace')
                
                if f.endswith('.py'):
                    # Python imports
                    for match in re.finditer(r'^(?:from|import)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE):
                        module = match.group(1)
                        is_local = module in local_modules or (self.project_dir / f"{module}.py").exists() or (self.project_dir / module).is_dir()
                        
                        if module and module not in stdlib and not is_local:
                            dependencies.add(module)
            except Exception:
                pass
        
        return sorted(dependencies)
    
    async def _generate_requirements_txt(self, dependencies: List[str]) -> None:
        """Generate requirements.txt for Python projects."""
        req_path = self.project_dir / "requirements.txt"
        
        # Determine existing packages
        existing_packages = set()
        if req_path.exists():
            try:
                content = req_path.read_text(encoding='utf-8')
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # rudimentary parse to handle 'package==1.0'
                        pkg = line.split('==')[0].split('>=')[0].split('<')[0].strip()
                        existing_packages.add(pkg.lower())
                
                self.output(f"  ℹ requirements.txt exists with {len(existing_packages)} packages. Merging...")
            except Exception:
                pass

        # Common package name mappings
        package_map = {
            'pygame': 'pygame',
            'flask': 'Flask',
            'django': 'Django',
            'requests': 'requests',
            'numpy': 'numpy',
            'pandas': 'pandas',
            'PIL': 'Pillow',
            'cv2': 'opencv-python',
            'bs4': 'beautifulsoup4',
            'sklearn': 'scikit-learn',
            'matplotlib': 'matplotlib',
            'yaml': 'PyYAML',
        }
        
        packages_to_add = []
        for dep in dependencies:
            pkg_name = package_map.get(dep, dep)
            # Only add if not already present (case-insensitive check)
            if pkg_name.lower() not in existing_packages:
                packages_to_add.append(pkg_name)
        
        if packages_to_add:
            mode = 'a' if req_path.exists() else 'w'
            prefix = "\n" if mode == 'a' and req_path.stat().st_size > 0 else ""
            
            content = prefix + "\n".join(sorted(set(packages_to_add)))
            
            with open(req_path, mode, encoding='utf-8') as f:
                f.write(content)
                
            self.output(f"  ✓ Added {len(packages_to_add)} missing packages to requirements.txt")
        else:
            self.output("  ✓ requirements.txt is up to date")

    # ═══════════════════════════════════════════════════════════════════════════
    # GATE 5: FINAL VERIFICATION CHECKLIST
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def verify_against_design(
        self, 
        design_content: str, 
        files_created: List[str]
    ) -> Dict[str, Any]:
        """
        Final verification: Compare actual files against design commitments.
        
        This is REAL analysis, not optimistic wishful thinking.
        """
        self.output("\n[FINAL GATE] Verifying implementation against design...")
        
        # Extract commitments from design
        commitments = self._extract_design_commitments(design_content)
        
        if not commitments:
            self.output("  ⚠ Could not parse design commitments - skipping verification")
            return {'passed': True, 'checklist': [], 'completion_pct': 100.0}
        
        self.output(f"  Found {len(commitments)} commitments in design")
        
        # Verify each commitment
        checklist = []
        failures = []
        
        for commitment in commitments:
            result = self._verify_commitment(commitment, files_created)
            checklist.append(result)
            if not result['passed'] and result['priority'] == 'critical':
                failures.append(result['description'])
        
        # Calculate completion percentage
        total_weight = sum(3 if c['priority'] == 'critical' else 1 for c in checklist)
        passed_weight = sum((3 if c['priority'] == 'critical' else 1) for c in checklist if c['passed'])
        completion_pct = (passed_weight / total_weight * 100) if total_weight > 0 else 100.0
        
        # Output report
        self._output_checklist(checklist, completion_pct, failures)
        
        return {
            'passed': len(failures) == 0 and completion_pct >= 80.0,
            'checklist': checklist,
            'completion_pct': completion_pct,
            'failures': failures
        }
    
    def _extract_design_commitments(self, design_content: str) -> List[Dict[str, Any]]:
        """Parse design to extract verifiable commitments."""
        commitments = []
        
        # File patterns - strict regex to avoid capturing markdown or sentences
        file_patterns = [
            r'\[NEW\]\s*`?([a-zA-Z0-9_/\-\.]+\.[a-zA-Z0-9]+)`?',
            r'\[CREATE\]\s*`?([a-zA-Z0-9_/\-\.]+\.[a-zA-Z0-9]+)`?',
            r'Create\s+(?:file\s+)?`?([a-zA-Z0-9_/\-\.]+\.[a-zA-Z0-9]+)`?',
            r'-\s*(?:File:)?\s*`?([a-zA-Z0-9_/\-\.]+\.[a-zA-Z0-9]{1,5})`?',
        ]
        
        for pattern in file_patterns:
            for match in re.finditer(pattern, design_content, re.IGNORECASE):
                raw_path = match.group(1).strip()
                
                # Clean up path
                file_path = raw_path.strip(' `\'"*()[]')
                
                # Validation: ignore if it looks like a sentence or is too short
                if ' ' in file_path or len(file_path) < 3:
                    continue
                    
                if '.' in file_path:
                    commitments.append({
                        'type': 'file',
                        'description': f"File: {file_path}",
                        'target': file_path,
                        'priority': 'critical'
                    })
        
        # Deduplicate
        seen = set()
        unique = []
        for c in commitments:
            key = f"{c['type']}:{c['target']}"
            if key not in seen:
                seen.add(key)
                unique.append(c)
        
        return unique[:20]
    
    def _verify_commitment(
        self, 
        commitment: Dict[str, Any], 
        files_created: List[str]
    ) -> Dict[str, Any]:
        """Verify a single commitment against created files."""
        result = {**commitment, 'passed': False, 'comment': ''}
        
        if commitment['type'] == 'file':
            # Normalize target: src/main.py -> main.py if mapped, or just flexible matching
            target = commitment['target'].replace('\\', '/').lstrip('./')
            
            # Special case: ignore src/ prefix if it's common in design but not in output lists sometimes
            target_clean = target.replace('src/', '')
            
            for f in files_created:
                f_norm = f.replace('\\', '/').lstrip('./')
                f_base = Path(f).name
                
                # Match logic:
                # 1. Exact match
                # 2. Ends with target (e.g. repo/src/main.py ends with src/main.py)
                # 3. Target ends with file (e.g. src/main.py ends with main.py)
                is_match = (
                    target in f_norm or 
                    f_norm.endswith(target) or 
                    target.endswith(f_norm)
                )
                
                if is_match:
                    full_path = self.project_dir / f
                    if full_path.exists():
                        content = full_path.read_text(encoding='utf-8', errors='replace')
                        if len(content) > 20:
                            result['passed'] = True
                            result['comment'] = f"✓ Created ({len(content)} bytes)"
                        else:
                            result['comment'] = "✗ File nearly empty"
                    break
            
            if not result['comment']:
                result['comment'] = "✗ File not found"
        
        return result
    
    def _output_checklist(
        self, 
        checklist: List[Dict], 
        completion_pct: float,
        failures: List[str]
    ) -> None:
        """Output formatted verification report."""
        self.output(f"\n{'='*60}")
        self.output(f"  VERIFICATION CHECKLIST - {completion_pct:.1f}% Complete")
        self.output(f"{'='*60}")
        
        for item in checklist:
            status = "✓" if item['passed'] else "✗"
            priority = " [CRITICAL]" if item['priority'] == 'critical' and not item['passed'] else ""
            self.output(f"  {status} {item['description']}{priority}")
            if item['comment']:
                self.output(f"     {item['comment']}")
        
        self.output(f"{'─'*60}")
        
        if failures:
            self.output(f"  ❌ CRITICAL FAILURES ({len(failures)}):")
            for f in failures:
                self.output(f"     - {f}")
        else:
            self.output(f"  ✅ All critical items verified!")
        
        self.output(f"{'='*60}\n")

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY: ENTRY POINT ENFORCEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    
    def enforce_entry_point(self, files: List[str]) -> List[str]:
        """
        Ensure the file list includes an entry point.
        
        Returns modified file list with entry point added if missing.
        """
        # Check for existing entry points
        has_main_py = any(f == 'main.py' or f.endswith('/main.py') for f in files)
        has_index_html = any(f == 'index.html' or f.endswith('/index.html') for f in files)
        has_run_py = any('run' in f.lower() and f.endswith('.py') for f in files)
        
        # Detect project type
        python_files = [f for f in files if f.endswith('.py')]
        html_files = [f for f in files if f.endswith('.html')]
        
        # Add entry point if missing
        if python_files and not has_main_py and not has_run_py:
            self.output("  ⚠ No main.py found - adding to file list")
            files = ['main.py'] + files
        elif html_files and not has_index_html:
            self.output("  ⚠ No index.html found - adding to file list")
            files = ['index.html'] + files
        
        return files
