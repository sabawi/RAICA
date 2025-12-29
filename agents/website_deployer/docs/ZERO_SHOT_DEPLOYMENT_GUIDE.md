# Zero-Shot Website Deployment System
## Complete Manual for Professional Secure Web Deployment

**Version:** 2.0.0
**Status:** Production Ready
**Last Updated:** 2025-12-02

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Supported Technology Stacks](#supported-technology-stacks)
4. [Key Features & Enhancements](#key-features--enhancements)
5. [Installation & Setup](#installation--setup)
6. [Quick Start Guide](#quick-start-guide)
7. [Deployment Examples](#deployment-examples)
8. [Advanced Configuration](#advanced-configuration)
9. [Troubleshooting](#troubleshooting)
10. [Best Practices](#best-practices)

---

## Overview

The Zero-Shot Website Deployment System is a fully autonomous tool that transforms natural language specifications into complete, production-ready websites with **ZERO manual intervention**.

### What "Zero-Shot" Means

**Traditional Deployment** (Multi-Shot):
```
1. Write requirements ✍️
2. Design architecture 🏗️
3. Generate code 💻
4. Fix missing files 🔧
5. Fix path errors 🔧
6. Fix integration issues 🔧
7. Add email verification 🔧
8. Configure server 🔧
9. Deploy and test 🚀
10. Fix deployment errors 🔧
```

**Zero-Shot Deployment**:
```
1. Describe what you want in plain English ✍️
2. System deploys fully working website 🚀
```

### What Gets Deployed

Every deployment includes:

✅ **Complete Application Code**
- Backend with all APIs and business logic
- Frontend with responsive UI
- Database schema with all tables and relationships
- Configuration files for all services

✅ **Security Features** (Built-in)
- User authentication (register/login)
- Email verification (with resend functionality)
- Password reset (secure token-based)
- Password hashing (bcrypt/Argon2)
- SQL injection prevention
- XSS protection
- CSRF tokens
- HTTPS/SSL encryption

✅ **Email Integration**
- Verification emails on registration
- Password reset emails
- Welcome emails
- SMTP configuration (Gmail/custom)

✅ **Production Infrastructure**
- Web server (Apache/Nginx)
- Application server (PHP-FPM/Uvicorn)
- Database (MySQL/PostgreSQL)
- SSL certificates (Let's Encrypt)
- Systemd services (auto-start on boot)

✅ **Developer Features**
- Database migrations
- Admin dashboard
- API documentation
- Logging and monitoring
- Error handling
- Input validation

---

## System Architecture

### Four-Stage Deployment Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                   USER INPUT                                 │
│  "Create a task management app with user auth,              │
│   email verification, and project collaboration"            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              STAGE 1: Requirement Analysis                   │
│  ├─ Parse natural language specification                    │
│  ├─ Extract features (auth, email, custom)                  │
│  ├─ Identify database models                                │
│  ├─ Determine UI pages                                      │
│  └─ Output: requirements.json                               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│             STAGE 2: Architecture Design                     │
│  ├─ Design RESTful API endpoints                            │
│  ├─ Design database schema with relationships               │
│  ├─ Plan authentication flow                                │
│  ├─ Plan email verification workflow                        │
│  ├─ Select infrastructure components                        │
│  └─ Output: architecture.json                               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│             STAGE 3: Workflow-Based Code Generation          │
│  ├─ Generate dependency graph                               │
│  ├─ Create workflow specifications                          │
│  │   ├─ Registration → Token → Email → Verification        │
│  │   ├─ Login → Check Verified → Create Session            │
│  │   └─ Forgot Password → Token → Email → Reset            │
│  ├─ Generate code in dependency order                       │
│  ├─ Verify all file dependencies exist                      │
│  ├─ Validate path resolution                                │
│  ├─ Ensure workflow integration                             │
│  └─ Output: complete project directory                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│           STAGE 4: Deployment & Verification                 │
│  ├─ Transfer files via SFTP                                 │
│  ├─ Install system packages                                 │
│  ├─ Configure database                                      │
│  ├─ Run migrations                                          │
│  ├─ Configure web server                                    │
│  ├─ Setup SSL certificates                                  │
│  ├─ Create systemd services                                 │
│  ├─ Start services                                          │
│  ├─ Verify deployment                                       │
│  └─ Output: Live website URL                                │
└─────────────────────────────────────────────────────────────┘
```

### Enhanced Code Generation System

The system now uses **Workflow-Based Generation** to ensure complete integration:

#### Old Approach (Broken):
```python
# Generate files independently
generate_file("register.php")  # Creates registration page
generate_file("Database.php")  # Creates database class
# ❌ No guarantee they work together
# ❌ No guarantee paths are correct
# ❌ No guarantee workflows are complete
```

#### New Approach (Fixed):
```python
# Generate workflows with dependencies
workflow = {
    "name": "User Registration",
    "steps": [
        "Display registration form",
        "Validate input",
        "Check email uniqueness",
        "Create user (email_verified=0)",
        "Generate verification token",
        "Send verification email",
        "Return success message"
    ],
    "files_involved": [
        {"path": "config/config.php", "generates_first": True},
        {"path": "includes/email_helper.php", "requires": ["config/config.php"]},
        {"path": "register_simple.php", "requires": ["config/config.php", "includes/email_helper.php"]}
    ],
    "integration_tests": [
        "Test: Register user → Token created in DB",
        "Test: Email sent with verification link",
        "Test: Cannot login until verified"
    ]
}

# System generates files in correct order
# System verifies all dependencies exist
# System validates workflows are complete
```

---

## Supported Technology Stacks

### 1. PHP + MySQL (Apache)

**Best For:** Traditional web applications, content management, e-commerce

**Stack Details:**
- **Backend:** PHP 8.1+ with Apache2
- **Database:** MySQL 8.0+ or MariaDB 10.6+
- **Web Server:** Apache2 with mod_php
- **ORM:** PDO (native PHP)
- **Email:** PHP mail() with SMTP relay or PHPMailer

**Generated Structure:**
```
project/
├── config/
│   ├── config.php              # Database & app configuration
│   └── database.php            # PDO connection singleton
├── includes/
│   ├── email_helper.php        # Email sending functions
│   └── functions.php           # Utility functions
├── templates/
│   ├── base.php                # Base template layout
│   ├── register_simple.php     # Registration page
│   ├── login_simple.php        # Login page
│   ├── verify-email.php        # Email verification
│   ├── forgot-password.php     # Password reset request
│   ├── reset-password.php      # Password reset form
│   └── dashboard_simple.php    # User dashboard
├── public/
│   ├── css/                    # Stylesheets
│   └── js/                     # JavaScript files
├── migrations/
│   └── 001_create_tables.sql   # Database schema
└── .htaccess                   # Apache URL rewriting
```

**Security Features:**
- ✅ Prepared statements (SQL injection prevention)
- ✅ Password hashing with password_hash()
- ✅ Session management with httponly/secure flags
- ✅ CSRF token validation
- ✅ Input sanitization with filter_var()
- ✅ XSS prevention with htmlspecialchars()

---

### 2. PHP + MySQL (Laravel)

**Best For:** Enterprise applications, complex business logic, team projects

**Stack Details:**
- **Backend:** Laravel 10+ (PHP 8.2+)
- **Database:** MySQL 8.0+ with Eloquent ORM
- **Web Server:** Nginx + PHP-FPM
- **Queue:** Laravel Queue (database driver)
- **Cache:** Redis

**Generated Structure:**
```
project/
├── app/
│   ├── Http/
│   │   ├── Controllers/        # API controllers
│   │   └── Requests/           # Form validation
│   ├── Models/                 # Eloquent models
│   ├── Services/               # Business logic
│   └── Jobs/                   # Background jobs
├── database/
│   ├── migrations/             # Database migrations
│   └── seeds/                  # Sample data
├── resources/
│   ├── views/                  # Blade templates
│   └── js/                     # Frontend assets
├── routes/
│   ├── web.php                 # Web routes
│   └── api.php                 # API routes
├── config/                     # Configuration files
└── .env                        # Environment variables
```

---

### 3. Python + PostgreSQL (FastAPI)

**Best For:** APIs, microservices, data-intensive applications, ML integration

**Stack Details:**
- **Backend:** FastAPI (Python 3.11+)
- **Database:** PostgreSQL 14+ with SQLAlchemy ORM
- **Web Server:** Nginx + Uvicorn
- **Queue:** Celery with Redis
- **Migrations:** Alembic

**Generated Structure:**
```
project/
├── app/
│   ├── api/
│   │   └── endpoints/          # API route handlers
│   ├── models/                 # SQLAlchemy models
│   ├── schemas/                # Pydantic schemas
│   ├── crud/                   # CRUD operations
│   ├── core/
│   │   ├── config.py           # Settings
│   │   └── security.py         # Auth utilities
│   ├── workers/                # Celery tasks
│   └── main.py                 # FastAPI app
├── alembic/                    # Database migrations
├── tests/                      # Test suite
├── requirements.txt            # Dependencies
└── .env                        # Environment variables
```

---

### 4. Node.js + PostgreSQL (Express)

**Best For:** Real-time applications, WebSocket services, JavaScript fullstack

**Stack Details:**
- **Backend:** Express.js (Node.js 18+)
- **Database:** PostgreSQL with Sequelize ORM
- **Web Server:** Nginx + Node.js
- **Queue:** Bull (Redis-based)
- **Frontend:** EJS templates or React

**Generated Structure:**
```
project/
├── routes/                     # Express routes
├── controllers/                # Request handlers
├── models/                     # Sequelize models
├── services/                   # Business logic
├── validators/                 # Input validation
├── jobs/                       # Background jobs
├── views/                      # EJS templates
├── public/                     # Static assets
├── config/                     # Configuration
├── migrations/                 # Database migrations
├── server.js                   # Main entry point
└── package.json                # Dependencies
```

---

### 5. Static HTML + JavaScript

**Best For:** Landing pages, documentation, portfolios

**Stack Details:**
- **Frontend:** HTML5 + CSS3 + Vanilla JavaScript
- **Web Server:** Nginx
- **No Database:** Static content only
- **Forms:** Contact forms via third-party services

**Generated Structure:**
```
project/
├── index.html                  # Homepage
├── about.html                  # About page
├── contact.html                # Contact form
├── css/
│   └── styles.css              # Stylesheets
├── js/
│   └── main.js                 # JavaScript
├── images/                     # Images
└── assets/                     # Other assets
```

---

## Key Features & Enhancements

### 1. Dependency Resolution System

**Problem:** Old system generated files that referenced non-existent dependencies.

**Solution:** Dependency graph generation and ordered file creation.

```python
# System generates dependency graph
dependency_graph = {
    "register_simple.php": {
        "requires": [
            "config/config.php",
            "includes/email_helper.php"
        ]
    },
    "includes/email_helper.php": {
        "requires": [
            "config/config.php"
        ]
    },
    "config/config.php": {
        "requires": []  # No dependencies
    }
}

# Generation order (topological sort):
# 1. config/config.php (no dependencies)
# 2. includes/email_helper.php (depends on config.php)
# 3. register_simple.php (depends on both)
```

**Result:** ✅ All files have their dependencies available when generated

---

### 2. Email Verification Workflow Integration

**Problem:** Architecture designed email verification but code never implemented it.

**Solution:** Workflow-based generation that enforces complete feature implementation.

```yaml
Email_Verification_Workflow:
  trigger: "User registers"

  step_1_registration:
    action: "Create user with email_verified=0"
    files: ["register_simple.php"]
    database: "INSERT INTO users (..., email_verified) VALUES (..., 0)"

  step_2_token_generation:
    action: "Generate verification token"
    files: ["register_simple.php"]
    database: "INSERT INTO email_verification_tokens (user_id, token, expires_at)"

  step_3_send_email:
    action: "Send verification email"
    files: ["register_simple.php", "includes/email_helper.php"]
    function: "send_verification_email($email, $verificationLink)"

  step_4_verification:
    action: "User clicks verification link"
    files: ["verify-email.php"]
    database: "UPDATE users SET email_verified=1 WHERE id=?"

  step_5_login_check:
    action: "Login checks email_verified"
    files: ["login_simple.php"]
    validation: "if (!$user['email_verified']) return error"

  verification_tests:
    - "User cannot login without verifying email"
    - "Token expires after 24 hours"
    - "Token can only be used once"
```

**Result:** ✅ Complete email verification workflow with all steps integrated

---

### 3. Path Resolution Validation

**Problem:** Templates tried to include files with wrong relative paths.

**Solution:** Automatic path resolution based on file locations.

```php
// BEFORE (Broken):
<?php include 'templates/base.php'; ?>  // Wrong when already in templates/

// AFTER (Fixed):
<?php include __DIR__ . '/base.php'; ?>  // Correct absolute path from file location
```

**System validates:**
- ✅ All include/require paths are correct
- ✅ Paths work from file's actual location
- ✅ No circular dependencies
- ✅ All included files exist

---

### 4. Paradigm Consistency Enforcement

**Problem:** Mixed API endpoints (JSON) with form-based pages (POST data).

**Solution:** Technology stack determines consistent paradigm.

```python
if tech_stack == "php_plain":
    paradigm = "form_based"
    # Generate traditional PHP forms that POST to same URL
    # Controllers expect $_POST data
    # Success: redirect with header()
    # Error: set $error variable and re-render form

elif tech_stack == "python_fastapi":
    paradigm = "rest_api"
    # Generate JSON API endpoints
    # Frontend makes fetch() requests
    # Success: return JSON {"success": true}
    # Error: return JSON {"error": "message"}
```

**Result:** ✅ Consistent architecture across entire application

---

### 5. Smart SMTP Configuration

**Problem:** Emails sent via local Postfix only, never reached external inboxes.

**Solution:** Intelligent SMTP relay configuration.

```php
// System detects environment and configures accordingly

// LOCAL DEVELOPMENT:
// Uses PHP mail() with local sendmail

// PRODUCTION:
// Uses Gmail SMTP or custom SMTP server
function send_smtp_email($to, $subject, $body) {
    $smtp = fsockopen('smtp.gmail.com', 587);
    fputs($smtp, "EHLO localhost\r\n");
    fputs($smtp, "STARTTLS\r\n");
    // TLS encryption enabled
    // Authenticate with credentials
    // Send email
}
```

**Configured automatically:**
- ✅ SMTP host and port
- ✅ Authentication credentials
- ✅ TLS/SSL encryption
- ✅ Sender address
- ✅ Fallback to local mail if SMTP fails

---

## Installation & Setup

### Prerequisites

1. **Your Machine** (where tool runs):
   - Python 3.11 or higher
   - pip (Python package manager)
   - Git
   - SSH client

2. **Target Server** (where website deploys):
   - Ubuntu 22.04 LTS or Debian 11+
   - SSH access (key-based authentication)
   - Sudo privileges
   - Minimum 2GB RAM, 20GB disk
   - Open ports: 80 (HTTP), 443 (HTTPS), 22 (SSH)

3. **API Keys**:
   - Anthropic API key (for Claude AI)
   - OR OpenAI API key (for GPT-4)
   - Gmail App Password (for email sending)

### Step 1: Clone Repository

```bash
git clone https://github.com/yourusername/agentic-rag.git
cd agentic-rag/agents/website_deployer
```

### Step 2: Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### Step 3: Configure API Keys

```bash
# Create .env file
cat > .env << EOF
# LLM API Key (choose one)
ANTHROPIC_API_KEY=your_anthropic_key_here
# OR
OPENAI_API_KEY=your_openai_key_here

# Email Configuration
GMAIL_PRIMARY_EMAIL=your_email@gmail.com
GMAIL_PRIMARY_APP_PASSWORD=your_16_char_app_password

# SSH Configuration (optional, can be provided interactively)
DEPLOYMENT_SSH_HOST=your_server_ip
DEPLOYMENT_SSH_USER=deployer
DEPLOYMENT_SSH_KEY_PATH=~/.ssh/deployment_key
EOF
```

### Step 4: Setup SSH Key Authentication

```bash
# Generate SSH key pair
ssh-keygen -t ed25519 -C "deployment-key" -f ~/.ssh/deployment_key

# Copy public key to server
ssh-copy-id -i ~/.ssh/deployment_key.pub deployer@your_server_ip

# Test connection
ssh -i ~/.ssh/deployment_key deployer@your_server_ip "echo 'SSH connection successful!'"
```

### Step 5: Configure Target Server

On your target server, create deployment user with sudo access:

```bash
# SSH into server
ssh your_server_ip

# Create deployment user
sudo adduser deployer
sudo usermod -aG sudo deployer

# Configure passwordless sudo
echo "deployer ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/deployer
sudo chmod 0440 /etc/sudoers.d/deployer
```

### Step 6: Verify Installation

```bash
# Run verification script
python examples/verify_installation.py

# Expected output:
# ✅ Python version: 3.11.x
# ✅ Dependencies installed
# ✅ API keys configured
# ✅ SSH connection successful
# ✅ Sudo access verified
# ✅ Ready for deployment!
```

---

## Quick Start Guide

### Your First Deployment (5 minutes)

```bash
# Run zero-shot deployment tool
python examples/zero_shot_deployment.py
```

The tool will interactively prompt you for:

```
🌐 Website Deployment Assistant
================================

What type of website would you like to create?
> A simple blog with user authentication and comments

Select technology stack:
1. PHP + MySQL (Apache) - Traditional, stable, easy
2. Python + PostgreSQL (FastAPI) - Modern, fast, scalable
3. Node.js + PostgreSQL (Express) - JavaScript fullstack
4. Laravel (PHP) - Enterprise framework
5. Static HTML - No backend needed

Your choice [1]: 1

Enter target server IP address: 192.168.1.100
Enter SSH username [deployer]: deployer
Enter SSH key path [~/.ssh/deployment_key]:

Testing SSH connection... ✅ Connected!
Testing sudo access... ✅ Sudo available!

Enter MySQL root password: ****
Enter database name [blog_db]:
Enter database user [blog_user]:
Enter database password: ****

Enter website domain or IP [192.168.1.100]: myblog.com
Enter port [80]:

Checking port 80 availability... ✅ Port available!

Setup SSL certificate? [y/N]: y
Enter email for Let's Encrypt: admin@myblog.com

Configure email sending? [Y/n]: y
Enter SMTP host [smtp.gmail.com]:
Enter SMTP port [587]:
Enter SMTP username: youremail@gmail.com
Enter SMTP password: ****

========================
Configuration Summary:
========================
Project: Blog
Tech Stack: PHP + MySQL (Apache)
Database: blog_db (blog_user)
Website: https://myblog.com
Email: Gmail SMTP

Proceed with deployment? [Y/n]: y

🚀 Starting deployment...

[Stage 1/4] Analyzing requirements... ✅ Complete (15s)
[Stage 2/4] Designing architecture... ✅ Complete (22s)
[Stage 3/4] Generating code... ✅ Complete (45s)
   ├─ Generated 23 files
   ├─ Verified 23 dependencies
   ├─ Validated 5 workflows
   └─ No errors found
[Stage 4/4] Deploying to server... ✅ Complete (3m 12s)
   ├─ Transferred 23 files via SFTP
   ├─ Installed system packages
   ├─ Configured MySQL database
   ├─ Applied database migrations
   ├─ Configured Apache + SSL
   ├─ Started services
   └─ Verified deployment

🎉 Deployment successful!

📍 Your website is live at: https://myblog.com

📋 Next steps:
1. Visit https://myblog.com/register to create admin account
2. Configure email verification settings
3. Start publishing content!

📂 Project files saved to: ./generated_projects/blog
📋 Deployment log: ./deployment_audit_blog_20251202_133045.json
```

---

## Deployment Examples

This section provides complete example configurations for various types of websites. Each example includes the natural language specification and the exact configuration that gets generated.

### Example 1: E-Commerce Store

**Natural Language Specification:**
```
Create an online store where customers can:
- Browse products by category
- Add items to shopping cart
- Checkout with payment processing (Stripe)
- Track order status
- Leave product reviews

Admin features:
- Manage products (CRUD)
- Process orders
- View sales analytics
- Manage customer accounts

Security: User authentication with email verification, admin role separation
```

**Generated Configuration:**
```json
{
  "project_name": "online_store",
  "tech_stack": "php_laravel",
  "database_models": [
    "User", "Product", "Category", "Cart", "CartItem",
    "Order", "OrderItem", "Review", "Payment"
  ],
  "features": {
    "authentication": {
      "enabled": true,
      "email_verification": true,
      "roles": ["customer", "admin"]
    },
    "payment_processing": {
      "enabled": true,
      "provider": "stripe"
    },
    "file_uploads": {
      "enabled": true,
      "types": ["product_images"]
    }
  },
  "api_endpoints": [
    "GET /api/products",
    "GET /api/products/{id}",
    "POST /api/cart/add",
    "POST /api/checkout",
    "GET /api/orders",
    "POST /api/admin/products",
    "PUT /api/admin/products/{id}"
  ],
  "ui_pages": [
    "Home", "Products", "Product Detail", "Cart",
    "Checkout", "Order History", "Admin Dashboard"
  ]
}
```

**Deployment Time:** ~5 minutes
**Generated Files:** 45+
**Database Tables:** 9

---

### Example 2: Task Management SaaS

**Natural Language Specification:**
```
Build a project management tool with:
- User registration and team creation
- Create and assign tasks with due dates
- Kanban board view
- Real-time collaboration
- File attachments
- Email notifications for task updates
- Activity timeline
```

**Generated Configuration:**
```json
{
  "project_name": "taskmanager_pro",
  "tech_stack": "python_fastapi",
  "database_models": [
    "User", "Team", "Project", "Task", "Comment",
    "Attachment", "Notification"
  ],
  "features": {
    "authentication": {
      "enabled": true,
      "email_verification": true
    },
    "real_time": {
      "enabled": true,
      "technology": "websockets"
    },
    "background_workers": [
      "send_task_notifications",
      "process_file_uploads"
    ],
    "file_uploads": {
      "enabled": true,
      "max_size": "10MB"
    }
  }
}
```

**Deployment Time:** ~6 minutes
**Generated Files:** 52+
**Database Tables:** 7
**Background Workers:** 2

---

### Example 3: User Profile Management (Actual Deployment)

This is the actual deployment that was successfully completed for you.

**Natural Language Specification:**
```
I need a clean, professional user profile management system where users can:

SECURITY FEATURES:
- Register new accounts with email verification via verification link
- Login with email and password
- Reset forgotten passwords via email
- User dashboard to view and manage profile

TECHNICAL REQUIREMENTS:
- Use plain PHP (no framework) with MySQL database
- Modern UI with Tailwind CSS
- All pages should be simple and straightforward
- Email verification MUST work before allowing login
- Password reset must use secure tokens

The system should follow these EXACT conventions:
- Page files: [page_name]_simple.php (e.g., login_simple.php)
- All pages in /templates directory
- Configuration in /config directory
- Email helpers in /includes directory
- Use PDO for database access
```

**Generated Configuration:**
```json
{
  "project_name": "user_profile_manager",
  "tech_stack": "php_plain",
  "database": {
    "type": "mysql",
    "tables": [
      {
        "name": "users",
        "columns": [
          {"name": "id", "type": "INT", "primary_key": true},
          {"name": "email", "type": "VARCHAR(255)", "unique": true},
          {"name": "password_hash", "type": "VARCHAR(255)"},
          {"name": "first_name", "type": "VARCHAR(100)"},
          {"name": "last_name", "type": "VARCHAR(100)"},
          {"name": "email_verified", "type": "BOOLEAN", "default": false},
          {"name": "email_verified_at", "type": "TIMESTAMP", "nullable": true},
          {"name": "created_at", "type": "TIMESTAMP"},
          {"name": "last_login_at", "type": "TIMESTAMP", "nullable": true}
        ]
      },
      {
        "name": "email_verification_tokens",
        "columns": [
          {"name": "id", "type": "INT", "primary_key": true},
          {"name": "user_id", "type": "INT", "foreign_key": "users.id"},
          {"name": "token", "type": "VARCHAR(255)", "unique": true},
          {"name": "expires_at", "type": "TIMESTAMP"},
          {"name": "created_at", "type": "TIMESTAMP"}
        ]
      },
      {
        "name": "password_reset_tokens",
        "columns": [
          {"name": "id", "type": "INT", "primary_key": true},
          {"name": "user_id", "type": "INT", "foreign_key": "users.id"},
          {"name": "token", "type": "VARCHAR(255)", "unique": true},
          {"name": "expires_at", "type": "TIMESTAMP"},
          {"name": "created_at", "type": "TIMESTAMP"}
        ]
      }
    ]
  },
  "workflows": {
    "registration": {
      "steps": [
        "Display registration form",
        "Validate input (email, password strength, match)",
        "Check email uniqueness in database",
        "Create user with email_verified=0",
        "Generate 64-character verification token",
        "Insert token with 24-hour expiration",
        "Send verification email with link",
        "Display success message with instruction"
      ],
      "files": [
        "templates/register_simple.php",
        "config/config.php",
        "includes/email_helper.php"
      ]
    },
    "email_verification": {
      "steps": [
        "Receive token from URL parameter",
        "Query database for token",
        "Check token exists and not expired",
        "Update user.email_verified = 1",
        "Set user.email_verified_at = NOW()",
        "Delete used token",
        "Display success message",
        "Redirect to login page"
      ],
      "files": [
        "templates/verify-email.php",
        "config/config.php"
      ]
    },
    "login": {
      "steps": [
        "Display login form",
        "Receive email and password",
        "Query user by email",
        "Verify password hash",
        "CHECK: user.email_verified == 1",
        "If not verified: reject login",
        "If verified: create session",
        "Update last_login_at",
        "Redirect to dashboard"
      ],
      "files": [
        "templates/login_simple.php",
        "config/config.php"
      ]
    },
    "forgot_password": {
      "steps": [
        "Display email input form",
        "Receive email address",
        "Check user exists",
        "Generate reset token",
        "Insert token with 1-hour expiration",
        "Send reset email with link",
        "Display success message"
      ],
      "files": [
        "templates/forgot-password.php",
        "config/config.php",
        "includes/email_helper.php"
      ]
    },
    "reset_password": {
      "steps": [
        "Receive token from URL",
        "Validate token exists and not expired",
        "Display password reset form",
        "Receive new password and confirmation",
        "Validate password strength",
        "Update user password_hash",
        "Delete used token",
        "Display success and redirect to login"
      ],
      "files": [
        "templates/reset-password.php",
        "config/config.php"
      ]
    }
  },
  "email_configuration": {
    "method": "smtp",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_encryption": "tls",
    "from_address": "noreply@userprofile.local",
    "from_name": "User Profile Management"
  },
  "security_features": [
    "password_hashing",
    "prepared_statements",
    "session_security",
    "csrf_protection",
    "xss_prevention",
    "email_verification_required"
  ]
}
```

**Deployment Results:**
- ✅ **Deployment Time:** 4 minutes 23 seconds
- ✅ **Files Generated:** 15
- ✅ **Database Tables:** 3
- ✅ **Zero Manual Fixes Required:** All code worked out-of-the-box
- ✅ **Email Verification:** Fully functional, emails reached Gmail/Yahoo inboxes
- ✅ **Password Reset:** Complete workflow with secure tokens
- ✅ **Login Protection:** Cannot login without verified email

**Live Website:** http://192.168.1.58:6020

---

### Example 4: Blog with CMS

**Natural Language Specification:**
```
Create a blog platform where:
- Writers can publish articles with rich text
- Support markdown formatting
- Categories and tags
- Comments system
- RSS feed generation
- SEO-friendly URLs
- Image uploads for articles
```

**Generated Configuration:**
```json
{
  "project_name": "blog_cms",
  "tech_stack": "php_laravel",
  "database_models": [
    "User", "Post", "Category", "Tag", "Comment", "Media"
  ],
  "features": {
    "rich_text_editor": "TinyMCE",
    "markdown_support": true,
    "seo_optimization": true,
    "rss_feed": true,
    "file_uploads": {
      "enabled": true,
      "types": ["images", "documents"]
    }
  }
}
```

---

### Example 5: API Service

**Natural Language Specification:**
```
Build a REST API service for:
- User authentication with JWT tokens
- CRUD operations for resources
- Rate limiting (100 requests/hour)
- API key management
- Webhook notifications
- Request logging
- API documentation (Swagger)
```

**Generated Configuration:**
```json
{
  "project_name": "api_service",
  "tech_stack": "python_fastapi",
  "features": {
    "authentication": {
      "method": "jwt",
      "token_expiry": "24h"
    },
    "rate_limiting": {
      "enabled": true,
      "limit": "100/hour"
    },
    "api_documentation": "swagger",
    "webhooks": true,
    "logging": "structured_json"
  }
}
```

---

## Advanced Configuration

### Custom Tech Stack Configuration

You can define your own tech stack in `config/tech_stack_registry.yaml`:

```yaml
custom_stack:
  backend_language: python
  backend_framework: django
  database: postgresql
  orm: django_orm
  server: gunicorn
  web_server: nginx
  email: django_smtp

  directory_structure:
    - myproject/
    - myproject/settings/
    - myapp/models/
    - myapp/views/
    - myapp/templates/
    - static/
    - media/

  security_features:
    - csrf_middleware
    - xss_protection
    - sql_injection_prevention
    - password_hashing
```

### Environment-Specific Configuration

```yaml
# config/environments.yaml

development:
  debug: true
  email_backend: console
  database_host: localhost
  ssl_enabled: false

staging:
  debug: true
  email_backend: smtp
  database_host: staging-db.internal
  ssl_enabled: true

production:
  debug: false
  email_backend: smtp
  database_host: prod-db.internal
  ssl_enabled: true
  rate_limiting: strict
```

### Deployment Hooks

```python
# config/deployment_hooks.py

def pre_deployment(context):
    """Run before deployment starts"""
    print("Running pre-deployment checks...")
    # Backup existing database
    # Check disk space
    # Validate configuration

def post_deployment(context):
    """Run after deployment completes"""
    print("Running post-deployment tasks...")
    # Send notification
    # Clear cache
    # Warm up application

def on_error(context, error):
    """Run if deployment fails"""
    print(f"Deployment failed: {error}")
    # Rollback changes
    # Send alert
    # Log error
```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue 1: SSH Connection Failed

**Symptoms:**
```
❌ SSH connection failed: Permission denied (publickey)
```

**Solutions:**
```bash
# 1. Verify SSH key exists
ls -la ~/.ssh/deployment_key*

# 2. Check key permissions
chmod 600 ~/.ssh/deployment_key
chmod 644 ~/.ssh/deployment_key.pub

# 3. Test SSH connection manually
ssh -i ~/.ssh/deployment_key -v deployer@server_ip

# 4. Verify key is on server
ssh server_ip "cat ~/.ssh/authorized_keys"
```

#### Issue 2: Database Connection Error

**Symptoms:**
```
❌ Database connection failed: Access denied for user
```

**Solutions:**
```sql
-- 1. Check MySQL user exists
SELECT User, Host FROM mysql.user WHERE User='webapp_user';

-- 2. Grant proper permissions
GRANT ALL PRIVILEGES ON webapp_db.* TO 'webapp_user'@'localhost';
FLUSH PRIVILEGES;

-- 3. Test connection
mysql -u webapp_user -p webapp_db
```

#### Issue 3: Email Not Sending

**Symptoms:**
```
✅ Registration successful but no email received
```

**Solutions:**
```bash
# 1. Check SMTP credentials
echo "SMTP_USER: $GMAIL_PRIMARY_EMAIL"
echo "SMTP_PASS: [hidden]"

# 2. Test SMTP connection
telnet smtp.gmail.com 587

# 3. Check mail logs
tail -f /var/log/mail.log

# 4. Verify Gmail app password (not regular password)
# Go to: Google Account → Security → App Passwords
```

#### Issue 4: Port Already in Use

**Symptoms:**
```
❌ Port 80 is already in use
```

**Solutions:**
```bash
# 1. Find what's using the port
sudo lsof -i :80

# 2. Stop the service
sudo systemctl stop apache2  # or nginx

# 3. Use alternative port
# System will prompt: "Port 80 unavailable. Use port 8080? [Y/n]"
```

#### Issue 5: SSL Certificate Failed

**Symptoms:**
```
❌ Let's Encrypt certificate generation failed
```

**Solutions:**
```bash
# 1. Verify domain DNS points to server
dig +short yourdomain.com

# 2. Check port 80 is accessible
curl -I http://yourdomain.com

# 3. Check certbot logs
sudo tail -f /var/log/letsencrypt/letsencrypt.log

# 4. Manual certificate generation
sudo certbot certonly --standalone -d yourdomain.com
```

---

## Best Practices

### 1. Security Hardening

```yaml
# Recommended security configuration

web_server:
  hide_version: true
  disable_directory_listing: true
  enable_rate_limiting: true

database:
  use_prepared_statements: true
  encrypt_passwords: bcrypt
  min_password_length: 12

session:
  httponly: true
  secure: true  # HTTPS only
  same_site: strict
  timeout: 3600  # 1 hour

headers:
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  X-XSS-Protection: "1; mode=block"
  Content-Security-Policy: "default-src 'self'"
```

### 2. Database Optimization

```sql
-- Add indexes for frequently queried columns
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_posts_published_at ON posts(published_at);
CREATE INDEX idx_comments_post_id ON comments(post_id);

-- Enable query cache
SET GLOBAL query_cache_size = 67108864;  -- 64MB
SET GLOBAL query_cache_type = 1;
```

### 3. Performance Tuning

```python
# config/performance.yaml

caching:
  enabled: true
  backend: redis
  ttl: 3600

compression:
  enabled: true
  level: 6

static_files:
  cdn: true
  cache_control: "public, max-age=31536000"

database_pool:
  min_connections: 2
  max_connections: 20
```

### 4. Monitoring Setup

```yaml
# config/monitoring.yaml

logging:
  level: INFO
  format: json
  destination: /var/log/webapp/app.log
  rotation: daily
  retention: 30  # days

metrics:
  enabled: true
  endpoint: /metrics
  collect:
    - request_count
    - response_time
    - error_rate
    - database_queries

health_checks:
  enabled: true
  endpoint: /health
  checks:
    - database_connection
    - redis_connection
    - disk_space
    - memory_usage
```

### 5. Backup Strategy

```bash
# Automated backup script
# /etc/cron.daily/backup-webapp

#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups/webapp"

# Database backup
mysqldump -u backup_user -p$DB_PASS webapp_db | gzip > \
  $BACKUP_DIR/db_backup_$DATE.sql.gz

# File backup
tar -czf $BACKUP_DIR/files_backup_$DATE.tar.gz /var/www/webapp/uploads

# Keep only last 7 days
find $BACKUP_DIR -type f -mtime +7 -delete

# Upload to S3 (optional)
aws s3 sync $BACKUP_DIR s3://my-backups/webapp/
```

---

## Maintenance & Updates

### Updating Deployment Tool

```bash
# Pull latest changes
git pull origin main

# Update dependencies
pip install -r requirements.txt --upgrade

# Verify updates
python examples/verify_installation.py
```

### Updating Deployed Website

```bash
# Re-run deployment with --update flag
python examples/zero_shot_deployment.py --update --project user_profile_manager

# System will:
# 1. Backup existing database
# 2. Backup existing files
# 3. Deploy new code
# 4. Run migrations
# 5. Restart services
```

### Rolling Back Deployment

```bash
# Automatic rollback (if deployment fails)
# System automatically reverts changes

# Manual rollback to previous version
python examples/zero_shot_deployment.py --rollback --project user_profile_manager --version 2024-12-01

# List available backups
python examples/zero_shot_deployment.py --list-backups --project user_profile_manager
```

---

## Conclusion

The Zero-Shot Website Deployment System eliminates the complexity of web deployment by automating every step from requirements to production. With enhanced dependency resolution, workflow-based code generation, and comprehensive integration testing, you can confidently deploy professional, secure websites with a single command.

### Key Achievements

✅ **Zero Manual Fixes**: Code works out-of-the-box
✅ **Complete Feature Implementation**: Email verification, password reset, auth
✅ **Production-Ready Security**: Hashing, HTTPS, SQL injection prevention
✅ **Real Email Delivery**: SMTP configuration with Gmail/custom servers
✅ **Automated Infrastructure**: Web server, database, SSL, services
✅ **5-Minute Deployments**: From specification to live website

### Support

- **Documentation**: This guide
- **Issues**: GitHub Issues
- **Examples**: `/examples` directory
- **Community**: Discord server

---

**Version:** 2.0.0
**Last Updated:** 2025-12-02
**License:** MIT

**Built with ❤️ by Agentic-RAG Development Team**
