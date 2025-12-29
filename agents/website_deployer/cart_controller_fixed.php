<?php

/**
 * Cart Controller
 *
 * This file contains the API endpoints for cart operations.
 * It handles HTTP requests related to shopping cart management,
 * including adding and removing items from the cart.
 *
 * @package SecureFish Technologies
 * @version 1.0.0
 */

require_once __DIR__ . '/../../config/config.php';
require_once __DIR__ . '/../services/cart.php';
require_once __DIR__ . '/../models/cart.php';

/**
 * CartController class
 *
 * Provides RESTful API endpoints for cart operations.
 * Handles authentication, input validation, and response formatting.
 */
class CartController
{
    /**
     * @var CartService The cart service instance
     */
    private CartService $cartService;

    /**
     * @var array<string, mixed> The application configuration
     */
    private array $config;

    /**
     * CartController constructor.
     *
     * @param CartService $cartService The cart service instance
     * @param array<string, mixed> $config The application configuration
     */
    public function __construct(CartService $cartService, array $config)
    {
        $this->cartService = $cartService;
        $this->config = $config;
    }

    /**
     * Handle POST /api/cart/add request
     *
     * Adds an item to the user's shopping cart.
     *
     * @return void
     */
    public function addToCart(): void
    {
        // Set content type to JSON
        header('Content-Type: application/json');

        try {
            // Check if request method is POST
            if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
                http_response_code(405);
                echo json_encode(['message' => 'Method not allowed']);
                return;
            }

            // Check authentication (simplified for this example)
            // In a real application, you would verify a JWT token or session
            $userId = $this->getAuthenticatedUserId();
            if (!$userId) {
                http_response_code(401);
                echo json_encode(['message' => 'Unauthorized']);
                return;
            }

            // Get JSON input
            $input = json_decode(file_get_contents('php://input'), true);

            // Validate JSON input
            if (json_last_error() !== JSON_ERROR_NONE) {
                http_response_code(400);
                echo json_encode(['message' => 'Invalid JSON input']);
                return;
            }

            // Validate required fields
            if (!isset($input['product_id']) || !is_numeric($input['product_id']) || (int)$input['product_id'] <= 0) {
                http_response_code(400);
                echo json_encode(['message' => 'Product ID must be a positive integer']);
                return;
            }

            if (!isset($input['quantity']) || !is_numeric($input['quantity']) || (int)$input['quantity'] <= 0) {
                http_response_code(400);
                echo json_encode(['message' => 'Quantity must be a positive integer']);
                return;
            }

            // Add user_id to input data
            $input['user_id'] = $userId;

            // Call service to add item to cart
            $result = $this->cartService->addToCart($input);

            // Handle response
            if ($result['success']) {
                http_response_code(200);
                echo json_encode(['message' => $result['message']]);
            } else {
                http_response_code(400);
                echo json_encode([
                    'message' => $result['message'],
                    'errors' => $result['errors'] ?? []
                ]);
            }
        } catch (Exception $e) {
            http_response_code(500);
            echo json_encode(['message' => 'Internal server error']);
        }
    }

    /**
     * Handle DELETE /api/cart/remove request
     *
     * Removes an item from the user's shopping cart.
     *
     * @return void
     */
    public function removeFromCart(): void
    {
        // Set content type to JSON
        header('Content-Type: application/json');

        try {
            // Check if request method is DELETE
            if ($_SERVER['REQUEST_METHOD'] !== 'DELETE') {
                http_response_code(405);
                echo json_encode(['message' => 'Method not allowed']);
                return;
            }

            // Check authentication (simplified for this example)
            // In a real application, you would verify a JWT token or session
            $userId = $this->getAuthenticatedUserId();
            if (!$userId) {
                http_response_code(401);
                echo json_encode(['message' => 'Unauthorized']);
                return;
            }

            // Get JSON input
            $input = json_decode(file_get_contents('php://input'), true);

            // Validate JSON input
            if (json_last_error() !== JSON_ERROR_NONE) {
                http_response_code(400);
                echo json_encode(['message' => 'Invalid JSON input']);
                return;
            }

            // Validate required fields
            if (!isset($input['item_id']) || !is_numeric($input['item_id']) || (int)$input['item_id'] <= 0) {
                http_response_code(400);
                echo json_encode(['message' => 'Item ID must be a positive integer']);
                return;
            }

            // Add user_id to input data
            $input['user_id'] = $userId;

            // This would typically be handled in the service or model layer
            // For now, we'll proceed with the removal

            // Call service to remove item from cart
            $result = $this->cartService->removeFromCart($input);

            // Handle response
            if ($result['success']) {
                http_response_code(200);
                echo json_encode(['message' => $result['message']]);
            } else {
                // Check if it's a not found error
                if ($result['message'] === 'Failed to remove item from cart') {
                    http_response_code(404);
                } else {
                    http_response_code(400);
                }
                echo json_encode([
                    'message' => $result['message'],
                    'errors' => $result['errors'] ?? []
                ]);
            }
        } catch (Exception $e) {
            http_response_code(500);
            echo json_encode(['message' => 'Internal server error']);
        }
    }

    /**
     * Get authenticated user ID
     *
     * In a real application, this would verify a JWT token or session
     * and return the authenticated user's ID.
     *
     * @return int|null The authenticated user ID or null if not authenticated
     */
    private function getAuthenticatedUserId(): ?int
    {
        // This is a placeholder implementation
        // In a real application, you would:
        // 1. Check for an Authorization header with a JWT token
        // 2. Validate the token
        // 3. Extract the user ID from the token
        // 4. Return the user ID if valid, null otherwise

        // For demonstration purposes, we're returning a fixed user ID
        // In reality, you should implement proper authentication
        return 1; // Assuming user ID 1 is authenticated
    }
}

// Initialize and run the controller based on the request URI
try {
    // Get the request URI and method
    $uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $method = $_SERVER['REQUEST_METHOD'];

    // Database connection
    $config = require_once __DIR__ . '/../../config/config.php';
    $dsn = "mysql:host={$config['database']['host']};dbname={$config['database']['dbname']};charset={$config['database']['charset']}";
    $pdo = new PDO($dsn, $config['database']['user'], $config['database']['pass']);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

    // Initialize cart model and service
    $cartModel = new Cart($pdo);
    $cartService = new CartService($cartModel);

    // Initialize controller
    $controller = new CartController($cartService, $config);

    // Route requests
    if ($uri === '/api/cart/add' && $method === 'POST') {
        $controller->addToCart();
    } elseif ($uri === '/api/cart/remove' && $method === 'DELETE') {
        $controller->removeFromCart();
    } else {
        // 404 Not Found for undefined routes
        http_response_code(404);
        header('Content-Type: application/json');
        echo json_encode(['message' => 'Endpoint not found']);
    }
} catch (Exception $e) {
    // Handle any uncaught exceptions
    http_response_code(500);
    header('Content-Type: application/json');
    echo json_encode(['message' => 'Internal server error']);
}