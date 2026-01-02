#!/bin/bash
#
# RAICA Setup Script
# ==================
# Sets up the 'raica' command to be available system-wide.
#
# Usage:
#   ./setup_raica.sh           # Standard setup
#   ./setup_raica.sh --symlink # Create symlink instead of wrapper
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAICA_SCRIPT="$SCRIPT_DIR/raica"
VENV_DIR="$SCRIPT_DIR/venv"
BIN_DIR="$HOME/.local/bin"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "RAICA Setup"
echo "==========="
echo ""

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}ERROR: Virtual environment not found at $VENV_DIR${NC}"
    echo "Please create a virtual environment first:"
    echo "  python3 -m venv $VENV_DIR"
    echo "  source $VENV_DIR/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Check if raica script exists
if [ ! -f "$RAICA_SCRIPT" ]; then
    echo -e "${RED}ERROR: raica script not found at $RAICA_SCRIPT${NC}"
    exit 1
fi

# Create ~/.local/bin if it doesn't exist
mkdir -p "$BIN_DIR"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "${YELLOW}NOTE: $BIN_DIR is not in your PATH${NC}"
    echo "Add this line to your ~/.bashrc or ~/.zshrc:"
    echo ""
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

# Create wrapper script that activates venv
WRAPPER_SCRIPT="$BIN_DIR/raica"

if [ "$1" = "--symlink" ]; then
    # Just create a symlink (requires user to activate venv manually)
    ln -sf "$RAICA_SCRIPT" "$WRAPPER_SCRIPT"
    echo -e "${GREEN}Created symlink: $WRAPPER_SCRIPT -> $RAICA_SCRIPT${NC}"
    echo ""
    echo "NOTE: You'll need to activate the venv before running raica:"
    echo "  source $VENV_DIR/bin/activate"
    echo "  raica"
else
    # Create wrapper script that auto-activates venv
    cat > "$WRAPPER_SCRIPT" << EOF
#!/bin/bash
# Auto-generated wrapper for RAICA
# This script activates the virtual environment and runs raica

RAICA_DIR="$SCRIPT_DIR"
VENV_DIR="$VENV_DIR"

# Activate virtual environment
source "\$VENV_DIR/bin/activate"

# Run raica with all arguments
exec "\$RAICA_DIR/raica" "\$@"
EOF
    chmod +x "$WRAPPER_SCRIPT"
    echo -e "${GREEN}Created wrapper script: $WRAPPER_SCRIPT${NC}"
fi

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Usage:"
echo "  raica                    # Launch interactive TUI"
echo "  raica -d ./my-project    # Work in specific directory"
echo "  raica --help             # Show all options"
echo ""
echo "If 'raica' command is not found, run:"
echo "  source ~/.bashrc"
echo "  # or"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
