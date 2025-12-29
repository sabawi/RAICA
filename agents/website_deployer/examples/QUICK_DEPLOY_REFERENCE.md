# Quick Deploy Reference

## ⚠️ Important: Virtual Environment Required

The deployment script requires LLM provider packages. Use one of these methods:

**Method 1: Use the wrapper script (Recommended)**
```bash
./deploy.sh --auto-input auto_deploy_simple_php.json
```

**Method 2: Activate venv manually**
```bash
source ../../../venv/bin/activate
./zero_shot_deployment.py --auto-input auto_deploy_simple_php.json
```

**Method 3: Install packages system-wide (Not recommended)**
```bash
pip3 install -r ../requirements.txt
./zero_shot_deployment.py --auto-input auto_deploy_simple_php.json
```

---

## All Available Templates with Auto-Deploy Configs

### Quick-Start Templates (3-5 minutes)

#### 1. Simple PHP Website
**Template**: `templates/simple_php_website.json`
**Auto-Deploy**: `auto_deploy_simple_php.json`
**Stack**: PHP + MySQL + Apache2
**Port**: 8080
**Features**: User auth, email verification, password reset

```bash
./zero_shot_deployment.py --auto-input auto_deploy_simple_php.json
```

#### 2. Simple Python API
**Template**: `templates/simple_python_api.json`
**Auto-Deploy**: `auto_deploy_simple_python.json`
**Stack**: Python FastAPI + PostgreSQL + Nginx
**Port**: 8000
**Features**: JWT auth, basic CRUD, OpenAPI docs

```bash
./zero_shot_deployment.py --auto-input auto_deploy_simple_python.json
```

#### 3. Simple Node.js App
**Template**: `templates/simple_nodejs_app.json`
**Auto-Deploy**: `auto_deploy_simple_nodejs.json`
**Stack**: Node.js Express + PostgreSQL + Nginx
**Port**: 3000
**Features**: Session auth, posts, basic CRUD

```bash
./zero_shot_deployment.py --auto-input auto_deploy_simple_nodejs.json
```

---

### Production Templates (5-9 minutes)

#### 4. E-commerce Store
**Template**: `templates/ecommerce_store.json`
**Auto-Deploy**: `auto_deploy_ecommerce.json`
**Stack**: PHP Laravel + MySQL + Apache2
**Port**: 6050 (HTTPS)
**Features**: Stripe payments, inventory tracking, product reviews, order management
**Models**: 9 (User, Product, Category, Cart, Order, Payment, Review)
**Endpoints**: 17

```bash
./zero_shot_deployment.py --auto-input auto_deploy_ecommerce.json
```

#### 5. SaaS Task Manager
**Template**: `templates/task_manager_saas.json`
**Auto-Deploy**: `auto_deploy_task_manager.json`
**Stack**: Python FastAPI + PostgreSQL + Nginx
**Port**: 8082
**Features**: Real-time WebSockets, team collaboration, file attachments, notifications
**Models**: 9 (User, Team, Project, Task, Comment, Notification, Activity)
**Endpoints**: 26 (including WebSocket)

```bash
./zero_shot_deployment.py --auto-input auto_deploy_task_manager.json
```

#### 6. Blog/CMS Platform
**Template**: `templates/blog_cms.json`
**Auto-Deploy**: `auto_deploy_blog_cms.json`
**Stack**: PHP Laravel + MySQL + Apache2
**Port**: 8081
**Features**: Rich text editor (TinyMCE), Markdown support, SEO optimization, RSS feeds, comments moderation
**Models**: 6 (User, Post, Category, Tag, Comment, Media)
**Endpoints**: 16
**Pages**: 15 (including admin panel)

```bash
./zero_shot_deployment.py --auto-input auto_deploy_blog_cms.json
```

#### 7. API Gateway Service
**Template**: `templates/api_service.json`
**Auto-Deploy**: `auto_deploy_api_service.json`
**Stack**: Python FastAPI + PostgreSQL + Nginx
**Port**: 8443 (HTTPS)
**Features**: JWT + API key auth, rate limiting, webhooks, OpenAPI documentation, request logging
**Models**: 6 (User, ApiKey, Resource, Webhook, WebhookDelivery, RequestLog)
**Endpoints**: 22
**Workers**: 4 background workers

```bash
./zero_shot_deployment.py --auto-input auto_deploy_api_service.json
```

---

## Deployment Matrix

| Template | Tech Stack | DB | Web Server | Port | Time | Models | Endpoints |
|----------|-----------|-----|------------|------|------|--------|-----------|
| Simple PHP | PHP | MySQL | Apache2 | 8080 | 3-4 min | 3 | 7 pages |
| Simple Python | FastAPI | PostgreSQL | Nginx | 8000 | 4-5 min | 2 | 9 |
| Simple Node | Express | PostgreSQL | Nginx | 3000 | 4-5 min | 2 | 8 |
| E-commerce | Laravel | MySQL | Apache2 | 6050 | 7-9 min | 9 | 17 |
| Task Manager | FastAPI | PostgreSQL | Nginx | 8082 | 7-9 min | 9 | 26 |
| Blog CMS | Laravel | MySQL | Apache2 | 8081 | 7-9 min | 6 | 16 |
| API Gateway | FastAPI | PostgreSQL | Nginx | 8443 | 5-7 min | 6 | 22 |

---

## Port Assignments

Make sure these ports are available on your target server:

- **3000**: Simple Node.js App
- **6050**: E-commerce Store (HTTPS)
- **8000**: Simple Python API
- **8080**: Simple PHP Website
- **8081**: Blog/CMS Platform
- **8082**: SaaS Task Manager
- **8443**: API Gateway Service (HTTPS)

Check port availability:
```bash
sudo netstat -tuln | grep -E ':(3000|6050|8000|8080|8081|8082|8443) '
```

---

## Customizing Auto-Deploy Configs

To customize for your environment, edit the auto-deploy JSON files:

### Change SSH Credentials
```json
{
  "ssh_host": "your.server.com",
  "ssh_user": "your_user",
  "ssh_password": "your_password"
}
```

### Change Database
```json
{
  "database_name": "your_custom_db_name",
  "db_web_user": "your_db_user",
  "db_web_password": "your_secure_password"
}
```

### Change Port
```json
{
  "http_port": "9000",
  "domain": "myapp.example.com"
}
```

### Enable HTTPS
```json
{
  "web_protocol": "HTTPS",
  "https_port": "443",
  "ssl_type": "Let's Encrypt"
}
```

---

## Sequential Deployment (Multiple Apps)

Deploy all quick-start templates:
```bash
for config in auto_deploy_simple*.json; do
    echo "Deploying: $config"
    ./zero_shot_deployment.py --auto-input "$config"
    echo "---"
done
```

Deploy all production templates:
```bash
for config in auto_deploy_{ecommerce,task_manager,blog_cms,api_service}.json; do
    echo "Deploying: $config"
    ./zero_shot_deployment.py --auto-input "$config"
    echo "---"
done
```

---

## Testing After Deployment

### Simple PHP Website
```bash
curl http://192.168.1.58:8080
curl http://192.168.1.58:8080/register_simple.php
```

### Simple Python API
```bash
curl http://192.168.1.58:8000/docs  # Swagger UI
curl http://192.168.1.58:8000/api/items
```

### E-commerce Store
```bash
curl -k https://192.168.1.58:6050
curl -k https://192.168.1.58:6050/api/products
```

### Task Manager
```bash
curl http://192.168.1.58:8082/docs
curl http://192.168.1.58:8082/api/v1/projects
```

---

## Troubleshooting

### Port Already in Use
```bash
# Find what's using the port
sudo netstat -tuln | grep :8080

# Kill the process
sudo kill $(sudo lsof -t -i:8080)
```

### Database Connection Failed
```bash
# Check MySQL
sudo systemctl status mysql

# Check PostgreSQL
sudo systemctl status postgresql
```

### SSH Connection Failed
```bash
# Test SSH manually
ssh sabawi@192.168.1.58

# Check SSH service
sudo systemctl status ssh
```

### Permission Denied
```bash
# Check sudo access
sudo -v

# Grant sudo without password (optional)
echo "sabawi ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/sabawi
```

---

## Clean Up Deployments

Remove a deployment:
```bash
# Stop services
sudo systemctl stop simple_php_website
sudo systemctl stop blog_platform

# Remove files
sudo rm -rf /var/www/simple_website
sudo rm -rf /var/www/blog_platform

# Drop databases
mysql -u root -p -e "DROP DATABASE simple_website_db;"
mysql -u root -p -e "DROP DATABASE blog_platform_db;"
```

---

## Next Steps

1. **Test simple templates first**: Start with `auto_deploy_simple_php.json`
2. **Verify deployment**: Access the URL and test functionality
3. **Deploy production templates**: Once comfortable, try the larger templates
4. **Customize**: Modify auto-deploy configs for your environment
5. **Secure**: Change default passwords, enable HTTPS with Let's Encrypt

For detailed documentation:
- **Auto-Input Guide**: `AUTO_INPUT_GUIDE.md`
- **Deployment Guide**: `../docs/ZERO_SHOT_DEPLOYMENT_GUIDE.md`
- **Main README**: `../README.md`
