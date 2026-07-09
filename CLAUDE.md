# ⛔🛑⚠️ MANDATORY PRE-FLIGHT HOOK - READ BEFORE ANY CODE CHANGE ⛔🛑⚠️

## THIS HOOK MUST BE PROCESSED BEFORE EVERY CODE MODIFICATION

**STOP. Before writing ANY code, you MUST verify your approach passes this checklist.**

### THE CARDINAL RULE: LLM-DRIVEN ITERATION LOOP

Every solution in RAICA MUST follow this pattern:
```
┌─────────────────────────────────────────────────────────────┐
│  1. RAICA prompts LLM with context + request                │
│  2. LLM responds with STRUCTURED DATA (JSON) telling        │
│     RAICA exactly what to do                                │
│  3. RAICA executes LLM's instructions (no interpretation!)  │
│  4. RAICA feeds results back to LLM                         │
│  5. REPEAT until LLM says task is complete                  │
└─────────────────────────────────────────────────────────────┘
```

### ⛔ FORBIDDEN - INSTANT REJECTION IF YOU DO ANY OF THESE:

| VIOLATION | EXAMPLE | WHY IT'S WRONG |
|-----------|---------|----------------|
| **Hardcoded lists** | `KEYWORDS = ["fix", "debug", ...]` | RAICA doesn't decide meaning, LLM does |
| **Pattern matching** | `if "install" in request:` | RAICA doesn't interpret text, LLM does |
| **Text parsing for meaning** | Filtering "explanation" lines from LLM output | LLM should return JSON, not prose to parse |
| **Special case handlers** | `if error_type == "ImportError":` | LLM handles ALL cases generically |
| **Fallback defaults** | `return ['ls -la']` when LLM fails | Fail explicitly, don't guess |
| **Keyword-based routing** | `WEB_SEARCH_KEYWORDS = [...]` | LLM classifies semantically |

### ✅ REQUIRED - YOUR CODE MUST DO ALL OF THESE:

| REQUIREMENT | IMPLEMENTATION |
|-------------|----------------|
| **LLM returns structured JSON** | `{"commands": [...], "next_action": "..."}` |
| **RAICA only parses JSON** | `data = json.loads(response)` - no text interpretation |
| **RAICA executes blindly** | Whatever LLM says, RAICA does (within safety limits) |
| **Results fed back to LLM** | LLM sees output and decides next step |
| **LLM decides completion** | `{"status": "complete"}` not RAICA guessing |

### 🔍 PRE-FLIGHT CHECKLIST (Mental verification before coding):

Before writing code, answer these questions:

1. **"Am I adding a hardcoded list?"** → If YES, STOP. Make LLM decide.
2. **"Am I parsing text to extract meaning?"** → If YES, STOP. Make LLM return JSON.
3. **"Am I handling a specific case differently?"** → If YES, STOP. Generalize.
4. **"Does RAICA interpret/decide anything?"** → If YES, STOP. LLM interprets/decides.
5. **"Would a new edge case break this?"** → If YES, STOP. You're not generalized.
6. **"Am I writing complex logic?"** → If YES, STOP. RAICA is scaffolding, LLM does heavy lifting.

### ⚡ THE MINIMAL SCAFFOLDING PRINCIPLE:

**RAICA IS NOT A TRADITIONAL FRAMEWORK - IT'S A SCAFFOLD FOR THE LLM**

```
┌────────────────────────────────────────────────────────┐
│  RAICA's Role: MINIMAL SCAFFOLDING                     │
│  - Call LLM with context                               │
│  - Execute what LLM says                               │
│  - Feed results back                                   │
│  - Loop until complete                                 │
│                                                         │
│  LLM's Role: EVERYTHING ELSE                           │
│  - Design                                              │
│  - Code                                                │
│  - Parse                                               │
│  - Analyze                                             │
│  - Fix                                                 │
│  - Decide                                              │
└────────────────────────────────────────────────────────┘
```

**NEVER OVERCODE - Examples:**

| ❌ OVERCODING | ✅ MINIMAL SCAFFOLDING |
|--------------|------------------------|
| Write 60-line test parser with complex logic | Run test file, return output. LLM parses. |
| Write regex patterns to extract code | Ask LLM to extract code in JSON |
| Write error categorization logic | Show LLM the error, it categorizes |
| Write validation checks for fixes | Apply fix, show LLM the result, it validates |
| Write output formatters | LLM formats output as part of response |

**The Test: "Could this be a simple LLM prompt instead?"**
- If YES → Make it an LLM prompt
- If NO → You need minimal scaffolding (loop, execute, return)

### 🧪 THE GENERALIZATION TEST:

```
If tomorrow a completely new, never-seen-before request type appears,
will your code handle it correctly?

YES → Good, LLM will figure it out
NO  → Bad, you hardcoded something
```

---

- Operation Plan for updating and committing the project code: 1) Read and understand all project directive and rules in CLAUDE.md file, project configurations, /doc documentations to make sure you understand the baseline of the project 2) Review the development work status: What was accomplished in fixes, features, modifications for this the current update 3) Take count of all tracked files changes, added files, and configuration changes 4) Decisions: a) Does the documentaions need update as a result of the modifications?  b) does the install/upgrade process or scripts need update? Make a list of action plans to make the needed update to a, b, or both 5) Was thorough testing (Unit/Functional Verifications/ System) done? If it was not, build and run the needed testing scenaios. Once passed you are readu to the last 2 steps 6) Does the version number needs updating? if yes, increment the product version number 7) Stage the files correctly 8) Commit and push to github
- YOU DO NOT NEED MY PERMISSION to view the logs or view any files in the project, YOU WILL NEED PERMISSION TO MAKE CODE OR CONFIGURATION CHANGES IN THE PROJECT FILES. ALWAYS EXPLAIN WHAT YOU ARE DOING AND WHY.
- ALL DOCUMENTATIONS AND HELP INFORMATION SHOULD GO UNER THE ./docs DIRECTORY UNDER APPROPRIATE LOCATION AND POSSIBLY MERGED WIHIN THE MAIN DOCUMENTATION FILES
- ALL TEST SCRIPTS AND TESTING CODE SHOULD GO UNDER THE ./tests DIRECTORY UNDER APPROPRIATE SUBDIRECTORY STRUCTURE

# 📁 MANDATORY PROJECT DIRECTORY ORGANIZATION

## ROOT DIRECTORY - Keep Clean and Essential Only
- **README.md** - Main project documentation (REQUIRED)
- **CLAUDE.md** - Project directives and rules (REQUIRED)
- **Core Python modules with active dependencies** - http_helpers.py, http_pool_manager.py, text_chunker.py, document_interrogator.py, signature_image_detection.py (KEEP IN ROOT - critical imports)
- **fastapi_server_complete.py** - Main server file (REQUIRED)
- **version.py** - Centralized version management (REQUIRED)

## DIRECTORY STRUCTURE RULES - STRICTLY ENFORCE

### /docs/ - Development Documentation
```
docs/
├── production/          # REQUIRED - User/Admin/Developer/Installation guides
├── housekeeping/        # NEW - Project management, internal docs
│   ├── procedures/      # Emergency procedures, test checklists
│   ├── status-tracking/ # Project status, phase reviews, changelogs
│   └── workflow-automation/ # Internal workflow tools, optimization
├── archive/             # Historical docs, validation reports
└── *.md                 # Technical documentation (HTML_EMAIL_CONVERSION_SYSTEM.md, etc.)
```

### /tests/ - All Testing Code
```
tests/
├── utilities/           # Test utilities, API testing scripts
├── vision_regression/   # Image/vision testing
├── integration/         # Integration testing
└── data/               # Test data files
```

### /archive/experimental/ - Development/Debug Files
- analyze_*.py, debug_*.py, improved_*.py files
- Experimental implementations not in production

## FILE PLACEMENT RULES

### HOUSEKEEPING DOCUMENTATION (→ docs/housekeeping/)
**Project management docs NOT relevant to code development:**
- Status tracking: PHASE_STATUS_*.md, PROJECT_CHANGELOG.md, *_STATUS.md, **CHANGELOG_v*.md** (version-specific changelogs)
- Procedures: ROLLBACK_PROCEDURE*.md, *_TEST_CHECKLIST.md, UNTESTED_CHANGES.md
- Workflow: AUTOMATION_*PLAN.md, CLI_*QUICKSTART.md
- **MANDATORY: Every version release MUST have CHANGELOG_vX.X.X.XX.md in docs/housekeeping/status-tracking/**

### DEVELOPMENT DOCUMENTATION (→ docs/)
**Technical docs relevant to developers:**
- Configuration guides: LLM_CONFIGURATION_GUIDE.md, PROJECT_CONFIGURATION_DIRECTIVE.md
- Technical specs: HTML_EMAIL_CONVERSION_SYSTEM.md, VERSION_MANAGEMENT.md
- Implementation plans: *_IMPLEMENTATION_PLAN.md

### TEST FILES (→ tests/appropriate_subdir/)
- test_*.py files go to tests/utilities/ or tests/vision_regression/ or tests/integration/
- Never leave test files in root directory

### DEBUG/ANALYSIS FILES (→ archive/experimental/)
- debug_*.py, analyze_*.py, improved_*.py files
- Experimental implementations
- Development analysis scripts

## ENFORCEMENT RULES
1. **NEVER leave housekeeping docs in root or docs/ main directory**
2. **NEVER leave test files in root directory**
3. **ALWAYS check dependencies before moving Python files** (use comprehensive grep analysis)
4. **ALWAYS document moves as "UNTESTED" until validation complete**
5. **PRESERVE all core development documentation in proper locations**

# 🚨 MANDATORY PROJECT CONFIGURATION DIRECTIVE 🚨
## ZERO TOLERANCE FOR HARDCODED CONFIGURATION VALUES

**CRITICAL:** Read and enforce /docs/PROJECT_CONFIGURATION_DIRECTIVE.md

### CONFIGURATION RULES (NO EXCEPTIONS):
1. **NO HARDCODED CONFIGURATION VALUES IN CODE EVER!** - All config must be in llm_config.yaml
2. **NO HARDCODED FALLBACKS** - System must fail fast if config is missing
3. **NO CONSTANTS FILES** - config/llm_constants.py is ELIMINATED from project
4. **.env ONLY FOR SECRETS** - Email addresses, passwords, API keys, user IDs ONLY
5. **SINGLE CONFIG FILE** - config/llm_config.yaml is the ONLY source of truth

### ENFORCEMENT:
- REJECT any code with hardcoded config values
- REQUIRE configuration values be moved to llm_config.yaml
- VERIFY .env contains ONLY user secrets (no URLs, models, timeouts)
- ENFORCE fail-fast behavior when configuration is missing

**Before making ANY configuration changes, read /docs/PROJECT_CONFIGURATION_DIRECTIVE.md**

# 🧠 MANDATORY GENERALIZATION DIRECTIVE 🧠
## ZERO TOLERANCE FOR BAND-AID FIXES AND HARDCODED KNOWLEDGE

**CRITICAL PRINCIPLE:** When building intelligent systems (agents, debuggers, analyzers), NEVER hardcode specific-case handling. Instead, provide the LLM with context and let it reason.

### GENERALIZATION RULES (NO EXCEPTIONS):

1. **NO BAND-AID FIXES FOR SPECIFIC CASES**
   - ❌ WRONG: Hardcoding a list of Python built-in modules
   - ✅ RIGHT: LLM asks "check if module X is built-in" → system runs `python -c "import sys; print('X' in sys.stdlib_module_names)"`
   - ❌ WRONG: Pattern-matching specific error types to specific handlers
   - ✅ RIGHT: LLM analyzes ANY error and requests what it needs to diagnose

2. **LLM ASKS FOR WHAT IT NEEDS**
   - When the LLM doesn't know something, it should REQUEST information
   - System provides diagnostic capabilities: run commands, read files, search, etc.
   - LLM reasons from gathered evidence, not from hardcoded knowledge

3. **ITERATIVE DIAGNOSIS OVER SINGLE-SHOT FIXES**
   - First ask: "What information do you need to diagnose this?"
   - Execute diagnostic requests
   - Feed results back
   - Repeat until LLM has enough context to fix

4. **DYNAMIC DISCOVERY OVER STATIC LISTS**
   - ❌ WRONG: `BUILTIN_MODULES = ["os", "sys", "json", ...]`
   - ✅ RIGHT: `check_module("os")` → runs actual Python check
   - ❌ WRONG: `if error_type == "ImportError": do_import_fix()`
   - ✅ RIGHT: LLM sees error, requests file contents, proposes fix

5. **CONTEXT + PROMPT > HARDCODED LOGIC**
   - Provide rich context (files, symbols, project structure, error traces)
   - Let LLM reason about the problem
   - Trust the LLM to figure out edge cases you didn't anticipate

### ENFORCEMENT:
- REJECT any code that handles specific cases with hardcoded logic
- REQUIRE diagnostic/discovery mechanisms instead of static knowledge
- VERIFY that LLM-driven components can request information dynamically
- TEST with novel error types to ensure generalization works

### THE GENERALIZATION TEST:
Ask yourself: "If a completely new error type appears that I never anticipated, will this code handle it?"
- If NO → You're doing pattern-matching, refactor to generalization
- If YES → You're letting the LLM reason, good job

# 🎯 MANDATORY REQUEST INTERPRETATION DIRECTIVE 🎯
## LLM INTERPRETS USER INTENT - NOT THE USER

**CRITICAL PRINCIPLE:** RAICA must NEVER require users to categorize their request (debug/fix/enhance/create). The LLM interprets intent from context + prompt.

### THE PROBLEM (What NOT to do):
```
❌ WRONG: User must prefix with "Fix ...", "Debug ...", "Enhance ...", "Create ..."
❌ WRONG: Different code paths based on user's command choice
❌ WRONG: Forcing user to decide if "Pi key shows undefined" is a bug or missing feature
```

### THE SOLUTION (What TO do):

**STEP 1: Gather Project Context**
- Go to project directory (specified or current)
- Build/load full context: files, structure, docs, logs, symbols, directives
- If no project exists, that's context too (implies "create new")

**STEP 2: LLM Interprets Request**
System prompt to LLM:
```
Based on the provided project context (or lack of it), analyze this user request
and determine the most likely intention:

User request: "{user_prompt}"

1. What is the user trying to accomplish?
2. Based on the project context, is this:
   - A FIX? (something exists but is broken)
   - An ENHANCEMENT? (something exists, user wants it improved/extended)
   - A NEW FEATURE? (something doesn't exist, user wants it added)
   - A NEW PROJECT? (no project exists or user wants fresh start)
3. What specific information do you need to proceed?

Respond with your interpretation and information requests.
```

**STEP 3: Iterative Context Gathering**
- LLM requests what it needs (read files, run commands, search, etc.)
- System executes requests
- LLM refines understanding
- Repeat until LLM has enough context to proceed

**STEP 4: Execute with Confirmed Intent**
- LLM proceeds with the interpreted intent
- No rigid "debug mode" vs "enhance mode" - just intelligent action

### EXAMPLE:
User prompt: "The Pi and e keys on the keypad produce undefined values, make them generate their actual values"

**WITHOUT Context:**
- Could be fix OR enhancement - ambiguous

**WITH Context (LLM reads keypad.py):**
```python
# Found in keypad.py:
KEYS = {"Pi": None, "e": None, "sqrt": math.sqrt}  # Pi and e are None!
```
LLM interpretation: "This is a FIX. The keys exist but have None values instead of math.pi and math.e. I need to update keypad.py lines 5-6."

**OR WITH Different Context:**
```python
# Found in keypad.py:
KEYS = {"sqrt": math.sqrt, "sin": math.sin}  # No Pi or e keys!
```
LLM interpretation: "This is an ENHANCEMENT. The user wants to ADD new keys for Pi and e. I need to add entries to the KEYS dict."

### ENFORCEMENT:
- REJECT any code that requires user to categorize request type
- REQUIRE LLM interpretation step before any action
- VERIFY that identical prompts can result in different actions based on context
- TEST with ambiguous requests to ensure LLM interprets correctly

### THE INTERPRETATION TEST:
Ask yourself: "Does this code path change based on magic keywords in user's prompt?"
- If YES → You're forcing user categorization, refactor
- If NO → You're letting LLM interpret from context, good job

- WHEN PROMPTED TO INVESTIGATE A BUG/PROBLEM ALWAYS START BY REVIEWING THE LOGS AND COMPARING IT TO THE EXPECTED SERVER BEHAVIOUR ACCORDING THE ARCHITECURE AND DESIGN
- NEVER ASSUMES THE FIX WORKS UNLESS THE HUMAN USER TELLS YOU IT DOES
- ALWAYS FOLLOW THE DOCUMENTED PROJECT DIRECTORY ORGANIZATION WHEN CREATING AND MOVING FILES
- ALWAYS TEST YOUR FIX THROUGH PROMPTS TO THE SERVER FROM END-TO-END
- ALWAYS FOLLOW THE RULE OF ALL RULES AND NEVER FORGET IT: Read and understand CLAUDE.md FULLY. Second, I want you to read ALL the architecture, design, and development documentations in /docs very carefully and learn about ALL ASPECTS OF ARCHITECTURE AND DESIGN OF THE SERVER BEFORE ATTAMPTING TO ANSWER ANY QUESTION. IT IS PROHIBITED TO MAKE ANY CODE CHANGES IF YOU HAVE NOT 'RECENTLY' READ AND UNDERSTOOD THE ARCHITECTURE AND DESIGN
- DO NOT MAKE ASSUMPTIONS AND BASE ANYTHING ON THEM WITHOUT INVESTIGATING AND TESTING THEM FIRST
- WHEN INDOUBT, ALWAYS EXPLAIN THE ISSUE AND ASK GUIDANCE FROM HUMAN USER
- BEFORE WRITING A NEW UTILITY FUNCTION, SEARCH THE CODEBASE IF THERE IS A WORKING FUNCTION ALREADY WRITTEN TO DO THE SAME WORK. ALWAYS, REUSED EXITING CODE AND IMPROVE IT
- KEEP INVESTIGATING THE ROOT CAUSE OF A BUG/ISSUE UNTIL YOU HAVE NEAR ~100% OF THE CORRECT AND FULL ROOT CAUSE THEN REPORT IT TO USER
- NEVER ATTEMPT A CODE FIX UNTIL (1) YOU HAVE SATISFIED THE REQUIREMENTS OF INVESTIGATING THE ROOT CAUSE (2) YOU HAVE PLANNED/ANALYZED/RESEARCH/EXPERIMENTED WITH AND VERIFIED THAT THE FIX WILL WORK WITH HIGH CONFIDENCE (NEAR ~100%)
- CHECKPOINT PROTOCOL: FOLLOW A STRICT PLAN TO STAGE AND COMMIT FILES TO REPO: review all the code change in this current project diectory and list all changed files tracked and untracked. Examine all current documentations for requiring updates/correction and update them as result of changes (README.md, ./docs/production, other files in ./docs etc). Ensure the directory organization is strictly followed. Ensure security issues are resolved 100% (no passwords/keys/credintials etc). Update the version numbers to be consistant across ALL files and gitbuh README.md, as well as the 'About' box version number on github site. **MANDATORY: Create version-specific changelog at docs/housekeeping/status-tracking/CHANGELOG_vX.X.X.XX.md documenting all changes, new features, fixes, dependencies, breaking changes, and migration guide.** Add core/required files (tracked and new if required only) and stage them for check-in. Ensure the dependencies (./requirements.txt) is uptodate for any new imports. Commit and Push changes.
- DEPLOYMENT PROTOCOL: FOLLOW A STRICT SEQUENTIAL WORKFLOW FOR TESTING AND PRODUCING RELEASES:
  1. Commit the code fixes or upgrades locally.
  2. Apply the changes to the local development server.
  3. Restart the local server (`./stop_complete.sh && sleep 10 && ./start_complete.sh` or local foreground runner).
  4. Verify local health status (`/health` endpoint on localhost:5000).
  5. Review local startup logs (`logs/server_complete.log`) for any warnings or errors.
  6. Run regression tests and E2E verification locally (`pytest` + `run_mu_e2e_verify.py`).
  7. Once fully clean and problem-free, push the changes to GitHub.
  8. Deploy to the live remote server (`sabawi.net`) by pulling the repository changes.
  9. Restart the remote production server.
  10. Verify remote health status (`/health` on remote host).
  11. Review remote startup logs carefully to ensure no runtime warnings or errors.
  12. Ensure both local and remote environments are byte-identical and running exactly as expected.
- NO FULL CONTENT OF BINARY FILE SHOULD BE DUMPED IN THE LOGS. ONLY FIRST 100 BYTES e.g."/HmfPngUAfPjhh1i6dGmx/Rw+fBiTJk1Cu3bt0KBBA9So ..."