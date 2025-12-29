<?php

/**
 * Main API Router
 *
 * This file serves as the central router for all API endpoints.
 * It directs requests to appropriate controllers based on the URL path.
 *
 * @package SecureFish Technologies
 * @version 1.0.0
 */

// Set default content type to JSON
header('Content-Type: application/json');

// Get the request URI and method
$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$method = $_SERVER['REQUEST_METHOD'];

// Route requests to appropriate controllers
try {
    // Authentication routes
    if (strpos($uri, '/api/auth/') === 0) {
        require_once __DIR__ . '/../app/controllers/auth.php';
        // The auth controller handles its own routing based on the URI
        return;
    }

    // Product routes
    if (strpos($uri, '/api/products') === 0) {
        // Load required files for products
        require_once __DIR__ . '/../config/config.php';
        require_once __DIR__ . '/../app/models/product.php';
        require_once __DIR__ . '/../app/services/product.php';
        require_once __DIR__ . '/../app/schemas/products.php';
        require_once __DIR__ . '/../app/controllers/products.php';

        // Create database connection
        $config = require __DIR__ . '/../config/config.php';
        $dsn = "mysql:host=" . $config['database']['host'] . ";dbname=" . $config['database']['dbname'] . ";charset=" . $config['database']['charset'];
        $pdo = new PDO($dsn, $config['database']['user'], $config['database']['pass']);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

        // Create service and controller instances
        $productService = new ProductService($pdo);
        $productController = new ProductController($productService);

        // Route to appropriate method based on URI and HTTP method
        if ($uri === '/api/products' && $method === 'GET') {
            $productController->getProducts($_GET);
            return;
        } elseif (preg_match('/^\/api\/products\/(\d+)$/', $uri, $matches) && $method === 'GET') {
            $productController->getProduct((int)$matches[1]);
            return;
        } elseif ($uri === '/api/products' && $method === 'POST') {
            $input = json_decode(file_get_contents('php://input'), true);
            $productController->createProduct($input);
            return;
        } elseif (preg_match('/^\/api\/products\/(\d+)$/', $uri, $matches) && $method === 'PUT') {
            $input = json_decode(file_get_contents('php://input'), true);
            $productController->updateProduct((int)$matches[1], $input);
            return;
        } elseif (preg_match('/^\/api\/products\/(\d+)$/', $uri, $matches) && $method === 'DELETE') {
            $productController->deleteProduct((int)$matches[1]);
            return;
        }
    }

    // Cart routes
    if (strpos($uri, '/api/cart/') === 0) {
        require_once __DIR__ . '/../app/controllers/cart.php';
        // The cart controller handles its own routing based on the URI
        return;
    }

    // Contact routes
    if ($uri === '/api/contact') {
        require_once __DIR__ . '/../app/controllers/contact.php';
        // The contact controller handles its own routing
        return;
    }

    // If no route matched, return 404
    http_response_code(404);
    echo json_encode(['error' => 'Endpoint not found']);
} catch (Exception $e) {
    // Handle any uncaught exceptions
    http_response_code(500);
    echo json_encode(['error' => 'Internal server error: ' . $e->getMessage()]);
}
?>