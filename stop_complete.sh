#!/bin/bash

# Stop FastAPI complete server
cd "$(dirname "$0")"

# ── DEFER TO SYSTEMD ────────────────────────────────────────────────────────
# When raica.service owns this server, a hand-run script must NOT fight it:
# stopping by PID would just be undone by `Restart=always` five seconds later,
# and starting by hand would race systemd for port 5000. Hand control to
# systemctl and exit. (Guards that disagree with each other were how the NewX
# systemd rollout produced two 503 outages on 2026-08-27.)
if command -v systemctl >/dev/null 2>&1 && \
   systemctl list-unit-files raica.service --no-pager 2>/dev/null | grep -q "^raica.service"; then
    echo "ℹ️  raica.service is installed — this server is managed by systemd."
    echo "    stop it with:   sudo systemctl stop raica"
    echo "    status:  systemctl status raica    |    logs: tail -f logs/server_complete.log"
    exit 0
fi

# Check if PID file exists
if [ ! -f "runtime/server_complete.pid" ]; then
    echo "❌ No PID file found (runtime/server_complete.pid)"
    echo "Checking for running processes..."
    
    # Try to find and kill any running server processes
    PIDS=$(pgrep -f "python3 fastapi_server_complete.py")
    if [ ! -z "$PIDS" ]; then
        echo "🔍 Found running server processes: $PIDS"
        echo "🛑 Stopping servers..."
        kill $PIDS
        sleep 2
        
        # Check if any are still running
        STILL_RUNNING=$(pgrep -f "python3 fastapi_server_complete.py")
        if [ ! -z "$STILL_RUNNING" ]; then
            echo "⚠️  Some processes still running, force killing..."
            kill -9 $STILL_RUNNING
        fi
        echo "✅ Server processes stopped"
    else
        echo "ℹ️  No server processes found running"
    fi
    exit 0
fi

# Read PID from file
SERVER_PID=$(cat runtime/server_complete.pid)

echo "🛑 Stopping FastAPI Complete Server (PID: $SERVER_PID)..."

# Check if process is running
if ps -p $SERVER_PID > /dev/null; then
    # Try graceful shutdown first
    kill $SERVER_PID
    
    # Wait a few seconds
    sleep 3
    
    # Check if still running
    if ps -p $SERVER_PID > /dev/null; then
        echo "⚠️  Process still running, force killing..."
        kill -9 $SERVER_PID
        sleep 1
    fi
    
    # Final check
    if ps -p $SERVER_PID > /dev/null; then
        echo "❌ Failed to stop server"
        exit 1
    else
        echo "✅ Server stopped successfully"
    fi
else
    echo "ℹ️  Server was not running"
fi

# Clean up PID file
rm -f runtime/server_complete.pid

echo "🧹 Cleanup complete"