# Auto-Input Configuration Guide

## Overview

The `--auto-input` flag allows fully automated deployment without interactive prompts. It requires a JSON configuration file containing:

1. **Specification**: What to build (template reference or natural language)
2. **Configuration**: How to deploy (SSH, database, web server settings)

## Quick Start

### Simple PHP Website (3-4 minutes)
```bash
cd examples
./zero_shot_deployment.py --auto-input auto_deploy_simple_php.json
```

### E-commerce Store (7-9 minutes)
```bash
cd examples
./zero_shot_deployment.py --auto-input auto_deploy_ecommerce.json
```

## Configuration File Format

```json
{
  "specification": "templates/simple_php_website.json",

  "backend_framework": "PHP (Apache2/Nginx)",
  "database_type": "MySQL",
  "web_server": "Apache2",
  "frontend_framework": "HTML/CSS/JavaScript (traditional)",

  "ssh_host": "192.168.1.58",
  "ssh_user": "deployer",
  "ssh_password": "your_password",
  "ssh_port": "22",
  "ssh_auth_method": "Password",

  "sudo_requires_password": true,
  "sudo_password": "your_sudo_password",

  "db_admin_user": "root",
  "db_admin_password": "your_db_password",
  "database_name": "my_database",
  "db_web_user": "webuser",
  "db_web_password": "webuser",
  "db_web_permissions": "SELECT, INSERT, UPDATE, DELETE",

  "web_protocol": "HTTP",
  "http_port": "8080",
  "domain": "your_domain.com"
}
```

## Configuration Keys

### Specification
- **specification**: Path to JSON template file OR natural language description

### Technology Stack
- **backend_framework**:
  - `"PHP (Apache2/Nginx)"`
  - `"Python (FastAPI/Django)"`
  - `"Node.js (Express)"`
  - `"Custom"`

- **database_type**:
  - `"MySQL"`
  - `"PostgreSQL"`
  - `"SQLite"`
  - `"Custom"`

- **web_server**:
  - `"Apache2"`
  - `"Nginx"`
  - `"Built-in (development only)"`
  - `"Custom"`

- **frontend_framework**:
  - `"HTML/CSS/JavaScript (traditional)"`
  - `"React"`
  - `"Vue"`
  - `"Custom"`

### SSH Configuration
- **ssh_host**: IP address or hostname
- **ssh_user**: SSH username
- **ssh_password**: SSH password (if using password auth)
- **ssh_port**: SSH port (default: "22")
- **ssh_auth_method**:
  - `"Password"`
  - `"SSH Key"`

### Sudo Configuration
- **sudo_requires_password**: `true` or `false`
- **sudo_password**: Sudo password (if required)

### Database Configuration
- **db_admin_user**: MySQL/PostgreSQL admin username (usually "root")
- **db_admin_password**: Admin password
- **database_name**: Name for the application database
- **db_web_user**: Database user for web application
- **db_web_password**: Password for web user
- **db_web_permissions**: Permissions string (e.g., "SELECT, INSERT, UPDATE, DELETE")

### Web Server Configuration
- **web_protocol**:
  - `"HTTP"`
  - `"HTTPS"`
  - `"Both"`

- **http_port**: HTTP port (default: "80")
- **https_port**: HTTPS port (default: "443")
- **domain**: Domain name or IP address
- **ssl_type**: (if HTTPS)
  - `"Let's Encrypt"`
  - `"Self-signed (development)"`
  - `"Custom certificate"`

## Available Templates

### Quick-Start Templates (3-5 minutes)
1. **simple_php_website.json** - Basic auth with email verification
2. **simple_python_api.json** - Minimal REST API
3. **simple_nodejs_app.json** - Basic Express application

### Production Templates (5-9 minutes)
1. **ecommerce_store.json** - Full e-commerce with Stripe
2. **task_manager_saas.json** - SaaS with real-time features
3. **blog_cms.json** - Blog platform with SEO
4. **api_service.json** - Enterprise API gateway

## Examples

### Using Template Reference
```json
{
  "specification": "templates/simple_php_website.json",
  ...
}
```

### Using Natural Language
```json
{
  "specification": "Create a blog website with user authentication, posts, comments, and categories. Use PHP and MySQL.",
  ...
}
```

### Using Inline JSON Template
```json
{
  "specification": "{\"project_name\": \"my_app\", \"tech_stack\": \"php_plain\", ...}",
  ...
}
```

## Testing Your Configuration

Test without deploying:
```bash
# Just validate the configuration
./zero_shot_deployment.py --auto-input your_config.json --dry-run
```

## Security Notes

⚠️ **IMPORTANT**: Auto-input files contain sensitive credentials:

1. **Never commit to git**: Add `*auto_deploy*.json` to `.gitignore`
2. **Secure permissions**: `chmod 600 auto_deploy_*.json`
3. **Use SSH keys**: Prefer SSH key authentication over passwords
4. **Environment variables**: Consider using env vars for passwords

Example with environment variables:
```bash
export SSH_PASSWORD="your_password"
export DB_PASSWORD="your_db_password"

# Then reference in JSON:
{
  "ssh_password": "${SSH_PASSWORD}",
  "db_admin_password": "${DB_PASSWORD}"
}
```

## Troubleshooting

### "Could not load as JSON template"
- Check the file path is correct
- Ensure the JSON is valid
- Verify the file exists

### "SSH connection failed"
- Verify ssh_host, ssh_user, ssh_password
- Check SSH port is correct
- Ensure target server is accessible

### "Database setup failed"
- Verify db_admin_user and db_admin_password
- Check MySQL/PostgreSQL is installed
- Ensure admin user has CREATE DATABASE privileges

### "Port already in use"
- Change http_port or https_port
- Check what's using the port: `sudo netstat -tuln | grep :PORT`

## Advanced Usage

### Multiple Deployments
Deploy multiple sites in sequence:
```bash
for config in auto_deploy_*.json; do
    ./zero_shot_deployment.py --auto-input "$config"
done
```

### Parallel Deployments (different servers)
```bash
./zero_shot_deployment.py --auto-input server1_config.json &
./zero_shot_deployment.py --auto-input server2_config.json &
wait
```

### Automated Testing Pipeline
```bash
# Deploy
./zero_shot_deployment.py --auto-input test_config.json

# Run tests
./run_integration_tests.sh

# Cleanup
./cleanup_deployments.py
```

## Support

For issues or questions:
- Check the main README: `../README.md`
- Review deployment guide: `../docs/ZERO_SHOT_DEPLOYMENT_GUIDE.md`
- Check troubleshooting: `../docs/TROUBLESHOOTING.md`
