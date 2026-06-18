#!/bin/bash
# Idempotently wire the RAICA benchmark Tier-0 trigger into .git/hooks/pre-commit, AFTER the existing
# CLAUDE.md compliance check (it does not replace it). Safe to re-run. The trigger LOGIC lives in
# tools/benchmark_precommit.sh (version-controlled); only the one-line call is added to the local hook.
#
# Run after a fresh clone:  bash tools/install_git_hooks.sh
set -eu

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$PROJECT_ROOT/.git/hooks/pre-commit"
MARKER="tools/benchmark_precommit.sh"

mkdir -p "$PROJECT_ROOT/.git/hooks"

# Create a minimal hook if none exists yet.
if [ ! -f "$HOOK" ]; then
    cat > "$HOOK" <<'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
exit 0
EOF
    chmod +x "$HOOK"
fi

if grep -q "$MARKER" "$HOOK"; then
    echo "✅ benchmark pre-commit trigger already installed."
    exit 0
fi

# Insert the trigger call just before the final `exit 0` (after the CLAUDE.md check).
python3 - "$HOOK" <<'PY'
import sys
hook = sys.argv[1]
lines = open(hook).read().rstrip("\n").split("\n")
block = [
    "",
    "# >>> RAICA benchmark trigger (Tier-0 gate on CORE workflow changes) — tools/benchmark_precommit.sh >>>",
    '"$PROJECT_ROOT/tools/benchmark_precommit.sh" || exit 1',
    "# <<< RAICA benchmark trigger <<<",
    "",
]
for i in range(len(lines) - 1, -1, -1):
    if lines[i].strip() == "exit 0":
        lines[i:i] = block
        break
else:
    lines += block + ["exit 0"]
open(hook, "w").write("\n".join(lines) + "\n")
PY

chmod +x "$HOOK"
echo "✅ benchmark pre-commit trigger installed into .git/hooks/pre-commit"
