# Intelligent Dependency Resolver - Integration Plan
**Date**: 2024-12-03
**Status**: Design Complete, Implementation Pending

## Executive Summary

Instead of hardcoding dependencies and security patterns in prompts, we leverage the **parent RAICA model** with tool calling to dynamically research:

1. **Latest dependencies** for any tech stack (with versions)
2. **Security best practices** (password hashing, auth middleware, etc.)
3. **Solutions to verification failures** (retry with intelligent fixes)

**Architecture**:
- Parent Server (`http://localhost:5050`) - RAICA with OpenAI tool calling (web search, documentation, research)
- Website Deployer Agent - Queries parent for research, uses results in code generation

## Current Problem (Root Cause)

**Zero deployments succeed** because:

| Issue | Current Approach | Problem |
|-------|-----------------|---------|
| Dependencies | Hardcoded in prompts | Outdated, incomplete, inflexible |
| Security Patterns | Generic instructions | LLM doesn't generate specific code |
| Verification Failures | Retry with same prompt | No learning, same errors repeat |

**Evidence**:
```
❌ Python FastAPI (3/3 attempts): Missing 7 dependencies in requirements.txt
❌ Laravel E-commerce (3/3 attempts): Missing Hash::make(), auth middleware
```

## Proposed Solution: Agentic Research Architecture

### Phase 1: Pre-Generation Research

**Before generating code**, query parent model for dependencies:

```python
# Instead of hardcoded:
requirements_txt = ["fastapi", "sqlalchemy", "pydantic", ...]  # ❌ Static, outdated

# Use intelligent research:
resolver = IntelligentDependencyResolver()
result = await resolver.research_dependencies(
    tech_stack="python",
    framework="fastapi",
    features=["jwt_auth", "email_verification", "async_operations"],
    database="postgresql"
)
# Returns: ['fastapi==0.104.1', 'sqlalchemy==2.0.23', ...] ✅ Dynamic, current
```

**Parent model uses**:
- Web search for latest package versions
- Documentation lookup for best practices
- Tool calling to aggregate accurate information

### Phase 2: Enhanced Prompts with Research

**Inject research results into LLM prompts**:

```python
# Current prompt (generic):
prompt = "Generate FastAPI config with JWT authentication"  # ❌ Vague

# Enhanced prompt (specific):
dependencies_str = '\n'.join(result.dependencies)
security_patterns_str = result.security_patterns['password_hashing']

prompt = f"""
Generate FastAPI config with JWT authentication.

REQUIRED DEPENDENCIES (add to requirements.txt):
{dependencies_str}

SECURITY PATTERN (password hashing):
{security_patterns_str}

Include ALL packages in requirements.txt.
"""  # ✅ Explicit, actionable
```

### Phase 3: Intelligent Retry on Failures

**When verification fails**, query for specific fixes:

```python
# Verification failed with:
errors = [
    "Password hashing not detected (expected Hash::make or Hash::check)",
    "Auth middleware not found on protected routes"
]

# Query parent for solutions:
fix_result = await resolver.research_verification_fix(
    tech_stack="php",
    framework="laravel",
    verification_errors=errors,
    generated_code_sample=generated_code['register.php']
)

# Retry with specific fixes:
enhanced_prompt = f"""
Previous attempt failed with these errors:
{errors}

Here's the correct implementation:
{fix_result['fixes']}

Regenerate the code with these fixes applied.
"""
```

## Integration Points

### 1. Workflow Planner Enhancement

**File**: `stages/intelligent_generators/workflow_planner.py`

**Changes**:
```python
from ..intelligent_dependency_resolver import IntelligentDependencyResolver

class WorkflowPlanner:
    def __init__(self, tech_config: Optional[TechStackConfig] = None):
        self.dependency_resolver = IntelligentDependencyResolver()
        # ... rest of init

    async def plan_workflow(self, spec: DetailedSpecification) -> WorkflowPlan:
        """Enhanced with Agentic research."""

        # STEP 1: Research dependencies BEFORE code generation
        logger.info("🔬 Researching dependencies via parent RAICA...")

        dep_research = await self.dependency_resolver.research_dependencies(
            tech_stack=spec.tech_stack,
            framework=spec.framework,
            features=self._extract_features(spec),
            database=spec.database_type
        )

        if not dep_research.success:
            logger.warning(f"⚠️ Dependency research failed, using fallback")
            # Fall back to static prompts
        else:
            logger.info(f"✅ Researched {len(dep_research.dependencies)} dependencies")
            # Inject into prompts
            self.researched_dependencies = dep_research.dependencies
            self.security_patterns = dep_research.security_patterns

        # STEP 2: Generate workflow with enhanced prompts
        # ... rest of workflow planning
```

### 2. LLM Code Generator Enhancement

**File**: `stages/intelligent_generators/llm_code_generator.py`

**Changes**:
```python
def generate_file(self, file_path: str, prompt: str, context: Dict) -> str:
    """Enhanced prompt with researched dependencies."""

    # Check if we have researched dependencies
    if hasattr(self, 'researched_dependencies') and file_path == 'requirements.txt':
        # Use researched dependencies instead of asking LLM
        deps = '\n'.join(self.researched_dependencies)

        return f"""# Auto-generated via RAICA research
# Researched dependencies for {context['tech_stack']} project

{deps}
"""

    # For other files, enhance prompt with security patterns
    if 'auth' in file_path.lower() or 'register' in file_path.lower():
        enhanced_prompt = self._inject_security_patterns(prompt, context)
        return self.llm_client.generate(enhanced_prompt, context)

    return self.llm_client.generate(prompt, context)
```

### 3. Consistency Verifier Enhancement

**File**: `stages/intelligent_generators/consistency_verifier.py`

**Changes**:
```python
from ..intelligent_dependency_resolver import IntelligentDependencyResolver

class ConsistencyVerifier:
    def __init__(self, tech_config: Optional[TechStackConfig] = None):
        self.dependency_resolver = IntelligentDependencyResolver()
        # ... rest of init

    async def verify_with_retry(self, generated_files: Dict, spec: DetailedSpecification, max_attempts: int = 3):
        """Verification with intelligent retry."""

        for attempt in range(1, max_attempts + 1):
            logger.info(f"🔍 Verification attempt {attempt}/{max_attempts}")

            result = self.verify(generated_files, spec)

            if result.is_valid:
                return result  # Success!

            if attempt < max_attempts:
                # Query parent for fix solutions
                logger.info(f"🔬 Querying parent model for solutions...")

                fix_result = await self.dependency_resolver.research_verification_fix(
                    tech_stack=spec.tech_stack,
                    framework=spec.framework,
                    verification_errors=result.critical_issues,
                    generated_code_sample=self._get_sample_code(generated_files)
                )

                if fix_result['success']:
                    # Apply fixes and regenerate
                    logger.info(f"✅ Got {len(fix_result['fixes'])} fixes from research")
                    # TODO: Regenerate with fixes
                else:
                    logger.warning(f"⚠️ Failed to get fixes, using fallback retry")

        return result  # Failed after max attempts
```

## Implementation Checklist

### Phase 1: Core Infrastructure (2-3 hours)
- [x] Create `intelligent_dependency_resolver.py`
- [ ] Test connection to parent server
- [ ] Test dependency research query
- [ ] Test verification fix query

### Phase 2: Integration (3-4 hours)
- [ ] Enhance `workflow_planner.py` with pre-generation research
- [ ] Enhance `llm_code_generator.py` with injected dependencies
- [ ] Enhance `consistency_verifier.py` with intelligent retry
- [ ] Update retry logic in `intelligent_code_generator.py`

### Phase 3: Testing (2-3 hours)
- [ ] Test simple Python API deployment with research
- [ ] Test simple PHP website deployment with research
- [ ] Verify dependencies are correctly researched
- [ ] Verify fixes are applied on retry
- [ ] Test with parent server offline (fallback to static prompts)

### Phase 4: Optimization (1-2 hours)
- [ ] Add caching for research results (don't query twice for same stack)
- [ ] Add confidence scoring (use static fallback if research confidence low)
- [ ] Add detailed logging of research queries and results

## Testing Plan

### Test 1: Dependency Research

**Setup**:
1. Start parent server: `python fastapi_server_complete.py`
2. Run test: `python stages/intelligent_dependency_resolver.py`

**Expected**:
```
EXAMPLE 1: Research FastAPI Project Dependencies
✅ Successfully researched dependencies:

Found 10+ packages:
  - fastapi==0.104.1
  - sqlalchemy==2.0.23
  - python-jose[cryptography]==3.3.0
  - passlib[bcrypt]==1.7.4
  ...

Security patterns: 2
  - password_hashing
  - jwt_authentication
```

### Test 2: Full Deployment with Research

**Setup**:
1. Start parent server
2. Run deployment: `./deploy.sh --auto-input auto_deploy_simple_python.json`

**Expected**:
```
🔬 Researching dependencies via parent RAICA...
✅ Researched 12 dependencies
📝 Injecting researched dependencies into requirements.txt
...
✅ DEPLOYMENT SUCCESS
```

### Test 3: Intelligent Retry

**Setup**:
1. Simulate verification failure
2. Observe retry with research

**Expected**:
```
❌ Verification failed: Password hashing not detected
🔬 Querying parent model for solutions...
✅ Got 2 fixes from research
🔄 Retrying with fixes (attempt 2/3)
...
✅ Verification passed
```

## Success Metrics

After implementation:

| Metric | Before | After (Target) |
|--------|--------|----------------|
| Deployment Success Rate | 0% (0/2) | 60-80% (5-6/7) |
| Dependencies Correctness | 0% | 95%+ |
| Security Pattern Detection | 0% | 90%+ |
| Retry Success Rate | 0% | 70%+ |
| Time to Deploy | N/A (all failed) | 5-15 min |

## Advantages Over Static Prompts

| Aspect | Static Prompts | Agentic Research |
|--------|---------------|------------------|
| Dependency Versions | Hardcoded (outdated) | Latest (researched) |
| Coverage | Incomplete (forgot packages) | Complete (web search) |
| Security Patterns | Generic instructions | Concrete code examples |
| Adaptability | Must update manually | Auto-updates |
| Failure Recovery | Blind retry | Intelligent fix suggestions |
| Tech Stack Support | 3-5 stacks only | Unlimited (dynamic research) |

## Fallback Strategy

If parent server is unavailable:

1. **Log warning**: "Parent RAICA unavailable, using static fallback"
2. **Use static prompts**: Fall back to current hardcoded approach
3. **Continue deployment**: Don't block on research failure
4. **Cache last successful research**: Use cached results if available

**Implementation**:
```python
try:
    dep_research = await resolver.research_dependencies(...)
except Exception as e:
    logger.warning(f"⚠️ Research failed ({e}), using static fallback")
    dep_research = self._get_static_dependencies_fallback(tech_stack)
```

## Next Steps

1. **Immediate**: Test `intelligent_dependency_resolver.py` standalone
2. **Short-term**: Integrate into workflow planner (Phase 2)
3. **Medium-term**: Add intelligent retry to verifier (Phase 3)
4. **Long-term**: Add caching, confidence scoring, metrics dashboard

## Conclusion

This architecture transforms the deployment system from:
- **Static**: Hardcoded, outdated, inflexible
- **To Dynamic**: Researched, current, adaptive

**Expected Impact**:
- ✅ First successful deployment within 1 hour of implementation
- ✅ 60-80% success rate across all 7 templates
- ✅ Automatic adaptation to new frameworks without code changes
- ✅ Intelligent failure recovery instead of blind retries

**Time Investment**: 8-12 hours
**Expected ROI**: System that actually deploys websites successfully!
