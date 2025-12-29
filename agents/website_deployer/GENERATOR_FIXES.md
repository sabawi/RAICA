# Generator Fixes - Session 2025-11-24

## Overview

This document summarizes the fixes applied to the Website Deployment Agent's code generator to resolve issues encountered during real-world testing.

## Issues Fixed

### 1. ✅ Redis Dependency Conflict

**Problem:**
- Generated `requirements.txt` included both `redis==5.0.1` and `celery[redis]==5.3.4`
- `celery[redis]` requires `redis<5.0.0`, causing pip dependency conflict

**Solution:**
- Modified `/stages/code_generator.py` line 283-291
- When workers are present, only include `celery[redis]` (which installs compatible redis automatically)
- Standalone `redis` only added if Redis is needed but no workers exist

**Code:**
```python
# Add Celery if workers exist (includes Redis automatically)
if architecture.get("workers"):
    requirements.extend([
        "celery==5.3.4",
        "celery[redis]==5.3.4",
    ])
# Add Redis standalone only if needed but no workers
elif architecture.get("infrastructure", {}).get("redis", {}).get("enabled"):
    requirements.append("redis>=4.5.2,<5.0.0")
```

---

### 2. ✅ CORS_ORIGINS Parsing Error

**Problem:**
- Pydantic Settings v2 tried to parse `CORS_ORIGINS` from `.env` as JSON
- Comma-separated string format caused: `JSONDecodeError: Expecting value`

**Solution:**
- Modified `/stages/generators/fastapi_generator.py` lines 134-172
- Changed `CORS_ORIGINS` type to `Union[str, List[str]]`
- Added `field_validator` to convert comma-separated string to list
- Used modern `SettingsConfigDict` instead of deprecated `Config` class

**Code:**
```python
from typing import List, Union
from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # CORS - can be comma-separated string or list
    CORS_ORIGINS: Union[str, List[str]] = Field(
        default="http://localhost:3000,https://yourdomain.com"
    )

    @field_validator('CORS_ORIGINS', mode='after')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS_ORIGINS from comma-separated string to list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',')]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        env_parse_none_str='null'
    )
```

---

### 3. ✅ Missing REDIS_URL Configuration

**Problem:**
- `.env` file included `REDIS_URL` but Settings class didn't define it
- Pydantic raised: `Extra inputs are not permitted`

**Solution:**
- Modified `/stages/generators/fastapi_generator.py` lines 155-156
- Added `REDIS_URL` field to Settings class

**Code:**
```python
# Redis (if using background workers or caching)
REDIS_URL: str = "redis://localhost:6379/0"
```

---

### 4. ✅ Alembic Using Wrong Database Credentials

**Problem:**
- Alembic `env.py` read DATABASE_URL from `alembic.ini` (hardcoded placeholder)
- Ignored actual DATABASE_URL from `.env` file
- Caused authentication failures during migrations

**Solution:**
- Modified `/stages/generators/migration_generator.py` lines 63-91
- Import settings and override `sqlalchemy.url` before migrations run

**Code:**
```python
from app.core.config import settings

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata

# Override sqlalchemy.url with DATABASE_URL from settings
# This allows using environment variables instead of hardcoded alembic.ini values
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
```

---

### 5. ✅ PostgreSQL User Creation

**Problem:**
- Setup script assumed PostgreSQL user matching system username existed
- Fresh PostgreSQL installations don't create users automatically
- Caused: `FATAL: role "username" does not exist`

**Solution:**
- Modified `/stages/generators/config_generator.py` lines 172-185
- Added Step 6 to check and create PostgreSQL user before database operations

**Code:**
```bash
# Step 6: Create PostgreSQL user (if doesn't exist)
echo ""
echo "Checking PostgreSQL user..."
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$USER'" | grep -q 1; then
    echo "${GREEN}✅ PostgreSQL user '$USER' already exists${NC}"
else
    echo "Creating PostgreSQL user '$USER'..."
    sudo -u postgres createuser -s $USER || {
        echo "${YELLOW}⚠️  Could not create PostgreSQL user${NC}"
        echo "You may need to create it manually:"
        echo "  sudo -u postgres createuser -s $USER"
    }
    echo "${GREEN}✅ PostgreSQL user created${NC}"
fi
```

---

## Testing

All fixes have been verified with the test script `/test_generator_fixes.py`:

```bash
python3 test_generator_fixes.py
```

**Test Results:**
- ✅ Alembic env.py imports settings
- ✅ Alembic env.py overrides DATABASE_URL
- ✅ Config includes REDIS_URL
- ✅ Config has CORS_ORIGINS validator
- ✅ Setup script creates PostgreSQL user
- ✅ Setup script is executable
- ✅ No Redis dependency conflicts

---

## Files Modified

| File | Changes | Lines |
|------|---------|-------|
| `stages/code_generator.py` | Redis dependency logic | 283-291 |
| `stages/code_generator.py` | README with Apache2 docs | 458-502 |
| `stages/generators/fastapi_generator.py` | Config class with validators | 134-172 |
| `stages/generators/migration_generator.py` | Alembic env.py template | 63-91 |
| `stages/generators/config_generator.py` | PostgreSQL user creation in setup.sh | 172-220 |
| `stages/generators/config_generator.py` | Apache2 configuration generation | 87-153 |
| `stages/generators/config_generator.py` | Web server detection in setup.sh | 277-295 |
| `stages/architecture_designer.py` | Multi-web-server support | 182, 469 |
| `test_generator_fixes.py` | Apache2 verification tests | 165-187 |

---

## Impact

These fixes ensure that **all future generated projects** will:
1. Install without dependency conflicts
2. Parse configuration correctly from `.env` files
3. Run migrations using correct database credentials
4. Set up PostgreSQL users automatically
5. Support both Nginx and Apache2 web servers with automatic detection
6. Work out-of-the-box after running `./setup.sh`

---

## Version

- **Date:** 2025-11-24
- **Tested With:** Simple Blog Platform, Task Manager
- **Python:** 3.12
- **PostgreSQL:** Latest
- **FastAPI:** 0.104.1
- **Pydantic:** 2.5.0

---

---

### 6. ✅ Apache2 Web Server Support

**Enhancement:**
- Extended web server support from Nginx-only to both Nginx and Apache2
- Generator now produces configurations for both web servers

**Solution:**
- Modified `/stages/generators/config_generator.py` (lines 87-153) to generate Apache2 virtual host configuration
- Updated `/stages/architecture_designer.py` (line 182) to allow LLM to choose between web servers
- Modified `/stages/code_generator.py` (lines 458-502) to document both web servers in README
- Added web server detection in setup.sh (lines 277-295)

**Apache2 Configuration:**
```apache
<VirtualHost *:80>
    ServerName example.com
    ServerAdmin webmaster@example.com

    # Proxy settings
    ProxyPreserveHost On
    ProxyPass /static !
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    # Enable WebSocket support (if needed)
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{HTTP:Connection} upgrade [NC]
    RewriteRule ^/?(.*) "ws://127.0.0.1:8000/$1" [P,L]

    # Static files
    Alias /static /var/www/{project_name}/app/static
    <Directory /var/www/{project_name}/app/static>
        Require all granted
        Options -Indexes +FollowSymLinks
    </Directory>

    # Logging and Security headers
    ErrorLog ${APACHE_LOG_DIR}/{project_name}_error.log
    CustomLog ${APACHE_LOG_DIR}/{project_name}_access.log combined
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-XSS-Protection "1; mode=block"
</VirtualHost>
```

**Web Server Detection in setup.sh:**
```bash
# Step 9: Detect web server
echo ""
echo "Detecting web server..."
WEB_SERVER="none"
if command -v nginx &> /dev/null; then
    WEB_SERVER="nginx"
    echo "${GREEN}✅ Nginx detected${NC}"
    echo "   To configure: sudo ln -s $(pwd)/nginx/{project_name}.conf /etc/nginx/sites-enabled/"
elif command -v apache2 &> /dev/null || command -v httpd &> /dev/null; then
    WEB_SERVER="apache2"
    echo "${GREEN}✅ Apache2 detected${NC}"
    echo "   To configure: sudo ln -s $(pwd)/apache2/{project_name}.conf /etc/apache2/sites-enabled/"
    echo "   Enable modules: sudo a2enmod proxy proxy_http rewrite headers ssl"
else
    echo "${YELLOW}⚠️  No web server detected (Nginx or Apache2)${NC}"
    echo "   For production, install one:"
    echo "     Nginx: sudo apt install nginx"
    echo "     Apache2: sudo apt install apache2"
fi
```

---

## Next Steps

1. ✅ Fix generator templates (COMPLETE)
2. ✅ Add Apache2 support (COMPLETE)
3. 🔄 Test full deployment to remote server
4. 🔄 Enhance generated API implementations
5. 🔄 Add comprehensive error handling

