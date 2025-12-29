#!/bin/bash
set -e

echo "=========================================="
echo "REMOTE WEBSITE DEPLOYMENT"
echo "=========================================="
echo ""

# Configuration
SSH_HOST="192.168.1.58"
SSH_USER="sabawi"
SSH_PASS="Down2earth!"
MYSQL_ROOT_PASS="Down2earth!"
DB_NAME="user_profile_db"
DB_WEB_USER="webuser"
DB_WEB_PASS="webuser"
WEB_PORT="6020"
APP_DIR="/var/www/user_profile_manager"
PROJECT_SRC="generated_projects/User Profile Management Website"

echo "📋 Deployment Configuration:"
echo "   Server: $SSH_USER@$SSH_HOST"
echo "   Database: $DB_NAME"
echo "   Web Port: $WEB_PORT (HTTPS)"
echo "   App Directory: $APP_DIR"
echo ""

# Test SSH connection
echo "Step 1: Testing SSH connection..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no $SSH_USER@$SSH_HOST 'echo "✓ SSH Connected"'
echo ""

# Create database and user
echo "Step 2: Setting up MySQL database..."
sshpass -p "$SSH_PASS" ssh $SSH_USER@$SSH_HOST "echo '$SSH_PASS' | sudo -S mysql -u root -p'$MYSQL_ROOT_PASS' <<'EOSQL'
DROP DATABASE IF EXISTS $DB_NAME;
CREATE DATABASE $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

DROP USER IF EXISTS '$DB_WEB_USER'@'localhost';
CREATE USER '$DB_WEB_USER'@'localhost' IDENTIFIED BY '$DB_WEB_PASS';
GRANT SELECT, INSERT, UPDATE, DELETE ON $DB_NAME.* TO '$DB_WEB_USER'@'localhost';
FLUSH PRIVILEGES;

USE $DB_NAME;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(20),
    address TEXT,
    bio TEXT,
    email_verified BOOLEAN DEFAULT FALSE,
    email_verified_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP NULL,
    is_active BOOLEAN DEFAULT TRUE,
    INDEX idx_email (email),
    INDEX idx_verified (email_verified),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE email_verification_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_token (token),
    INDEX idx_user (user_id),
    INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE password_reset_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_token (token),
    INDEX idx_user (user_id),
    INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
EOSQL
"

echo "✓ Database and tables created"
echo ""

# Create application directory
echo "Step 3: Creating application directory..."
sshpass -p "$SSH_PASS" ssh $SSH_USER@$SSH_HOST "echo '$SSH_PASS' | sudo -S mkdir -p $APP_DIR && echo '$SSH_PASS' | sudo -S chown $SSH_USER:$SSH_USER $APP_DIR"
echo "✓ Directory created: $APP_DIR"
echo ""

# Transfer application files
echo "Step 4: Transferring application files..."
sshpass -p "$SSH_PASS" scp -r -o StrictHostKeyChecking=no "$PROJECT_SRC"/* $SSH_USER@$SSH_HOST:$APP_DIR/
echo "✓ Files transferred"
echo ""

# Create .env file on remote server
echo "Step 5: Creating configuration files..."
sshpass -p "$SSH_PASS" ssh $SSH_USER@$SSH_HOST "cat > $APP_DIR/.env <<'ENVEOF'
# Application
APP_NAME=User Profile Manager
APP_ENV=production
APP_DEBUG=false
APP_URL=https://$SSH_HOST:$WEB_PORT
APP_TIMEZONE=UTC

# Database
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=$DB_NAME
DB_USERNAME=$DB_WEB_USER
DB_PASSWORD=$DB_WEB_PASS
DB_CHARSET=utf8mb4
DB_COLLATION=utf8mb4_unicode_ci

# Security
CSRF_TOKEN_SECRET=production_csrf_secret_change_this
BCRYPT_ROUNDS=12
SESSION_NAME=user_profile_session
SESSION_LIFETIME=120
SESSION_SECURE_COOKIE=true
SESSION_HTTP_ONLY=true
SESSION_SAME_SITE=Lax

# Email
MAIL_DRIVER=smtp
MAIL_HOST=localhost
MAIL_PORT=25
MAIL_FROM_ADDRESS=noreply@192.168.1.58
MAIL_FROM_NAME=User Profile Manager

# Logging
LOG_LEVEL=info
ENVEOF
"
echo "✓ Configuration created"
echo ""

# Set permissions
echo "Step 6: Setting permissions..."
sshpass -p "$SSH_PASS" ssh $SSH_USER@$SSH_HOST "
echo '$SSH_PASS' | sudo -S chown -R www-data:www-data $APP_DIR
echo '$SSH_PASS' | sudo -S chmod -R 755 $APP_DIR
echo '$SSH_PASS' | sudo -S mkdir -p $APP_DIR/storage/logs
echo '$SSH_PASS' | sudo -S chown -R www-data:www-data $APP_DIR/storage
echo '$SSH_PASS' | sudo -S chmod -R 775 $APP_DIR/storage
"
echo "✓ Permissions set"
echo ""

# Configure Apache for port 6020 with HTTPS
echo "Step 7: Configuring Apache web server..."
sshpass -p "$SSH_PASS" ssh $SSH_USER@$SSH_HOST "echo '$SSH_PASS' | sudo -S bash <<'APACHE_CONFIG'
# Add Listen directive for port 6020 if not already present
if ! grep -q 'Listen 6020' /etc/apache2/ports.conf; then
    echo 'Listen 6020' >> /etc/apache2/ports.conf
fi

# Enable required Apache modules
a2enmod ssl
a2enmod rewrite
a2enmod headers

# Create self-signed SSL certificate (for testing)
if [ ! -f /etc/ssl/certs/apache-selfsigned.crt ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/ssl/private/apache-selfsigned.key \
        -out /etc/ssl/certs/apache-selfsigned.crt \
        -subj '/CN=192.168.1.58'
fi

# Create Apache virtual host configuration
cat > /etc/apache2/sites-available/user-profile.conf <<'VHOST'
<VirtualHost *:6020>
    ServerName 192.168.1.58
    DocumentRoot $APP_DIR

    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/apache-selfsigned.crt
    SSLCertificateKeyFile /etc/ssl/private/apache-selfsigned.key

    <Directory $APP_DIR>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted

        # Redirect to login page by default
        DirectoryIndex login_simple.php index.php

        # Enable PHP
        <FilesMatch \\.php$>
            SetHandler application/x-httpd-php
        </FilesMatch>
    </Directory>

    ErrorLog \${APACHE_LOG_DIR}/user-profile-error.log
    CustomLog \${APACHE_LOG_DIR}/user-profile-access.log combined
</VirtualHost>
VHOST

# Enable the site
a2ensite user-profile.conf

# Restart Apache
systemctl restart apache2

echo '✓ Apache configured and restarted'
APACHE_CONFIG
"
echo ""

# Test database connection
echo "Step 8: Testing database connection..."
sshpass -p "$SSH_PASS" ssh $SSH_USER@$SSH_HOST "php -r \"
\\\$dsn = 'mysql:host=127.0.0.1;port=3306;dbname=$DB_NAME;charset=utf8mb4';
try {
    \\\$pdo = new PDO(\\\$dsn, '$DB_WEB_USER', '$DB_WEB_PASS');
    \\\$stmt = \\\$pdo->query('SHOW TABLES');
    \\\$tables = \\\$stmt->fetchAll(PDO::FETCH_COLUMN);
    echo '✓ Database connection successful\n';
    echo '✓ Tables: ' . implode(', ', \\\$tables) . '\n';
} catch (PDOException \\\$e) {
    echo '✗ Database error: ' . \\\$e->getMessage() . '\n';
    exit(1);
}
\""
echo ""

echo "=========================================="
echo "✅ DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "🌐 Website URL: https://192.168.1.58:6020/"
echo "📄 Landing Page: https://192.168.1.58:6020/login_simple.php"
echo ""
echo "📊 Database:"
echo "   Name: $DB_NAME"
echo "   User: $DB_WEB_USER"
echo "   Tables: users, email_verification_tokens, password_reset_tokens"
echo ""
echo "📁 Application:"
echo "   Directory: $APP_DIR"
echo "   Owner: www-data"
echo ""
echo "🔒 Security:"
echo "   SSL: Enabled (self-signed certificate)"
echo "   HTTPS: Yes"
echo "   Port: 6020"
echo ""
echo "⚠️  Note: You may need to accept the self-signed certificate in your browser"
echo ""
echo "=========================================="
