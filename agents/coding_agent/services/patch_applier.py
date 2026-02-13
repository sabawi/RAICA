"""
Patch Applier Service
====================

Handles surgical application of code patches.
Supports strict matching and fuzzy fallbacks.
"""

import logging
import re
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

@dataclass
class Patch:
    file_path: str
    search_block: str
    replace_block: str

@dataclass
class PatchResult:
    success: bool
    modified_files: List[str]
    error: Optional[str] = None
    applied_patches: int = 0
    total_patches: int = 0


class TimeoutError(Exception):
    """Raised when operation exceeds timeout."""
    pass

class PatchApplier:
    """
    Service for applying search/replace patches to files.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)

    def apply_patches(self, patches: List[Dict[str, str]], allow_full_rewrite: bool = False) -> PatchResult:
        """
        Apply a list of patch dictionaries.

        Args:
            patches: List of dicts with keys 'file', 'search', 'replace'
            allow_full_rewrite: If True, relax validation to allow full function/file rewrites
                               (enabled after multiple surgical fix failures)

        Returns:
            PatchResult
        """
        modified_files = []
        applied_count = 0
        total_patches = len(patches)

        if allow_full_rewrite:
            logger.info("Full rewrite mode enabled - relaxed patch validation")
            print("    ℹ️  Full rewrite mode enabled (surgical fixes failed)", flush=True)

        # CRITICAL: Validate patches BEFORE application to prevent wholesale replacements
        from .patch_validator import PatchValidator

        validator = PatchValidator(self.project_dir, allow_full_rewrite=allow_full_rewrite)
        valid_patches, validation_errors = validator.validate_patches_batch(patches)
        
        if validation_errors:
            error_msg = "\n\n".join(validation_errors)
            logger.error(f"Patch validation failed:\n{error_msg}")
            return PatchResult(False, [], error=f"Wholesale replacement rejected:\n\n{error_msg}", total_patches=total_patches)
        
        patches = valid_patches  # Use only validated patches
        total_patches = len(patches)
        
        
        # Log progress for large patch batches
        if total_patches > 5:
            logger.info(f"Applying {total_patches} patches...")
        
        # Group patches by file to read/write once per file
        # But wait, patches might rely on order? 
        # Usually they are independent or sequential. 
        # Safest is to process sequentially, reading fresh each time or caching.
        # Let's process sequentially for correctness.
        
        for i, p in enumerate(patches):
            # Immediate progress feedback (use print for stdout, logger might be buffered)
            print(f"  [{i+1}/{total_patches}] Applying patch to {p.get('file', 'unknown')}...", flush=True)
            
            fname = p.get('file')
            search = p.get('search')
            replace = p.get('replace')
            
            if not fname or search is None or replace is None:
                return PatchResult(False, modified_files, f"Invalid patch format at index {i}")
            
            # Reject extremely short search blocks (high risk of ambiguity)
            # Except for very small files (<50 chars)
            full_path = self.project_dir / fname
            if search.strip() and len(search.strip()) < 10:
                 if full_path.exists() and full_path.stat().st_size > 50:
                      return PatchResult(False, modified_files, 
                            f"SEARCH block is too short ({len(search.strip())} chars). "
                            f"It must be at least 10 characters to be unique.\n"
                            f"Block: '{search.strip()}'")
                
            full_path = self.project_dir / fname
            if not full_path.exists():
                # Check if this is a "create new file" patch (empty search block)
                if not search or not search.strip():
                    # NEW FILE CREATION: empty search = create file with replace content
                    logger.info(f"Creating new file: {fname}")
                    print(f"    ✓ Creating new file: {fname}", flush=True)
                    try:
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        full_path.write_text(replace, encoding='utf-8')
                        if fname not in modified_files:
                            modified_files.append(fname)
                        applied_count += 1
                        continue  # Move to next patch
                    except Exception as e:
                        return PatchResult(False, modified_files, f"Failed to create file {fname}: {e}")
                else:
                    # File doesn't exist AND search is non-empty = error
                    return PatchResult(False, modified_files, f"File {fname} does not exist")
            
            # Handle duplicate "create file" patches - file now exists but search is empty
            # This happens when LLM generates multiple patches with empty SEARCH for same file
            if not search or not search.strip():
                if fname in modified_files:
                    # File was just created by a previous patch in this batch, skip duplicate
                    logger.info(f"Skipping duplicate empty-SEARCH patch for {fname} (already created)")
                    print(f"    ⏭️  Skipping duplicate patch for {fname} (already created)", flush=True)
                    continue
                else:
                    # File exists from before, empty search = replace entire content
                    logger.info(f"Replacing entire content of {fname} (empty SEARCH on existing file)")
                    try:
                        full_path.write_text(replace, encoding='utf-8')
                        if fname not in modified_files:
                            modified_files.append(fname)
                        applied_count += 1
                        continue
                    except Exception as e:
                        return PatchResult(False, modified_files, f"Failed to replace {fname}: {e}")
                
            try:
                # Progress indicator for large batches (keep for logging)
                if total_patches > 5 and (i + 1) % 5 == 0:
                    logger.info(f"  Progress: {i + 1}/{total_patches} patches applied")

                # Set a timeout for the entire patch operation (30 seconds per patch)
                def patch_timeout_handler(signum, frame):
                    raise TimeoutError(f"Patch application timed out for {fname}")

                signal.signal(signal.SIGALRM, patch_timeout_handler)
                signal.alarm(30)  # 30 second timeout per patch

                # Read content
                content = full_path.read_text(encoding='utf-8')

                # Check for file corruption before attempting patch
                from .adaptive_patch_matcher import AdaptivePatchMatcher
                corruption = AdaptivePatchMatcher.detect_file_corruption(content, full_path)
                if corruption:
                    print(f"    ⚠ File corruption detected: {corruption}", flush=True)
                    logger.warning(f"File corruption in {fname}: {corruption}")

                # Pre-check for ambiguity to provide better error message
                if search in content:
                    count = content.count(search)
                    if count > 1:
                        # AMBIGUOUS! Provide specific guidance
                        error_msg = (
                            f"AMBIGUOUS PATCH: The SEARCH block matches {count} different locations in {fname}!\n\n"
                            f"You MUST include MORE surrounding context to make your SEARCH block unique.\n"
                            f"For example, include the function definition line, comments above, or adjacent lines.\n\n"
                            f"Your current SEARCH block:\n{search[:300]}...\n\n"
                            f"HINT: Add 2-3 lines BEFORE and AFTER to create a unique match."
                        )
                        return PatchResult(False, modified_files, error_msg)

                # Try Apply
                new_content = self._apply_single_patch(content, search, replace)

                if new_content is None:
                    # Provide helpful feedback if search failed
                    nearest = self._find_nearest_match(content, search)
                    error_msg = f"Could not find SEARCH block in {fname}."
                    if nearest:
                        error_msg += f"\n\nDid you mean to match this instead?\n{nearest}\n\n"
                        error_msg += "HINT: Your SEARCH block must match EXACTLY (including docstrings and whitespace)."
                    else:
                        error_msg += f"\nBlock:\n{search[:200]}..."

                    return PatchResult(False, modified_files, error_msg)
                
                # Write back immediately so next patch sees it
                full_path.write_text(new_content, encoding='utf-8')
                
                # Cancel patch timeout
                signal.alarm(0)
                
                if fname not in modified_files:
                    modified_files.append(fname)
                applied_count += 1
                
            except TimeoutError as e:
                signal.alarm(0)
                print(f"  ⏱️  Timeout: {e}", flush=True)
                return PatchResult(False, modified_files, str(e))
            except Exception as e:
                signal.alarm(0)
                return PatchResult(False, modified_files, f"Failed applying patch to {fname}: {str(e)}")
        
        # Final Syntax Verification (Gate 0.5) with TIMEOUT
        # Check all modified python files for basic syntax validity
        import ast
        import json

        def timeout_handler(signum, frame):
            raise TimeoutError("Syntax validation timeout")
        
        # Adaptive timeout: reduce per-file timeout for large patch batches
        syntax_timeout = 10 if total_patches <= 10 else 5  # 5s for large batches
        
        print(f"  Validating syntax for {len(modified_files)} modified files...", flush=True)
        if total_patches > 5:
            logger.info(f"Validating syntax for {len(modified_files)} modified files (timeout: {syntax_timeout}s each)...")

        for fname in modified_files:
            full_path = self.project_dir / fname

            # Python syntax check with 10-second timeout
            if fname.endswith('.py'):
                try:
                    # Set alarm with adaptive timeout
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(syntax_timeout)
                    
                    content = full_path.read_text(encoding='utf-8')
                    
                    # Limit file size for syntax check (max 100KB)
                    if len(content) > 100000:
                        logger.warning(f"File {fname} is very large ({len(content)} bytes), skipping deep syntax check")
                        # Just check for basic syntax errors (unclosed brackets, etc)
                        try:
                            compile(content, fname, 'exec', dont_inherit=True)
                        except SyntaxError as e:
                            signal.alarm(0)
                            return PatchResult(False, modified_files, f"Patch introduced Syntax Error in {fname}: {e}")
                    else:
                        ast.parse(content)
                    
                    signal.alarm(0)  # Cancel alarm
                    
                except TimeoutError:
                    signal.alarm(0)
                    logger.warning(f"Syntax validation timed out for {fname}, skipping")
                    # Continue anyway - linting will catch issues
                except SyntaxError as e:
                    signal.alarm(0)
                    # Controller handles rollback based on result.success=False
                    return PatchResult(False, modified_files, f"Patch introduced Syntax Error in {fname}: {e}")

            # JSON syntax check - CRITICAL: LLM often generates invalid JSON (e.g., hex numbers)
            elif fname.endswith('.json'):
                try:
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(5)  # 5 second timeout for JSON
                    
                    content = full_path.read_text(encoding='utf-8')
                    json.loads(content)
                    
                    signal.alarm(0)
                except TimeoutError:
                    signal.alarm(0)
                    logger.warning(f"JSON validation timed out for {fname}, skipping")
                except json.JSONDecodeError as e:
                    signal.alarm(0)
                    # Provide helpful error message
                    error_msg = f"Patch introduced invalid JSON in {fname}: {e}\n"

                    # Check for common LLM mistakes
                    if '0x' in content:
                        error_msg += "\nHINT: JSON does not support hexadecimal numbers (0x...).\n"
                        error_msg += "Use decimal numbers instead (e.g., 0xffffff should be 16777215)."

                    return PatchResult(False, modified_files, error_msg)

        return PatchResult(True, modified_files, applied_patches=applied_count, total_patches=len(patches))

    def _apply_single_patch(self, content: str, search: str, replace: str) -> Optional[str]:
        """Apply a single patch with fallback strategies."""
        
        # Strategy 0: Adaptive Multi-Strategy Matcher (NEW - Most Robust)
        try:
            from .adaptive_patch_matcher import AdaptivePatchMatcher
            
            matcher = AdaptivePatchMatcher(
                file_path=Path('temp.py'),
                content=content,
                verbose=True
            )
            
            result = matcher.find_and_replace(search, replace)
            if result:
                return result
        except Exception as e:
            logger.debug(f'Adaptive matcher failed, falling back: {e}')
        
        # Strategy 1: Exact String Match (Fastest, Safest)
        if search in content:
            count = content.count(search)
            if count > 1:
                # AMBIGUOUS MATCH - Multiple occurrences found!
                # Return None to signal failure - LLM must provide more context
                logger.warning(f"Ambiguous patch: SEARCH block found {count} times in file. "
                               f"Patch will be rejected. LLM must include more surrounding context.")
                return None  # Force LLM to provide more specific search block
            return content.replace(search, replace, 1)
            
        # Strategy 3: Block-level Regex Match (Handles line splitting/joining)
        try:
            # Escape search for regex, then replace escaped whitespace with flexible matcher
            # We strip to avoid issues with leading/trailing newlines in the regex itself
            s_stripped = search.strip()
            if s_stripped:
                escaped_search = re.escape(s_stripped)
                # Replace any sequence of escaped whitespace with \s*
                flexible_search = re.sub(r'(\\ )|(\\ \n)|(\\\n)', r'\\s*', escaped_search)
                
                match = re.search(flexible_search, content, re.MULTILINE)
                if match:
                    start, end = match.span()
                    # We have a match! 
                    # For simplicity, we'll use the replacement as is, 
                    # but Strategy 2 (Fuzzy) is better for indentation.
                    # Let's return the content with the replacement.
                    return content[:start] + replace.strip('\n') + content[end:]
        except Exception as e:
            logger.debug(f"Regex match failed: {e}")

        # Strategy 3: Fuzzy Line Matcher (most robust for indentation)
        fuzzy_result = self._apply_fuzzy_patch(content, search, replace)
        if fuzzy_result:
            return fuzzy_result
            
        # Strategy 4: Line Collapse Matcher (Aggressive fallback for line splitting)
        return self._apply_collapse_patch(content, search, replace)

    def _apply_fuzzy_patch(self, content: str, search: str, replace: str) -> Optional[str]:
        """
        Apply using robust line-by-line whitespace-insensitive matching.
        """
        content_lines = content.splitlines(keepends=True)
        search_lines = search.splitlines(keepends=True)
        
        if not search_lines:
            return content # Empty search matches nothing but effectively changes nothing? Or invalid?
            
        # Strip whitespace for comparison
        clean_search = [l.strip() for l in search_lines if l.strip()]
        
        if not clean_search:
            # Search block was only whitespace?
            if not search.strip():
                 # Matches any empty line? No, too dangerous.
                 return None
        
        # Scan content
        match_start = -1
        match_end = -1
        
        for i in range(len(content_lines)):
            # Check for match starting at i
            # We look for the sequence of non-empty search lines
            
            content_idx = i
            search_idx = 0
            
            possible_match = True
            
            temp_end = i
            
            while search_idx < len(clean_search):
                if content_idx >= len(content_lines):
                    possible_match = False
                    break
                    
                line = content_lines[content_idx]
                
                # If content line is empty/whitespace, skip it?
                # This depends on strictness. 
                # If search block skipped empty lines, we should probably skip them in content too.
                if not line.strip():
                    content_idx += 1
                    continue
                    
                if line.strip() != clean_search[search_idx]:
                    possible_match = False
                    break
                    
                search_idx += 1
                content_idx += 1
                temp_end = content_idx
            
            if possible_match and search_idx == len(clean_search):
                # Found it!
                match_start = i
                match_end = temp_end
                break
                
        if match_start != -1:
             # SMART INDENTATION LOGIC
            # 1. Identify indentation of the first matched line in content
            first_matched_line = content_lines[match_start]
            existing_indent = len(first_matched_line) - len(first_matched_line.lstrip())
            
            # 2. Identify indentation of the first line in search block (that isn't empty)
            first_search_line = clean_search[0] # This is stripped
            # We need the original search line corresponding to the first matched line
            # Wait, clean_search is stripped. Let's look at `search_lines`
            # Find first non-empty line in search_lines
            search_indent = 0
            for s_line in search_lines:
                if s_line.strip():
                    search_indent = len(s_line) - len(s_line.lstrip())
                    break
            
            indent_delta = existing_indent - search_indent
            
            # 3. Adjust replacement block
            replace_lines = replace.splitlines() # splitlines() eats newlines usually, we want to reconstruct
            # Let's split, adjust, then join
            
            adjusted_replace_lines = []
            for r_line in replace_lines:
                if not r_line.strip():
                    adjusted_replace_lines.append(r_line) # Empty lines keep as is
                    continue
                    
                current_r_indent = len(r_line) - len(r_line.lstrip())
                new_indent = max(0, current_r_indent + indent_delta)
                adjusted_replace_lines.append(" " * new_indent + r_line.lstrip())
            
            # Reconstruct replacement string
            # Check original line endings? usually \n is fine
            adjusted_replace = "\n".join(adjusted_replace_lines)
            if replace.endswith('\n') and not adjusted_replace.endswith('\n'):
                 adjusted_replace += '\n'

            # Reconstruct content
            prefix = "".join(content_lines[:match_start])
            suffix = "".join(content_lines[match_end:])
            
            # Ensure adjusted_replace ends with a newline if the original did or if it's multi-line
            if not adjusted_replace.endswith('\n'):
                 adjusted_replace += '\n'
                 
            return prefix + adjusted_replace + suffix
            
        return None

    def _apply_collapse_patch(self, content: str, search: str, replace: str) -> Optional[str]:
        """
        Aggressive fallback: collapse all whitespace in both search and content.
        Useful when LLM splits lines in the search block that aren't split in content.
        """
        def collapse(text: str) -> str:
            return re.sub(r'\s+', '', text)

        collapsed_search = collapse(search)
        if not collapsed_search:
            return None

        content_lines = content.splitlines(keepends=True)
        
        # We'll use a sliding window of lines
        # But how many lines? The collapsed search might span fewer or more lines.
        # Let's try windows of varying sizes around the expected line count.
        
        search_line_count = len(search.splitlines())
        
        # Scan content
        for i in range(len(content_lines)):
            # Try windows of size from 1 to search_line_count * 2
            for window_size in range(1, search_line_count * 3):
                if i + window_size > len(content_lines):
                    break
                    
                window_lines = content_lines[i : i + window_size]
                window_content = "".join(window_lines)
                
                if collapse(window_content) == collapsed_search:
                    # Found a match!
                    # Indentation logic
                    first_matched_line = content_lines[i]
                    existing_indent = len(first_matched_line) - len(first_matched_line.lstrip())
                    
                    # Estimate search indentation
                    search_indent = 0
                    for s_line in search.splitlines():
                        if s_line.strip():
                            search_indent = len(s_line) - len(s_line.lstrip())
                            break
                    
                    indent_delta = existing_indent - search_indent
                    
                    # Adjust replacement lines
                    replace_lines = replace.splitlines()
                    adjusted_replace_lines = []
                    for r_line in replace_lines:
                        if not r_line.strip():
                            adjusted_replace_lines.append(r_line)
                            continue
                        current_r_indent = len(r_line) - len(r_line.lstrip())
                        new_indent = max(0, current_r_indent + indent_delta)
                        adjusted_replace_lines.append(" " * new_indent + r_line.lstrip())
                    
                    adjusted_replace = "\n".join(adjusted_replace_lines)
                    if not adjusted_replace.endswith('\n'):
                        adjusted_replace += '\n'
                        
                    prefix = "".join(content_lines[:i])
                    suffix = "".join(content_lines[i + window_size:])
                    return prefix + adjusted_replace + suffix
                    
        return None

    def _find_nearest_match(self, content: str, search: str) -> Optional[str]:
        """Find the most similar block in content for feedback. Optimized for speed on large files/blocks."""
        import difflib
        
        search = search.strip()
        search_lines = search.splitlines()
        if not search_lines:
            return None
            
        content_lines = content.splitlines()
        if len(content_lines) < len(search_lines):
            return None
            
        # Optimization: if the block is very large, don't check every window.
        # SequenceMatcher is O(N*M), so a sliding window is O(F * S^2).
        
        # Find first non-empty line of search to help anchor
        first_line_clean = ""
        anchor_idx = 0
        for idx, line in enumerate(search_lines):
            if line.strip():
                first_line_clean = line.strip()
                anchor_idx = idx
                break
        
        if not first_line_clean:
            return None

        best_ratio = 0.0
        best_block = None
        
        window_size = len(search_lines)
        
        # To avoid extreme slowness, we'll only check windows that have some 
        # lexical similarity to the anchor line.
        # Also limit the total number of expensive comparisons.
        max_comparisons = 200
        comparisons_done = 0
        
        # Limit string sizes for SequenceMatcher to prevent hangs (max 5000 chars)
        search_sample = search[:5000]
        
        for i in range(len(content_lines) - window_size + 1):
            # Check if this line is a potential anchor
            content_line = content_lines[i + anchor_idx].strip()
            
            if not content_line:
                continue
                
            if first_line_clean not in content_line and content_line not in first_line_clean:
                continue
            
            window = content_lines[i : i + window_size]
            window_str = "\n".join(window)
            window_sample = window_str[:5000]
            
            # Use SequenceMatcher with capped string sizes
            matcher = difflib.SequenceMatcher(None, search_sample, window_sample)
            ratio = matcher.ratio()
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_block = window_str
            
            comparisons_done += 1
            if comparisons_done >= max_comparisons:
                break
        
        if best_ratio > 0.5:
             return best_block
             
        return None
