#!/usr/bin/env python3
"""
Analytical Visualizer Tool
Generates plots, charts, and tables based on user prompts for enhanced analytical responses
"""

import os
import re
import json
import asyncio
import tempfile
import subprocess
import base64
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging
import aiohttp

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from .base_user_tool import BaseUserTool
except ImportError:
    from base_user_tool import BaseUserTool
try:
    from .sandboxed_executor import load_config as _sandbox_config
except ImportError:
    from sandboxed_executor import load_config as _sandbox_config

# This repo's config — found relative to this file, like sandboxed_executor's loader.
_PROJECT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "llm_config.yaml"


def _workspace_dir() -> Path:
    """The sandbox workspace, resolved from user_tools.sandboxed_executor exactly as that tool does.

    Used to be hardcoded to /home/<user>/Development/flaskserver/sandbox_workspace — another project's
    folder on one laptop."""
    cfg = _sandbox_config()
    base = Path(cfg["base_directory"]) if cfg.get("base_directory") else Path.home()
    return base / cfg.get("sandbox_workspace_name", "sandbox_workspace")

class AnalyticalVisualizerTool(BaseUserTool):
    """
    Intelligent visualization generator that creates relevant charts and plots
    based on user prompts to enhance analytical explanations
    """
    
    def __init__(self):
        super().__init__()
        self._name = "analytical_visualizer"
        self._description = "Draw a chart or diagram for exactly two cases: (1) numbers the USER typed into their own message (e.g. 'chart these quarterly figures: 12, 15, 11, 18'), and (2) a diagram with no real data — a flowchart, a process or concept illustration, a schematic. It writes and runs matplotlib code and saves a PNG. Do NOT use it for anything with a real data source: a stock, ETF or index -> comprehensive_stock_analyzer (detailed=true renders the real price chart); a public statistic (GDP, population, inflation...) -> search_datasets / compare_datasets; a table another tool fetched this turn -> plot_data. Never pass it numbers you wrote yourself for real-world data."
        self.working_dir = str(_workspace_dir())
        os.makedirs(self.working_dir, exist_ok=True)
        self.visualization_llm_config = self._load_visualization_llm_config()

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Description of the visualization to create (e.g., 'Create a bar chart of sales by quarter', 'Plot temperature trends over time')"
                },
                "data": {
                    "type": "string",
                    "description": "Optional data to visualize in JSON, CSV, or plain text format"
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename for the visualization (e.g., 'chart.png', 'distribution_plot.png'). Must end with .png. Default: 'visualization_output.png'. IMPORTANT: Use the SAME filename when attaching to email."
                }
            },
            "required": ["prompt"]
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute the analytical visualization request."""
        try:
            prompt = kwargs.get('prompt', '')
            data = kwargs.get('data', '')
            # A distinct default per call: a shared 'visualization_output.png' let concurrent requests —
            # or two charts in one answer — overwrite each other before the image was published.
            import uuid as _uuid
            filename = kwargs.get('filename') or f"visualization_{_uuid.uuid4().hex[:10]}.png"

            # Validate filename
            if not filename.endswith('.png'):
                filename += '.png'

            if not prompt:
                return "❌ **Visualization Generation Failed**: No visualization prompt provided"

            logger.info(f"🎨 Starting analytical visualization: {prompt[:100]}...")
            logger.info(f"📁 Output filename: {filename}")
            logger.info(f"🔧 DEBUG: execute() method called - this should be the one in use")

            # Generate visualization code using LLM
            result = await self._generate_and_execute_visualization(prompt, data, filename)
            
            logger.info(f"🔧 DEBUG: execute() method - result keys: {list(result.keys()) if isinstance(result, dict) else 'not dict'}")
            logger.info(f"🔧 DEBUG: execute() method - success: {result.get('success') if isinstance(result, dict) else 'N/A'}")
            logger.info(f"🔧 DEBUG: execute() method - has base64_image: {'base64_image' in result if isinstance(result, dict) else 'N/A'}")
            if isinstance(result, dict) and 'base64_image' in result:
                logger.info(f"🔧 DEBUG: execute() method - base64_image length: {len(result['base64_image'])}")
            
            if isinstance(result, dict) and result.get("success"):
                # Make sure base64 image data is included in the result for LLM integration
                base64_image = result.get("base64_image")
                
                # Fallback to generating base64 if not available
                if not base64_image and "output_path" in result:
                    logger.warning(f"⚠️ DEBUG: No base64 in result, generating from path: {result.get('output_path')}")
                    base64_image = self._image_to_base64(result['output_path'])
                    if base64_image:
                        result["base64_image"] = base64_image
                
                # Get the full output path for attachment reference
                full_output_path = result.get('output_path', str(_workspace_dir() / 'visualization_output.png'))
                filename = os.path.basename(full_output_path)

                # Create formatted response with EXPLICIT attachment instructions
                response = f"""✅ **Analytical Visualization Generated with LLM**

**Figure Created**: {filename}
**Full Path**: {full_output_path}
**File Type**: PNG image
**Generation Method**: {"LLM-driven dynamic code generation" if result.get('llm_generated') else "Pattern-based"}
**Original Prompt**: {result.get('original_prompt', 'N/A')}

**Execution Status**: {result.get('description', 'Visualization completed successfully')}

📎 **ATTACHMENT INSTRUCTION FOR EMAIL**: To attach this file to an email, use exactly: attachments: "{filename}"
"""

                # PUBLISH the PNG and hand back a REAL chart marker — the same path plot_data uses
                # (publish_chart -> _marker). This used to paste the whole image as base64 into the text
                # with "will be displayed to the user"; nothing downstream renders that, so the answer
                # model invented a marker from the filename ([[chart:quarterly_revenue_chart.png]]) — a
                # broken chart in the post. No URL means no marker, and the result says so.
                marker = None
                try:
                    from utils.chart_publisher import publish_chart
                    from datasources.data_chart_builder import _marker
                    with open(full_output_path, 'rb') as _f:
                        _url = publish_chart(_f.read(), filename_hint=os.path.splitext(filename)[0][:40])
                    if _url:
                        marker = _marker(_url, (prompt or "chart")[:80])
                except Exception as _pub_err:  # noqa: BLE001 — reported below as "no marker"
                    logger.warning(f"🎨 analytical_visualizer: publishing failed: {_pub_err}")
                if marker:
                    logger.info(f"🎨 analytical_visualizer: chart published → {marker[:120]}")
                    response += ("\nINLINE CHART — place this marker, exactly as written, where the chart "
                                 f"belongs in the answer:\n{marker}\n")
                else:
                    response += ("\nThe chart was drawn but could NOT be published, so there is NO marker to "
                                 "show. Do NOT write a chart marker yourself — describe the figure in words "
                                 "(it is still available as an email attachment, above).\n")
                
                logger.info(f"🔧 DEBUG: Final response length: {len(response)}")
                
                # Return the result dict with the formatted response and ensure base64 is preserved
                return {
                    "success": True,
                    "result": response,  # The formatted response with base64 image
                    "response": response,
                    "base64_image": base64_image,
                    "output_path": result.get('output_path'),
                    "description": response,  # Use the full response as description
                    "llm_generated": result.get('llm_generated'),
                    "original_prompt": result.get('original_prompt')
                }
            else:
                error_msg = result.get('error', 'Unknown error') if isinstance(result, dict) else str(result)
                logger.error(f"❌ DEBUG: Visualization failed: {error_msg}")
                return {
                    "success": False,
                    "error": f"Visualization generation failed: {error_msg}",
                    "response": f"❌ **Visualization Generation Failed**: {error_msg}"
                }
            
        except Exception as e:
            logger.error(f"🎨 Analytical visualization failed: {e}")
            return {
                "success": False,
                "error": f"Visualization generation failed: {str(e)}",
                "response": f"❌ **Visualization Generation Failed**: {str(e)}"
            }
    
    async def _generate_and_execute_visualization(self, prompt: str, data: str = '', filename: str = 'visualization_output.png') -> Dict[str, Any]:
        """Generate and execute visualization based on prompt and optional data."""
        try:
            # Use the existing generate_visualization method
            full_prompt = prompt
            if data:
                full_prompt = f"{prompt}\n\nData to visualize:\n{data}"

            result = await self.generate_visualization(full_prompt, filename)
            return result

        except Exception as e:
            logger.error(f"🎨 Visualization generation failed: {e}")
            return {
                "success": False,
                "error": f"Failed to generate visualization: {str(e)}"
            }
    
    def _load_visualization_llm_config(self) -> Dict[str, Any]:
        """The visualizer's model = RAICA's ARBITRATOR lane, read from this repo's llm_config.yaml.

        Used to read another project's config by an absolute path that never existed on live, and then
        fall back SILENTLY to a hardcoded OpenAI gpt-4o-mini (spending OPENAI_API_KEY outside any config)
        or a local qwen2.5:14b. No fallbacks now: a missing lane disables the tool with the reason, and
        execute reports it instead of quietly using a different provider.
        """
        try:
            with open(_PROJECT_CONFIG, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            arb = config.get('arbitrator') or {}
            if not arb.get('enabled') or not (arb.get('config') or {}).get('model'):
                raise ValueError("arbitrator lane is missing or disabled in config/llm_config.yaml")
            lane = {'enabled': True, 'type': arb['type'], 'config': dict(arb['config'])}
            if lane['type'] == 'ollama' and not lane['config'].get('base_url'):
                base = ((config.get('llm') or {}).get('providers') or {}).get('ollama', {}).get('base_url')
                if not base:
                    raise ValueError("llm.providers.ollama.base_url is not set in config/llm_config.yaml")
                lane['config']['base_url'] = base
            return lane
        except Exception as e:  # noqa: BLE001 — reported at execute time, never swapped for a default
            logger.error(f"❌ analytical_visualizer disabled: {e}")
            return {'enabled': False, 'error': str(e), 'type': None, 'config': {}}

    async def _generate_visualization_code_with_llm(self, prompt: str, filename: str = 'visualization_output.png') -> Dict[str, Any]:
        """
        Use LLM to generate complete Python matplotlib code for any visualization request
        """
        # Construct the full output path
        full_output_path = f"{self.working_dir}/{filename}"

        system_prompt = f"""You are an expert Python data visualization specialist using matplotlib.

Your task is to generate complete, executable Python code to create the visualization for the user's request.

IMPORTANT REQUIREMENTS:
1. Generate complete, runnable Python code.
2. Use realistic data.
3. Create professional-looking plots with labels, titles, and legends.
4. Save the plot to the full working directory path and output success markers.

REQUIRED CODE STRUCTURE:
```python
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.figure(figsize=(12, 8))

# [Generate appropriate data and create the visualization]

# CRITICAL: Use full path and output success markers
output_path = "{full_output_path}"
plt.savefig(output_path, dpi=100, bbox_inches='tight', facecolor='white', edgecolor='none')
plt.close()

# REQUIRED: Output success markers for system integration
print("VISUALIZATION_SUCCESS")
print(f"OUTPUT_PATH: {{output_path}}")
print("SUMMARY_DATA: {{'chart_type': 'scientific_visualization', 'method': 'llm_generated'}}")
```

Respond with ONLY the Python code following this exact format."""

        user_message = f"Generate Python matplotlib code for: {prompt}"
        
        # Get visualization LLM configuration
        llm_config = self.visualization_llm_config
        
        if not llm_config.get('enabled', False):
            reason = llm_config.get('error') or "no model configured"
            logger.error(f"❌ Visualization LLM is disabled: {reason}")
            return {"success": False, "error": f"Visualization LLM is disabled: {reason}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                # Handle different provider types
                if llm_config['type'] == 'openai':
                    # OpenAI API format
                    payload = {
                        "model": llm_config['config']['model'],
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        "stream": False,
                        "temperature": llm_config['config'].get('temperature', 0.1),
                        "max_tokens": llm_config['config'].get('max_tokens', 2048)  # Increase for code generation
                    }
                    
                    # Resolve environment variables in API key
                    api_key = llm_config['config']['api_key']
                    if api_key.startswith('${') and api_key.endswith('}'):
                        env_var = api_key[2:-1]  # Remove ${ and }
                        api_key = os.getenv(env_var)
                        if not api_key:
                            logger.error(f"❌ Environment variable {env_var} not set")
                            return {"success": False, "error": f"Environment variable {env_var} not set"}
                        if api_key == 'ollama':
                            logger.error(f"❌ Incorrect API key. The OPENAI_API_KEY environment variable is set to 'ollama'. Please check your environment configuration.")
                            return {"success": False, "error": "Incorrect OPENAI_API_KEY. Please check your environment."}
                        llm_config['config']['api_key'] = api_key
                    
                    headers = {
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json'
                    }
                    
                    base_url = llm_config['config']['base_url']
                    url = f"{base_url}/chat/completions"
                    
                    logger.info(f"🧠 Using OpenAI-compatible LLM: {llm_config['config']['model']}")
                    
                    async with session.post(
                        url, 
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=llm_config['config'].get('timeout', 60))
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            generated_code = result['choices'][0]['message']['content']
                            
                            # Clean up the code if it has markdown formatting
                            if '```python' in generated_code:
                                generated_code = generated_code.split('```python')[1].split('```')[0].strip()
                            elif '```' in generated_code:
                                generated_code = generated_code.split('```')[1].split('```')[0].strip()
                            
                            logger.info(f"🧠 {llm_config['config']['model']} generated visualization code ({len(generated_code)} chars)")
                            logger.debug(f"Generated code preview: {generated_code[:200]}...")
                            
                            return {
                                "success": True,
                                "code": generated_code,
                                "output_type": "png",
                                "description": "LLM-generated scientific visualization"
                            }
                        else:
                            error_text = await response.text()
                            logger.error(f"❌ OpenAI API call failed with status {response.status}: {error_text}")
                            return {"success": False, "error": f"API call failed with status {response.status}"}
                
                else:
                    # Ollama format (fallback)
                    payload = {
                        "model": llm_config['config']['model'],
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        "stream": False
                    }
                    
                    base_url = llm_config['config'].get('base_url', 'http://127.0.0.1:11434')
                    url = f"{base_url}/api/chat"
                    
                    logger.info(f"🧠 Using Ollama LLM: {llm_config['config']['model']}")
                    
                    async with session.post(
                        url, 
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=llm_config['config'].get('timeout', 60))
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            generated_code = result.get('message', {}).get('content', '')
                            
                            # Clean up the code if it has markdown formatting
                            if '```python' in generated_code:
                                generated_code = generated_code.split('```python')[1].split('```')[0].strip()
                            elif '```' in generated_code:
                                generated_code = generated_code.split('```')[1].split('```')[0].strip()
                            
                            logger.info(f"🧠 {llm_config['config']['model']} generated visualization code ({len(generated_code)} chars)")
                            logger.debug(f"Generated code preview: {generated_code[:200]}...")
                            
                            return {
                                "success": True,
                                "code": generated_code,
                                "output_type": "png",
                                "description": "LLM-generated scientific visualization"
                            }
                        else:
                            error_text = await response.text()
                            logger.error(f"❌ Ollama API call failed with status {response.status}: {error_text}")
                            return {"success": False, "error": f"API call failed with status {response.status}"}
        
        except Exception as e:
            logger.error(f"❌ Error calling LLM for code generation: {e}")
            import traceback
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return {"success": False, "error": f"LLM call error: {str(e)}"}

    def _image_to_base64(self, image_path: str) -> str:
        """Convert image file to base64 data URL for inline display"""
        try:
            logger.info(f"🖼️ Converting image to base64: {image_path}")
            
            # Check if file exists
            if not os.path.exists(image_path):
                logger.error(f"❌ Image file does not exist: {image_path}")
                return ""
            
            # Check file size
            file_size = os.path.getsize(image_path)
            logger.info(f"📊 Image file size: {file_size} bytes")
            
            with open(image_path, "rb") as image_file:
                image_data = image_file.read()
                encoded_string = base64.b64encode(image_data).decode()
                data_url = f"data:image/png;base64,{encoded_string}"
                
                logger.info(f"✅ Base64 conversion successful! Data URL length: {len(data_url)} chars")
                logger.info(f"🔍 Base64 preview (first 100 chars): {data_url[:100]}...")
                
                return data_url
                
        except Exception as e:
            logger.error(f"❌ Failed to convert image to base64: {e}")
            import traceback
            logger.error(f"🔍 Full traceback: {traceback.format_exc()}")
            return ""
        
    # DEPRECATED: Pattern-based visualization matching removed
    # All visualization decisions are now made by the LLM based on scientific understanding
    
    # DEPRECATED: Pattern analysis removed in favor of LLM-driven approach
    # The LLM now intelligently determines appropriate visualizations for any prompt
    
    # DEPRECATED: Hardcoded chart functions removed in favor of LLM-driven approach
    # The old pattern-matching system has been replaced with comprehensive LLM code generation
    
    
    
    async def execute_visualization_code(self, code_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the generated visualization code in a safe environment
        """
        if not code_result["success"]:
            return code_result
        
        try:
            # Create temporary file for the code
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                temp_file.write(code_result["code"])
                temp_file_path = temp_file.name
            
            # Execute the code
            # RAICA's OWN interpreter, not whatever "python3" is on PATH: on live the system python3 has
            # no matplotlib (only the venv does), so the result depended on how the service was started.
            # MPLBACKEND=Agg: the code runs headless — an interactive default (QtAgg) crashes with
            # "could not load the Qt platform plugin" and no chart is produced.
            import sys as _sys
            result = subprocess.run(
                [_sys.executable, temp_file_path],
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                cwd=self.working_dir,
                env={**os.environ, "MPLBACKEND": "Agg"},
            )
            
            # Clean up temp file
            os.unlink(temp_file_path)
            
            if result.returncode == 0:
                # Parse the output for success indicators and paths
                output_lines = result.stdout.strip().split('\n')
                success_line = None
                path_line = None
                summary_line = None
                
                for line in output_lines:
                    if line.startswith("VISUALIZATION_SUCCESS"):
                        success_line = line
                    elif line.startswith("OUTPUT_PATH:"):
                        path_line = line.replace("OUTPUT_PATH: ", "")
                    elif line.startswith("SUMMARY_DATA:"):
                        summary_line = line.replace("SUMMARY_DATA: ", "")
                
                if success_line and path_line:
                    # Verify the file was created
                    if os.path.exists(path_line):
                        summary_data = {}
                        if summary_line:
                            try:
                                # Try JSON parsing first, then eval as fallback
                                import json
                                summary_data = json.loads(summary_line)
                            except:
                                try:
                                    summary_data = eval(summary_line)  # Safe in controlled environment
                                except:
                                    summary_data = {"note": "Summary data unavailable"}
                        
                        return {
                            "success": True,
                            "output_path": path_line,
                            "output_type": code_result["output_type"],
                            "description": code_result["description"],
                            "summary_data": summary_data,
                            "execution_time": "Generated successfully"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Output file not created: {path_line}"
                        }
                else:
                    return {
                        "success": False,
                        "error": "Visualization code did not produce expected output markers"
                    }
            else:
                return {
                    "success": False,
                    "error": f"Code execution failed: {result.stderr}"
                }
        
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Visualization generation timed out (30s limit)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Execution error: {str(e)}"
            }
    
    async def generate_visualization(self, prompt: str, filename: str = 'visualization_output.png') -> Dict[str, Any]:
        """
        Main method: Generate visualization based on user prompt using LLM-driven approach
        """
        logger.info(f"🎨 Generating LLM-driven visualization for prompt: {prompt}")
        logger.info(f"📁 Output filename: {filename}")

        # Step 1: Use LLM to generate complete Python code for the visualization
        code_result = await self._generate_visualization_code_with_llm(prompt, filename)
        
        if not code_result["success"]:
            logger.error(f"❌ LLM code generation failed: {code_result.get('error', 'Unknown error')}")
            return {
                "success": False,
                "error": f"Failed to generate visualization code: {code_result.get('error', 'Unknown error')}",
                "llm_error": True
            }
        
        # Step 2: Execute the LLM-generated code safely
        execution_result = await self.execute_visualization_code(code_result)
        
        if not execution_result["success"]:
            logger.error(f"❌ Code execution failed: {execution_result.get('error', 'Unknown error')}")
            return execution_result
        
        # Step 3: Convert image to base64 for LLM system integration
        if "output_path" in execution_result and os.path.exists(execution_result["output_path"]):
            base64_image = self._image_to_base64(execution_result["output_path"])
            if base64_image:
                execution_result["base64_image"] = base64_image
                logger.info(f"✅ Base64 image added to result for LLM integration")
            else:
                logger.warning(f"⚠️ Failed to convert image to base64: {execution_result['output_path']}")
        else:
            logger.warning(f"⚠️ No output file found for base64 conversion")
        
        # Step 4: Return complete result with LLM-generated info
        execution_result["llm_generated"] = True
        execution_result["original_prompt"] = prompt
        return execution_result

# Tool function for LLM system integration
async def analytical_visualizer(prompt: str) -> str:
    """
    Generate analytical visualizations based on user prompts
    
    Args:
        prompt: User prompt that may benefit from visualization
        
    Returns:
        JSON string with visualization result including file path and analysis
    """
    tool = AnalyticalVisualizerTool()
    result = await tool.generate_visualization(prompt)
    
    logger.info(f"🔧 DEBUG: analytical_visualizer function - result keys: {list(result.keys())}")
    logger.info(f"🔧 DEBUG: analytical_visualizer function - success: {result.get('success')}")
    logger.info(f"🔧 DEBUG: analytical_visualizer function - has base64_image: {'base64_image' in result}")
    if 'base64_image' in result:
        logger.info(f"🔧 DEBUG: analytical_visualizer function - base64_image length: {len(result['base64_image'])}")
    
    if result["success"]:
        # Use base64 image data if already generated
        base64_image = result.get("base64_image")
        
        # Fallback to generating base64 if not available
        if not base64_image and "output_path" in result:
            logger.warning(f"⚠️ DEBUG: No base64 in result, generating from path: {result.get('output_path')}")
            tool_instance = AnalyticalVisualizerTool()
            base64_image = tool_instance._image_to_base64(result['output_path'])
        
        # Get the full output path for attachment reference
        full_output_path = result.get('output_path', str(_workspace_dir() / 'visualization_output.png'))
        filename = os.path.basename(full_output_path)

        response = f"""✅ **Analytical Visualization Generated with LLM**

**Figure Created**: {filename}
**Full Path**: {full_output_path}
**File Type**: PNG image
**Generation Method**: {"LLM-driven dynamic code generation" if result.get('llm_generated') else "Pattern-based"}
**Original Prompt**: {result.get('original_prompt', 'N/A')}

**Execution Status**: {result.get('description', 'Visualization completed successfully')}

📎 **ATTACHMENT INSTRUCTION FOR EMAIL**: To attach this file to an email, use exactly: attachments: "{filename}"
"""

        # DO NOT add base64 to LLM context - only reference the chart
        if base64_image:
            logger.info(f"✅ DEBUG: Base64 image available (length: {len(base64_image[:100])}...)")
            response += "\n**📊 Chart successfully generated and will be displayed to the user. Reference this chart in your analysis.**"
        else:
            logger.warning(f"⚠️ DEBUG: No base64 image available for response")
            response += f"\n**Integration Note**: This visualization is saved and ready for attachment."
        
        logger.info(f"🔧 DEBUG: Final response length: {len(response)}")

        # Return dict structure with base64 for server image injection
        return {
            "success": True,
            "result": response,
            "base64_image": base64_image,  # Critical: Include base64 for server display
            "output_path": result.get('output_path'),
            "description": response
        }
    else:
        logger.error(f"❌ DEBUG: Visualization failed: {result.get('error')}")
        error_msg = f"❌ **Visualization Generation Failed**: {result['error']}"
        return {
            "success": False,
            "result": error_msg,
            "base64_image": None,
            "description": error_msg
        }

if __name__ == "__main__":
    # Test the tool
    import asyncio
    
    test_prompts = [
        "Explain supply-demand curve and its influence on price discovery",
        "Show me a normal distribution and explain the 68-95-99.7 rule",
        "Plot some mathematical functions and their derivatives"
    ]
    
    async def test_tool():
        tool = AnalyticalVisualizerTool()
        for prompt in test_prompts:
            print(f"\n🧪 Testing: {prompt}")
            result = await tool.generate_visualization(prompt)
            print(f"Result: {result}")
    
    asyncio.run(test_tool())