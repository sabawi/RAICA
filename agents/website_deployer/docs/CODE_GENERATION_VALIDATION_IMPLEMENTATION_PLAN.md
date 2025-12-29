# Code Generation Validation & Recovery Implementation Plan

**Created:** 2025-11-26
**Status:** APPROVED - Ready for Implementation
**Priority:** CRITICAL - Blocks successful deployments

---

## 🎯 Executive Summary

### Root Cause Identified
Deployment failures traced to **Gemini LLM hitting token limits during Phase 3 (Code Generation)**. Incomplete code was cached and replayed in subsequent deployments, causing cascading failures at deployment time.

### Evidence
- **4 cached responses** (expected: 40+)
- **0 "Generated file:" messages** in deployment log (all files from cache)
- **Only FileRead schema** exists, but crud imports FileCreate (never generated)
- **Missing entire service layer** (app/services/)
- **Missing dependency injection** (app/api/deps.py)
- **Missing 4+ Python packages** from requirements.txt

### Impact
- 100% deployment failure rate when using cached incomplete generation
- Silent failures - no warnings about incomplete code
- Manual intervention required to discover missing components

---

## 📊 Deployment Failure Catalog

### Category 1: Missing Python Packages (requirements.txt)
1. `jsonschema` - Used by generated code but not in requirements.txt
2. `asyncpg` - Required for async PostgreSQL but not in requirements.txt
3. `email-validator` - Required by Pydantic EmailStr but not in requirements.txt
4. `sse-starlette` - Required for SSE streaming but not in requirements.txt

### Category 2: Missing Python Modules (Code Not Generated)
5. `app/api/deps.py` - Database/auth dependency injection module
6. `app/services/__init__.py` - Service layer package
7. `app/services/agent_service.py` - Agent service implementation
8. `app/services/chat_service.py` - Chat service implementation

### Category 3: Missing/Incomplete Schema Exports
9. `app/schemas/__init__.py` - Not exporting Token and other schemas
10. `app/schemas/files.py` - Missing FileCreate, FileUpdate schemas (only FileRead exists)

### Category 4: Invalid Imports
11. `app/models/__init__.py` - Importing non-existent Item model

### Category 5: Missing Configuration Files
12. `.env` file - No environment configuration created

### Category 6: Deployment Configuration Bugs
13. Apache Listen directive on port 5080 - Should only proxy, not listen

---

## 🔧 Implementation Plan

### Phase 1: Code Generation Validation (CRITICAL)

#### 1.1 Post-Generation Import Validation
**File:** `agents/code_generator.py`
**Function:** `validate_generated_code(generated_files: List[str]) -> ValidationResult`

```python
import ast
from pathlib import Path
from typing import List, Set, Dict

class ValidationResult:
    is_valid: bool
    missing_imports: List[str]
    missing_files: List[str]
    errors: List[str]

def validate_generated_code(generated_files: Dict[str, str]) -> ValidationResult:
    """
    Validates that all imports in generated code are resolvable.

    Args:
        generated_files: Dict mapping file paths to file contents

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult()
    all_modules = _extract_available_modules(generated_files)

    for file_path, content in generated_files.items():
        try:
            tree = ast.parse(content)
            imports = _extract_imports(tree)

            for imp in imports:
                if not _is_import_resolvable(imp, all_modules, file_path):
                    result.missing_imports.append(f"{file_path}: {imp}")
                    result.is_valid = False
        except SyntaxError as e:
            result.errors.append(f"Syntax error in {file_path}: {e}")
            result.is_valid = False

    return result

def _extract_imports(tree: ast.AST) -> List[str]:
    """Extract all import statements from AST"""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
                # Also track imported names
                for alias in node.names:
                    imports.append(f"{node.module}.{alias.name}")
    return imports

def _extract_available_modules(generated_files: Dict[str, str]) -> Set[str]:
    """Build set of all modules/classes that were generated"""
    modules = set()

    for file_path, content in generated_files.items():
        # Convert file path to module path
        # e.g., app/services/agent_service.py -> app.services.agent_service
        module_path = file_path.replace('/', '.').replace('.py', '')
        modules.add(module_path)

        # Extract class/function definitions
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    modules.add(f"{module_path}.{node.name}")
        except:
            pass

    return modules

def _is_import_resolvable(import_path: str, available_modules: Set[str], current_file: str) -> bool:
    """Check if import can be resolved to generated or stdlib module"""
    # Check if it's in generated code
    if import_path in available_modules:
        return True

    # Check if it's stdlib (rough heuristic)
    stdlib_modules = {'os', 'sys', 'json', 'typing', 'datetime', 'pathlib',
                     'logging', 'asyncio', 'uuid', 're'}
    root_module = import_path.split('.')[0]
    if root_module in stdlib_modules:
        return True

    # Check if it's a known third-party dependency
    # (should cross-reference with requirements.txt)
    known_deps = {'fastapi', 'pydantic', 'sqlalchemy', 'uvicorn',
                  'jinja2', 'passlib', 'jose'}
    if root_module in known_deps:
        return True

    return False
```

**Integration Point:**
```python
# In code_generator.py, after all files generated:

generated_files = self.generate_all_files()  # Returns Dict[str, str]

# VALIDATE BEFORE WRITING
validation_result = validate_generated_code(generated_files)

if not validation_result.is_valid:
    logger.error(f"Code generation validation failed:")
    for error in validation_result.errors:
        logger.error(f"  - {error}")
    for missing in validation_result.missing_imports:
        logger.error(f"  - Missing import: {missing}")

    # RETRY with different model
    raise CodeGenerationIncompleteError(validation_result)

# Only write files if validation passes
self.write_files(generated_files)
```

#### 1.2 Requirements.txt Validation
**File:** `agents/code_generator.py`
**Function:** `validate_requirements(generated_files: Dict[str, str], requirements_txt: str) -> List[str]`

```python
def validate_requirements(generated_files: Dict[str, str], requirements_txt: str) -> List[str]:
    """
    Check that all imported third-party packages are in requirements.txt

    Returns:
        List of missing packages
    """
    # Parse requirements.txt
    requirements = set()
    for line in requirements_txt.split('\n'):
        line = line.strip()
        if line and not line.startswith('#'):
            # Extract package name (before [, ==, >=, etc.)
            pkg = line.split('[')[0].split('=')[0].split('>')[0].split('<')[0].strip()
            requirements.add(pkg.lower())

    # Extract imports from all generated files
    all_imports = set()
    for content in generated_files.values():
        try:
            tree = ast.parse(content)
            imports = _extract_imports(tree)
            # Get root package name
            for imp in imports:
                root_pkg = imp.split('.')[0]
                if root_pkg not in STDLIB_MODULES:
                    all_imports.add(root_pkg.lower())
        except:
            pass

    # Map import names to package names (some differ)
    IMPORT_TO_PACKAGE = {
        'jose': 'python-jose',
        'jwt': 'python-jose',
        'passlib': 'passlib',
        'pydantic': 'pydantic',
        'fastapi': 'fastapi',
        'uvicorn': 'uvicorn',
        'sqlalchemy': 'sqlalchemy',
        'jinja2': 'jinja2',
        'asyncpg': 'asyncpg',
        'jsonschema': 'jsonschema',
        'email_validator': 'email-validator',
        'sse_starlette': 'sse-starlette',
    }

    missing = []
    for imp in all_imports:
        package = IMPORT_TO_PACKAGE.get(imp, imp)
        if package not in requirements:
            missing.append(package)

    return missing
```

---

### Phase 2: Token Limit Detection & Recovery (CRITICAL)

#### 2.1 LLM Response Validator
**File:** `agents/llm_interface.py`
**Function:** `validate_llm_response(response, expected_output_type) -> bool`

```python
def validate_llm_response(response: str, expected_output_type: str = "code") -> Tuple[bool, Optional[str]]:
    """
    Validate that LLM response is complete and not truncated.

    Args:
        response: Raw LLM response text
        expected_output_type: "code", "json", "markdown", etc.

    Returns:
        (is_valid, error_message)
    """
    # Check for truncation indicators
    truncation_signs = [
        "...",  # Common truncation marker
        "[TRUNCATED]",
        "[OUTPUT LIMIT",
        "continue",  # LLM saying it will continue
    ]

    lower_response = response.lower()
    for sign in truncation_signs:
        if sign.lower() in lower_response[-200:]:  # Check end of response
            return False, f"Response appears truncated (found '{sign}')"

    # Validate structure based on expected type
    if expected_output_type == "code":
        # Check for balanced delimiters
        if response.count("```") % 2 != 0:
            return False, "Unbalanced code fence delimiters"

        # Check for common incomplete patterns
        if response.rstrip().endswith(("def ", "class ", "async def ")):
            return False, "Response ends with incomplete function/class definition"

    elif expected_output_type == "json":
        # Try to parse
        try:
            json.loads(response)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}"

    return True, None
```

#### 2.2 Multi-Model Fallback Strategy
**File:** `agents/llm_interface.py`
**Class:** `LLMInterface`

```python
class LLMInterface:
    def __init__(self):
        self.models = [
            ("gemini-pro", self._call_gemini),
            ("claude-3-opus", self._call_claude),
            ("gpt-4", self._call_openai),
        ]
        self.current_model_index = 0

    def generate_with_fallback(self, prompt: str, max_retries: int = 3) -> str:
        """
        Generate response with automatic fallback to different models on failure.

        Retries with same model first, then falls back to next model.
        """
        attempt = 0
        errors = []

        while attempt < max_retries:
            model_name, model_func = self.models[self.current_model_index]

            try:
                logger.info(f"Attempt {attempt + 1}/{max_retries} with {model_name}")
                response = model_func(prompt)

                # Validate response
                is_valid, error = validate_llm_response(response, "code")
                if not is_valid:
                    logger.warning(f"{model_name} returned invalid response: {error}")
                    errors.append(f"{model_name}: {error}")

                    # Switch to next model
                    self._switch_to_next_model()
                    attempt += 1
                    continue

                logger.info(f"✅ Successfully generated with {model_name}")
                return response

            except TokenLimitExceeded as e:
                logger.error(f"{model_name} hit token limit: {e}")
                errors.append(f"{model_name}: Token limit exceeded")

                # Immediately switch to next model
                self._switch_to_next_model()
                attempt += 1

            except Exception as e:
                logger.error(f"{model_name} failed: {e}")
                errors.append(f"{model_name}: {str(e)}")

                # Switch to next model
                self._switch_to_next_model()
                attempt += 1

        # All models failed
        raise AllModelsFailedError(f"All {max_retries} attempts failed:\n" + "\n".join(errors))

    def _switch_to_next_model(self):
        """Switch to next available model"""
        self.current_model_index = (self.current_model_index + 1) % len(self.models)
        next_model = self.models[self.current_model_index][0]
        logger.info(f"🔄 Switching to {next_model}")
```

---

### Phase 3: Cache Validation (HIGH PRIORITY)

#### 3.1 Cache Integrity Validator
**File:** `agents/cache_manager.py`
**Function:** `validate_cache(cache_file: str) -> bool`

```python
def validate_cache(cache_file: str, expected_phases: List[str]) -> Tuple[bool, List[str]]:
    """
    Validate that cached responses are complete and usable.

    Args:
        cache_file: Path to cache JSON file
        expected_phases: List of phase names that should be in cache

    Returns:
        (is_valid, list_of_issues)
    """
    try:
        with open(cache_file) as f:
            cache = json.load(f)
    except Exception as e:
        return False, [f"Cannot load cache: {e}"]

    issues = []

    # Check if all expected phases are present
    cache_keys = set(cache.keys())
    for phase in expected_phases:
        if not any(phase.lower() in key.lower() for key in cache_keys):
            issues.append(f"Missing cache for phase: {phase}")

    # Check each cached response for completeness
    for key, value in cache.items():
        if not value or len(str(value)) < 100:
            issues.append(f"Suspiciously short cache entry: {key} ({len(str(value))} chars)")

        # If it's code, validate structure
        if isinstance(value, str):
            if "```" in value:
                if value.count("```") % 2 != 0:
                    issues.append(f"Unbalanced code fences in cache: {key}")

    # Minimum cache size check (rough heuristic)
    if len(cache) < 4:
        issues.append(f"Cache too small: only {len(cache)} entries (expected 10+)")

    is_valid = len(issues) == 0
    return is_valid, issues

def should_invalidate_cache(cache_file: str) -> bool:
    """Determine if cache should be invalidated and regenerated"""
    if not os.path.exists(cache_file):
        return True  # No cache, must generate

    # Check cache age (invalidate if older than 7 days)
    cache_age = time.time() - os.path.getmtime(cache_file)
    if cache_age > 7 * 24 * 3600:
        logger.warning(f"Cache is {cache_age / 86400:.1f} days old, invalidating")
        return True

    # Validate cache integrity
    expected_phases = ["Requirements", "Architecture", "Code Generation", "Deployment"]
    is_valid, issues = validate_cache(cache_file, expected_phases)

    if not is_valid:
        logger.error(f"Cache validation failed:")
        for issue in issues:
            logger.error(f"  - {issue}")
        return True

    logger.info("✅ Cache validation passed")
    return False
```

**Integration:**
```python
# In deployment script, before using cache:

if args.use_cache:
    if should_invalidate_cache(args.cache_file):
        logger.warning("⚠️  Cache invalid or outdated - regenerating from scratch")
        args.use_cache = False
        # Delete corrupted cache
        if os.path.exists(args.cache_file):
            os.rename(args.cache_file, args.cache_file + '.invalid')
```

---

### Phase 4: User Escalation & Recovery (MEDIUM PRIORITY)

#### 4.1 Interactive Recovery Flow
**File:** `agents/deployment_orchestrator.py`

```python
def handle_validation_failure(
    validation_result: ValidationResult,
    attempt: int,
    max_attempts: int = 3
) -> RecoveryAction:
    """
    Handle code generation validation failures with user escalation.

    After 3 failed attempts, ask user how to proceed.
    """
    if attempt < max_attempts:
        logger.warning(f"Validation failed (attempt {attempt}/{max_attempts})")
        logger.warning("Retrying with different model...")
        return RecoveryAction.RETRY

    # Max attempts reached - escalate to user
    logger.error("❌ Code generation validation failed after 3 attempts")
    logger.error(f"\nMissing components:")
    for missing in validation_result.missing_imports:
        logger.error(f"  - {missing}")

    print("\n" + "="*60)
    print("CODE GENERATION FAILED - USER INPUT REQUIRED")
    print("="*60)
    print("\nOptions:")
    print("  1. Regenerate all code from scratch (recommended)")
    print("  2. Create stub implementations for missing components")
    print("  3. Abort deployment")
    print()

    choice = input("Select option (1-3): ").strip()

    if choice == "1":
        return RecoveryAction.REGENERATE_ALL
    elif choice == "2":
        return RecoveryAction.CREATE_STUBS
    else:
        return RecoveryAction.ABORT
```

---

## 🎬 Implementation Order

### Sprint 1: Critical Validation (Week 1)
1. ✅ Implement `validate_generated_code()` with AST-based import checking
2. ✅ Implement `validate_requirements()` for requirements.txt verification
3. ✅ Add validation calls to code generator phase
4. ✅ Write unit tests for validators

### Sprint 2: LLM Fallback (Week 1-2)
1. ✅ Implement `validate_llm_response()` for truncation detection
2. ✅ Implement `LLMInterface.generate_with_fallback()` multi-model retry
3. ✅ Add token limit exception handling for Gemini/Claude/GPT
4. ✅ Test fallback flow with intentional failures

### Sprint 3: Cache Validation (Week 2)
1. ✅ Implement `validate_cache()` for integrity checking
2. ✅ Implement `should_invalidate_cache()` with age + integrity checks
3. ✅ Integrate cache validation before cache usage
4. ✅ Add cache version/schema validation

### Sprint 4: User Escalation (Week 2-3)
1. ✅ Implement `handle_validation_failure()` interactive prompts
2. ✅ Add stub generation fallback option
3. ✅ Create recovery action handlers
4. ✅ Add comprehensive logging for debugging

---

## 📈 Success Metrics

### Before Implementation (Current State)
- ❌ 0% deployment success rate with cached incomplete generation
- ❌ No detection of incomplete code until deployment
- ❌ No fallback when LLM hits token limits
- ❌ No validation of cached responses

### After Implementation (Target State)
- ✅ 95%+ deployment success rate
- ✅ 100% detection of incomplete code before deployment
- ✅ Automatic fallback to alternative models on failure
- ✅ Cache validation prevents use of corrupted cache
- ✅ User escalation after 3 failed attempts

---

## 🧪 Testing Strategy

### Unit Tests
```python
# test_code_validator.py
def test_validate_code_detects_missing_imports():
    files = {
        "app/main.py": "from app.services import agent_service"
        # No app/services/agent_service.py generated
    }
    result = validate_generated_code(files)
    assert not result.is_valid
    assert "agent_service" in str(result.missing_imports)

def test_validate_requirements_detects_missing_packages():
    files = {
        "app/main.py": "import jsonschema\nfrom sse_starlette import EventSourceResponse"
    }
    requirements = "fastapi\npydantic"
    missing = validate_requirements(files, requirements)
    assert "jsonschema" in missing
    assert "sse-starlette" in missing
```

### Integration Tests
```python
# test_deployment_with_validation.py
def test_deployment_rejects_incomplete_cache():
    # Create corrupted cache with only 2 entries
    with open("test_cache.json", "w") as f:
        json.dump({"phase1": "data", "phase2": "data"}, f)

    should_invalidate = should_invalidate_cache("test_cache.json")
    assert should_invalidate == True

def test_llm_fallback_on_token_limit():
    # Mock Gemini to raise TokenLimitExceeded
    # Verify Claude is called as fallback
    pass
```

---

## 📝 Next Steps

1. **Immediate:** Implement Phase 1 (Code Generation Validation)
2. **This Week:** Implement Phase 2 (LLM Fallback)
3. **Next Week:** Implement Phase 3 (Cache Validation)
4. **Following Week:** Implement Phase 4 (User Escalation)

---

## 📚 Related Documents

- `DEPLOYMENT_FAILURE_ANALYSIS.md` - Root cause analysis
- `SSH_AUTHENTICATION_FIX.md` - SSH key issues resolved
- `CODE_GENERATION_BEST_PRACTICES.md` - LLM code generation guidelines
