"""
Patch Validator - Prevents LLM from generating wholesale file replacements
==========================================================================

Multi-layer validation to ensure surgical changes only.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class PatchValidationError(Exception):
    """Raised when patch validation fails."""
    pass


class PatchValidator:
    """
    Validates patches before application to prevent destructive operations.

    Checks:
    1. Patch size relative to file size (rejects >80% replacements normally)
    2. Critical section preservation (imports, class definitions)
    3. Line count changes (rejects dramatic changes)
    4. Feedback generation for LLM to regenerate better patches

    When allow_full_rewrite=True (after multiple surgical fix failures):
    - Limits are relaxed to allow function/file rewrites
    - Still validates syntax and critical imports
    """

    # Normal thresholds (surgical mode)
    MAX_REPLACEMENT_RATIO = 0.80  # 80% of file
    MAX_LINE_CHANGE_RATIO = 0.60  # 60% line count change
    MIN_SURGICAL_LINES = 3
    MAX_SURGICAL_LINES_FOR_SMALL_FILE = 50  # For files <100 lines

    # Relaxed thresholds (full rewrite mode)
    MAX_REPLACEMENT_RATIO_FULL_REWRITE = 1.0  # 100% allowed
    MAX_LINE_CHANGE_RATIO_FULL_REWRITE = 1.0  # 100% allowed
    MAX_SURGICAL_LINES_FULL_REWRITE = 500  # Much larger

    def __init__(self, project_dir: Path, allow_full_rewrite: bool = False):
        self.project_dir = Path(project_dir)
        self.allow_full_rewrite = allow_full_rewrite

        # Use appropriate thresholds based on mode
        if allow_full_rewrite:
            self._max_replacement_ratio = self.MAX_REPLACEMENT_RATIO_FULL_REWRITE
            self._max_line_change_ratio = self.MAX_LINE_CHANGE_RATIO_FULL_REWRITE
            self._max_surgical_lines = self.MAX_SURGICAL_LINES_FULL_REWRITE
        else:
            self._max_replacement_ratio = self.MAX_REPLACEMENT_RATIO
            self._max_line_change_ratio = self.MAX_LINE_CHANGE_RATIO
            self._max_surgical_lines = self.MAX_SURGICAL_LINES_FOR_SMALL_FILE
    
    def validate_patch(
        self, 
        file_path: str, 
        search_block: str, 
        replace_block: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a single patch before application.
        
        Args:
            file_path: Relative path to file
            search_block: Code to search for
            replace_block: Replacement code
            
        Returns:
            (is_valid, error_message)
            error_message contains LLM-friendly feedback for regeneration
        """
        full_path = self.project_dir / file_path
        
        if not full_path.exists():
            # New file or missing - allow it
            return True, None
        
        try:
            file_content = full_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f"Could not read {file_path}: {e}")
            return True, None  # Allow if can't read
        
        # SPECIAL CASE: Allow "wholesale replacement" when creating/populating new files
        # This happens when:
        # 1. The search block is empty (new file creation via empty SEARCH)
        # 2. The file is a tiny placeholder (< 5 lines, likely auto-generated stub)
        file_lines = len(file_content.splitlines())
        is_new_file_creation = not search_block or not search_block.strip()
        is_placeholder_file = file_lines < 5 and (
            '# [NEW FILE' in file_content or 
            '# TODO' in file_content or 
            file_content.strip() == '' or
            'placeholder' in file_content.lower()
        )
        
        if is_new_file_creation or is_placeholder_file:
            logger.info(f"Allowing large patch for {file_path}: new_file={is_new_file_creation}, placeholder={is_placeholder_file}")
            return True, None
        
        # Check 1: Wholesale Replacement Detection
        file_size = len(file_content)
        search_size = len(search_block)
        
        # [NEW] Allow wholesale replacement for config files and small files
        # Config files often need complete rewrites, and small files (< 500 chars) are safe to rewrite
        is_config_file = file_path.endswith(('.txt', '.md', '.ini', '.toml', '.cfg', '.yml', '.yaml', 'Dockerfile', 'Makefile', '.json'))
        is_small_file = file_size < 500
        
        if is_config_file or is_small_file:
            # Skip wholesale replacement check for these files
            logger.info(f"Skipping wholesale replacement check for {file_path} (config={is_config_file}, small={is_small_file})")
        else:
            replacement_ratio = search_size / max(file_size, 1)
            
            # [MODIFIED] Dynamic threshold based on file size and allow_full_rewrite mode
            # For small files (up to 500 lines), allow almost full rewrites (surgery is less critical)
            # For large files, use configured threshold (80% normal, 100% if full rewrite enabled)
            dynamic_max_ratio = self._max_replacement_ratio
            if file_lines < 500 or self.allow_full_rewrite:
                dynamic_max_ratio = 1.0  # Allow full rewrite

            if replacement_ratio > dynamic_max_ratio:
                error_msg = self._generate_wholesale_replacement_feedback(
                    file_path, file_size, search_size, file_content, search_block
                )
                return False, error_msg
        
        # Check 2: Line Count Change Detection
        # file_lines already computed above
        search_lines = len(search_block.splitlines())
        replace_lines = len(replace_block.splitlines())

        line_change = abs(replace_lines - search_lines)
        line_change_ratio = line_change / max(file_lines, 1)

        # [MODIFIED] Dynamic threshold for line changes
        # - For TINY files (< 20 lines): Skip ratio check entirely - these are stubs/broken files
        #   that legitimately need substantial additions (e.g., 2-line file needs imports, functions)
        # - For small files (< 500 lines): Allow 100% changes
        # - For large files: Use configured threshold (60% normal, 100% if full rewrite)

        # TINY files: stubs, broken files, minimal scaffolds - allow any amount of additions
        if file_lines < 20:
            logger.info(f"Skipping line change ratio check for tiny file {file_path} ({file_lines} lines)")
        elif file_lines < 500 or self.allow_full_rewrite:
            # Small files or full rewrite mode: allow major refactors but still check
            if line_change_ratio > 5.0:  # Only reject if change is >500% (5x file size)
                error_msg = self._generate_line_change_feedback(
                    file_path, file_lines, search_lines, replace_lines
                )
                return False, error_msg
        else:
            # Large files: use standard threshold
            if line_change_ratio > self._max_line_change_ratio:
                error_msg = self._generate_line_change_feedback(
                    file_path, file_lines, search_lines, replace_lines
                )
                return False, error_msg
        
        # Check 3: Surgical Patch Size (for small files)
        # Skip if full rewrite mode is enabled OR if file is tiny (< 20 lines)
        # Tiny files are often stubs/broken files that need substantial rewrites
        if not self.allow_full_rewrite and file_lines >= 20 and file_lines < 100:
            if search_lines > self._max_surgical_lines:
                error_msg = self._generate_non_surgical_feedback(
                    file_path, file_lines, search_lines
                )
                return False, error_msg

        # Check 4: Critical Section Preservation
        # (imports, class/function definitions should rarely be in SEARCH block)
        # Skip this check for small files, or when full rewrite is allowed
        if not self.allow_full_rewrite and file_lines >= 500 and self._contains_critical_definitions(search_block):
            # This is OK if the search block is small (targeted class/function modification)
            if search_lines > 20:
                error_msg = self._generate_critical_section_feedback(
                    file_path, search_block
                )
                return False, error_msg
        
        # All checks passed
        return True, None
    
    def _contains_critical_definitions(self, code_block: str) -> bool:
        """Check if code block contains critical definitions."""
        critical_patterns = [
            'import ',
            'from ',
            'class ',
            'def ',
            '__init__',
        ]
        
        lines = code_block.splitlines()
        critical_count = sum(
            1 for line in lines 
            if any(pattern in line for pattern in critical_patterns)
        )
        
        # If multiple critical patterns, likely replacing too much
        return critical_count > 3
    
    def _generate_wholesale_replacement_feedback(
        self,
        file_path: str,
        file_size: int,
        search_size: int,
        file_content: str,
        search_block: str
    ) -> str:
        """Generate feedback for wholesale replacement attempt."""
        ratio = (search_size / file_size) * 100
        
        # Find what's actually changing
        file_lines = file_content.splitlines()
        search_lines = search_block.splitlines()
        
        return f"""
🛑 REJECTED: WHOLESALE FILE REPLACEMENT DETECTED

File: {file_path}
Your SEARCH block replaces {ratio:.0f}% of the file ({search_size}/{file_size} chars)!

This violates the SURGICAL CHANGE principle.

❌ WHAT YOU DID (WRONG):
- Replaced nearly the entire file ({len(search_lines)} lines)
- This is equivalent to deleting the file and creating a new one
- High risk of losing existing functionality

✅ WHAT YOU MUST DO (CORRECT):
1. Identify the SPECIFIC lines that need to change
2. Create a SMALL SEARCH block (3-15 lines) around those lines
3. Include ONLY the changed lines in your REPLACE block

EXAMPLE:
Instead of replacing the entire {len(file_lines)}-line file, find the specific function/section to modify:

File: {file_path}
<<<<<<< SEARCH
def specific_function():
    old_code = "here"
    return old_code
=======
def specific_function():
    new_code = "here"
    return new_code
>>>>>>> REPLACE

🔧 ACTION REQUIRED:
Regenerate patches using SMALL, TARGETED search blocks (max 15 lines each).
Focus on the MINIMAL change needed to achieve the goal.
"""
    
    def _generate_line_change_feedback(
        self,
        file_path: str,
        file_lines: int,
        search_lines: int,
        replace_lines: int
    ) -> str:
        """Generate feedback for excessive line count changes."""
        change = abs(replace_lines - search_lines)
        ratio = (change / file_lines) * 100
        
        return f"""
🛑 REJECTED: EXCESSIVE LINE COUNT CHANGE

File: {file_path}
Your patch changes {change} lines ({ratio:.0f}% of file's {file_lines} lines)!

❌ PROBLEM:
- SEARCH block: {search_lines} lines
- REPLACE block: {replace_lines} lines  
- Net change: {change} lines ({ratio:.0f}% of file)

✅ SOLUTION:
Break this into MULTIPLE SMALLER patches:
- Each patch should modify 3-15 lines
- Target specific functions/sections
- Make incremental changes

EXAMPLE:
Instead of one large patch, create 3-5 small patches:

Patch 1 - Update imports:
File: {file_path}
<<<<<<< SEARCH
import old_module
=======
import new_module
>>>>>>> REPLACE

Patch 2 - Modify function:
File: {file_path}
<<<<<<< SEARCH
def function():
    old_logic()
=======
def function():
    new_logic()
>>>>>>> REPLACE

🔧 ACTION REQUIRED:
Split your large patch into multiple surgical patches (max 15 lines each).
"""
    
    def _generate_non_surgical_feedback(
        self,
        file_path: str,
        file_lines: int,
        search_lines: int
    ) -> str:
        """Generate feedback for non-surgical patches on small files."""
        return f"""
🛑 REJECTED: NON-SURGICAL PATCH ON SMALL FILE

File: {file_path} (only {file_lines} lines total)
Your SEARCH block: {search_lines} lines

For small files, patches should be EXTRA surgical!

❌ PROBLEM:
- File is {file_lines} lines
- Your SEARCH block is {search_lines} lines ({(search_lines/file_lines)*100:.0f}% of file)
- This is essentially rewriting the file

✅ SOLUTION:
- SEARCH block should be max 10-15 lines for small files
- Target the SPECIFIC function or section to change
- Don't include surrounding code that doesn't change

🔧 ACTION REQUIRED:
Identify the MINIMAL lines that need changes and create a focused SEARCH block.
"""
    
    def _generate_critical_section_feedback(
        self,
        file_path: str,
        search_block: str
    ) -> str:
        """Generate feedback for patches affecting critical sections."""
        return f"""
🛑 REJECTED: LARGE PATCH CONTAINING CRITICAL DEFINITIONS

File: {file_path}
Your SEARCH block contains multiple imports/class/function definitions!

❌ PROBLEM:
- SEARCH block includes critical definitions (imports, class headers, etc.)
- Large blocks with definitions are risky
- High chance of breaking existing functionality

✅ SOLUTION:
- To ADD an import: Find an existing import and add after it
- To MODIFY a function: Search for just that function body
- To MODIFY a class method: Search for just that method

EXAMPLE - Adding an import:
File: {file_path}
<<<<<<< SEARCH
import existing_module
=======
import existing_module
import new_module
>>>>>>> REPLACE

EXAMPLE - Modifying a method:
File: {file_path}
<<<<<<< SEARCH
    def method(self):
        old_code()
=======
    def method(self):
        new_code()
>>>>>>> REPLACE

🔧 ACTION REQUIRED:
Create smaller, focused patches that target specific functions/methods.
"""
    
    def validate_patches_batch(
        self,
        patches: List[Dict[str, str]]
    ) -> Tuple[List[Dict[str, str]], List[str]]:
        """
        Validate a batch of patches, filtering out invalid ones.
        
        Args:
            patches: List of dicts with 'file', 'search', 'replace'
            
        Returns:
            (valid_patches, error_messages)
        """
        valid = []
        errors = []
        
        for i, patch in enumerate(patches):
            file_path = patch.get('file', '')
            search = patch.get('search', '')
            replace = patch.get('replace', '')
            
            is_valid, error_msg = self.validate_patch(file_path, search, replace)
            
            if is_valid:
                valid.append(patch)
            else:
                errors.append(f"Patch {i+1} ({file_path}): {error_msg}")
                logger.warning(f"Rejected patch {i+1} for {file_path}")
        
        return valid, errors
