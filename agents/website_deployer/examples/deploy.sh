#!/bin/bash
# Deployment wrapper script that ensures virtual environment is activated
# Usage: ./deploy.sh --auto-input auto_deploy_simple_php.json

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
VENV_PATH="$PROJECT_ROOT/venv"

# Check if virtual environment exists
if [ ! -d "$VENV_PATH" ]; then
    echo "❌ Virtual environment not found at: $VENV_PATH"
    echo ""
    echo "Please create it first:"
    echo "  cd $PROJECT_ROOT"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r agents/website_deployer/requirements.txt"
    exit 1
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source "$VENV_PATH/bin/activate"

# Check if required packages are installed
python3 -c "import google.generativeai" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Required packages not installed in venv"
    echo ""
    echo "Installing packages..."
    cd "$SCRIPT_DIR/.."
    pip install -r requirements.txt
fi

# Run the deployment script with all arguments passed through
echo "🚀 Starting deployment..."
echo ""
python3 "$SCRIPT_DIR/zero_shot_deployment.py" "$@"
