<?php
/**
 * Database Setup Script
 *
 * This script creates the database and all required tables for the application.
 */

// Load configuration
require_once 'config/config.php';

// Database connection details (using the credentials from your request)
$host = 'localhost';
$dbname = 'securefish_tech_db';
$username = 'webuser';
$password = 'webuser';

try {
    // Connect to MySQL as root/admin to create database
    echo "Connecting to MySQL...\n";
    $pdo = new PDO("mysql:host=$host", $username, $password);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    
    // Create database
    echo "Creating database '$dbname'...\n";
    $pdo->exec("CREATE DATABASE IF NOT EXISTS `$dbname` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");
    echo "✅ Database created successfully\n";
    
    // Connect to the specific database
    echo "Connecting to database '$dbname'...\n";
    $pdo = new PDO("mysql:host=$host;dbname=$dbname", $username, $password);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    
    // Include all model files to get table creation methods
    echo "Loading model files...\n";
    require_once 'app/models/user.php';
    require_once 'app/models/product.php';
    require_once 'app/models/order.php';
    require_once 'app/models/orderitem.php';
    require_once 'app/models/cart.php';
    
    // Create all tables
    echo "Creating tables...\n";
    
    // Create users table
    $userModel = new User($pdo);
    if ($userModel->createTable()) {
        echo "✅ Users table created successfully\n";
    }
    
    // Create products table
    $productModel = new Product($pdo);
    if ($productModel->createTable()) {
        echo "✅ Products table created successfully\n";
    }
    
    // Create orders table
    $orderModel = new Order($pdo);
    if ($orderModel->createTable()) {
        echo "✅ Orders table created successfully\n";
    }
    
    // Create order items table
    $orderItemModel = new OrderItem($pdo);
    if ($orderItemModel->createTable()) {
        echo "✅ Order items table created successfully\n";
    }
    
    // Create cart table
    $cartModel = new Cart($pdo);
    if ($cartModel->createTable()) {
        echo "✅ Cart table created successfully\n";
    }
    
    echo "\n🎉 All database tables created successfully!\n";
    echo "Database: $dbname\n";
    echo "User: $username\n";
    echo "Host: $host\n";
    
} catch (Exception $e) {
    echo "❌ Error: " . $e->getMessage() . "\n";
    exit(1);
}

echo "\n✅ Database setup completed successfully!\n";
?>