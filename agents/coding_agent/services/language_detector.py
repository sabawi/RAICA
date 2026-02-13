"""
Language Detector Service
=========================

Detects the primary programming language of a project and provides
language-specific configuration for test frameworks, linters, etc.

This enables RAICA to be fully language-agnostic.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LanguageInfo:
    """Information about a detected programming language."""
    name: str                           # e.g., "Python", "JavaScript", "Go"
    short_name: str                     # e.g., "python", "javascript", "go"
    file_extensions: List[str]          # e.g., [".py"], [".js", ".ts"]
    test_framework: str                 # e.g., "pytest", "jest", "go test"
    test_command: List[str]             # e.g., ["python", "-m", "pytest"]
    test_file_pattern: str              # e.g., "test_*.py", "*.test.js"
    package_manager: Optional[str]      # e.g., "pip", "npm", "cargo"
    manifest_files: List[str]           # e.g., ["requirements.txt", "setup.py"]
    code_block_name: str                # For markdown: ```python, ```javascript
    common_frameworks: List[str] = field(default_factory=list)  # e.g., ["Django", "Flask"]


# Language definitions
LANGUAGE_DEFINITIONS: Dict[str, LanguageInfo] = {
    "python": LanguageInfo(
        name="Python",
        short_name="python",
        file_extensions=[".py", ".pyw", ".pyx"],
        test_framework="pytest",
        test_command=["python", "-m", "pytest", "-v", "--tb=short"],
        test_file_pattern="test_*.py",
        package_manager="pip",
        manifest_files=["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
        code_block_name="python",
        common_frameworks=["Django", "Flask", "FastAPI", "PyQt", "Tkinter"]
    ),
    "javascript": LanguageInfo(
        name="JavaScript",
        short_name="javascript",
        file_extensions=[".js", ".mjs", ".cjs"],
        test_framework="jest",
        test_command=["npx", "jest", "--verbose"],
        test_file_pattern="*.test.js",
        package_manager="npm",
        manifest_files=["package.json"],
        code_block_name="javascript",
        common_frameworks=["React", "Vue", "Express", "Next.js", "Node.js"]
    ),
    "typescript": LanguageInfo(
        name="TypeScript",
        short_name="typescript",
        file_extensions=[".ts", ".tsx", ".mts", ".cts"],
        test_framework="jest",
        test_command=["npx", "jest", "--verbose"],
        test_file_pattern="*.test.ts",
        package_manager="npm",
        manifest_files=["package.json", "tsconfig.json"],
        code_block_name="typescript",
        common_frameworks=["React", "Angular", "Vue", "Next.js", "NestJS"]
    ),
    "go": LanguageInfo(
        name="Go",
        short_name="go",
        file_extensions=[".go"],
        test_framework="go test",
        test_command=["go", "test", "-v", "./..."],
        test_file_pattern="*_test.go",
        package_manager="go mod",
        manifest_files=["go.mod", "go.sum"],
        code_block_name="go",
        common_frameworks=["Gin", "Echo", "Fiber", "Chi"]
    ),
    "rust": LanguageInfo(
        name="Rust",
        short_name="rust",
        file_extensions=[".rs"],
        test_framework="cargo test",
        test_command=["cargo", "test", "--", "--nocapture"],
        test_file_pattern="*_test.rs",
        package_manager="cargo",
        manifest_files=["Cargo.toml", "Cargo.lock"],
        code_block_name="rust",
        common_frameworks=["Actix", "Rocket", "Axum", "Tokio"]
    ),
    "java": LanguageInfo(
        name="Java",
        short_name="java",
        file_extensions=[".java"],
        test_framework="JUnit",
        test_command=["mvn", "test"],
        test_file_pattern="*Test.java",
        package_manager="maven",
        manifest_files=["pom.xml", "build.gradle", "build.gradle.kts"],
        code_block_name="java",
        common_frameworks=["Spring", "Spring Boot", "Hibernate", "Jakarta EE"]
    ),
    "csharp": LanguageInfo(
        name="C#",
        short_name="csharp",
        file_extensions=[".cs"],
        test_framework="xUnit",
        test_command=["dotnet", "test"],
        test_file_pattern="*Tests.cs",
        package_manager="nuget",
        manifest_files=["*.csproj", "*.sln"],
        code_block_name="csharp",
        common_frameworks=[".NET", "ASP.NET", "Entity Framework", "Blazor"]
    ),
    "ruby": LanguageInfo(
        name="Ruby",
        short_name="ruby",
        file_extensions=[".rb", ".rake"],
        test_framework="RSpec",
        test_command=["bundle", "exec", "rspec"],
        test_file_pattern="*_spec.rb",
        package_manager="bundler",
        manifest_files=["Gemfile", "Gemfile.lock", "*.gemspec"],
        code_block_name="ruby",
        common_frameworks=["Rails", "Sinatra", "Hanami"]
    ),
    "php": LanguageInfo(
        name="PHP",
        short_name="php",
        file_extensions=[".php"],
        test_framework="PHPUnit",
        test_command=["./vendor/bin/phpunit"],
        test_file_pattern="*Test.php",
        package_manager="composer",
        manifest_files=["composer.json", "composer.lock"],
        code_block_name="php",
        common_frameworks=["Laravel", "Symfony", "CodeIgniter", "WordPress"]
    ),
    "cpp": LanguageInfo(
        name="C++",
        short_name="cpp",
        file_extensions=[".cpp", ".cc", ".cxx", ".hpp", ".h"],
        test_framework="Google Test",
        test_command=["ctest", "--output-on-failure"],
        test_file_pattern="*_test.cpp",
        package_manager="cmake",
        manifest_files=["CMakeLists.txt", "Makefile", "meson.build"],
        code_block_name="cpp",
        common_frameworks=["Qt", "Boost", "OpenCV"]
    ),
    "swift": LanguageInfo(
        name="Swift",
        short_name="swift",
        file_extensions=[".swift"],
        test_framework="XCTest",
        test_command=["swift", "test"],
        test_file_pattern="*Tests.swift",
        package_manager="swift package",
        manifest_files=["Package.swift"],
        code_block_name="swift",
        common_frameworks=["SwiftUI", "UIKit", "Vapor"]
    ),
    "kotlin": LanguageInfo(
        name="Kotlin",
        short_name="kotlin",
        file_extensions=[".kt", ".kts"],
        test_framework="JUnit",
        test_command=["./gradlew", "test"],
        test_file_pattern="*Test.kt",
        package_manager="gradle",
        manifest_files=["build.gradle.kts", "build.gradle"],
        code_block_name="kotlin",
        common_frameworks=["Ktor", "Spring Boot", "Android"]
    ),
    "gdscript": LanguageInfo(
        name="GDScript",
        short_name="gdscript",
        file_extensions=[".gd", ".tscn", ".tres"],
        test_framework="manual",  # Godot requires running the game to test
        test_command=["echo", "GDScript requires manual testing - run game in Godot engine"],
        test_file_pattern="test_*.gd",
        package_manager=None,
        manifest_files=["project.godot"],  # Godot project marker
        code_block_name="gdscript",
        common_frameworks=["Godot 4", "Godot 3"]
    ),
    "html": LanguageInfo(
        name="HTML/CSS/JS",
        short_name="html",
        file_extensions=[".html", ".htm", ".css"],
        test_framework="manual",  # Static HTML requires browser testing
        test_command=["echo", "HTML projects require browser testing"],
        test_file_pattern="test_*.html",
        package_manager=None,
        manifest_files=["index.html"],
        code_block_name="html",
        common_frameworks=["Static HTML", "Bootstrap", "Tailwind"]
    ),
    "lua": LanguageInfo(
        name="Lua",
        short_name="lua",
        file_extensions=[".lua"],
        test_framework="busted",
        test_command=["busted", "--verbose"],
        test_file_pattern="*_spec.lua",
        package_manager="luarocks",
        manifest_files=["*.rockspec"],
        code_block_name="lua",
        common_frameworks=["LÖVE", "Corona", "Defold", "Roblox"]
    ),
}


class LanguageDetector:
    """
    Detects the primary programming language of a project.

    Detection is based on:
    1. Manifest files (highest priority)
    2. File extension counts
    3. Framework-specific files
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self._cached_result: Optional[LanguageInfo] = None

    def detect(self) -> LanguageInfo:
        """
        Detect the primary language of the project.

        Returns LanguageInfo for the detected language, or a generic
        "Unknown" language if detection fails.
        """
        if self._cached_result:
            return self._cached_result

        # Strategy 1: Check for manifest files (most reliable)
        for lang_key, lang_info in LANGUAGE_DEFINITIONS.items():
            for manifest in lang_info.manifest_files:
                if '*' in manifest:
                    # Glob pattern
                    if list(self.project_dir.glob(manifest)):
                        logger.info(f"Detected {lang_info.name} from manifest pattern: {manifest}")
                        self._cached_result = lang_info
                        return lang_info
                else:
                    if (self.project_dir / manifest).exists():
                        logger.info(f"Detected {lang_info.name} from manifest: {manifest}")
                        self._cached_result = lang_info
                        return lang_info

        # Strategy 2: Count file extensions
        extension_counts: Dict[str, int] = {}
        files_scanned = 0
        max_files = 2000  # Safety limit to prevent hanging
        try:
            for file_path in self.project_dir.rglob("*"):
                if files_scanned >= max_files:
                    logger.warning(f"Reached file scan limit ({max_files}) during language detection")
                    break

                try:
                    # Skip symlinks and non-files
                    if not file_path.is_file() or file_path.is_symlink():
                        continue
                except (OSError, PermissionError):
                    continue

                if not self._is_ignored(file_path):
                    ext = file_path.suffix.lower()
                    if ext:
                        extension_counts[ext] = extension_counts.get(ext, 0) + 1
                    files_scanned += 1
        except Exception as e:
            logger.warning(f"Error scanning files: {e}")

        # Find language with most matching files
        best_match: Optional[LanguageInfo] = None
        best_count = 0

        for lang_key, lang_info in LANGUAGE_DEFINITIONS.items():
            count = sum(extension_counts.get(ext, 0) for ext in lang_info.file_extensions)
            if count > best_count:
                best_count = count
                best_match = lang_info

        if best_match and best_count > 0:
            logger.info(f"Detected {best_match.name} from file extensions ({best_count} files)")
            self._cached_result = best_match
            return best_match

        # Fallback: Unknown language
        logger.warning("Could not detect project language, using generic defaults")
        self._cached_result = self._get_unknown_language()
        return self._cached_result

    def _is_ignored(self, path: Path) -> bool:
        """Check if path should be ignored (node_modules, venv, etc.)."""
        ignore_dirs = {
            'node_modules', 'venv', '.venv', 'env', '.env',
            '__pycache__', '.git', '.svn', 'dist', 'build',
            'target', 'vendor', '.idea', '.vscode'
        }
        return any(part in ignore_dirs for part in path.parts)

    def _get_unknown_language(self) -> LanguageInfo:
        """Return a generic language info for unknown projects."""
        return LanguageInfo(
            name="Unknown",
            short_name="unknown",
            file_extensions=[],
            test_framework="generic",
            test_command=["echo", "No test framework detected"],
            test_file_pattern="test_*.*",
            package_manager=None,
            manifest_files=[],
            code_block_name="",
            common_frameworks=[]
        )

    def get_language_context_for_llm(self) -> str:
        """
        Get a string describing the detected language for use in LLM prompts.
        """
        lang = self.detect()
        return f"""PROJECT LANGUAGE: {lang.name}
Test Framework: {lang.test_framework}
Common Frameworks: {', '.join(lang.common_frameworks) if lang.common_frameworks else 'None detected'}
File Extensions: {', '.join(lang.file_extensions)}"""
