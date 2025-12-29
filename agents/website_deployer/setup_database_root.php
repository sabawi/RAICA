<?php
/**
 * Database Setup Script
 *
 * This script creates the database and all required tables for the application.
 */

// Database connection details (using root user)
$host = 'localhost';
$dbname = 'securefish_tech_db';
$root_username = 'root';
$root_password = 'Down2earth!';
$app_username = 'webuser';
$app_password = 'webuser';

try {
    // Connect to MySQL as root to create database and user
    echo "Connecting to MySQL as root...\n";
    $pdo = new PDO("mysql:host=$host", $root_username, $root_password);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    
    // Create database
    echo "Creating database '$dbname'...\n";
    $pdo->exec("CREATE DATABASE IF NOT EXISTS `$dbname` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");
    echo "✅ Database created successfully\n";
    
    // Create user if not exists and grant privileges
    echo "Setting up database user...\n";
    $pdo->exec("CREATE USER IF NOT EXISTS '$app_username'@'localhost' IDENTIFIED BY '$app_password'");
    $pdo->exec("GRANT ALL PRIVILEGES ON `$dbname`.* TO '$app_username'@'localhost'");
    $pdo->exec("FLUSH PRIVILEGES");
    echo "✅ Database user created and privileges granted\n";
    
    // Connect to the specific database with app user
    echo "Connecting to database '$dbname' as '$app_username'...\n";
    $pdo = new PDO("mysql:host=$host;dbname=$dbname", $app_username, $app_password);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    
    // Create all tables
    echo "Creating tables...\n";
    
    // Create users table
    echo "Creating users table...\n";
    $sql = "CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        email VARCHAR(255) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        email_verified_at DATETIME NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )";
    $pdo->exec($sql);
    echo "✅ users table created successfully\n";
    
    // Create products table
    echo "Creating products table...\n";
    $sql = "CREATE TABLE IF NOT EXISTS products (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        price DECIMAL(10, 2) NOT NULL,
        stock_quantity INT DEFAULT 0,
        image_url VARCHAR(500),
        category VARCHAR(100),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )";
    $pdo->exec($sql);
    echo "✅ products table created successfully\n";
    
    // Create orders table
    echo "Creating orders table...\n";
    $sql = "CREATE TABLE IF NOT EXISTS orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        total_amount DECIMAL(10, 2) NOT NULL,
        status VARCHAR(50) DEFAULT 'pending',
        shipping_address TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )";
    $pdo->exec($sql);
    echo "✅ orders table created successfully\n";
    
    // Create order items table
    echo "Creating order_items table...\n";
    $sql = "CREATE TABLE IF NOT EXISTS order_items (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT NOT NULL,
        price DECIMAL(10, 2) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    )";
    $pdo->exec($sql);
    echo "✅ order_items table created successfully\n";
    
    // Create cart table
    echo "Creating cart table...\n";
    $sql = "CREATE TABLE IF NOT EXISTS cart (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    )";
    $pdo->exec($sql);
    echo "✅ cart table created successfully\n";
    
    echo "\n🎉 All database tables created successfully!\n";
    echo "Database: $dbname\n";
    echo "User: $app_username\n";
    echo "Host: $host\n";
    
} catch (Exception $e) {
    echo "❌ Error: " . $e->getMessage() . "\n";
    exit(1);
}

echo "\n✅ Database setup completed successfully!\n";
?>