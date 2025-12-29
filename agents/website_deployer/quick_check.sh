#!/bin/bash
# Quick deployment diagnostic - run this on the REMOTE server

echo "========================================="
echo "QUICK DEPLOYMENT DIAGNOSTIC"
echo "========================================="
echo ""

PROJECT="LLM_Chat_and_Agent_Orchestration_Platform"

echo "1. Is the application service running?"
echo "--------------------------------------"
sudo systemctl status $PROJECT --no-pager | head -10
echo ""

echo "2. What's listening on port 8000?"
echo "--------------------------------------"
ss -tlnp | grep :8000 || echo "Nothing listening on port 8000!"
echo ""

echo "3. Can we reach the app directly?"
echo "--------------------------------------"
curl -v http://localhost:8000 2>&1 | head -20
echo ""

echo "4. Is Nginx running?"
echo "--------------------------------------"
sudo systemctl status nginx --no-pager | head -5
echo ""

echo "5. Is Nginx listening on port 80?"
echo "--------------------------------------"
ss -tlnp | grep :80 || echo "Nothing listening on port 80!"
echo ""

echo "6. Nginx configuration test:"
echo "--------------------------------------"
sudo nginx -t
echo ""

echo "7. Check application logs:"
echo "--------------------------------------"
echo "Last 20 lines of application logs:"
sudo journalctl -u $PROJECT -n 20 --no-pager
echo ""

echo "8. Check Nginx error logs:"
echo "--------------------------------------"
echo "Last 10 lines of Nginx errors:"
sudo tail -10 /var/log/nginx/error.log 2>/dev/null || echo "No Nginx error log"
echo ""

echo "========================================="
echo "DIAGNOSTIC COMPLETE"
echo "========================================="
