"""
dependency_resolver.py
~~~~~~~~~~~~~~~~~~~~~~
Service to resolve Python imports to PyPI package names using LLM assistance.
"""

import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set

logger = logging.getLogger(__name__)

class DependencyResolver:
    """
    Resolves project dependencies for multiple languages using LLM heuristics.
    Supports Python (pip), JavaScript/Node (npm), etc.
    """

    def __init__(self, llm_client):
        self.llm_client = llm_client
        # Generic cache for resolved packages
        self._cache: Dict[str, Dict[str, str]] = {
            'python': {
                'PIL': 'Pillow',
                'cv2': 'opencv-python',
                'sklearn': 'scikit-learn',
                'yaml': 'PyYAML',
                'bs4': 'beautifulsoup4',
                'dotenv': 'python-dotenv',
                'gi': 'PyGObject',
                'cairo': 'pycairo',
                'Xlib': 'python-xlib',
                'dbus': 'dbus-python',
            }
        }
        
    def detect_language(self, project_dir: Path) -> str:
        """Detect the primary programming language of the project."""
        extensions = {}
        for file in project_dir.rglob("*"):
            if file.is_file() and not any(part.startswith('.') for part in file.parts):
                ext = file.suffix.lower()
                if ext:
                    extensions[ext] = extensions.get(ext, 0) + 1
        
        if not extensions:
            return "python" # Default fallback
            
        # Prioritize based on common extensions
        if extensions.get('.py', 0) > 0:
            return "python"
        if extensions.get('.js', 0) > 0 or extensions.get('.ts', 0) > 0:
            return "javascript"
        if extensions.get('.go', 0) > 0:
            return "go"
        if extensions.get('.rs', 0) > 0:
            return "rust"
            
        return "python"

    def resolve_packages(self, identifiers: List[str], language: str = "python") -> Dict[str, str]:
        """
        Map a list of code identifiers (imports, requires) to package manager names.
        """
        if not identifiers:
            return {}

        lang_cache = self._cache.get(language, {})
        results = {}
        to_resolve = []
        
        for ident in identifiers:
            if ident in lang_cache:
                results[ident] = lang_cache[ident]
            elif ident.lower() in lang_cache:
                results[ident] = lang_cache[ident.lower()]
            else:
                to_resolve.append(ident)
                
        if not to_resolve:
            return results

        # 2. Use LLM to resolve remaining
        pkg_manager = "pip"
        if language == "javascript": pkg_manager = "npm"
        elif language == "go": pkg_manager = "go get"
        elif language == "rust": pkg_manager = "cargo"

        prompt = f"""Map these {language} dependency identifiers to their official {pkg_manager} package names.

IDENTIFIERS: {to_resolve}

For each identifier, return the exact package name needed for installation.
- Some match exactly.
- Some are different (e.g., Python 'cv2' -> 'opencv-python').
- Exclude standard library/built-in modules for {language}.

Return ONLY a JSON object mapping identifier to package name:
{{"identifier": "package_name"}}
"""
        try:
            response = self.llm_client.generate(prompt, temperature=0.0)
            content = response.content if hasattr(response, 'content') else str(response)
            
            from agents.coding_agent.utils.json_utils import extract_json_from_llm_response
            llm_results = extract_json_from_llm_response(content)
            
            if llm_results and isinstance(llm_results, dict):
                if language not in self._cache:
                    self._cache[language] = {}
                for ident, pkg in llm_results.items():
                    if ident in to_resolve:
                        results[ident] = pkg
                        self._cache[language][ident] = pkg
                        
        except Exception as e:
            logger.warning(f"LLM dependency resolution failed for {language}: {e}")
            for ident in to_resolve:
                if ident not in results:
                    results[ident] = ident.lower()
                    
        return results

    def extract_dependencies_from_files(self, project_dir: Path, language: str = "python") -> Set[str]:
        """Scan project for all unique dependency identifiers based on language."""
        deps = set()
        patterns = {
            'python': [re.compile(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', re.MULTILINE)],
            'javascript': [
                re.compile(r'import\s+.*?\s+from\s+[\'"](.+?)[\'"]'),
                re.compile(r'require\s*\(\s*[\'"](.+?)[\'"]\s*\)')
            ],
            'go': [re.compile(r'^\s*"(.*?)"', re.MULTILINE)], # Simplified for imports
            'rust': [re.compile(r'use\s+([a-zA-Z0-9_]+)', re.MULTILINE)]
        }
        
        curr_patterns = patterns.get(language, patterns['python'])
        ext_map = {
            'python': '.py',
            'javascript': '.js',
            'go': '.go',
            'rust': '.rs'
        }
        target_ext = ext_map.get(language, '.py')
        
        for file in project_dir.rglob(f"*{target_ext}"):
            if any(part.startswith('.') or part == 'node_modules' or part == 'venv' for part in file.parts):
                continue
            try:
                content = file.read_text(encoding='utf-8', errors='replace')
                for pattern in curr_patterns:
                    for match in pattern.finditer(content):
                        dep = match.group(1)
                        # Filter out internal paths
                        if dep.startswith('.'): continue
                        if '/' in dep: dep = dep.split('/')[0] # Get base package for JS/Go
                        deps.add(dep)
            except Exception as e:
                logger.error(f"Error reading {file}: {e}")
                
        return deps

    def filter_stdlib(self, deps: Set[str], language: str = "python") -> Set[str]:
        """Filter out standard library modules using LLM or local lists."""
        if not deps: return set()
        
        if language == "python":
            import sys
            try:
                stdlib = set(getattr(sys, 'stdlib_module_names', set()))
                stdlib.update(sys.builtin_module_names)
            except Exception:
                stdlib = {'os', 'sys', 're', 'json', 'time', 'datetime', 'math', 'pathlib'}
            return {d for d in deps if d not in stdlib}
            
        # For other languages, use LLM to filter if the list is reasonably small
        # Or just let resolve_packages handle it via the prompt instruction
        return deps

    def resolve_system_dependencies(self, error_output: str) -> Dict[str, List[str]]:
        """
        Analyze a failed installation error and resolve to system packages or search terms.
        
        Returns:
            Dict with 'commands' and 'search_queries'
        """
        if not error_output:
            return {"commands": [], "search_queries": []}

        # Try to detect OS/Distro for better context
        distro_info = "Linux (Ubuntu/Debian likely)"
        try:
            if Path("/etc/os-release").exists():
                content = Path("/etc/os-release").read_text()
                for line in content.splitlines():
                    if line.startswith("PRETTY_NAME="):
                        distro_info = line.split("=")[1].strip('"')
                        break
        except Exception:
            pass

        # Use LLM with strong versioning awareness and research output
        prompt = f"""Analyze this installation error output and determine the missing system-level dependencies.
The user is running: {distro_info}

ERROR OUTPUT:
{error_output[:1500]}

Return a JSON object with:
1. "commands": A list of exact `sudo apt-get install` commands if you are 100% certain.
2. "search_queries": A list of specific search terms to find the current correct package for this OS version if you are unsure or if previous attempts failed.
3. "reason": A brief explanation of what is missing.

Example:
{{
  "commands": ["sudo apt-get install libgirepository-2.0-dev"],
  "search_queries": ["install girepository-2.0 on {distro_info}"],
  "reason": "Missing GObject Introspection development headers for modern Ubuntu versions"
}}
"""
        try:
            response = self.llm_client.generate(prompt, temperature=0.0)
            content = response.content if hasattr(response, 'content') else str(response)
            
            from agents.coding_agent.utils.json_utils import extract_json_from_llm_response
            llm_results = extract_json_from_llm_response(content)
            
            if llm_results and isinstance(llm_results, dict):
                return {
                    "commands": llm_results.get("commands", []),
                    "search_queries": llm_results.get("search_queries", []),
                    "reason": llm_results.get("reason", "")
                }
                        
        except Exception as e:
            logger.warning(f"LLM system dependency resolution failed: {e}")
            
        return {"commands": [], "search_queries": []}

    def generate_dependency_file_content(self, project_dir: Path) -> Optional[Dict[str, str]]:
        """
        High-level method to scan project and return (filename, content).
        """
        language = self.detect_language(project_dir)
        all_deps = self.extract_dependencies_from_files(project_dir, language)
        external_deps = self.filter_stdlib(all_deps, language)
        
        # Filter out local modules
        filtered_deps = set()
        for dep in external_deps:
            if language == "python":
                if (project_dir / f"{dep}.py").exists() or (project_dir / dep).is_dir():
                    continue
            elif language == "javascript":
                if (project_dir / f"{dep}.js").exists() or (project_dir / dep).is_dir():
                    continue
            filtered_deps.add(dep)
            
        if not filtered_deps:
            return None
            
        package_map = self.resolve_packages(list(filtered_deps), language)
        unique_packages = sorted(list(set(package_map.values())))
        
        filename = "requirements.txt"
        if language == "javascript": filename = "package_json_deps.txt" 
        elif language == "go": filename = "go_deps.txt"
        
        return {
            "filename": filename,
            "content": "\n".join(unique_packages) + "\n"
        }
