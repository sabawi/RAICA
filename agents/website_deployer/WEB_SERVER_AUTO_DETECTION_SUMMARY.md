# Web Server Auto-Detection Feature

## Overview
The deployment system now automatically detects and uses the web server already installed on the target system (Apache2 or Nginx), respecting existing configurations like self-signed SSL certificates.

## What Changed

### 1. New Module: `web_server_detector.py`
**Location:** `stages/deployment_modules/web_server_detector.py`

**Features:**
- Detects Apache2 and Nginx installation status
- Checks which server is running, enabled, or installed
- Determines port 80 usage
- Provides intelligent recommendations based on priority:
  1. Currently running server
  2. Enabled server (auto-start)
  3. Installed server
  4. Default to Nginx if nothing found

**Detection Results Include:**
```python
{
    "server": "apache2",  # or "nginx"
    "apache2_installed": True,
    "apache2_running": True,
    "apache2_enabled": True,
    "apache2_version": "Apache/2.4.41",
    "nginx_installed": False,
    "nginx_running": False,
    "nginx_enabled": False,
    "nginx_version": None,
    "recommendation": "apache2",
    "port_80_used_by": "apache2"
}
```

### 2. New Module: `apache_configurator.py`
**Location:** `stages/deployment_modules/apache_configurator.py`

**Features:**
- Configures Apache2 as reverse proxy for FastAPI applications
- Enables required Apache modules: `proxy`, `proxy_http`, `rewrite`, `headers`
- WebSocket support
- Security headers (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection)
- Disables conflicting default site
- Tests configuration before restart

**Generated Configuration:**
```apache
<VirtualHost *:80>
    ServerName your-domain.com

    # Reverse proxy to FastAPI on port 8000
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    # WebSocket support
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{HTTP:Connection} upgrade [NC]
    RewriteRule ^/?(.*) "ws://127.0.0.1:8000/$1" [P,L]

    # Logging and security headers
    ErrorLog ${APACHE_LOG_DIR}/project_error.log
    CustomLog ${APACHE_LOG_DIR}/project_access.log combined
</VirtualHost>
```

### 3. Updated: `deployment_orchestrator.py`

**Changes:**

#### Step 0: Web Server Detection (NEW)
```python
# Detect web server early in deployment
from .deployment_modules import WebServerDetector
detector = WebServerDetector(self.ssh_manager)
web_server_info = detector.detect()
architecture["web_server"] = web_server_info["recommendation"]
logger.info(f"✅ Will use: {architecture['web_server'].upper()}")
```

#### Step 7: Dynamic Web Server Configuration
```python
# Use detected web server instead of hardcoded Nginx
web_server = architecture.get("web_server", "nginx")

if web_server == "apache2":
    from .deployment_modules import ApacheConfigurator
    web_config = ApacheConfigurator(self.ssh_manager)
else:
    from .deployment_modules import NginxConfigurator
    web_config = NginxConfigurator(self.ssh_manager)

web_result = web_config.configure(safe_project_name, domain, architecture)
```

#### Step 10: Smart Service Restart
```python
# Test and restart the appropriate web server
if web_server == "apache2":
    # Test with: sudo apache2ctl configtest
    # Restart with: sudo systemctl restart apache2
else:
    # Test with: sudo nginx -t
    # Restart with: sudo systemctl restart nginx
```

### 4. Updated: `deployment_modules/__init__.py`
Added exports for new modules:
- `ApacheConfigurator`
- `WebServerDetector`

## Benefits

### 1. **Respects Existing Infrastructure**
- No more forcing Nginx on Apache2 systems
- Preserves existing SSL certificates (self-signed or Let's Encrypt)
- Works with current system configurations

### 2. **Prevents Port Conflicts**
- Detects which server is using port 80
- Uses that server instead of trying to start a conflicting one
- Avoids "Address already in use" errors

### 3. **Intelligent Decision Making**
```
Priority Order:
1. Is Apache2 running? → Use Apache2
2. Is Nginx running? → Use Nginx
3. Is Apache2 enabled? → Use Apache2
4. Is Nginx enabled? → Use Nginx
5. Is Apache2 installed? → Use Apache2
6. Is Nginx installed? → Use Nginx
7. Nothing found? → Default to Nginx
```

### 4. **Comprehensive Logging**
```
=============================================================
WEB SERVER DETECTION RESULTS
=============================================================
Apache2: ✅ Installed
  - Running: ✅ Yes
  - Enabled: ✅ Yes
  - Version: Apache/2.4.41 (Ubuntu)

Nginx: ❌ Not installed

Port 80 Status: apache2
Recommendation: Use APACHE2
=============================================================
```

## Testing

### Import Test
```bash
python3 -c "from stages.deployment_modules import WebServerDetector, ApacheConfigurator"
```

### Manual Detection Test
```python
from ssh import SSHConnectionManager
from stages.deployment_modules import WebServerDetector

# Setup SSH connection
ssh_manager = SSHConnectionManager(credentials)
detector = WebServerDetector(ssh_manager)

# Run detection
result = detector.detect()
print(f"Recommended server: {result['recommendation']}")
```

## Backward Compatibility

The changes are **fully backward compatible**:
- Existing Nginx deployments continue to work
- Default behavior (no detection info) falls back to Nginx
- All original functionality preserved

## Future Enhancements

Possible improvements:
1. Support for other web servers (Caddy, Lighttpd)
2. Automatic migration from one server to another
3. SSL certificate migration between servers
4. Multi-domain support with SNI

## Related Files

- `stages/deployment_modules/web_server_detector.py` - Detection logic
- `stages/deployment_modules/apache_configurator.py` - Apache2 configuration
- `stages/deployment_modules/nginx_configurator.py` - Nginx configuration (existing)
- `stages/deployment_orchestrator.py` - Integration point
- `stages/deployment_modules/__init__.py` - Module exports

## User Impact

**Before:** Users with Apache2 systems would experience deployment failures with:
- `bind() to 0.0.0.0:80 failed (98: Address already in use)`
- Nginx unable to start
- Deployed applications unreachable

**After:** Deployment automatically:
- Detects Apache2 is running
- Configures Apache2 as reverse proxy
- Respects existing SSL configuration
- Application accessible immediately after deployment

## Success Criteria

✅ Web server detection implemented
✅ Apache2 configurator created
✅ Deployment orchestrator updated
✅ Imports tested successfully
✅ Backward compatibility maintained
⏳ End-to-end deployment test (pending user validation)

---

**Version:** 1.0.0
**Date:** 2025-11-24
**Status:** Ready for testing
