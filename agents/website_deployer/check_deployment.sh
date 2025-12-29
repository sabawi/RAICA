#!/bin/bash
# Deployment Status Check Script

echo "========================================="
echo "DEPLOYMENT STATUS CHECK"
echo "========================================="
echo ""

PROJECT="LLM_Chat_and_Agent_Orchestration_Platform"

echo "1. Application Files:"
echo "-------------------"
if [ -d "/var/www/$PROJECT" ]; then
    echo "✅ Project directory exists"
    ls -la "/var/www/$PROJECT" | head -20
else
    echo "❌ Project directory NOT found"
fi
echo ""

echo "2. FastAPI Main File:"
echo "-------------------"
if [ -f "/var/www/$PROJECT/main.py" ]; then
    echo "✅ main.py found"
elif [ -f "/var/www/$PROJECT/app/main.py" ]; then
    echo "✅ app/main.py found"
else
    echo "⚠️  Main file not found in expected locations"
    find "/var/www/$PROJECT" -name "main.py" -o -name "app.py" 2>/dev/null
fi
echo ""

echo "3. Systemd Service:"
echo "-------------------"
if systemctl is-active --quiet "$PROJECT"; then
    echo "✅ Service is running"
    systemctl status "$PROJECT" --no-pager | head -15
else
    echo "❌ Service is NOT running"
    echo "Status:"
    systemctl status "$PROJECT" --no-pager | head -15
fi
echo ""

echo "4. Service Port (FastAPI):"
echo "-------------------"
if ss -tlnp | grep -q ':8000'; then
    echo "✅ FastAPI listening on port 8000"
    ss -tlnp | grep ':8000'
else
    echo "⚠️  Nothing listening on port 8000"
fi
echo ""

echo "5. Nginx Status:"
echo "-------------------"
if systemctl is-active --quiet nginx; then
    echo "✅ Nginx is running"
else
    echo "❌ Nginx is NOT running"
fi

echo ""
echo "6. Nginx Configuration:"
echo "-------------------"
if [ -f "/etc/nginx/sites-enabled/$PROJECT" ]; then
    echo "✅ Nginx config exists"
    echo "Config snippet:"
    head -20 "/etc/nginx/sites-enabled/$PROJECT"
elif [ -f "/etc/nginx/conf.d/$PROJECT.conf" ]; then
    echo "✅ Nginx config exists (conf.d)"
    echo "Config snippet:"
    head -20 "/etc/nginx/conf.d/$PROJECT.conf"
else
    echo "⚠️  Nginx config not found"
fi

echo ""
echo "7. Apache Status:"
echo "-------------------"
if systemctl is-active --quiet apache2; then
    echo "✅ Apache is running"
else
    echo "⚠️  Apache is not running (this is OK if using Nginx)"
fi

echo ""
echo "8. Test Application Response:"
echo "-------------------"
echo "Testing http://localhost:8000 ..."
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://localhost:8000 2>/dev/null || echo "❌ Cannot connect to FastAPI"

echo ""
echo "========================================="
