# Sandboxed Executor Configuration Guide
**Version:** 2.0 - Fully Configurable
**Date:** February 5, 2026
**Compliance:** PROJECT_CONFIGURATION_DIRECTIVE.md

---

## Overview

The Sandboxed Executor tool has been upgraded from hardcoded limitations to **full configuration-based control**. All security settings, command access, and filesystem restrictions are now defined in `config/llm_config.yaml`.

---

## Key Changes from v1.0

| Aspect | v1.0 (Old) | v2.0 (New) |
|--------|------------|------------|
| **Configuration** | Hardcoded in code | Loaded from llm_config.yaml |
| **Command Access** | Fixed whitelist/blacklist | 3 modes: strict/permissive/unrestricted |
| **Sudo Access** | Always blocked | Configurable with approval |
| **Filesystem Access** | Sandbox directory only | User home + configurable paths |
| **Limits** | Fixed (30s, 10MB, 50k chars) | Configurable (120s, 50MB, 100k chars default) |
| **Path Restrictions** | Hardcoded | Configurable lists |

---

## Configuration Location

**File:** `config/llm_config.yaml`
**Section:** `user_tools.sandboxed_executor`

---

## Quick Start Examples

### Example 1: Maximum Security (Strict Mode)

```yaml
user_tools:
  sandboxed_executor:
    command_mode: "strict"  # Only whitelisted commands
    sudo_access:
      enabled: false  # No sudo at all
```

**Result:** Only explicitly allowed commands can run, no sudo access.

---

### Example 2: Developer Mode (Permissive)

```yaml
user_tools:
  sandboxed_executor:
    command_mode: "permissive"  # Most commands allowed
    sudo_access:
      enabled: true  # Sudo allowed
      require_approval: true  # Must approve sudo commands
```

**Result:** Most commands work, sudo available but requires confirmation.

---

### Example 3: Full Access (Unrestricted)

```yaml
user_tools:
  sandboxed_executor:
    command_mode: "unrestricted"  # All commands
    sudo_access:
      enabled: true
      require_approval: false  # Auto-approve sudo
```

**Result:** Full system access (use with caution!).

---

## Configuration Reference

### Command Access Modes

#### `command_mode: "strict"` (Most Secure)

- **Behavior:** Only commands in `allowed_commands` list can run
- **Use When:** Maximum security needed, limited functionality required
- **Commands:** ~63 whitelisted development/system tools
- **Sudo:** Separate configuration

**Example:**
```yaml
command_mode: "strict"
allowed_commands:
  - python3
  - node
  - git
  - ls
  # ... only these work
```

---

#### `command_mode: "permissive"` (Default, Recommended)

- **Behavior:** All commands work EXCEPT those in `blocked_commands`
- **Use When:** Normal development, need flexibility with safety
- **Commands:** Everything except ~13 dangerous commands
- **Sudo:** Separate configuration

**Example:**
```yaml
command_mode: "permissive"
blocked_commands:
  - mkfs  # Format filesystem
  - dd    # Disk destroyer
  - reboot
  # ... only these are blocked
```

---

#### `command_mode: "unrestricted"` (Use with Caution)

- **Behavior:** ALL commands allowed (only basic safety checks)
- **Use When:** Full control needed, trusted environment
- **Commands:** Everything
- **Sudo:** Separate configuration

**Warning:** This mode removes most safety guardrails!

---

### Sudo/Root Access Configuration

```yaml
sudo_access:
  enabled: true  # Allow sudo commands

  # Require user approval before running sudo
  require_approval: true

  # Only these commands can use sudo
  allowed_sudo_commands:
    - apt
    - apt-get
    - systemctl
    - service
    - docker
    - chown
    - chmod
    # ... package managers and system services

  # These are NEVER allowed with sudo
  blocked_sudo_commands:
    - rm        # Prevent sudo rm disasters
    - mkfs      # Prevent filesystem format
    - dd        # Prevent disk overwrites
    - fdisk     # Prevent partition changes
    - passwd    # Prevent password changes
    - reboot    # Prevent system reboot
```

**How It Works:**

1. User/LLM requests: `sudo apt update`
2. Tool checks: Is `sudo_access.enabled`? → Yes
3. Tool checks: Is `apt` in `allowed_sudo_commands`? → Yes
4. Tool checks: Is `apt` in `blocked_sudo_commands`? → No
5. Tool checks: Is `require_approval` true? → Yes
6. **Tool asks user:** "Allow sudo apt update?" → User approves
7. Command executes

---

### Filesystem Access Control

```yaml
filesystem:
  # Base directory (null = user's home directory)
  default_base: null  # /home/sabawi

  # Allow absolute paths outside base directory
  allow_absolute_paths: true

  # These paths are NEVER accessible
  restricted_paths:
    - /etc/shadow  # Password hashes
    - /etc/passwd  # User database
    - /root        # Root user home
    - /proc        # Process info
    - /sys         # System info
    - /dev         # Device files
    - /boot        # Boot files

  # Additional paths that ARE accessible
  allowed_paths:
    - /tmp
    - /var/tmp
    - /opt
    - /usr/local
```

**Path Validation Logic:**

```
1. Is path in restricted_paths? → BLOCK
2. Is path within base_dir (/home/sabawi)? → ALLOW
3. Is path in allowed_paths? → ALLOW
4. Is allow_absolute_paths=true? → ALLOW
5. Otherwise → BLOCK
```

**Examples:**

| Path | Result | Reason |
|------|--------|--------|
| `/home/sabawi/Documents/file.txt` | ✅ ALLOW | Within base_dir |
| `/tmp/test.txt` | ✅ ALLOW | In allowed_paths |
| `/etc/shadow` | ❌ BLOCK | In restricted_paths |
| `/opt/myapp/data` | ✅ ALLOW | In allowed_paths |
| `/root/secret` | ❌ BLOCK | In restricted_paths |
| `/usr/bin/python3` | ✅ ALLOW | absolute_paths enabled |

---

### Execution Limits

```yaml
execution:
  max_execution_time: 120  # seconds (2 minutes)
  max_output_size: 100000  # characters (100k chars)
  max_file_size: 52428800  # bytes (50MB)
```

**Recommendations:**

| Use Case | Timeout | Output Size | File Size |
|----------|---------|-------------|-----------|
| **Quick scripts** | 30s | 50k chars | 10MB |
| **Development (default)** | 120s | 100k chars | 50MB |
| **Build processes** | 600s | 500k chars | 500MB |
| **Data processing** | 1800s | 1M chars | 5GB |

---

## Complete Configuration Template

```yaml
# config/llm_config.yaml

user_tools:
  sandboxed_executor:
    # ==========================================
    # WORKSPACE SETTINGS
    # ==========================================
    base_directory: null  # null = user home, or "/path/to/custom"
    sandbox_workspace_name: "sandbox_workspace"

    # ==========================================
    # EXECUTION LIMITS
    # ==========================================
    execution:
      max_execution_time: 120  # seconds
      max_output_size: 100000  # characters
      max_file_size: 52428800  # bytes (50MB)

    # ==========================================
    # COMMAND ACCESS MODE
    # ==========================================
    # Options: "strict", "permissive", "unrestricted"
    command_mode: "permissive"

    # ==========================================
    # ALLOWED COMMANDS (for strict mode)
    # ==========================================
    allowed_commands:
      # Development
      - python3
      - python
      - node
      - npm
      - pip
      - pip3

      # Compilers
      - gcc
      - g++
      - java
      - javac
      - rustc
      - cargo
      - go

      # System utilities
      - ls
      - cat
      - grep
      - find
      - echo
      - pwd
      - chmod
      - mkdir
      - cp
      - mv
      - rm

      # Version control
      - git
      - svn

      # Archives
      - tar
      - gzip
      - zip
      - unzip

      # Network
      - curl
      - wget

    # ==========================================
    # BLOCKED COMMANDS (always blocked)
    # ==========================================
    blocked_commands:
      - mkfs
      - dd
      - reboot
      - shutdown
      - halt
      - "rm -rf /"

    # ==========================================
    # SUDO CONFIGURATION
    # ==========================================
    sudo_access:
      enabled: true
      require_approval: true

      allowed_sudo_commands:
        - apt
        - apt-get
        - systemctl
        - service
        - docker
        - chown
        - chmod
        - mount
        - umount

      blocked_sudo_commands:
        - rm
        - mkfs
        - dd
        - fdisk
        - passwd
        - reboot
        - shutdown

    # ==========================================
    # FILESYSTEM ACCESS
    # ==========================================
    filesystem:
      default_base: null  # null = home directory
      allow_absolute_paths: true

      restricted_paths:
        - /etc/shadow
        - /etc/passwd
        - /root
        - /proc
        - /sys
        - /dev
        - /boot

      allowed_paths:
        - /tmp
        - /var/tmp
        - /opt
        - /usr/local
```

---

## Security Best Practices

### 1. Start Restrictive, Relax as Needed

```yaml
# Start with this
command_mode: "strict"
sudo_access:
  enabled: false

# Then gradually enable:
# 1. command_mode: "permissive"
# 2. sudo_access.enabled: true (with approval)
# 3. sudo_access.require_approval: false (if trusted)
```

---

### 2. Never Disable These Blocks

**Always keep blocked:**
```yaml
blocked_commands:
  - mkfs        # Filesystem format
  - dd          # Disk operations

blocked_sudo_commands:
  - rm          # Prevent sudo rm disasters
  - mkfs
  - fdisk
  - passwd
```

---

### 3. Use Approval for Sudo

```yaml
sudo_access:
  enabled: true
  require_approval: true  # ALWAYS use this initially
```

Only disable `require_approval` when you fully trust the environment.

---

### 4. Restrict Sensitive Paths

```yaml
filesystem:
  restricted_paths:
    - /etc/shadow      # Password hashes
    - /etc/passwd      # User database
    - /root            # Root home
    - /home/otheruser  # Other users' files
```

---

## Testing Your Configuration

### Test 1: Verify Configuration Loads

```bash
python3 -c "
import sys
sys.path.insert(0, 'user_tools')
from sandboxed_executor import SandboxedExecutorTool
tool = SandboxedExecutorTool()
print(f'Mode: {tool.command_mode}')
print(f'Sudo: {tool.sudo_enabled}')
print(f'Base: {tool.base_dir}')
"
```

---

### Test 2: Test Command Validation

```bash
python3 << 'EOF'
import sys
sys.path.insert(0, 'user_tools')
from sandboxed_executor import SandboxedExecutorTool

tool = SandboxedExecutorTool()
commands = ["ls", "sudo apt update", "mkfs", "rm -rf /"]
for cmd in commands:
    ok, msg = tool._validate_command(cmd)
    print(f"{'✅' if ok else '❌'} {cmd}: {msg}")
EOF
```

---

### Test 3: Check Sandbox README

```bash
cat ~/sandbox_workspace/README.md
```

Should show your current configuration.

---

## Troubleshooting

### Issue: "Configuration missing" error

**Problem:** `user_tools.sandboxed_executor` not found in llm_config.yaml

**Solution:**
1. Check `config/llm_config.yaml` has the section
2. Verify YAML syntax (no tabs, proper indentation)
3. Restart server

---

### Issue: Command blocked unexpectedly

**Problem:** Command should work but is blocked

**Check:**
1. What is `command_mode`? (strict requires whitelist)
2. Is command in `blocked_commands`?
3. Is it a sudo command without sudo config?
4. Check logs for exact block reason

**Debug:**
```python
tool._validate_command("your_command_here")
```

---

### Issue: Sudo not working

**Problem:** `sudo` commands fail

**Check:**
1. Is `sudo_access.enabled: true`?
2. Is command in `allowed_sudo_commands`?
3. Is command in `blocked_sudo_commands`?
4. Does user have sudo rights in OS?

---

### Issue: Path access denied

**Problem:** Can't access a file/directory

**Check:**
1. Is path in `restricted_paths`?
2. Is path outside `base_dir` AND not in `allowed_paths`?
3. Is `allow_absolute_paths: false`?

**Debug:**
```python
tool._validate_path("/your/path/here")
```

---

## Migration from v1.0

### Old Code (Hardcoded)
```python
# v1.0 - hardcoded
self.max_execution_time = 30
self.allowed_commands = {'python3', 'ls', ...}
self.blocked_commands = {'sudo', 'mkfs', ...}
```

### New Code (Configured)
```python
# v2.0 - loaded from config
self.max_execution_time = exec_config.get('max_execution_time', 120)
self.allowed_commands = set(self.config.get('allowed_commands', []))
self.command_mode = self.config.get('command_mode', 'permissive')
```

**No code changes needed** - just update `llm_config.yaml`!

---

## Examples

### Example 1: Data Science Environment

```yaml
command_mode: "permissive"
execution:
  max_execution_time: 600  # 10 minutes for training
  max_file_size: 524288000  # 500MB for datasets
sudo_access:
  enabled: false  # No sudo needed
```

---

### Example 2: DevOps/System Admin

```yaml
command_mode: "permissive"
sudo_access:
  enabled: true
  require_approval: true
  allowed_sudo_commands:
    - systemctl
    - docker
    - nginx
    - apache2
    - ufw
    - iptables
```

---

### Example 3: Restricted Student Environment

```yaml
command_mode: "strict"
allowed_commands:
  - python3
  - gcc
  - java
  - javac
  - ls
  - cat
  - mkdir
  - rm
sudo_access:
  enabled: false
filesystem:
  allow_absolute_paths: false
```

---

## API Reference

### Tool Initialization

```python
from sandboxed_executor import SandboxedExecutorTool

tool = SandboxedExecutorTool()
# Automatically loads config from llm_config.yaml
```

### Configuration Access

```python
tool.command_mode           # "strict" | "permissive" | "unrestricted"
tool.sudo_enabled           # True | False
tool.base_dir               # Path object
tool.max_execution_time     # int (seconds)
tool.allowed_commands       # set[str]
tool.blocked_commands       # set[str]
```

### Validation Methods

```python
# Validate command
is_valid, message = tool._validate_command("sudo apt update")

# Validate path
is_valid, abs_path = tool._validate_path("/home/user/file.txt")
```

---

## Support

For issues or questions:
1. Check configuration in `config/llm_config.yaml`
2. Test with examples above
3. Check logs for detailed error messages
4. Review PROJECT_CONFIGURATION_DIRECTIVE.md for config standards

---

**END OF CONFIGURATION GUIDE**
