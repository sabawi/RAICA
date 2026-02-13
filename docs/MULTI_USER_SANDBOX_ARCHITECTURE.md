# Multi-User Sandbox Architecture Analysis

**Date:** 2026-02-07
**Issue:** Where should sandbox_workspace be located in multi-user scenarios?

---

## Current Implementation

**Code:** `sandboxed_executor.py` line 118
```python
self.base_dir = Path(base_dir_config) if base_dir_config else Path.home()
```

**Config:** `config/llm_config.yaml`
```yaml
user_tools:
  sandboxed_executor:
    base_directory: null  # null = user's home directory
```

**Result:** `Path.home() / "sandbox_workspace"` = `/home/{username}/sandbox_workspace/`

---

## Scenario Analysis

### Scenario 1: Single User Running Server (CURRENT)

**Setup:**
- User `sabawi` runs server: `./start_complete.sh`
- Server process runs as user `sabawi`
- `Path.home()` returns `/home/sabawi`

**Sandbox location:** `/home/sabawi/sandbox_workspace/`

**Behavior:**
- ✅ All files accessible (same user)
- ✅ No permission issues
- ✅ Simple and predictable

**Verdict:** WORKS PERFECTLY ✅

---

### Scenario 2: Multiple Users, Each Running Their Own Server Instance

**Setup:**
- User `alice` runs: `./start_complete.sh` (port 5000)
- User `bob` runs: `./start_complete.sh` (port 5001)
- Each server runs as the respective user

**Sandbox locations:**
- Alice: `/home/alice/sandbox_workspace/`
- Bob: `/home/bob/sandbox_workspace/`

**Behavior:**
- ✅ Complete isolation (each user has own sandbox)
- ✅ No permission conflicts
- ✅ Files owned by correct user
- ✅ Privacy preserved

**Verdict:** WORKS PERFECTLY ✅

---

### Scenario 3: System-Wide Server (Single Process, Multiple Users)

**Setup:**
- Server runs as system user (e.g., `raica-server` or `www-data`)
- Multiple users (alice, bob) make requests to same server instance
- Server runs from `/opt/raica/` or similar

**Current behavior:**
```python
Path.home()  # Returns home of SERVER process user (e.g., /home/raica-server)
```

**Sandbox location:** `/home/raica-server/sandbox_workspace/`

**Problems:**
- ❌ All users share same sandbox (NO ISOLATION!)
- ❌ User A can see User B's files
- ❌ File conflicts (both users creating "report.html")
- ❌ Security issue (shared workspace)

**Verdict:** BROKEN - NEEDS FIX ❌

---

## Multi-User Architecture Options

### Option 1: Per-User Sandboxes (RECOMMENDED)

**Implementation:**
```python
# In sandboxed_executor.py, determine calling user
def _get_user_sandbox_path(self):
    """Get sandbox path for the calling user."""
    # Try to get actual user (not process user)
    import os

    # Option A: From environment (if set by auth system)
    user = os.getenv('RAICA_USER') or os.getenv('REMOTE_USER')

    # Option B: From request context (passed by API)
    # user = self.context.get('authenticated_user')

    # Option C: Fallback to process user
    if not user:
        user = os.getenv('USER')

    # Create per-user sandbox
    if self.base_dir is None:
        # System-wide: /var/raica/workspaces/{user}/
        return Path('/var/raica/workspaces') / user / 'sandbox_workspace'
    else:
        # User home: /home/{user}/sandbox_workspace/
        return Path.home() / 'sandbox_workspace'
```

**Pros:**
- ✅ Complete user isolation
- ✅ Each user has private workspace
- ✅ No file conflicts
- ✅ Proper security

**Cons:**
- ⚠️ Requires authentication/user identification
- ⚠️ More complex setup

---

### Option 2: Shared Sandbox with User Subdirectories

**Implementation:**
```python
# Shared base, per-user subdirs
sandbox_base = Path('/var/raica/shared_workspace')
user_sandbox = sandbox_base / f"user_{user_id}" / 'sandbox_workspace'
```

**Directory structure:**
```
/var/raica/shared_workspace/
├── user_alice/
│   └── sandbox_workspace/
│       └── report.html
├── user_bob/
│   └── sandbox_workspace/
│       └── analysis.pdf
└── user_charlie/
    └── sandbox_workspace/
        └── chart.png
```

**Pros:**
- ✅ User isolation
- ✅ Centralized management
- ✅ Easy backups (one location)

**Cons:**
- ⚠️ Requires user identification
- ⚠️ Needs careful permission management

---

### Option 3: Session-Based Sandboxes (TEMP)

**Implementation:**
```python
# Temporary per-session sandboxes
import tempfile
session_id = generate_session_id()  # From API request
sandbox_path = Path(tempfile.gettempdir()) / f"raica_session_{session_id}"
```

**Pros:**
- ✅ No user tracking needed
- ✅ Automatic cleanup
- ✅ Complete isolation

**Cons:**
- ❌ Files lost after session ends
- ❌ Can't reference files across requests
- ❌ Poor for persistent workflows

---

## Current Production Deployment Pattern

Based on your system:
- **Server runs as:** User `sabawi` (process owner)
- **Accessed by:** Same user `sabawi` (via CLI, Open-WebUI)
- **Pattern:** Single-user development/personal use

**Current architecture is CORRECT for this use case!**

---

## Recommendations

### For Current Setup (Single User - KEEP AS IS)

**No changes needed:**
```yaml
# config/llm_config.yaml
user_tools:
  sandboxed_executor:
    base_directory: null  # Uses /home/sabawi/sandbox_workspace/
```

**Behavior:**
- User `sabawi` runs server → sandbox at `/home/sabawi/sandbox_workspace/` ✅
- All tools use `Path.home() / "sandbox_workspace"` ✅
- Simple, predictable, works

### For Multi-User System-Wide Server (FUTURE)

**If deploying as system service for multiple users:**

1. **Add user identification:**
   ```python
   # In fastapi_server_complete.py
   # Add authentication middleware to identify calling user
   # Store user in request context
   ```

2. **Update sandbox path logic:**
   ```python
   # In sandboxed_executor.py
   def _get_sandbox_path(self, user_id: str):
       if self.multi_user_mode:
           # Per-user sandboxes
           return Path('/var/raica/workspaces') / user_id / 'sandbox_workspace'
       else:
           # Single-user mode (current)
           return Path.home() / 'sandbox_workspace'
   ```

3. **Update config:**
   ```yaml
   user_tools:
     sandboxed_executor:
       multi_user_mode: true  # Enable multi-user isolation
       workspaces_base: "/var/raica/workspaces"  # System-wide location
   ```

---

## Decision Matrix

| Use Case | Recommended Setup | Sandbox Location |
|----------|------------------|------------------|
| **Personal use (1 user)** | Current (Path.home()) | `/home/username/sandbox_workspace/` |
| **Multi-user dev (separate servers)** | Current (Path.home()) | `/home/user1/sandbox_workspace/`, `/home/user2/...` |
| **System-wide server (shared)** | Per-user subdirs | `/var/raica/workspaces/user1/sandbox_workspace/` |
| **API service (anonymous)** | Session-based temp | `/tmp/raica_session_xyz/` |

---

## Immediate Action for Current System

### 1. Keep Current Architecture ✅
**Reason:** Single user (`sabawi`), works perfectly

### 2. Remove Orphaned RAICA Sandbox
**Safe:** `/home/sabawi/Development/RAICA/sandbox_workspace/` is unused after fix

```bash
# Add to .gitignore
echo "sandbox_workspace/" >> /home/sabawi/Development/RAICA/.gitignore

# Remove orphaned sandbox
rm -rf /home/sabawi/Development/RAICA/sandbox_workspace/
```

### 3. Document Multi-User Path (Future)
**If/when deploying for multiple users:** Follow "Multi-User System-Wide Server" section above

---

## Summary

**Current implementation (`Path.home()`) is CORRECT for:**
- ✅ Single-user personal use (your case)
- ✅ Multi-user with separate server instances
- ✅ Development environments

**Would need changes for:**
- ❌ System-wide shared server with multiple authenticated users
- ❌ Multi-tenant SaaS deployment

**For your current setup: NO CHANGES NEEDED except cleanup of orphaned sandbox.**
