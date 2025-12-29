#!/usr/bin/env python3
"""
Deployment Configuration Gatherer
==================================

Interactive module for gathering deployment configuration and preferences.
Detects existing server configuration and prompts user for deployment choices.

Author: RAICA Development Team
Version: 1.0.0
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DeploymentConfig:
    """Deployment configuration gathered from user."""
    domain: Optional[str] = None
    deploy_path: str = "/var/www"
    database: Optional[Dict[str, Any]] = None  # Database configuration dict
    web_server: Optional[Dict[str, Any]] = None  # Web server configuration dict

    # Legacy fields for backward compatibility
    port: Optional[int] = None
    use_ssl: bool = False
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    resolve_conflicts: bool = True

    # Detection results
    detected_web_server: Optional[str] = None
    detected_websites: Optional[List[Dict[str, Any]]] = None
    port_conflicts: Optional[List[int]] = None


class DeploymentConfigGatherer:
    """
    Gathers deployment configuration interactively.

    Responsibilities:
    1. Detect existing web servers (Apache2/Nginx)
    2. Detect existing websites and ports
    3. Detect SSL certificates
    4. Prompt user for web server choice
    5. Prompt user for port selection
    6. Detect and resolve conflicts
    7. Get final approval before deployment
    """

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def gather(
        self,
        project_name: str,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any],
        interactive: bool = True,
        config_overrides: Optional[Dict[str, Any]] = None
    ) -> DeploymentConfig:
        """
        Gather deployment configuration from user.

        Args:
            project_name: Project name
            requirements: Requirements from Phase 2
            architecture: Architecture from Phase 3
            interactive: If True, prompt user for choices
            config_overrides: Optional dictionary of configuration overrides
        """
        print("\n" + "=" * 80)
        print("DEPLOYMENT CONFIGURATION GATHERING")
        print("=" * 80)
        print()

        # Step 1: Detect existing web server
        print("Step 1: Detecting existing web server configuration...")
        from .deployment_modules import WebServerDetector
        detector = WebServerDetector(self.ssh_manager)
        web_server_info = detector.detect()

        detected_server = web_server_info.get("recommendation", "nginx")
        print(f"✅ Detected: {detected_server.upper()}")
        print()

        # Step 2: Detect existing websites and ports
        print("Step 2: Detecting existing websites and port usage...")
        existing_sites = self._detect_existing_websites()
        port_conflicts = self._detect_port_usage()

        if existing_sites:
            print(f"✅ Found {len(existing_sites)} existing website(s):")
            for site in existing_sites:
                print(f"   - {site['name']} on port {site['port']}")
        else:
            print("   No existing websites detected")
        print()

        # Step 3: Detect SSL certificates
        print("Step 3: Detecting SSL certificates...")
        ssl_certs = self._detect_ssl_certificates()

        if ssl_certs:
            print(f"✅ Found {len(ssl_certs)} SSL certificate(s):")
            for cert in ssl_certs:
                print(f"   - {cert['cert_file']}")
                if cert['key_file']:
                    print(f"     Key: {cert['key_file']}")
        else:
            print("   No SSL certificates detected")
        print()

        # If overrides provided, use them (regardless of interactive mode)
        if config_overrides:
            print("\n✅ Using provided configuration overrides")
            return DeploymentConfig(
                web_server=config_overrides.get("web_server", detected_server),
                port=config_overrides.get("port", 8000),
                use_ssl=config_overrides.get("use_ssl", False),
                ssl_cert_path=config_overrides.get("ssl_cert_path"),
                ssl_key_path=config_overrides.get("ssl_key_path"),
                domain=config_overrides.get("domain"),
                deploy_path=config_overrides.get("deploy_path", "/var/www"),
                detected_web_server=detected_server,
                detected_websites=existing_sites,
                port_conflicts=port_conflicts
            )

        # If not interactive, use detected values
        if not interactive:
            return DeploymentConfig(
                web_server=detected_server,
                port=8000,  # Changed from 8080 to 8000 to match default
                use_ssl=bool(ssl_certs),
                ssl_cert_path=ssl_certs[0]['cert_file'] if ssl_certs else None,
                ssl_key_path=ssl_certs[0]['key_file'] if ssl_certs else None,
                detected_web_server=detected_server,
                detected_websites=existing_sites,
                port_conflicts=port_conflicts
            )

        # Interactive configuration
        print("=" * 80)
        print("INTERACTIVE CONFIGURATION")
        print("=" * 80)
        print()

        # Ask user for web server choice
        web_server = self._ask_web_server_choice(detected_server, web_server_info)

        # Ask user for port
        port = self._ask_port_choice(port_conflicts)

        # Ask user for SSL
        use_ssl, ssl_cert, ssl_key = self._ask_ssl_choice(ssl_certs)

        # Ask for domain if using SSL
        domain = None
        if use_ssl:
            domain = input("\nEnter domain name for SSL (or press Enter for self-signed): ").strip() or None

        # Create configuration
        config = DeploymentConfig(
            web_server=web_server,
            port=port,
            use_ssl=use_ssl,
            ssl_cert_path=ssl_cert,
            ssl_key_path=ssl_key,
            domain=domain,
            detected_web_server=detected_server,
            detected_websites=existing_sites,
            port_conflicts=port_conflicts
        )

        # Show summary and get approval
        approved = self._show_summary_and_approve(project_name, requirements, architecture, config)

        if not approved:
            print("\n❌ Deployment cancelled by user")
            raise KeyboardInterrupt("User cancelled deployment")

        return config

    def _detect_existing_websites(self) -> List[Dict[str, Any]]:
        """Detect existing websites on server."""
        websites = []

        try:
            client = self.ssh_manager.get_client()

            # Check Apache sites
            stdin, stdout, stderr = client.exec_command(
                "ls -1 /etc/apache2/sites-enabled/ 2>/dev/null | grep -v 'default' || echo ''"
            )
            apache_sites = stdout.read().decode('utf-8').strip().split('\n')

            for site in apache_sites:
                if site and site != '':
                    # Extract port from config
                    stdin, stdout, stderr = client.exec_command(
                        f"grep -oP 'VirtualHost.*:\\K[0-9]+' /etc/apache2/sites-enabled/{site} 2>/dev/null | head -1 || echo '80'"
                    )
                    port = stdout.read().decode('utf-8').strip() or "80"

                    websites.append({
                        "name": site.replace(".conf", ""),
                        "server": "apache2",
                        "port": int(port)
                    })

            # Check Nginx sites
            stdin, stdout, stderr = client.exec_command(
                "ls -1 /etc/nginx/sites-enabled/ 2>/dev/null | grep -v 'default' || echo ''"
            )
            nginx_sites = stdout.read().decode('utf-8').strip().split('\n')

            for site in nginx_sites:
                if site and site != '':
                    # Extract port from config
                    stdin, stdout, stderr = client.exec_command(
                        f"grep -oP 'listen\\s+\\K[0-9]+' /etc/nginx/sites-enabled/{site} 2>/dev/null | head -1 || echo '80'"
                    )
                    port = stdout.read().decode('utf-8').strip() or "80"

                    websites.append({
                        "name": site,
                        "server": "nginx",
                        "port": int(port)
                    })

        except Exception as e:
            logger.warning(f"Failed to detect existing websites: {e}")

        return websites

    def _detect_port_usage(self) -> List[int]:
        """Detect which ports are already in use."""
        used_ports = []

        try:
            client = self.ssh_manager.get_client()

            # Get all listening ports
            stdin, stdout, stderr = client.exec_command(
                "ss -tlnp 2>/dev/null | grep LISTEN | awk '{print $4}' | sed 's/.*://' | sort -u"
            )
            ports_output = stdout.read().decode('utf-8').strip()

            for port_str in ports_output.split('\n'):
                if port_str and port_str.isdigit():
                    used_ports.append(int(port_str))

        except Exception as e:
            logger.warning(f"Failed to detect port usage: {e}")

        return used_ports

    def _detect_ssl_certificates(self) -> List[Dict[str, Any]]:
        """Detect existing SSL certificates on server."""
        certs = []

        try:
            client = self.ssh_manager.get_client()

            # Common SSL certificate locations
            cert_paths = [
                "/etc/ssl/certs/",
                "/etc/apache2/ssl/",
                "/etc/nginx/ssl/",
            ]

            for cert_path in cert_paths:
                stdin, stdout, stderr = client.exec_command(
                    f"find {cert_path} -name '*.pem' -o -name '*.crt' 2>/dev/null || echo ''"
                )
                found_certs = stdout.read().decode('utf-8').strip().split('\n')

                for cert_file in found_certs:
                    if cert_file and cert_file != '':
                        # Try to find corresponding key file
                        key_file = cert_file.replace('.pem', '-key.pem').replace('.crt', '.key')
                        stdin, stdout, stderr = client.exec_command(f"test -f {key_file} && echo 'EXISTS' || echo 'NOT_FOUND'")
                        key_exists = "EXISTS" in stdout.read().decode('utf-8')

                        certs.append({
                            "cert_file": cert_file,
                            "key_file": key_file if key_exists else None
                        })

        except Exception as e:
            logger.warning(f"Failed to detect SSL certificates: {e}")

        return certs

    def _ask_web_server_choice(self, detected: str, detection_info: Dict[str, Any]) -> str:
        """Ask user to choose web server."""
        print("─" * 80)
        print("WEB SERVER SELECTION")
        print("─" * 80)
        print()
        print(f"Detected web server: {detected.upper()}")
        print()

        # Show details
        if detection_info.get("apache2_installed"):
            status = "✅ Running" if detection_info.get("apache2_running") else "⚠️  Installed but not running"
            print(f"Apache2: {status}")
            if detection_info.get("apache2_version"):
                print(f"  Version: {detection_info['apache2_version']}")
        else:
            print("Apache2: ❌ Not installed")

        if detection_info.get("nginx_installed"):
            status = "✅ Running" if detection_info.get("nginx_running") else "⚠️  Installed but not running"
            print(f"Nginx: {status}")
            if detection_info.get("nginx_version"):
                print(f"  Version: {detection_info['nginx_version']}")
        else:
            print("Nginx: ❌ Not installed")

        print()
        print("Options:")
        print("  1. Use detected server (recommended)")
        print("  2. Use Apache2")
        print("  3. Use Nginx")
        print()

        choice = input(f"Choose option (1-3) [default: 1]: ").strip() or "1"

        if choice == "2":
            return "apache2"
        elif choice == "3":
            return "nginx"
        else:
            return detected

    def _ask_port_choice(self, used_ports: List[int]) -> int:
        """Ask user to choose port."""
        print()
        print("─" * 80)
        print("PORT SELECTION")
        print("─" * 80)
        print()

        print("Currently used ports:")
        if used_ports:
            # Show first 10
            display_ports = sorted(used_ports)[:10]
            print(f"  {', '.join(map(str, display_ports))}")
            if len(used_ports) > 10:
                print(f"  ... and {len(used_ports) - 10} more")
        else:
            print("  None detected")

        print()
        print("Common port choices:")
        print("  80   - HTTP (default)")
        print("  443  - HTTPS")
        print("  8000 - Development")
        print("  8080 - Alternative HTTP")
        print("  5050 - Custom")
        print()

        while True:
            port_str = input("Enter port for deployed application [default: 8000]: ").strip() or "8000"

            try:
                port = int(port_str)
                if port < 1 or port > 65535:
                    print("❌ Port must be between 1 and 65535")
                    continue

                if port in used_ports:
                    print(f"⚠️  Warning: Port {port} is already in use")
                    confirm = input("Continue anyway? (y/n): ").strip().lower()
                    if confirm != 'y':
                        continue

                return port

            except ValueError:
                print("❌ Invalid port number")

    def _ask_ssl_choice(self, detected_certs: List[Dict[str, Any]]) -> tuple:
        """Ask user about SSL configuration."""
        print()
        print("─" * 80)
        print("SSL/HTTPS CONFIGURATION")
        print("─" * 80)
        print()

        use_ssl = input("Enable HTTPS/SSL? (y/n) [default: n]: ").strip().lower() == 'y'

        if not use_ssl:
            return False, None, None

        # If certificates detected, ask if user wants to use them
        if detected_certs:
            print()
            print("Detected SSL certificates:")
            for i, cert in enumerate(detected_certs, 1):
                print(f"  {i}. {cert['cert_file']}")
                if cert['key_file']:
                    print(f"     Key: {cert['key_file']}")

            print()
            print(f"  {len(detected_certs) + 1}. Use different certificate (manual path)")
            print(f"  {len(detected_certs) + 2}. Generate self-signed certificate")
            print()

            choice = input(f"Choose option (1-{len(detected_certs) + 2}) [default: 1]: ").strip() or "1"

            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(detected_certs):
                    selected = detected_certs[choice_num - 1]
                    return True, selected['cert_file'], selected['key_file']
            except ValueError:
                pass

        # Manual certificate path or generate
        print()
        print("Options:")
        print("  1. Provide certificate paths")
        print("  2. Generate self-signed certificate")
        print()

        cert_choice = input("Choose option (1-2) [default: 2]: ").strip() or "2"

        if cert_choice == "1":
            cert_path = input("Certificate file path: ").strip()
            key_path = input("Key file path: ").strip()
            return True, cert_path, key_path
        else:
            # Will generate self-signed
            return True, None, None

    def _show_summary_and_approve(
        self,
        project_name: str,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any],
        config: DeploymentConfig
    ) -> bool:
        """Show deployment summary and get final approval."""
        print()
        print("=" * 80)
        print("DEPLOYMENT SUMMARY - FINAL APPROVAL")
        print("=" * 80)
        print()

        # Project info
        print("📦 PROJECT INFORMATION")
        print("─" * 80)
        print(f"Name: {project_name}")
        print(f"Type: {requirements.get('project_type', 'Web Application')}")
        print(f"Description: {requirements.get('description', 'N/A')[:100]}")
        print()

        # Architecture info
        print("🏗️  ARCHITECTURE")
        print("─" * 80)
        backend = architecture.get("backend", {})
        frontend = architecture.get("frontend", {})
        database = architecture.get("database", {})

        print(f"Backend: {backend.get('framework', 'FastAPI')} (Python)")
        print(f"Frontend: {frontend.get('framework', 'HTML/CSS/JS')}")
        print(f"Database: {database.get('type', 'PostgreSQL')}")
        print()

        # Deployment configuration
        print("🚀 DEPLOYMENT CONFIGURATION")
        print("─" * 80)
        print(f"Web Server: {config.web_server.upper()}")
        print(f"Application Port: {config.port}")
        print(f"SSL/HTTPS: {'Yes' if config.use_ssl else 'No'}")

        if config.use_ssl:
            if config.ssl_cert_path:
                print(f"  Certificate: {config.ssl_cert_path}")
                print(f"  Key: {config.ssl_key_path}")
            else:
                print(f"  Certificate: Will generate self-signed")

            if config.domain:
                print(f"  Domain: {config.domain}")

        print(f"Deploy Path: {config.deploy_path}")
        print()

        # Detected conflicts
        if config.port_conflicts and config.port in config.port_conflicts:
            print("⚠️  WARNINGS")
            print("─" * 80)
            print(f"Port {config.port} is currently in use")
            print("This may cause deployment issues")
            print()

        # Existing websites
        if config.detected_websites:
            print("📄 EXISTING WEBSITES")
            print("─" * 80)
            for site in config.detected_websites:
                print(f"  • {site['name']} ({site['server']}) on port {site['port']}")
            print()

        print("=" * 80)
        print()

        # Final confirmation
        confirm = input("🚀 Proceed with deployment? (yes/no): ").strip().lower()
        return confirm in ['yes', 'y']


if __name__ == "__main__":
    print("This module is not meant to be run directly.")
    print("Use: python examples/full_deployment_demo.py")
