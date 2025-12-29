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
SUDO_PASS="Down2earth!"
WEB_PORT=8080

cd "$PROJECT_DIR"

echo "Step 1: Creating database..."
echo "$SUDO_PASS" | sudo -S mysql -u"$DB_USER" -e "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true
echo "$SUDO_PASS" | sudo -S mysql -u"$DB_USER" -e "CREATE DATABASE $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
echo "✓ Database created: $DB_NAME"
echo ""

echo "Step 2: Creating database schema..."
echo "$SUDO_PASS" | sudo -S mysql -u"$DB_USER" "$DB_NAME" <<'EOF'
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
DB_PASSWORD=$SUDO_PASS
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
    echo '✓ Database connection successful' . PHP_EOL;

    // Test tables
    \$stmt = \$pdo->query('SHOW TABLES');
    \$tables = \$stmt->fetchAll(PDO::FETCH_COLUMN);
    echo '✓ Found ' . count(\$tables) . ' tables: ' . implode(', ', \$tables) . PHP_EOL;

    // Insert test user
    \$stmt = \$pdo->prepare('INSERT INTO users (email, password_hash, first_name, last_name, bio) VALUES (?, ?, ?, ?, ?)');
    \$passwordHash = password_hash('password123', PASSWORD_DEFAULT);
    \$stmt->execute(['test@example.com', \$passwordHash, 'Test', 'User', 'This is a test user account']);
    echo '✓ Test user created: test@example.com / password123' . PHP_EOL;
} catch (PDOException \$e) {
    echo '✗ Database connection failed: ' . \$e->getMessage() . PHP_EOL;
    exit(1);
}
"
echo ""

echo "=========================================="
echo "✅ DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "📊 Test Credentials:"
echo "   Email: test@example.com"
echo "   Password: password123"
echo ""
echo "🌐 Starting PHP development server..."
echo "   URL: http://localhost:$WEB_PORT"
echo ""
echo "📝 Available Pages:"
echo "   • Landing Page: http://localhost:$WEB_PORT/"
echo "   • Login: http://localhost:$WEB_PORT/templates/login.php"
echo "   • Register: http://localhost:$WEB_PORT/templates/register.php"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""
echo "=========================================="
echo ""

# Start PHP server
php -S localhost:$WEB_PORT -t .
