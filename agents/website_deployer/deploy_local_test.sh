#!/bin/bash
set -e

echo "=========================================="
echo "LOCAL DEPLOYMENT TEST"
echo "=========================================="
echo ""

# Configuration
PROJECT_DIR="generated_projects/User Profile Management Website"
DB_NAME="user_profiles_test"
DB_USER="root"
DB_PASS="Down2earth!"
WEB_PORT=8080

cd "$PROJECT_DIR"

echo "Step 1: Creating database..."
mysql -u"$DB_USER" -p"$DB_PASS" -e "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true
mysql -u"$DB_USER" -p"$DB_PASS" -e "CREATE DATABASE $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
echo "✓ Database created: $DB_NAME"
echo ""

echo "Step 2: Creating database schema..."
mysql -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" <<'EOF'
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(20),
    address TEXT,
    bio TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP NULL,
    is_active BOOLEAN DEFAULT TRUE,
    INDEX idx_email (email),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS email_verification_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_token (token),
    INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_token (token),
    INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
EOF
echo "✓ Database schema created"
echo ""

echo "Step 3: Creating .env file..."
cat > .env <<ENVEOF
# Application
APP_NAME="User Profile Management"
APP_ENV=development
APP_DEBUG=true
APP_URL=http://localhost:$WEB_PORT
APP_TIMEZONE=UTC
APP_KEY=$(openssl rand -base64 32)

# Database
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=$DB_NAME
DB_USERNAME=$DB_USER
DB_PASSWORD=$DB_PASS
DB_CHARSET=utf8mb4
DB_COLLATION=utf8mb4_unicode_ci

# Security
CSRF_TOKEN_SECRET=$(openssl rand -hex 32)
BCRYPT_ROUNDS=10
SESSION_NAME=user_profile_session
SESSION_LIFETIME=120
SESSION_SECURE_COOKIE=false
SESSION_HTTP_ONLY=true
SESSION_SAME_SITE=Lax

# Mail (optional - for testing)
MAIL_DRIVER=log
MAIL_FROM_ADDRESS=noreply@localhost
MAIL_FROM_NAME="User Profile Management"

# Logging
LOG_LEVEL=debug
ENVEOF
echo "✓ .env file created"
echo ""

echo "Step 4: Creating storage directory..."
mkdir -p storage/logs
chmod 755 storage
chmod 755 storage/logs
echo "✓ Storage directory created"
echo ""

echo "Step 5: Testing database connection..."
php -r "
\$config = require 'config/config.php';
\$dbConfig = \$config['database']['connections'][\$config['database']['default']];
try {
    \$dsn = sprintf(
        '%s:host=%s;port=%d;dbname=%s;charset=%s',
        \$dbConfig['driver'],
        \$dbConfig['host'],
        \$dbConfig['port'],
        \$dbConfig['database'],
        \$dbConfig['charset']
    );
    \$pdo = new PDO(\$dsn, \$dbConfig['username'], \$dbConfig['password'], \$dbConfig['options']);
    echo '✓ Database connection successful\n';

    // Test tables
    \$stmt = \$pdo->query('SHOW TABLES');
    \$tables = \$stmt->fetchAll(PDO::FETCH_COLUMN);
    echo '✓ Found ' . count(\$tables) . ' tables: ' . implode(', ', \$tables) . '\n';
} catch (PDOException \$e) {
    echo '✗ Database connection failed: ' . \$e->getMessage() . '\n';
    exit(1);
}
"
echo ""

echo "=========================================="
echo "✅ DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "Starting PHP development server on port $WEB_PORT..."
echo "Access the website at: http://localhost:$WEB_PORT"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""
echo "=========================================="
echo ""

# Start PHP server
php -S localhost:$WEB_PORT -t .
