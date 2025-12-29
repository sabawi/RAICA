#!/usr/bin/env python3
"""Config Generator - Configuration files"""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class ConfigGenerator:
    """Generates configuration files."""

    def generate(
        self,
        project_dir: Path,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any]
    ) -> List[str]:
        files = []

        # Generate .env.example
        env_file = project_dir / ".env.example"
        project_name = architecture.get("project_name", "app")
        with open(env_file, 'w') as f:
            f.write(f'''# Database
DATABASE_URL=postgresql://user:password@localhost/{project_name}

# Security
SECRET_KEY=change-this-to-a-random-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# Redis (if using workers)
REDIS_URL=redis://localhost:6379/0
''')
        files.append(str(env_file.relative_to(project_dir)))

        # Generate .gitignore
        gitignore_file = project_dir / ".gitignore"
        with open(gitignore_file, 'w') as f:
            f.write('''__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
ENV/
.env
.venv
*.log
.DS_Store
.idea/
.vscode/
*.db
*.sqlite
alembic/versions/*.py
!alembic/versions/__init__.py
''')
        files.append(str(gitignore_file.relative_to(project_dir)))

        # Generate nginx config
        nginx_file = project_dir / "nginx" / f"{project_name}.conf"
        with open(nginx_file, 'w') as f:
            f.write(f'''server {{
    listen 80;
    server_name example.com;

    location / {{
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location /static {{
        alias /var/www/{project_name}/app/static;
    }}
}}
''')
        files.append(str(nginx_file.relative_to(project_dir)))

        # Generate apache2 config
        apache_file = project_dir / "apache2" / f"{project_name}.conf"
        apache_file.parent.mkdir(exist_ok=True)
        with open(apache_file, 'w') as f:
            f.write(f'''<VirtualHost *:80>
    ServerName example.com
    ServerAdmin webmaster@example.com

    # Proxy settings
    ProxyPreserveHost On
    ProxyPass /static !
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    # Enable WebSocket support (if needed)
    RewriteEngine On
    RewriteCond %{{HTTP:Upgrade}} websocket [NC]
    RewriteCond %{{HTTP:Connection}} upgrade [NC]
    RewriteRule ^/?(.*) "ws://127.0.0.1:8000/$1" [P,L]

    # Static files
    Alias /static /var/www/{project_name}/app/static
    <Directory /var/www/{project_name}/app/static>
        Require all granted
        Options -Indexes +FollowSymLinks
    </Directory>

    # Logging
    ErrorLog ${{APACHE_LOG_DIR}}/{project_name}_error.log
    CustomLog ${{APACHE_LOG_DIR}}/{project_name}_access.log combined

    # Security headers
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-XSS-Protection "1; mode=block"
</VirtualHost>

# SSL configuration (uncomment and configure for HTTPS)
# <VirtualHost *:443>
#     ServerName example.com
#     ServerAdmin webmaster@example.com
#
#     SSLEngine on
#     SSLCertificateFile /etc/letsencrypt/live/example.com/fullchain.pem
#     SSLCertificateKeyFile /etc/letsencrypt/live/example.com/privkey.pem
#
#     ProxyPreserveHost On
#     ProxyPass /static !
#     ProxyPass / http://127.0.0.1:8000/
#     ProxyPassReverse / http://127.0.0.1:8000/
#
#     RewriteEngine On
#     RewriteCond %{{HTTP:Upgrade}} websocket [NC]
#     RewriteCond %{{HTTP:Connection}} upgrade [NC]
#     RewriteRule ^/?(.*) "ws://127.0.0.1:8000/$1" [P,L]
#
#     Alias /static /var/www/{project_name}/app/static
#     <Directory /var/www/{project_name}/app/static>
#         Require all granted
#         Options -Indexes +FollowSymLinks
#     </Directory>
#
#     ErrorLog ${{APACHE_LOG_DIR}}/{project_name}_ssl_error.log
#     CustomLog ${{APACHE_LOG_DIR}}/{project_name}_ssl_access.log combined
# </VirtualHost>
''')
        files.append(str(apache_file.relative_to(project_dir)))

        # Generate systemd service
        systemd_file = project_dir / "systemd" / f"{project_name}.service"
        with open(systemd_file, 'w') as f:
            f.write(f'''[Unit]
Description={project_name} FastAPI Application
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/{project_name}
Environment="PATH=/var/www/{project_name}/venv/bin"
ExecStart=/var/www/{project_name}/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

[Install]
WantedBy=multi-user.target
''')
        files.append(str(systemd_file.relative_to(project_dir)))

        # Generate setup.sh
        setup_file = project_dir / "setup.sh"
        db_name = project_name.lower().replace(" ", "_").replace("-", "_")
        with open(setup_file, 'w') as f:
            f.write(f'''#!/bin/bash
# Auto-generated setup script for {project_name}
# Generated by Website Deployment Agent

set -e  # Exit on error

echo "=========================================="
echo "{project_name} - Quick Setup"
echo "=========================================="
echo ""

PROJECT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$PROJECT_DIR"

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m' # No Color

# Step 1: Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Step 2: Activate venv
echo "Activating virtual environment..."
source venv/bin/activate

# Step 3: Install dependencies
echo ""
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Step 4: Configure environment
echo ""
echo "Configuring environment..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    # Fix database name (remove spaces)
    sed -i 's/{project_name}/{db_name}/g' .env
    # Generate random secret key
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s/change-this-to-a-random-secret-key/$SECRET_KEY/g" .env
    echo "${{GREEN}}✅ Environment configured${{NC}}"
else
    echo "${{GREEN}}✅ .env already exists${{NC}}"
fi

# Step 5: Check PostgreSQL
echo ""
echo "Checking PostgreSQL..."
if ! command -v psql &> /dev/null; then
    echo "${{RED}}⚠️  PostgreSQL not found.${{NC}}"
    echo "Please install it:"
    echo "  sudo apt install postgresql postgresql-contrib"
    echo ""
    echo "After installing, create a database:"
    echo "  sudo -u postgres createdb {db_name}"
    exit 1
fi

# Step 6: Create PostgreSQL user (if doesn't exist)
echo ""
echo "Checking PostgreSQL user..."
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$USER'" | grep -q 1; then
    echo "${{GREEN}}✅ PostgreSQL user '$USER' already exists${{NC}}"
else
    echo "Creating PostgreSQL user '$USER'..."
    sudo -u postgres createuser -s $USER || {{
        echo "${{YELLOW}}⚠️  Could not create PostgreSQL user${{NC}}"
        echo "You may need to create it manually:"
        echo "  sudo -u postgres createuser -s $USER"
    }}
    echo "${{GREEN}}✅ PostgreSQL user created${{NC}}"
fi

# Step 7: Check if database exists
if sudo -u postgres psql -lqt | cut -d \\| -f 1 | grep -qw {db_name}; then
    echo "${{GREEN}}✅ Database already exists${{NC}}"
else
    echo "Creating database..."
    sudo -u postgres createdb {db_name} || {{
        echo "${{RED}}❌ Failed to create database${{NC}}"
        echo "Please create it manually:"
        echo "  sudo -u postgres createdb {db_name}"
        exit 1
    }}
    echo "${{GREEN}}✅ Database created${{NC}}"
fi

# Step 8: Run migrations
echo ""
echo "Running database migrations..."
alembic upgrade head || {{
    echo "${{YELLOW}}⚠️  Migrations failed. You may need to run them manually.${{NC}}"
}}

# Step 9: Detect web server
echo ""
echo "Detecting web server..."
WEB_SERVER="none"
if command -v nginx &> /dev/null; then
    WEB_SERVER="nginx"
    echo "${{GREEN}}✅ Nginx detected${{NC}}"
    echo "   To configure: sudo ln -s $(pwd)/nginx/{project_name}.conf /etc/nginx/sites-enabled/"
elif command -v apache2 &> /dev/null || command -v httpd &> /dev/null; then
    WEB_SERVER="apache2"
    echo "${{GREEN}}✅ Apache2 detected${{NC}}"
    echo "   To configure: sudo ln -s $(pwd)/apache2/{project_name}.conf /etc/apache2/sites-enabled/"
    echo "   Enable modules: sudo a2enmod proxy proxy_http rewrite headers ssl"
else
    echo "${{YELLOW}}⚠️  No web server detected (Nginx or Apache2)${{NC}}"
    echo "   For production, install one:"
    echo "     Nginx: sudo apt install nginx"
    echo "     Apache2: sudo apt install apache2"
fi

# Step 10: Check Redis (if needed)
{"" if architecture.get("workers") else "# "}echo ""
{"" if architecture.get("workers") else "# "}echo "Checking Redis..."
{"" if architecture.get("workers") else "# "}if ! command -v redis-cli &> /dev/null; then
{"" if architecture.get("workers") else "#     "}echo "${{YELLOW}}⚠️  Redis not found. Background workers won't work.${{NC}}"
{"" if architecture.get("workers") else "#     "}echo "   To install: sudo apt install redis-server"
{"" if architecture.get("workers") else "# "}else
{"" if architecture.get("workers") else "#     "}echo "${{GREEN}}✅ Redis is available${{NC}}"
{"" if architecture.get("workers") else "# "}fi

echo ""
echo "=========================================="
echo "${{GREEN}}✅ Setup Complete!${{NC}}"
echo "=========================================="
echo ""
echo "To start the server:"
echo "  source venv/bin/activate"
echo "  uvicorn app.main:app --reload"
echo ""
{"" if architecture.get("workers") else "# "}echo "To start Celery workers (in another terminal):"
{"" if architecture.get("workers") else "# "}echo "  source venv/bin/activate"
{"" if architecture.get("workers") else "# "}echo "  celery -A app.workers.celery_app worker --loglevel=info"
{"" if architecture.get("workers") else "# "}echo ""
echo "API Documentation: http://localhost:8000/docs"
echo ""
''')
        # Make executable
        import os
        os.chmod(setup_file, 0o755)
        files.append(str(setup_file.relative_to(project_dir)))

        logger.info(f"✅ Generated {len(files)} config files")
        return files
