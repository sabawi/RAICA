"""
Tool discovery and loading system for user-defined tools.
"""

import os
import importlib.util
import inspect
from typing import List, Dict, Any, Optional
import asyncio
try:
    from .base_user_tool import BaseUserTool
except ImportError:
    from base_user_tool import BaseUserTool


async def discover_user_tools(tools_directory: str = None) -> List[BaseUserTool]:
    """
    Discover and load all user-defined tools from the specified directory.

    Args:
        tools_directory: Path to the directory containing user tools.
                        Defaults to 'user_tools' in the RAICA installation directory.

    Returns:
        List of instantiated user tool objects
    """
    if tools_directory is None:
        # Default to RAICA installation directory, not current working directory
        # This ensures user_tools are system-wide, not per-project
        raica_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools_directory = os.path.join(raica_root, "user_tools")
    
    tools = []
    
    if not os.path.exists(tools_directory):
        print(f"User tools directory not found: {tools_directory}")
        return tools
    
    # Scan for Python files in the tools directory
    for filename in os.listdir(tools_directory):
        # CLAUDE.MD EXEMPTION: File extension check is legitimate file system filtering,
        # not semantic classification. This is technical fact (Python file format),
        # not interpretation that LLM should do.
        if filename.endswith('.py') and not filename.startswith('_'):
            # Skip base class, discovery, and utility files
            if filename in ['base_user_tool.py', 'tool_discovery.py', 'citation_mastery.py']:
                continue
                
            file_path = os.path.join(tools_directory, filename)
            try:
                tool_instance = await load_tool_from_file(file_path)
                if tool_instance:
                    tools.append(tool_instance)
                    print(f"✅ Loaded user tool: {tool_instance.name}")
                else:
                    print(f"⚠️ No valid tool found in {filename}")
            except Exception as e:
                print(f"❌ Failed to load tool from {filename}: {e}")
                import traceback
                traceback.print_exc()
    
    return tools


async def load_tool_from_file(file_path: str) -> Optional[BaseUserTool]:
    """
    Load a tool from a Python file.
    
    Args:
        file_path: Path to the Python file containing the tool
        
    Returns:
        Instantiated tool object or None if loading failed
    """
    try:
        # Create module spec and load the module
        module_name = os.path.splitext(os.path.basename(file_path))[0]
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return None
        
        # Add user_tools directory to sys.path temporarily for imports
        import sys
        tools_dir = os.path.dirname(file_path)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
            
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Find classes that inherit from BaseUserTool
        found_classes = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            try:
                is_subclass = issubclass(obj, BaseUserTool) if name != 'BaseUserTool' else False
                
                # Check if it has the expected methods (duck typing approach)
                has_required_methods = (hasattr(obj, 'name') and hasattr(obj, 'description') and 
                                      hasattr(obj, 'parameters') and hasattr(obj, 'execute'))
                
                if (is_subclass and obj is not BaseUserTool and not inspect.isabstract(obj)) or \
                   (has_required_methods and name.endswith('Tool') and name != 'BaseUserTool'):
                    found_classes.append((name, obj))
                    
                    # Instantiate the tool
                    tool_instance = obj()
                    
                    # Validate the tool
                    if await validate_tool(tool_instance):
                        return tool_instance
            
            except Exception as e:
                pass  # Skip problematic classes
        
                    
    except Exception as e:
        print(f"Error loading tool from {file_path}: {e}")
    
    return None


async def validate_tool(tool: BaseUserTool) -> bool:
    """
    Validate that a tool implements all required methods correctly.
    
    Args:
        tool: The tool instance to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        # Check that all required properties return valid values
        name = tool.name
        if not isinstance(name, str) or not name.strip():
            print(f"Tool name must be a non-empty string, got: {name}")
            return False
        
        description = tool.description
        if not isinstance(description, str) or not description.strip():
            print(f"Tool description must be a non-empty string")
            return False
        
        parameters = tool.parameters
        if not isinstance(parameters, dict):
            print(f"Tool parameters must be a dictionary")
            return False
        
        # Check that the execute method is properly defined
        if not hasattr(tool, 'execute') or not callable(tool.execute):
            print(f"Tool must have an execute method")
            return False
        
        # Check if execute method is async
        if not inspect.iscoroutinefunction(tool.execute):
            print(f"Tool execute method must be async")
            return False
        
        return True
        
    except Exception as e:
        print(f"Error validating tool: {e}")
        return False


def load_user_tools() -> List[BaseUserTool]:
    """
    Synchronous wrapper for discover_user_tools.
    
    Returns:
        List of instantiated user tool objects
    """
    return asyncio.run(discover_user_tools())


def get_user_tools_definitions(tools: List[BaseUserTool]) -> List[Dict[str, Any]]:
    """
    Get function definitions for all user tools.

    De-duplicates by function name. Two modules can legitimately expose the same
    tool name (e.g. analytical_visualizer.py defines the implementation class AND
    analytical_visualizer_tool.py wraps it for LLM use — both subclass BaseUserTool,
    so discovery returns both). Ollama silently accepted the repeated declaration;
    Google's OpenAI-compatible endpoint rejects the whole request with
    HTTP 400 "Duplicate function declaration found: <name>", which knocked out the
    entire tool-calling lane. Emitting each name once keeps every provider happy.

    The FIRST occurrence wins, which matches get_user_tool_by_name() below — that
    also returns the first match — so the schema advertised to the LLM stays
    consistent with the instance that will actually execute. A duplicate is a
    packaging smell worth fixing at the source, so it is logged as a warning
    rather than dropped silently.

    Args:
        tools: List of user tool instances

    Returns:
        List of function definitions for LLM prompt, one per unique name
    """
    definitions: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}

    for tool in tools:
        definition = tool.get_function_definition()
        # Support both flat ({"name": ...}) and OpenAI-nested
        # ({"function": {"name": ...}}) definition shapes.
        name = (definition.get('function') or {}).get('name') or definition.get('name')

        if name and name in seen:
            print(
                f"⚠️ Duplicate tool definition '{name}' from {type(tool).__name__} — "
                f"already provided by {seen[name]}. Keeping the first; the duplicate is "
                f"NOT sent to the LLM (providers such as Gemini reject duplicate function "
                f"declarations outright). Fix the duplication at the source."
            )
            continue

        if name:
            seen[name] = type(tool).__name__
        definitions.append(definition)

    return definitions


def get_user_tool_by_name(tools: List[BaseUserTool], name: str) -> Optional[BaseUserTool]:
    """
    Get a user tool by its name.
    
    Args:
        tools: List of user tool instances
        name: Name of the tool to find
        
    Returns:
        Tool instance or None if not found
    """
    for tool in tools:
        if tool.name == name:
            return tool
    return None