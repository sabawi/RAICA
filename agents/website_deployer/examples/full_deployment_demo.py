#!/usr/bin/env python3
"""
Full End-to-End Deployment Demo
================================

Complete pipeline from natural language to deployed production website.

Pipeline:
1. Natural Language → Requirements (Phase 2)
2. Requirements → Architecture (Phase 3)
3. Architecture → Code (Phase 4-5)
4. Code → Deployed Website (Phase 6-7)

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    export DEPLOYMENT_SSH_HOST="your-server-ip"
    export DEPLOYMENT_SSH_USER="deployer"
    export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/deployment_key"

    python examples/full_deployment_demo.py

Author: RAICA Development Team
Version: 1.0.0
"""

import os
import sys
import logging
import argparse
import json
from typing import Optional, Dict, Any
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from stages import (
    RequirementAnalyzer,
    ArchitectureDesigner,
    IntelligentCodeGeneratorWrapper,
    DeploymentOrchestrator,
    DeploymentConfigGatherer
)
from ssh import SSHConnectionManager, SSHCredentials

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def load_auto_input(file_path: str) -> Dict[str, Any]:
    """Load automated input from JSON file."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error loading auto input file: {e}")
        sys.exit(1)


def gather_specification(auto_spec: Optional[str] = None) -> str:
    """
    Interactive specification gathering from user.

    Returns:
        Specification text
    """
    if auto_spec:
        print("\n✅ Using automated specification")
        return auto_spec

    print("\n" + "=" * 80)
    print("WEBSITE SPECIFICATION")
    print("=" * 80)
    print()
    print("Let's gather information about the website you want to build.")
    print()

    # Option 1: Load from file
    print("Options:")
    print("  1. Enter specification interactively (recommended)")
    print("  2. Load from text file")
    print("  3. Use example blog platform")
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
        Build a simple blog platform where users can:
        - Register and log in with email/password
        - Create and publish blog posts with title, content, and images
        - View all published posts in reverse chronological order
        - Comment on posts
        - Edit and delete their own posts
        - Each post shows author name, publish date, and view count
        - Simple, clean, responsive interface
        """
        print("\n✅ Using example blog platform specification")
        return spec

    # Interactive mode (default)
    print("\n" + "-" * 80)
    print("INTERACTIVE SPECIFICATION BUILDER")
    print("-" * 80)
    print()

    # Gather key information
    print("Answer these questions to build your specification:")
    print()

    # 1. Project name/type
    project_name = input("1. What is your project name or type? (e.g., 'Blog Platform', 'Task Manager'): ").strip()

    # 2. Main purpose
    purpose = input("\n2. What is the main purpose of this website? ").strip()

    # 3. User features
    print("\n3. What can users do? (one per line, empty line to finish)")
    features = []
    while True:
        feature = input("   - ").strip()
        if not feature:
            break
        features.append(feature)

    # 4. Authentication
    needs_auth = input("\n4. Do users need to register/login? (y/n): ").strip().lower() == 'y'

    # 5. Data entities
    print("\n5. What types of data will you store? (e.g., 'posts', 'tasks', 'products')")
    print("   (one per line, empty line to finish)")
    entities = []
    while True:
        entity = input("   - ").strip()
        if not entity:
            break
        entities.append(entity)

    # 6. Special requirements
    special = input("\n6. Any special requirements? (e.g., 'email notifications', 'file uploads'): ").strip()

    # 7. UI preference
    ui_style = input("\n7. Preferred UI style? (default: 'simple and clean'): ").strip() or "simple and clean"

    # Build specification
    spec_lines = [
        f"Build a {project_name} where {purpose}.",
        ""
    ]

    if needs_auth:
        spec_lines.append("Users can:")
        spec_lines.append("- Register and log in with email/password")

    if features:
        if not needs_auth:
            spec_lines.append("Features:")
        for feature in features:
            spec_lines.append(f"- {feature}")

    spec_lines.append("")

    if entities:
        spec_lines.append(f"The system manages: {', '.join(entities)}.")
        spec_lines.append("")

    if special:
        spec_lines.append(f"Special requirements: {special}")
        spec_lines.append("")

    spec_lines.append(f"UI Style: {ui_style} interface with responsive design.")

    spec = "\n".join(spec_lines)

    # Show generated spec
    print("\n" + "=" * 80)
    print("GENERATED SPECIFICATION:")
    print("=" * 80)
    print(spec)
    print("=" * 80)
    print()

    # Confirm
    confirm = input("Use this specification? (y/n): ").strip().lower()
    if confirm != 'y':
        print("\nLet's try again...")
        return gather_specification()

    return spec


def main():
    """Run complete end-to-end deployment."""
    parser = argparse.ArgumentParser(description="Full End-to-End Deployment Demo")
    parser.add_argument("--auto-input", help="Path to JSON file with automated inputs")
    parser.add_argument("--save-responses", help="Save LLM responses to file for replay")
    parser.add_argument("--replay-responses", help="Replay LLM responses from file (faster, deterministic)")
    parser.add_argument("--ssh-host-user", help="SSH connection in format 'user@host' (will prompt for password)")
    args = parser.parse_args()

    auto_input = {}
    if args.auto_input:
        auto_input = load_auto_input(args.auto_input)
        print(f"\n🤖 Running in AUTOMATED mode with input: {args.auto_input}")

    print("=" * 80)
    print("WEBSITE DEPLOYMENT AGENT - FULL END-TO-END DEPLOYMENT")
    print("=" * 80)
    print()
    print("This will deploy a complete application from natural language to production!")
    print()
    print("Steps:")
    print("  1. Analyze requirements from natural language")
    print("  2. Design technical architecture")
    print("  3. Generate production-ready code")
    print("  4. Deploy to server with SSH")
    print()

    # Multi-provider LLM system (no API key check needed - configured in llm_config.yaml)
    print("\nUsing multi-provider LLM system")
    print("Provider: Configured in /config/llm_config.yaml\n")

    # Check SSH credentials - either from command line or environment
    ssh_creds = None
    if args.ssh_host_user:
        # Parse user@host format
        if '@' not in args.ssh_host_user:
            print(f"\n❌ ERROR: Invalid format for --ssh-host-user. Expected 'user@host', got '{args.ssh_host_user}'")
            return

        user, host = args.ssh_host_user.rsplit('@', 1)
        print(f"\n🔐 SSH Authentication for {user}@{host}")

        # Check for password in environment variable first (for automation)
        import getpass
        password = os.getenv("DEPLOYMENT_SSH_PASSWORD")

        if password:
            print("Using password from DEPLOYMENT_SSH_PASSWORD environment variable")
        else:
            # Prompt for password interactively
            try:
                password = getpass.getpass("Enter SSH password: ")
            except (EOFError, OSError):
                print("\n❌ ERROR: Cannot prompt for password in non-interactive mode")
                print("Set DEPLOYMENT_SSH_PASSWORD environment variable for automated deployments")
                return

        ssh_creds = SSHCredentials(
            host=host,
            user=user,
            password=password,
            port=22,
            timeout=30
        )
    else:
        # Try loading from environment variables (key-based auth)
        try:
            ssh_creds = SSHCredentials.from_env()
        except ValueError as e:
            print(f"\n❌ ERROR: {e}")
            print("\nOptions for SSH authentication:")
            print("  1. Use --ssh-host-user 'user@host' (will prompt for password)")
            print("  2. Set environment variables:")
            print("     - DEPLOYMENT_SSH_HOST")
            print("     - DEPLOYMENT_SSH_USER")
            print("     - DEPLOYMENT_SSH_KEY_PATH")
            return

    # Gather specification interactively
    spec = gather_specification(auto_spec=auto_input.get("specification"))

    try:
        # PHASE 1: Requirements
        print("\n" + "=" * 80)
        print("PHASE 1/4: REQUIREMENTS ANALYSIS")
        print("=" * 80)

        analyzer = RequirementAnalyzer()
        req_result = analyzer.analyze(spec)

        if not req_result.success:
            print(f"❌ Failed: {req_result.error_message}")
            return

        print("✅ Requirements complete")
        requirements = req_result.requirements
        
        # Store original spec for intelligent generator
        requirements["original_specification"] = spec

        # PHASE 2: Architecture
        print("\n" + "=" * 80)
        print("PHASE 2/4: ARCHITECTURE DESIGN")
        print("=" * 80)

        designer = ArchitectureDesigner()
        arch_result = designer.design(requirements)

        if not arch_result.success:
            print(f"❌ Failed: {arch_result.error_message}")
            return

        print("✅ Architecture complete")
        architecture = arch_result.architecture

        # PHASE 3: Code Generation (Intelligent Generator ONLY - No Templates)
        print("\n" + "=" * 80)
        print("PHASE 3/4: CODE GENERATION")
        print("=" * 80)
        print("Using Intelligent Code Generator (LLM-based, quality-focused)")

        # Determine response cache path
        response_cache_path = None
        if args.save_responses:
            response_cache_path = args.save_responses
            print(f"Will save LLM responses to: {response_cache_path}")
        elif args.replay_responses:
            response_cache_path = args.replay_responses
            print(f"Will replay LLM responses from: {response_cache_path}")

        generator = IntelligentCodeGeneratorWrapper(
            output_base_dir=Path("generated_projects"),
            response_cache_path=response_cache_path
        )

        code_result = generator.generate(requirements, architecture)

        if not code_result.success:
            print(f"❌ Failed: {code_result.error_message}")
            return

        print("✅ Code generation complete")
        print(f"   Generated: {code_result.output_directory}")

        # PHASE 4: Deployment
        print("\n" + "=" * 80)
        print("PHASE 4/4: DEPLOYMENT TO SERVER")
        print("=" * 80)
        print(f"   Target: {ssh_creds.user}@{ssh_creds.host}")
        print()

        # Connect to SSH
        with SSHConnectionManager(ssh_creds) as ssh_manager:
            # Test connection
            if not ssh_manager.test_sudo_access():
                print("❌ Sudo access required")
                return

            # Gather deployment configuration interactively
            config_gatherer = DeploymentConfigGatherer(ssh_manager)
            deployment_config = config_gatherer.gather(
                project_name=requirements.get('project_name', 'app'),
                requirements=requirements,
                architecture=architecture,
                interactive=not bool(auto_input.get("deployment_config")),
                config_overrides=auto_input.get("deployment_config")
            )

            # Deploy with gathered configuration
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
                print(f"   Failed at: {deploy_result.error_step}")
                return

            print("\n✅ Deployment complete!")

        # FINAL SUMMARY
        print("\n" + "=" * 80)
        print("🎉 FULL DEPLOYMENT SUCCESSFUL!")
        print("=" * 80)

        print(f"\n📦 Project: {requirements['project_name']}")
        print(f"🌐 URL: {deploy_result.deployment_url}")
        print(f"📁 Code: {code_result.output_directory}")

        print(f"\n✨ What was deployed:")
        summary = code_result.generation_summary
        print(f"   • {summary['components']['api_endpoints']} API endpoints")
        print(f"   • {summary['components']['database_tables']} database tables")
        print(f"   • {summary['components']['frontend_pages']} frontend pages")
        print(f"   • {summary['files_generated']} total files")

        print(f"\n🔧 Deployment steps completed:")
        for step in deploy_result.steps_completed:
            print(f"   ✓ {step}")

        print(f"\n📖 Next steps:")
        print(f"   1. Visit: {deploy_result.deployment_url}")
        print(f"   2. API docs: {deploy_result.deployment_url}/docs")
        print(f"   3. Check logs: sudo journalctl -u {requirements['project_name']} -f")

        print("\n" + "=" * 80)
        print("Deployment complete! Your website is live! 🚀")
        print("=" * 80)

    except KeyboardInterrupt:
        print("\n\n❌ Deployment cancelled by user")
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
