#!/usr/bin/env python3
"""
Zero-Shot Remote Deployment Tool
==================================

Fully interactive deployment tool that prompts for ALL missing configuration
parameters needed for end-to-end deployment.

Features:
- Technology stack selection (PHP/MySQL, Python/PostgreSQL, etc.)
- Interactive SSH credential gathering (password or key-based)
- Sudo password collection for remote operations
- MySQL/PostgreSQL admin credential prompts
- Web database user configuration
- Web server endpoint and port configuration
- Port conflict detection with alternative suggestions
- Workflow-level code generation with dependency verification
- Email verification integration enforcement

Usage:
    # Fully interactive (zero-shot):
    python examples/zero_shot_deployment.py

    # With automation file:
    python examples/zero_shot_deployment.py --auto-input config.json

Author: RAICA Development Team
Version: 2.0.0
"""

import os
import sys
import logging
import argparse
import json
import getpass
from typing import Optional, Dict, Any, List
from pathlib import Path
import re

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from stages import (
    RequirementAnalyzer,
    ArchitectureDesigner,
    IntelligentCodeGeneratorWrapper,
    DeploymentOrchestrator,
    DeploymentConfigGatherer
)
from ssh import SSHConnectionManager, SSHCredentials, SafeSSHExecutor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class ConfigurationGatherer:
    """Interactive configuration gathering with validation."""

    def __init__(self, auto_input: Optional[Dict] = None):
        self.auto_input = auto_input or {}

    def _get_input(self, prompt: str, key: str, default: Optional[str] = None,
                   password: bool = False, validator: Optional[callable] = None) -> str:
        """Get input from user or auto_input with validation."""
        # Check auto_input first
        if key in self.auto_input:
            value = self.auto_input[key]
            if not password:
                print(f"{prompt}: {value} (from auto-input)")
            else:
                print(f"{prompt}: *** (from auto-input)")
            return value

        # Interactive prompt
        while True:
            if default:
                display_prompt = f"{prompt} [{default}]: "
            else:
                display_prompt = f"{prompt}: "

            if password:
                value = getpass.getpass(display_prompt)
            else:
                value = input(display_prompt).strip()

            # Use default if empty
            if not value and default:
                value = default

            # Validate if validator provided
            if validator:
                is_valid, error_msg = validator(value)
                if not is_valid:
                    print(f"❌ {error_msg}")
                    continue

            return value

    def _yes_no(self, prompt: str, key: str, default: bool = False) -> bool:
        """Get yes/no confirmation."""
        if key in self.auto_input:
            value = self.auto_input[key]
            print(f"{prompt}: {'yes' if value else 'no'} (from auto-input)")
            return value

        default_str = "Y/n" if default else "y/N"
        response = input(f"{prompt} ({default_str}): ").strip().lower()

        if not response:
            return default

        return response in ['y', 'yes']

    def _menu_choice(self, prompt: str, options: List[str], key: str,
                     default_index: int = 0) -> str:
        """Display menu and get user choice."""
        if key in self.auto_input:
            value = self.auto_input[key]
            print(f"{prompt}: {value} (from auto-input)")
            return value

        print(f"\n{prompt}")
        for i, option in enumerate(options, 1):
            marker = " (default)" if i - 1 == default_index else ""
            print(f"  {i}. {option}{marker}")

        while True:
            choice = input(f"Choose (1-{len(options)}) [{default_index + 1}]: ").strip()

            if not choice:
                return options[default_index]

            try:
                index = int(choice) - 1
                if 0 <= index < len(options):
                    return options[index]
            except ValueError:
                pass

            print(f"❌ Please enter a number between 1 and {len(options)}")

    def gather_technology_stack(self) -> Dict[str, str]:
        """Gather technology stack preferences."""
        print("\n" + "=" * 80)
        print("TECHNOLOGY STACK CONFIGURATION")
        print("=" * 80)

        # Backend framework
        backend = self._menu_choice(
            "Select backend framework:",
            ["PHP (Apache2/Nginx)", "Python (FastAPI/Django)", "Node.js (Express)", "Custom"],
            "backend_framework",
            default_index=0
        )

        # Database
        database = self._menu_choice(
            "Select database:",
            ["MySQL", "PostgreSQL", "SQLite", "Custom"],
            "database_type",
            default_index=0
        )

        # Web server
        web_server = self._menu_choice(
            "Select web server:",
            ["Apache2", "Nginx", "Built-in (development only)", "Custom"],
            "web_server",
            default_index=0
        )

        # Frontend
        frontend = self._menu_choice(
            "Select frontend approach:",
            ["HTML/CSS/JavaScript (traditional)", "React", "Vue", "Custom"],
            "frontend_framework",
            default_index=0
        )

        return {
            "backend": backend,
            "database": database,
            "web_server": web_server,
            "frontend": frontend
        }

    def gather_ssh_credentials(self) -> SSHCredentials:
        """Gather SSH connection details."""
        print("\n" + "=" * 80)
        print("SSH CONNECTION CONFIGURATION")
        print("=" * 80)

        def validate_host(host):
            if not host:
                return False, "Host cannot be empty"
            # Simple validation - allow IPs and hostnames
            return True, None

        host = self._get_input(
            "SSH Host (IP or hostname)",
            "ssh_host",
            validator=validate_host
        )

        user = self._get_input(
            "SSH Username",
            "ssh_user",
            default="root"
        )

        port = int(self._get_input(
            "SSH Port",
            "ssh_port",
            default="22"
        ))

        # Auth method
        auth_method = self._menu_choice(
            "Authentication method:",
            ["Password", "SSH Key"],
            "ssh_auth_method",
            default_index=0
        )

        if auth_method == "Password":
            password = self._get_input(
                "SSH Password",
                "ssh_password",
                password=True
            )

            return SSHCredentials(
                host=host,
                user=user,
                password=password,
                port=port,
                timeout=30
            )
        else:
            key_path = self._get_input(
                "SSH Key Path",
                "ssh_key_path",
                default="~/.ssh/id_rsa"
            )

            key_path = Path(key_path).expanduser()

            if not key_path.exists():
                print(f"⚠️  Warning: Key file not found at {key_path}")
                if not self._yes_no("Continue anyway?", "continue_missing_key"):
                    sys.exit(1)

            return SSHCredentials(
                host=host,
                user=user,
                key_path=str(key_path),
                port=port,
                timeout=30
            )

    def gather_sudo_password(self, ssh_user: str) -> Optional[str]:
        """Gather sudo password for remote operations."""
        print("\n" + "=" * 80)
        print("SUDO ACCESS CONFIGURATION")
        print("=" * 80)

        print(f"Remote operations require sudo access for user '{ssh_user}'")

        needs_sudo_pass = self._yes_no(
            "Does sudo require a password?",
            "sudo_requires_password",
            default=True
        )

        if needs_sudo_pass:
            return self._get_input(
                f"Sudo password for {ssh_user}",
                "sudo_password",
                password=True
            )

        return None

    def gather_database_config(self, db_type: str) -> Dict[str, Any]:
        """Gather database configuration."""
        print("\n" + "=" * 80)
        print(f"{db_type.upper()} CONFIGURATION")
        print("=" * 80)

        # Admin credentials
        print("\n📝 Admin Credentials (for database creation and setup)")
        admin_user = self._get_input(
            f"{db_type} admin username",
            "db_admin_user",
            default="root"
        )

        admin_password = self._get_input(
            f"{db_type} admin password",
            "db_admin_password",
            password=True
        )

        # Database name
        def validate_db_name(name):
            if not name:
                return False, "Database name cannot be empty"
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', name):
                return False, "Database name must start with letter and contain only letters, numbers, underscores"
            return True, None

        db_name = self._get_input(
            "Database name",
            "database_name",
            validator=validate_db_name
        )

        # Web user credentials
        print("\n📝 Web Application Database User (for SELECT/INSERT/UPDATE/DELETE)")
        web_user = self._get_input(
            "Web app database username",
            "db_web_user",
            default="webuser"
        )

        web_password = self._get_input(
            "Web app database password",
            "db_web_password",
            default="webuser"
        )

        # Permissions
        default_permissions = "SELECT, INSERT, UPDATE, DELETE"
        permissions = self._get_input(
            "Database permissions for web user",
            "db_web_permissions",
            default=default_permissions
        )

        return {
            "type": db_type,
            "admin_user": admin_user,
            "admin_password": admin_password,
            "database_name": db_name,
            "web_user": web_user,
            "web_password": web_password,
            "permissions": [p.strip() for p in permissions.split(',')]
        }

    def gather_web_server_config(self, ssh_manager: Optional[SSHConnectionManager] = None) -> Dict[str, Any]:
        """Gather web server configuration with port conflict detection."""
        print("\n" + "=" * 80)
        print("WEB SERVER CONFIGURATION")
        print("=" * 80)

        # Protocol
        protocol = self._menu_choice(
            "Select protocol:",
            ["HTTP", "HTTPS", "Both"],
            "web_protocol",
            default_index=0
        )

        # Port selection with conflict detection
        def validate_port(port_str):
            try:
                port = int(port_str)
                if port < 1 or port > 65535:
                    return False, "Port must be between 1 and 65535"
                return True, None
            except ValueError:
                return False, "Port must be a number"

        while True:
            if protocol in ["HTTP", "Both"]:
                http_port = int(self._get_input(
                    "HTTP Port",
                    "http_port",
                    default="80",
                    validator=validate_port
                ))
            else:
                http_port = None

            if protocol in ["HTTPS", "Both"]:
                https_port = int(self._get_input(
                    "HTTPS Port",
                    "https_port",
                    default="443",
                    validator=validate_port
                ))
            else:
                https_port = None

            # Check for port conflicts if SSH connection available
            if ssh_manager:
                conflicts = self._check_port_conflicts(ssh_manager, http_port, https_port)
                if conflicts:
                    print("\n⚠️  Port conflicts detected:")
                    for conflict in conflicts:
                        print(f"   • {conflict}")

                    if not self._yes_no("Use different ports?", "retry_ports", default=True):
                        print("Proceeding with potentially conflicting ports...")
                        break
                else:
                    print("✅ Ports are available")
                    break
            else:
                break

        # Domain/IP
        domain = self._get_input(
            "Server domain or IP address",
            "domain",
            default="localhost"
        )

        # SSL configuration for HTTPS
        ssl_config = None
        if protocol in ["HTTPS", "Both"]:
            ssl_type = self._menu_choice(
                "SSL certificate type:",
                ["Self-signed (development)", "Let's Encrypt", "Custom certificate"],
                "ssl_type",
                default_index=0
            )

            ssl_config = {"type": ssl_type}

            # Handle both "Custom certificate" and "custom" (case-insensitive)
            if ssl_type and "custom" in ssl_type.lower():
                ssl_config["cert_path"] = self._get_input(
                    "SSL certificate path",
                    "ssl_cert_path"
                )
                ssl_config["key_path"] = self._get_input(
                    "SSL key path",
                    "ssl_key_path"
                )

        return {
            "protocol": protocol,
            "http_port": http_port,
            "https_port": https_port,
            "domain": domain,
            "ssl_config": ssl_config
        }

    def _check_port_conflicts(self, ssh_manager: SSHConnectionManager,
                             http_port: Optional[int], https_port: Optional[int]) -> List[str]:
        """Check if ports are already in use on remote server."""
        conflicts = []

        # Create SafeSSHExecutor for command execution
        executor = SafeSSHExecutor(ssh_manager)

        for port in [http_port, https_port]:
            if port is None:
                continue

            # Check if port is in use
            try:
                result = executor.execute(f"sudo netstat -tuln | grep ':{port} '", auto_approve=True)
                if result.exit_code == 0 and result.stdout.strip():
                    conflicts.append(f"Port {port} is already in use")
            except Exception as e:
                # Ignore errors (port check is non-critical)
                pass

        return conflicts


def gather_specification(auto_spec: Optional[str] = None) -> str:
    """
    Interactive specification gathering from user.

    Returns:
        Specification text or JSON template content
    """
    if auto_spec:
        print("\n✅ Using automated specification")

        # Check if it's a path to a JSON template file
        if auto_spec.endswith('.json') and os.path.exists(auto_spec):
            print(f"   Loading JSON template from: {auto_spec}")
            try:
                with open(auto_spec, 'r') as f:
                    template_data = json.load(f)
                # Convert JSON template to specification string
                spec_text = json.dumps(template_data, indent=2)
                print(f"   Template loaded: {template_data.get('project_name', 'Unknown')}")
                return spec_text
            except Exception as e:
                print(f"   ⚠️  Could not load as JSON template: {e}")
                print(f"   Using as plain text specification")
                return auto_spec

        return auto_spec

    print("\n" + "=" * 80)
    print("WEBSITE SPECIFICATION")
    print("=" * 80)
    print()
    print("Describe the website you want to build in natural language.")
    print()

    # Option 1: Load from file
    print("Options:")
    print("  1. Enter specification interactively")
    print("  2. Load from text file")
    print("  3. Use example user profile manager")
    print()

    choice = input("Choose option (1-3): ").strip()

    if choice == "2":
        # Load from file
        file_path = input("\nEnter path to specification file: ").strip()
        try:
            with open(Path(file_path).expanduser(), 'r') as f:
                spec = f.read()
            print(f"\n✅ Loaded specification from {file_path}")
            print(f"Length: {len(spec)} characters")
            return spec
        except Exception as e:
            print(f"\n❌ Error reading file: {e}")
            print("Falling back to interactive mode...")
            choice = "1"

    elif choice == "3":
        # Use example
        spec = """
        Create a full functioning website with friendly and beautifully designed interface.
        The frontend is HTML/JavaScript/CSS while the backend is Apache2/PHP/MySQL.
        Security is SSL/HTTPS, landing page is Login or register for new users.
        The opening page is made of left sidebar, header bar and footer bar while the main
        pane is where the message and input forms are displayed. For this website, it has
        only one form: User profile filled by the logged in user (first and last names,
        email, phone, address, a short bio).

        IMPORTANT: Registration MUST include email verification with unique verification link.
        Users cannot login until they verify their email address.
        """
        print("\n✅ Using example user profile manager specification")
        return spec

    # Interactive mode (default)
    print("\n" + "-" * 80)
    print("INTERACTIVE SPECIFICATION")
    print("-" * 80)
    print("Describe your website in detail (multi-line, press Ctrl+D when done):")
    print()

    lines = []
    try:
        while True:
            line = input()
            lines.append(line)
    except EOFError:
        pass

    spec = "\n".join(lines).strip()

    if not spec:
        print("\n❌ Empty specification. Please try again.")
        return gather_specification()

    print("\n" + "=" * 80)
    print("SPECIFICATION RECEIVED:")
    print("=" * 80)
    print(spec)
    print("=" * 80)
    print()

    return spec


def main():
    """Run zero-shot deployment."""
    parser = argparse.ArgumentParser(description="Zero-Shot Remote Deployment Tool")
    parser.add_argument("--auto-input", help="Path to JSON file with automated inputs")
    args = parser.parse_args()

    auto_input = {}
    if args.auto_input:
        try:
            with open(args.auto_input, 'r') as f:
                auto_input = json.load(f)
            print(f"\n🤖 Running with auto-input from: {args.auto_input}")
        except Exception as e:
            print(f"\n❌ Error loading auto-input: {e}")
            return

    print("=" * 80)
    print("ZERO-SHOT REMOTE DEPLOYMENT TOOL")
    print("=" * 80)
    print()
    print("This tool will guide you through deploying a complete website from")
    print("natural language specification to production server.")
    print()
    print("You will be prompted for:")
    print("  • Website specification (what to build)")
    print("  • Technology stack (PHP/MySQL, Python/PostgreSQL, etc.)")
    print("  • SSH credentials (host, user, password/key)")
    print("  • Sudo password for remote operations")
    print("  • Database credentials (admin + web user)")
    print("  • Web server configuration (port, protocol, domain)")
    print()

    if not auto_input and not input("Ready to begin? (y/n): ").strip().lower().startswith('y'):
        print("Deployment cancelled.")
        return

    config_gatherer = ConfigurationGatherer(auto_input)

    # Step 1: Technology Stack
    tech_stack = config_gatherer.gather_technology_stack()
    print(f"\n✅ Technology Stack: {tech_stack['backend']} + {tech_stack['database']}")

    # Step 2: SSH Credentials
    ssh_creds = config_gatherer.gather_ssh_credentials()
    print(f"\n✅ SSH: {ssh_creds.user}@{ssh_creds.host}:{ssh_creds.port}")

    # Step 3: Test SSH Connection
    print("\n" + "=" * 80)
    print("TESTING SSH CONNECTION")
    print("=" * 80)

    try:
        with SSHConnectionManager(ssh_creds) as ssh_manager:
            print("✅ SSH connection successful")

            # Step 4: Sudo Password
            sudo_password = config_gatherer.gather_sudo_password(ssh_creds.user)
            if sudo_password:
                # Store for use in deployment
                os.environ['SUDO_PASSWORD'] = sudo_password

            # Test sudo access
            if not ssh_manager.test_sudo_access():
                print("❌ Sudo access test failed")
                return
            print("✅ Sudo access confirmed")

            # Step 5: Database Configuration
            db_type = tech_stack['database'].split()[0]  # Extract "MySQL" from "MySQL"
            db_config = config_gatherer.gather_database_config(db_type)
            print(f"\n✅ Database: {db_config['database_name']} ({db_config['type']})")

            # Step 6: Web Server Configuration
            web_config = config_gatherer.gather_web_server_config(ssh_manager)
            print(f"\n✅ Web Server: {web_config['protocol']} on port {web_config.get('http_port') or web_config.get('https_port')}")

            # Step 7: Website Specification
            spec = gather_specification(auto_input.get("specification"))

            # Display configuration summary
            print("\n" + "=" * 80)
            print("CONFIGURATION SUMMARY")
            print("=" * 80)
            print(f"\n🏗️  Technology Stack:")
            print(f"   Backend:   {tech_stack['backend']}")
            print(f"   Database:  {tech_stack['database']}")
            print(f"   Web Server: {tech_stack['web_server']}")
            print(f"   Frontend:  {tech_stack['frontend']}")

            print(f"\n🔐 SSH Connection:")
            print(f"   Host: {ssh_creds.host}")
            print(f"   User: {ssh_creds.user}")
            print(f"   Port: {ssh_creds.port}")

            print(f"\n💾 Database:")
            print(f"   Type: {db_config['type']}")
            print(f"   Database: {db_config['database_name']}")
            print(f"   Admin User: {db_config['admin_user']}")
            print(f"   Web User: {db_config['web_user']}")

            print(f"\n🌐 Web Server:")
            print(f"   Protocol: {web_config['protocol']}")
            if web_config.get('http_port'):
                print(f"   HTTP Port: {web_config['http_port']}")
            if web_config.get('https_port'):
                print(f"   HTTPS Port: {web_config['https_port']}")
            print(f"   Domain: {web_config['domain']}")

            print("\n" + "=" * 80)

            if not auto_input:
                confirm = input("\nProceed with deployment? (y/n): ").strip().lower()
                if not confirm.startswith('y'):
                    print("Deployment cancelled.")
                    return

            # PHASE 1: Requirements Analysis
            print("\n" + "=" * 80)
            print("PHASE 1/4: REQUIREMENTS ANALYSIS")
            print("=" * 80)

            analyzer = RequirementAnalyzer()
            req_result = analyzer.analyze(spec)

            if not req_result.success:
                print(f"❌ Failed: {req_result.error_message}")
                return

            print("✅ Requirements analyzed")
            requirements = req_result.requirements
            requirements["original_specification"] = spec
            requirements["technology_stack"] = tech_stack

            # PHASE 2: Architecture Design
            print("\n" + "=" * 80)
            print("PHASE 2/4: ARCHITECTURE DESIGN")
            print("=" * 80)

            designer = ArchitectureDesigner()
            arch_result = designer.design(requirements)

            if not arch_result.success:
                print(f"❌ Failed: {arch_result.error_message}")
                return

            print("✅ Architecture designed")
            architecture = arch_result.architecture

            # PHASE 3: Code Generation with Enhanced Workflow Integration
            print("\n" + "=" * 80)
            print("PHASE 3/4: CODE GENERATION")
            print("=" * 80)
            print("Using Intelligent Code Generator with workflow-level specifications")
            print("Enforcing: dependency resolution, integration verification, email verification workflow")

            generator = IntelligentCodeGeneratorWrapper(
                output_base_dir=Path("generated_projects")
            )

            code_result = generator.generate(requirements, architecture)

            if not code_result.success:
                print(f"❌ Failed: {code_result.error_message}")
                return

            print("✅ Code generated")
            print(f"   Output: {code_result.output_directory}")

            # PHASE 4: Deployment
            print("\n" + "=" * 80)
            print("PHASE 4/4: REMOTE DEPLOYMENT")
            print("=" * 80)

            # Create deployment config from gathered information
            from stages.deployment_config_gatherer import DeploymentConfig

            deployment_config = DeploymentConfig(
                domain=web_config['domain'],
                deploy_path=f"/var/www/{db_config['database_name']}",
                database={
                    "type": db_config['type'].lower(),
                    "name": db_config['database_name'],
                    "admin_user": db_config['admin_user'],
                    "admin_password": db_config['admin_password'],
                    "web_user": db_config['web_user'],
                    "web_password": db_config['web_password']
                },
                web_server={
                    "type": tech_stack['web_server'].split()[0].lower(),
                    "port": web_config.get('http_port') or web_config.get('https_port'),
                    "ssl_enabled": 'HTTPS' in web_config['protocol'],
                    "ssl_config": web_config.get('ssl_config')
                }
            )

            orchestrator = DeploymentOrchestrator(ssh_manager)
            deploy_result = orchestrator.deploy(
                project_dir=code_result.output_directory,
                requirements=requirements,
                architecture=architecture,
                domain=deployment_config.domain,
                deploy_path=deployment_config.deploy_path,
                deployment_config=deployment_config
            )

            if not deploy_result.success:
                print(f"\n❌ Deployment failed: {deploy_result.error_message}")
                return

            print("\n✅ Deployment complete!")

            # FINAL SUMMARY
            print("\n" + "=" * 80)
            print("🎉 ZERO-SHOT DEPLOYMENT SUCCESSFUL!")
            print("=" * 80)

            print(f"\n📦 Project: {requirements.get('project_name', 'Website')}")
            print(f"🌐 URL: {deploy_result.deployment_url}")
            print(f"📁 Local Code: {code_result.output_directory}")
            print(f"📁 Remote Path: {deployment_config.deploy_path}")

            print(f"\n✨ Components deployed:")
            summary = code_result.generation_summary
            print(f"   • {summary['components']['api_endpoints']} API endpoints")
            print(f"   • {summary['components']['database_tables']} database tables")
            print(f"   • {summary['components']['frontend_pages']} frontend pages")
            print(f"   • {summary['files_generated']} total files")

            print(f"\n🔧 Deployment steps:")
            for step in deploy_result.steps_completed:
                print(f"   ✓ {step}")

            print(f"\n📖 Next steps:")
            print(f"   1. Visit: {deploy_result.deployment_url}")
            print(f"   2. Test registration with email verification")
            print(f"   3. Monitor logs: sudo journalctl -f")

            print("\n" + "=" * 80)

    except KeyboardInterrupt:
        print("\n\n❌ Deployment cancelled by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
