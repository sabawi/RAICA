#!/usr/bin/env python3
"""
Workflow-Based Code Generator
==============================

Generates code based on complete workflows rather than individual files.
Ensures end-to-end feature implementation with proper integration.

Key Features:
- Workflow-level specifications (e.g., "User Registration Flow")
- Step-by-step code generation with context awareness
- Automatic integration verification
- Email verification enforcement
- Password reset flow generation
- Authentication workflow generation
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """Single step in a workflow."""
    step_number: int
    action: str
    description: str
    files_involved: List[str] = field(default_factory=list)
    database_operations: List[str] = field(default_factory=list)
    functions_called: List[str] = field(default_factory=list)
    validation_required: List[str] = field(default_factory=list)
    success_action: Optional[str] = None
    error_action: Optional[str] = None


@dataclass
class Workflow:
    """Complete workflow specification."""
    name: str
    trigger: str
    description: str
    steps: List[WorkflowStep] = field(default_factory=list)
    files_generated: List[str] = field(default_factory=list)
    integration_tests: List[str] = field(default_factory=list)
    security_requirements: List[str] = field(default_factory=list)


class WorkflowGenerator:
    """
    Generates code following complete workflows to ensure proper integration.

    Example:
        generator = WorkflowGenerator(tech_stack="php_plain")

        # Generate registration workflow
        workflow = generator.generate_registration_workflow(
            with_email_verification=True
        )

        # Generate files for workflow
        files = generator.generate_workflow_files(workflow)
    """

    def __init__(self, tech_stack: str = "php_plain"):
        self.tech_stack = tech_stack
        self.workflows: Dict[str, Workflow] = {}

    def generate_registration_workflow(
        self,
        with_email_verification: bool = True,
        project_name: str = "app"
    ) -> Workflow:
        """
        Generate complete user registration workflow.

        Args:
            with_email_verification: Include email verification
            project_name: Project name for email context

        Returns:
            Complete Workflow specification
        """
        workflow = Workflow(
            name="User Registration",
            trigger="User visits registration page",
            description="Complete user registration flow with email verification",
            security_requirements=[
                "Password must be hashed with password_hash()",
                "Email must be unique in database",
                "SQL injection prevention with prepared statements",
                "XSS prevention with htmlspecialchars()",
                "CSRF token validation"
            ]
        )

        # Step 1: Display registration form
        workflow.steps.append(WorkflowStep(
            step_number=1,
            action="Display Registration Form",
            description="Show registration form to user",
            files_involved=["templates/register_simple.php"],
            validation_required=[],
            success_action="User sees form with email, password, name fields"
        ))

        # Step 2: Handle form submission
        workflow.steps.append(WorkflowStep(
            step_number=2,
            action="Receive Form Submission",
            description="Process POST request with registration data",
            files_involved=["templates/register_simple.php"],
            validation_required=[
                "Check if method is POST",
                "Validate email format with filter_var(FILTER_VALIDATE_EMAIL)",
                "Check password length >= 6 characters",
                "Verify password confirmation matches",
                "Sanitize first_name and last_name with htmlspecialchars()"
            ],
            error_action="Re-display form with error messages"
        ))

        # Step 3: Check email uniqueness
        workflow.steps.append(WorkflowStep(
            step_number=3,
            action="Check Email Uniqueness",
            description="Verify email doesn't already exist in database",
            files_involved=["templates/register_simple.php"],
            database_operations=[
                "SELECT id FROM users WHERE email = ?"
            ],
            error_action="Return error: 'Email already registered'"
        ))

        if with_email_verification:
            # Step 4: Begin transaction
            workflow.steps.append(WorkflowStep(
                step_number=4,
                action="Begin Database Transaction",
                description="Start transaction for atomic user creation + token generation",
                files_involved=["templates/register_simple.php"],
                database_operations=["$pdo->beginTransaction()"]
            ))

            # Step 5: Create user with email_verified=0
            workflow.steps.append(WorkflowStep(
                step_number=5,
                action="Create User Record",
                description="Insert user into database with email_verified=0",
                files_involved=["templates/register_simple.php"],
                database_operations=[
                    "INSERT INTO users (email, password_hash, first_name, last_name, email_verified) VALUES (?, ?, ?, ?, 0)"
                ],
                functions_called=["password_hash($password, PASSWORD_DEFAULT)"]
            ))

            # Step 6: Generate verification token
            workflow.steps.append(WorkflowStep(
                step_number=6,
                action="Generate Verification Token",
                description="Create unique 64-character token with 24-hour expiration",
                files_involved=["templates/register_simple.php"],
                database_operations=[
                    "INSERT INTO email_verification_tokens (user_id, token, expires_at) VALUES (?, ?, ?)"
                ],
                functions_called=[
                    "bin2hex(random_bytes(32))",
                    "date('Y-m-d H:i:s', strtotime('+24 hours'))"
                ]
            ))

            # Step 7: Commit transaction
            workflow.steps.append(WorkflowStep(
                step_number=7,
                action="Commit Transaction",
                description="Commit both user and token creation",
                files_involved=["templates/register_simple.php"],
                database_operations=["$pdo->commit()"],
                error_action="$pdo->rollBack() on any failure"
            ))

            # Step 8: Send verification email
            workflow.steps.append(WorkflowStep(
                step_number=8,
                action="Send Verification Email",
                description="Email user with verification link",
                files_involved=[
                    "templates/register_simple.php",
                    "includes/email_helper.php"
                ],
                functions_called=[
                    "send_verification_email($email, $verificationLink)"
                ],
                success_action="Display: 'Registration successful! Check your email to verify.'"
            ))

            # Add email verification workflow files
            workflow.files_generated.extend([
                "templates/register_simple.php",
                "includes/email_helper.php",
                "templates/verify-email.php",
                "config/config.php"
            ])

            # Integration tests
            workflow.integration_tests.extend([
                "Register user → User created with email_verified=0",
                "Register user → Verification token created in database",
                "Register user → Verification email sent",
                "Register user → Cannot login until email verified",
                "Click verification link → Email verified → Can login"
            ])

        else:
            # Without email verification - simpler flow
            workflow.steps.append(WorkflowStep(
                step_number=4,
                action="Create User Record",
                description="Insert user into database",
                files_involved=["templates/register_simple.php"],
                database_operations=[
                    "INSERT INTO users (email, password_hash, first_name, last_name) VALUES (?, ?, ?, ?)"
                ],
                functions_called=["password_hash($password, PASSWORD_DEFAULT)"],
                success_action="Redirect to login page"
            ))

            workflow.files_generated.extend([
                "templates/register_simple.php",
                "config/config.php"
            ])

        return workflow

    def generate_email_verification_workflow(self) -> Workflow:
        """Generate email verification workflow."""
        workflow = Workflow(
            name="Email Verification",
            trigger="User clicks verification link in email",
            description="Verify user's email address using token",
            security_requirements=[
                "Token must be checked for expiration",
                "Token must be deleted after use (one-time use)",
                "User must exist and not already be verified"
            ]
        )

        # Step 1: Receive token
        workflow.steps.append(WorkflowStep(
            step_number=1,
            action="Receive Token from URL",
            description="Get token from query parameter",
            files_involved=["templates/verify-email.php"],
            validation_required=["Check token parameter exists"]
        ))

        # Step 2: Validate token
        workflow.steps.append(WorkflowStep(
            step_number=2,
            action="Validate Token",
            description="Check token exists in database and is not expired",
            files_involved=["templates/verify-email.php"],
            database_operations=[
                "SELECT user_id, expires_at FROM email_verification_tokens WHERE token = ? AND expires_at > NOW()"
            ],
            error_action="Display: 'Invalid or expired verification link'"
        ))

        # Step 3: Update user
        workflow.steps.append(WorkflowStep(
            step_number=3,
            action="Mark Email as Verified",
            description="Set email_verified=1 and email_verified_at=NOW()",
            files_involved=["templates/verify-email.php"],
            database_operations=[
                "UPDATE users SET email_verified=1, email_verified_at=NOW() WHERE id=?"
            ]
        ))

        # Step 4: Delete token
        workflow.steps.append(WorkflowStep(
            step_number=4,
            action="Delete Used Token",
            description="Remove token from database (one-time use)",
            files_involved=["templates/verify-email.php"],
            database_operations=[
                "DELETE FROM email_verification_tokens WHERE token=?"
            ],
            success_action="Display: 'Email verified! You can now login.' Redirect to login after 3 seconds"
        ))

        workflow.files_generated = ["templates/verify-email.php", "config/config.php"]

        workflow.integration_tests = [
            "Valid token → Email verified → Token deleted",
            "Expired token → Error shown",
            "Used token → Error shown (already deleted)",
            "After verification → Can login successfully"
        ]

        return workflow

    def generate_login_workflow(self, with_email_verification_check: bool = True) -> Workflow:
        """Generate login workflow."""
        workflow = Workflow(
            name="User Login",
            trigger="User submits login form",
            description="Authenticate user and create session",
            security_requirements=[
                "Password verification with password_verify()",
                "Session security with httponly and secure flags",
                "Prevent timing attacks",
                "Rate limiting (optional)"
            ]
        )

        # Step 1: Display form
        workflow.steps.append(WorkflowStep(
            step_number=1,
            action="Display Login Form",
            description="Show login form with email and password fields",
            files_involved=["templates/login_simple.php"]
        ))

        # Step 2: Validate input
        workflow.steps.append(WorkflowStep(
            step_number=2,
            action="Validate Input",
            description="Check email and password are provided",
            files_involved=["templates/login_simple.php"],
            validation_required=[
                "Email field is not empty",
                "Password field is not empty"
            ],
            error_action="Display: 'Email and password are required'"
        ))

        # Step 3: Query user
        workflow.steps.append(WorkflowStep(
            step_number=3,
            action="Query User from Database",
            description="Fetch user record by email",
            files_involved=["templates/login_simple.php"],
            database_operations=[
                "SELECT id, email, password_hash, first_name, last_name, email_verified FROM users WHERE email=?"
            ]
        ))

        # Step 4: Verify password
        workflow.steps.append(WorkflowStep(
            step_number=4,
            action="Verify Password",
            description="Check password matches hash",
            files_involved=["templates/login_simple.php"],
            functions_called=["password_verify($password, $user['password_hash'])"],
            error_action="Display: 'Invalid email or password'"
        ))

        if with_email_verification_check:
            # Step 5: Check email verified
            workflow.steps.append(WorkflowStep(
                step_number=5,
                action="Check Email Verification Status",
                description="Ensure user has verified their email",
                files_involved=["templates/login_simple.php"],
                validation_required=["$user['email_verified'] == 1"],
                error_action="Display: 'Please verify your email before logging in. Check your inbox.'"
            ))

        # Step 6: Create session
        workflow.steps.append(WorkflowStep(
            step_number=6,
            action="Create Session",
            description="Store user info in session and redirect to dashboard",
            files_involved=["templates/login_simple.php"],
            functions_called=[
                "$_SESSION['user_id'] = $user['id']",
                "$_SESSION['user_email'] = $user['email']",
                "$_SESSION['user_name'] = $user['first_name'] . ' ' . $user['last_name']"
            ],
            database_operations=[
                "UPDATE users SET last_login_at=NOW() WHERE id=?"
            ],
            success_action="Redirect to dashboard_simple.php"
        ))

        workflow.files_generated = ["templates/login_simple.php", "config/config.php"]

        workflow.integration_tests = [
            "Valid credentials + verified email → Login successful",
            "Valid credentials + unverified email → Login blocked",
            "Invalid password → Error shown",
            "Non-existent email → Error shown",
            "After login → Session created → Can access dashboard"
        ]

        return workflow

    def generate_forgot_password_workflow(self) -> Workflow:
        """Generate forgot password workflow."""
        workflow = Workflow(
            name="Forgot Password",
            trigger="User clicks 'Forgot Password' link",
            description="Request password reset via email",
            security_requirements=[
                "Rate limiting on reset requests",
                "Token expires after 1 hour",
                "Token is one-time use only",
                "Don't reveal if email exists or not"
            ]
        )

        # Steps...
        workflow.steps.extend([
            WorkflowStep(
                step_number=1,
                action="Display Email Input Form",
                description="Show form to enter email address",
                files_involved=["templates/forgot-password.php"]
            ),
            WorkflowStep(
                step_number=2,
                action="Validate Email",
                description="Check email format is valid",
                files_involved=["templates/forgot-password.php"],
                validation_required=["filter_var($email, FILTER_VALIDATE_EMAIL)"]
            ),
            WorkflowStep(
                step_number=3,
                action="Query User",
                description="Check if user with email exists",
                files_involved=["templates/forgot-password.php"],
                database_operations=["SELECT id FROM users WHERE email=?"]
            ),
            WorkflowStep(
                step_number=4,
                action="Generate Reset Token",
                description="Create password reset token with 1-hour expiration",
                files_involved=["templates/forgot-password.php"],
                database_operations=[
                    "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)"
                ],
                functions_called=[
                    "bin2hex(random_bytes(32))",
                    "date('Y-m-d H:i:s', strtotime('+1 hour'))"
                ]
            ),
            WorkflowStep(
                step_number=5,
                action="Send Reset Email",
                description="Email user with password reset link",
                files_involved=["templates/forgot-password.php", "includes/email_helper.php"],
                functions_called=["send_password_reset_email($email, $resetLink)"],
                success_action="Display: 'If email exists, reset link has been sent.'"
            )
        ])

        workflow.files_generated = [
            "templates/forgot-password.php",
            "includes/email_helper.php",
            "config/config.php"
        ]

        return workflow

    def generate_password_reset_workflow(self) -> Workflow:
        """Generate password reset workflow."""
        workflow = Workflow(
            name="Password Reset",
            trigger="User clicks reset link in email",
            description="Reset password using token",
            security_requirements=[
                "Token must be valid and not expired",
                "New password must meet strength requirements",
                "Token deleted after successful reset"
            ]
        )

        # Steps...
        workflow.steps.extend([
            WorkflowStep(
                step_number=1,
                action="Validate Reset Token",
                description="Check token exists and is not expired",
                files_involved=["templates/reset-password.php"],
                database_operations=[
                    "SELECT user_id, expires_at FROM password_reset_tokens WHERE token=? AND expires_at>NOW()"
                ],
                error_action="Display: 'Invalid or expired reset link'"
            ),
            WorkflowStep(
                step_number=2,
                action="Display Password Reset Form",
                description="Show form to enter new password",
                files_involved=["templates/reset-password.php"]
            ),
            WorkflowStep(
                step_number=3,
                action="Validate New Password",
                description="Check password strength and confirmation match",
                files_involved=["templates/reset-password.php"],
                validation_required=[
                    "Password length >= 6",
                    "Password == Password confirmation"
                ]
            ),
            WorkflowStep(
                step_number=4,
                action="Update Password",
                description="Hash new password and update user record",
                files_involved=["templates/reset-password.php"],
                database_operations=[
                    "UPDATE users SET password_hash=? WHERE id=?"
                ],
                functions_called=["password_hash($newPassword, PASSWORD_DEFAULT)"]
            ),
            WorkflowStep(
                step_number=5,
                action="Delete Reset Token",
                description="Remove used token from database",
                files_involved=["templates/reset-password.php"],
                database_operations=["DELETE FROM password_reset_tokens WHERE token=?"],
                success_action="Display: 'Password reset successful! You can now login.' Redirect to login"
            )
        ])

        workflow.files_generated = ["templates/reset-password.php", "config/config.php"]

        return workflow

    def generate_all_auth_workflows(self, with_email_verification: bool = True) -> List[Workflow]:
        """
        Generate all authentication-related workflows.

        Args:
            with_email_verification: Include email verification

        Returns:
            List of all auth workflows
        """
        workflows = []

        # Registration
        workflows.append(self.generate_registration_workflow(
            with_email_verification=with_email_verification
        ))

        # Email verification (if enabled)
        if with_email_verification:
            workflows.append(self.generate_email_verification_workflow())

        # Login
        workflows.append(self.generate_login_workflow(
            with_email_verification_check=with_email_verification
        ))

        # Password reset
        workflows.append(self.generate_forgot_password_workflow())
        workflows.append(self.generate_password_reset_workflow())

        return workflows

    def generate_workflow_prompt(self, workflow: Workflow, file_path: str) -> str:
        """
        Generate detailed LLM prompt for a specific file in the workflow.

        Args:
            workflow: Workflow specification
            file_path: File to generate

        Returns:
            Detailed prompt for code generation
        """
        # Filter steps involving this file
        relevant_steps = [s for s in workflow.steps if file_path in s.files_involved]

        prompt = f"""
WORKFLOW-BASED CODE GENERATION
===============================

Workflow: {workflow.name}
Trigger: {workflow.trigger}
Description: {workflow.description}

File to Generate: {file_path}
Tech Stack: {self.tech_stack}

SECURITY REQUIREMENTS:
"""
        for req in workflow.security_requirements:
            prompt += f"- {req}\n"

        prompt += f"""

WORKFLOW STEPS (for this file):
"""

        for step in relevant_steps:
            prompt += f"""
Step {step.step_number}: {step.action}
  Description: {step.description}
"""
            if step.validation_required:
                prompt += "  Validations:\n"
                for validation in step.validation_required:
                    prompt += f"    - {validation}\n"

            if step.database_operations:
                prompt += "  Database Operations:\n"
                for op in step.database_operations:
                    prompt += f"    - {op}\n"

            if step.functions_called:
                prompt += "  Functions to Call:\n"
                for func in step.functions_called:
                    prompt += f"    - {func}\n"

            if step.success_action:
                prompt += f"  Success Action: {step.success_action}\n"

            if step.error_action:
                prompt += f"  Error Action: {step.error_action}\n"

        prompt += f"""

INTEGRATION REQUIREMENTS:
This file is part of a complete workflow and must integrate with:
"""
        for other_file in workflow.files_generated:
            if other_file != file_path:
                prompt += f"- {other_file}\n"

        prompt += f"""

INTEGRATION TESTS (must pass):
"""
        for test in workflow.integration_tests:
            prompt += f"- {test}\n"

        prompt += """

IMPORTANT CODE GENERATION RULES:
1. Generate COMPLETE, WORKING code - not pseudocode
2. Include ALL steps from the workflow
3. Use proper error handling for each step
4. Validate ALL inputs before processing
5. Use prepared statements for ALL database queries
6. Hash passwords with password_hash(PASSWORD_DEFAULT)
7. Use proper session security (httponly, secure flags)
8. Include user-friendly error messages
9. Include success messages and redirects
10. Follow {tech_stack} best practices

Generate the complete, production-ready code for: {file_path}
"""

        return prompt


if __name__ == "__main__":
    # Example usage
    print("Workflow Generator - Example Usage")
    print("=" * 80)

    generator = WorkflowGenerator(tech_stack="php_plain")

    # Generate registration workflow
    workflow = generator.generate_registration_workflow(with_email_verification=True)

    print(f"Workflow: {workflow.name}")
    print(f"Trigger: {workflow.trigger}")
    print(f"\nSteps ({len(workflow.steps)}):")
    for step in workflow.steps:
        print(f"  {step.step_number}. {step.action}")
        print(f"     {step.description}")

    print(f"\nFiles Generated ({len(workflow.files_generated)}):")
    for file in workflow.files_generated:
        print(f"  - {file}")

    print(f"\nIntegration Tests ({len(workflow.integration_tests)}):")
    for test in workflow.integration_tests:
        print(f"  ✓ {test}")

    # Generate prompt for specific file
    print("\n" + "=" * 80)
    print("GENERATED PROMPT FOR: templates/register_simple.php")
    print("=" * 80)
    prompt = generator.generate_workflow_prompt(workflow, "templates/register_simple.php")
    print(prompt)
