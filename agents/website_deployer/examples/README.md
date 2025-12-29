# Website Deployer - Examples & Auto-Deploy Configs

## Quick Start

### Using the Wrapper Script (Easiest)

```bash
cd examples
./deploy.sh --auto-input auto_deploy_simple_php.json
```

The `deploy.sh` wrapper:
- ✅ Automatically activates the virtual environment
- ✅ Installs missing packages if needed
- ✅ Passes all arguments to the deployment script

### Manual Deployment

If you prefer to manage the environment yourself:

```bash
# 1. Activate virtual environment
cd /home/sabawi/Development/flaskserver
source venv/bin/activate

# 2. Install requirements (if not already done)
pip install -r agents/website_deployer/requirements.txt

# 3. Run deployment
cd agents/website_deployer/examples
./zero_shot_deployment.py --auto-input auto_deploy_simple_php.json
```

## Available Templates

### Quick-Start (3-5 minutes)
- `auto_deploy_simple_php.json` - Simple PHP website with auth
- `auto_deploy_simple_python.json` - Simple Python FastAPI
- `auto_deploy_simple_nodejs.json` - Simple Node.js Express app

### Production (5-9 minutes)
- `auto_deploy_ecommerce.json` - E-commerce store with payments
- `auto_deploy_task_manager.json` - SaaS task manager with real-time
- `auto_deploy_blog_cms.json` - Blog/CMS platform
- `auto_deploy_api_service.json` - API gateway with webhooks

## Deployment Examples

### Deploy Simple PHP Website
```bash
./deploy.sh --auto-input auto_deploy_simple_php.json
```

### Deploy E-commerce Store
```bash
./deploy.sh --auto-input auto_deploy_ecommerce.json
```

### Deploy All Quick-Start Templates
```bash
for config in auto_deploy_simple*.json; do
    ./deploy.sh --auto-input "$config"
done
```

## Customizing Deployments

1. Copy an auto-deploy config:
   ```bash
   cp auto_deploy_simple_php.json my_custom_deploy.json
   ```

2. Edit the configuration:
   ```json
   {
     "ssh_host": "your.server.com",
     "database_name": "my_custom_db",
     "http_port": "9000"
   }
   ```

3. Deploy:
   ```bash
   ./deploy.sh --auto-input my_custom_deploy.json
   ```

## Troubleshooting

### "No module named 'google'" or "No module named 'anthropic'"

**Problem**: Python packages not installed or venv not activated.

**Solution**:
```bash
# Use the wrapper script
./deploy.sh --auto-input your_config.json

# OR activate venv manually
source ../../../venv/bin/activate
pip install -r ../requirements.txt
```

### "SSH connection failed"

**Problem**: Incorrect SSH credentials or server not accessible.

**Solution**: Check your auto-deploy JSON:
```json
{
  "ssh_host": "192.168.1.58",  // Verify this is correct
  "ssh_user": "sabawi",         // Verify this user exists
  "ssh_password": "***"         // Verify password is correct
}
```

### "Port already in use"

**Problem**: The port specified is already in use.

**Solution**:
1. Check what's using the port:
   ```bash
   sudo netstat -tuln | grep :8080
   ```

2. Change the port in your auto-deploy JSON:
   ```json
   {
     "http_port": "8081"  // Use a different port
   }
   ```

## Helper Scripts

- `./deploy.sh` - Wrapper script that activates venv and runs deployment
- `./list_templates.sh` - List all available templates
- `./zero_shot_deployment.py` - Main deployment script (use via deploy.sh)

## Documentation

- `AUTO_INPUT_GUIDE.md` - Complete guide to auto-input configuration
- `QUICK_DEPLOY_REFERENCE.md` - Quick reference for all templates
- `../docs/ZERO_SHOT_DEPLOYMENT_GUIDE.md` - Comprehensive deployment guide
- `../README.md` - Main project documentation

## Requirements

- Python 3.11+
- Virtual environment with packages installed
- SSH access to target server
- Database server (MySQL or PostgreSQL) on target

## Support

For issues:
1. Check the troubleshooting section above
2. Review `AUTO_INPUT_GUIDE.md`
3. Check the main documentation in `../docs/`
