#!/usr/bin/env python3
"""
Intelligent Dependency Resolver - Uses Parent RAICA Model for Research
============================================================================

Instead of hardcoding dependencies, this module queries the parent FastAPI server's
RAICA model (with tool calling) to get:
1. Latest dependencies for any tech stack
2. Security best practices
3. Solutions to verification failures

Architecture:
- Parent Server: http://localhost:5050 (RAICA with OpenAI tool calling)
- This Agent: Queries parent for research on dependencies/solutions
- Retry Logic: 3 attempts with increasingly specific queries
"""

import logging
import asyncio
import aiohttp
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DependencyResearchResult:
    """Result from RAICA research query."""
    success: bool
    dependencies: List[str]
    explanation: str
    security_patterns: Dict[str, str]
    error: Optional[str] = None


class IntelligentDependencyResolver:
    """
    Queries parent RAICA model to resolve dependencies dynamically.

    Instead of hardcoding:
        requirements.txt = ["fastapi", "sqlalchemy", ...]

    We query:
        "What are the required dependencies for a FastAPI project with JWT auth,
         SQLAlchemy ORM, PostgreSQL, email verification, and async operations?"

    The parent model uses tool calling (web search, documentation, etc.) to provide
    accurate, up-to-date dependency lists.
    """

    def __init__(self, parent_server_url: str = "http://localhost:5000"):
        self.parent_server_url = parent_server_url
        self.chat_endpoint = f"{parent_server_url}/v1/chat/completions"

    async def query_parent_model(
        self,
        query: str,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Query parent RAICA model with tool calling enabled.

        Args:
            query: Research question
            max_retries: Number of attempts if connection fails

        Returns:
            Response from parent model
        """
        logger.info(f"🔬 Querying parent RAICA model: {query[:100]}...")

        payload = {
            "model": "RAICA-Model1",  # Parent's RAICA model with tool calling
            "messages": [
                {
                    "role": "user",
                    "content": query
                }
            ],
            "stream": False
        }

        for attempt in range(1, max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.chat_endpoint,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=120)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            content = data['choices'][0]['message']['content']
                            logger.info(f"✅ Successfully queried parent model (attempt {attempt}/{max_retries})")
                            logger.info(f"📝 Response length: {len(content)} chars")
                            return {
                                'success': True,
                                'content': content,
                                'tools_used': data.get('tools_used', [])
                            }
                        else:
                            error_text = await response.text()
                            logger.warning(f"⚠️ Parent model returned {response.status}: {error_text}")

            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Timeout querying parent model (attempt {attempt}/{max_retries})")
            except Exception as e:
                logger.error(f"❌ Error querying parent model (attempt {attempt}/{max_retries}): {e}")

            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

        return {
            'success': False,
            'content': '',
            'error': f'Failed after {max_retries} attempts'
        }

    async def research_dependencies(
        self,
        tech_stack: str,
        framework: str,
        features: List[str],
        database: Optional[str] = None
    ) -> DependencyResearchResult:
        """
        Research required dependencies for a tech stack using RAICA.

        Args:
            tech_stack: "python", "php", "nodejs"
            framework: "fastapi", "laravel", "express"
            features: ["jwt_auth", "email_verification", "file_upload", etc.]
            database: "postgresql", "mysql", etc.

        Returns:
            DependencyResearchResult with packages and versions
        """
        # Build research query
        features_str = ", ".join(features)
        db_str = f" with {database} database" if database else ""

        query = f"""
I need to create a {framework} ({tech_stack}) project{db_str} with these features: {features_str}.

Please provide:
1. Complete list of required dependencies with specific versions (latest stable as of 2024)
2. Package manager file format (requirements.txt, composer.json, or package.json)
3. Security-critical packages (auth, password hashing, etc.)

Format your response as:
DEPENDENCIES:
- package-name==version (with brief explanation)
...

SECURITY_PATTERNS:
- Pattern name: Implementation code/instructions
"""

        response = await self.query_parent_model(query)

        if not response['success']:
            return DependencyResearchResult(
                success=False,
                dependencies=[],
                explanation="",
                security_patterns={},
                error=response.get('error', 'Unknown error')
            )

        # Parse response
        content = response['content']
        dependencies = self._extract_dependencies(content, tech_stack)
        security_patterns = self._extract_security_patterns(content)

        return DependencyResearchResult(
            success=True,
            dependencies=dependencies,
            explanation=content,
            security_patterns=security_patterns
        )

    async def research_verification_fix(
        self,
        tech_stack: str,
        framework: str,
        verification_errors: List[str],
        generated_code_sample: str
    ) -> Dict[str, Any]:
        """
        Research solutions to verification failures using RAICA.

        When verification fails (e.g., "Password hashing not detected"), query
        the parent model for specific implementation patterns.

        Args:
            tech_stack: "python", "php", "nodejs"
            framework: "fastapi", "laravel", "express"
            verification_errors: List of error messages from verifier
            generated_code_sample: Sample of generated code that failed

        Returns:
            Dict with fixes and patterns
        """
        errors_str = "\n".join(f"- {err}" for err in verification_errors)

        query = f"""
I'm deploying a {framework} ({tech_stack}) application and got these verification errors:

{errors_str}

Here's a sample of the generated code:
```
{generated_code_sample[:500]}
```

Please provide:
1. Specific code patterns to fix each error
2. Required imports/dependencies
3. Complete implementation examples

Focus on concrete, copy-pasteable code solutions.
"""

        response = await self.query_parent_model(query)

        if not response['success']:
            return {
                'success': False,
                'fixes': {},
                'error': response.get('error')
            }

        content = response['content']
        fixes = self._extract_fixes(content, verification_errors)

        return {
            'success': True,
            'fixes': fixes,
            'explanation': content
        }

    def _extract_dependencies(self, content: str, tech_stack: str) -> List[str]:
        """
        Extract dependency list from RAICA response.

        Looks for patterns like:
        - fastapi==0.104.1
        - "fastapi": "^0.104.1"
        - fastapi (>= 0.104.1)
        """
        dependencies = []
        lines = content.split('\n')

        for line in lines:
            line = line.strip()

            # Python: package==version or package>=version
            if tech_stack == "python" and ('==' in line or '>=' in line):
                if line.startswith('-'):
                    line = line[1:].strip()
                # Extract package name and version
                dep = line.split('#')[0].strip()  # Remove comments
                if dep and not dep.startswith('['):  # Skip section headers
                    dependencies.append(dep)

            # PHP composer: "package": "version"
            elif tech_stack == "php" and '"' in line and ':' in line:
                # TODO: Parse composer.json format
                pass

            # Node package.json: "package": "version"
            elif tech_stack == "nodejs" and '"' in line and ':' in line:
                # TODO: Parse package.json format
                pass

        logger.info(f"📦 Extracted {len(dependencies)} dependencies from research")
        return dependencies

    def _extract_security_patterns(self, content: str) -> Dict[str, str]:
        """Extract security implementation patterns from response."""
        patterns = {}

        # Look for code blocks with security keywords
        import re
        code_blocks = re.findall(r'```(?:\w+)?\n(.*?)\n```', content, re.DOTALL)

        security_keywords = ['Hash', 'password', 'auth', 'middleware', 'jwt', 'bcrypt', 'CryptContext']

        for block in code_blocks:
            for keyword in security_keywords:
                if keyword.lower() in block.lower():
                    patterns[keyword] = block.strip()
                    break

        logger.info(f"🔒 Extracted {len(patterns)} security patterns from research")
        return patterns

    def _extract_fixes(self, content: str, errors: List[str]) -> Dict[str, str]:
        """Extract specific fixes for each verification error."""
        fixes = {}

        # TODO: Parse response and map fixes to specific errors
        # For now, return full response for each error
        for error in errors:
            fixes[error] = content

        return fixes


# Example usage
async def main():
    """Example usage of IntelligentDependencyResolver."""
    resolver = IntelligentDependencyResolver()

    # Example 1: Research FastAPI dependencies
    print("=" * 80)
    print("EXAMPLE 1: Research FastAPI Project Dependencies")
    print("=" * 80)

    result = await resolver.research_dependencies(
        tech_stack="python",
        framework="fastapi",
        features=["jwt_auth", "email_verification", "password_hashing", "async_operations"],
        database="postgresql"
    )

    if result.success:
        print("\n✅ Successfully researched dependencies:")
        print(f"\nFound {len(result.dependencies)} packages:")
        for dep in result.dependencies:
            print(f"  - {dep}")

        print(f"\nSecurity patterns: {len(result.security_patterns)}")
        for pattern_name in result.security_patterns:
            print(f"  - {pattern_name}")
    else:
        print(f"\n❌ Failed: {result.error}")

    # Example 2: Research fix for verification failure
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Research Fix for Laravel Security Error")
    print("=" * 80)

    fix_result = await resolver.research_verification_fix(
        tech_stack="php",
        framework="laravel",
        verification_errors=[
            "Password hashing not detected (expected Hash::make or Hash::check)",
            "Authentication middleware not found on protected routes"
        ],
        generated_code_sample="""
        public function register(Request $request) {
            $user = User::create([
                'email' => $request->email,
                'password' => $request->password  // Missing Hash::make!
            ]);
        }
        """
    )

    if fix_result['success']:
        print("\n✅ Successfully researched fixes:")
        for error, fix in fix_result['fixes'].items():
            print(f"\nError: {error}")
            print(f"Fix preview: {fix[:200]}...")
    else:
        print(f"\n❌ Failed: {fix_result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())
