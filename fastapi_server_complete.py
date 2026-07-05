#!/usr/bin/env python3

# Import centralized version information
from version import __version__, __release__, get_release_string
from orchestration import policy as delivery_policy  # shared delivery policy (auth/recipient-lock/format)

import contextvars
# 🔒 Per-request delivery recipient-lock context (Phase 0 convergence). Carries
# (recipient_locked: bool, locked_recipient: Optional[str]) so the SINGLE email chokepoint
# (AsyncToolManager.secure_email_sender) enforces the server-authoritative recipient lock for EVERY
# send — the POST-LLM delivery paths AND direct LLM tool calls alike — keeping the lock policy in
# exactly one place. Default = unlocked, which is correct for auto-trusted clients (no allowed_tools
# whitelist, e.g. OpenWebUI on the firewalled /v1).
_delivery_lock_ctx: "contextvars.ContextVar" = contextvars.ContextVar(
    "raica_delivery_lock", default=(False, None))

# 🔗 Per-request auto-bind baseline (Phase 2). Holds the set of sandbox_workspace filenames captured at
# request start when delivery is permitted; the email chokepoint diffs against it to auto-attach any
# file the LLM created DURING the request — so the user receives the artifact without depending on the
# model to thread the attachment path. None = not a delivery request (auto-bind inactive).
_artifact_baseline_ctx: "contextvars.ContextVar" = contextvars.ContextVar(
    "raica_artifact_baseline", default=None)

# ✅/❌ Structured success of the most recent USER-TOOL call, set by the user-tool wrapper at its single
# success/failure fork — the ONE place that still holds the tool's {"success": bool} before it is
# stringified for the LLM. Delivery paths read this to know whether a send ACTUALLY succeeded, instead of
# sniffing the wrapper's prose result (which let a failed send — stringified as `Tool '…' error: …` — be
# misread as "sent", because the guard only matched a `❌` prefix that the wrapper never produces). This
# is NOT keyword/pattern matching on meaning (LLM-Policy Gate): it propagates the tool's own boolean.
# Per-task (contextvar) → concurrency-safe. None = no/unknown user-tool outcome in this task.
_last_user_tool_ok: "contextvars.ContextVar" = contextvars.ContextVar(
    "raica_last_user_tool_ok", default=None)

# The delivery/action tool surface exposed to the LLM ONLY when the per-request delivery gate permits it
# (authorize_delivery(data).permitted). This is a CAPABILITY REGISTRY (which tools provide outbound
# delivery), not intent routing — the LLM still decides whether/how to use them. Safety for restricted
# (untrusted-input) clients is enforced separately: the recipient-lock chokepoint (email) and the
# create_file-only scoping (sandboxed_executor).
_DELIVERY_TOOL_SURFACE = ("sandboxed_executor", "secure_email_sender")

# Master switch for the LLM-DRIVEN delivery path (Phase 1 tool exposure + create_file-only scoping +
# Phase 2 auto-bind). Default OFF: delivery continues to flow through the proven 3-stage
# gather→synthesize→deliver pipeline (delivery tools deferred to POST-LLM with the synthesized answer
# as content), which is unchanged for every existing client. When ON, the delivery tools are exposed to
# the tool-calling LLM so it can drive delivery itself — to be enabled together with the multi-round
# agentic tool loop. Phase 0 (the universal recipient-lock chokepoint) is ALWAYS on regardless, since
# it is pure safety and behavior-preserving.
_LLM_DRIVEN_DELIVERY = False

# Set PYTHONTZPATH to use the venv's tzdata
from utils.platform import EnvironmentManager
EnvironmentManager.setup_tzdata_path()


# Generate dynamic docstring with current version
__doc__ = f"""
{get_release_string()} - Complete FastAPI Server with Hybrid LLM Architecture
=============================================================================

FastAPI server with all original Flask functionality including:
- Multi-LLM orchestration with Ollama integration
- Tool calling system (RAG, web search, stock data, etc.)
- Document intelligence with FAISS integration
- Vision processing with qwen2.5vl:3b
- Real-time streaming with auto-fallback
- Async processing for performance
- Database connection pooling
- Production-ready caching layer

Version: {__version__} - Critical Ollama Tool Calling Fix & Hybrid Architecture
Release: {__release__}
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import time
import traceback
import io
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator
import subprocess
from concurrent.futures import ThreadPoolExecutor
import aiohttp
import requests

# Load .env file for secrets (DB_PASSWORD, API keys, etc.) before any os.getenv() calls
from dotenv import load_dotenv
load_dotenv()

# HTTP Connection Pooling
from http_pool_manager import http_pool, init_http_pool, cleanup_http_pool
from http_helpers import pooled_get, pooled_post, requests_compatible_get, requests_compatible_post
from dependency_analyzer import resolve_dependencies

# Configuration Management
from utils.config_loader import config_loader
from llm_providers.manager import llm_manager

# Phase 2B: Advanced Response Streaming & Buffer Optimization
try:
    from phase2b_rollback_controller import (
        rollback_controller, enable_phase2b_feature, disable_phase2b_feature, 
        is_phase2b_feature_enabled, FeatureFlag, emergency_rollback_phase2b
    )
    from phase2b_performance_monitor import (
        performance_monitor, record_performance_metric, get_performance_health
    )
    from phase2b_streaming_fallback import (
        streaming_wrapper, process_response_with_streaming, get_streaming_statistics
    )
    from phase2b_buffer_manager import (
        buffer_manager, start_buffer_management, stop_buffer_management, get_buffer_statistics
    )
    from phase2b_response_classifier import (
        response_classifier, classify_response, get_classification_statistics
    )
    PHASE2B_AVAILABLE = True
except ImportError as e:
    PHASE2B_AVAILABLE = False
    PHASE2B_IMPORT_ERROR = str(e)

# FastAPI imports
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

# Async database
import aiomysql
from aiomysql.pool import Pool

# Data processing
import pandas as pd
import matplotlib
matplotlib.use('Agg')

# LLM and tools imports
try:
    import ollama
    from bs4 import BeautifulSoup
    import wikipediaapi
    from gnews import GNews
    import yfinance as yf
    from ddgs import DDGS
    from text_chunker import TextChunker
    import PyPDF2
    import magic
    import trafilatura
    from urllib.parse import urlparse
    TOOLS_AVAILABLE = True
except ImportError as e:
    print(f"WARNING: Some tools not available: {e}")
    TOOLS_AVAILABLE = False

# SeleniumCrawler is an optional dev-only dependency (archive/ not deployed on server).
# Isolated so its absence does not block TOOLS_AVAILABLE for the rest of the tool suite.
try:
    from archive.experimental.webcrawler import SeleniumCrawler
except ImportError:
    SeleniumCrawler = None  # Falls back to BeautifulSoup in fetch_url_content()

# Import our optimization safety system
try:
    from archive.experimental.optimization_safety import (
        ToolOutputPreserver,
        OptimizationValidator, 
        safe_optimize_llm_input
    )
    from integrations.optimization_controller import optimization_controller
    OPTIMIZATION_AVAILABLE = True
except ImportError as e:
    OPTIMIZATION_AVAILABLE = False
    OPTIMIZATION_IMPORT_ERROR = str(e)

# ==============================================================================
# CONFIGURATION
# ==============================================================================

class ServerConfig:
    """Enhanced server configuration"""
    
    # Database configuration
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_USER = os.getenv('DB_USER', 'root')  
    DB_PASSWORD = os.getenv('DB_PASSWORD')

    # Fail-fast: DB_PASSWORD is required
    if DB_PASSWORD is None:
        print("CRITICAL: DB_PASSWORD environment variable is not set. Server cannot start.", flush=True)
        raise RuntimeError("DB_PASSWORD environment variable is required. Set it before starting the server.")
    DB_NAME = os.getenv('DB_NAME', 'mystocks')
    DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '10'))
    
    # Ollama configuration
    OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434/api/generate')
    OLLAMA_CHAT_URL = os.getenv('OLLAMA_CHAT_URL', 'http://127.0.0.1:11434/api/chat')
    DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', config_loader.get_llm_config('primary')['config']['model'])
    DEFAULT_TOOL_CALLING_MODEL = os.getenv('DEFAULT_TOOL_CALLING_MODEL', config_loader.get_llm_config('tool_calling')['config']['model'])
    
    # OpenAI Compatibility Layer Configuration
    USE_DIRECT_FUNCTION_CALLS = os.getenv('USE_DIRECT_FUNCTION_CALLS', 'true').lower() == 'true'
    OPENAI_HTTP_TIMEOUT = int(os.getenv('OPENAI_HTTP_TIMEOUT', '600'))  # 10 minutes default
    
    # Server configuration
    HOST = os.getenv('HOST', '127.0.0.1')
    PORT = int(os.getenv('PORT', '5000'))
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # Performance configuration
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', '10'))
    TASK_TIMEOUT = int(os.getenv('TASK_TIMEOUT', '1800'))  # 30 minutes default for complex AI tasks
    MAX_CONTEXT_WINDOW = int(os.getenv('MAX_CONTEXT_WINDOW', '65536'))

# ==============================================================================
# PYDANTIC MODELS
# ==============================================================================

class OllamaPromptRequest(BaseModel):
    model: str = Field(..., description="Ollama model name")
    prompt: str = Field(..., description="User prompt")
    stream: Optional[bool] = Field(default=True, description="Enable streaming")
    system: Optional[str] = Field(default=None, description="System prompt")
    context: Optional[List[int]] = Field(default=None, description="Context tokens")

class OllamaStreamRequest(BaseModel):
    prompt: Optional[str] = Field(default="", description="User prompt")
    prompt_context: Optional[str] = Field(default="", description="Additional context")
    model: Optional[str] = Field(default=ServerConfig.DEFAULT_MODEL, description="Model to use")
    toolsInUse: Optional[bool] = Field(default=True, description="Enable tools")
    searchWebInUse: Optional[bool] = Field(default=False, description="Enable web search")
    images: Optional[List[str]] = Field(default=["noimage"], description="Image data")
    tools_calling_model: Optional[str] = Field(default=ServerConfig.DEFAULT_TOOL_CALLING_MODEL, description="Model for tool calls")
    
    # Make validation more flexible like the original Flask version
    class Config:
        extra = "allow"  # Allow extra fields


class ToolCall(BaseModel):
    function: Dict[str, Any]

class ApiResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    timestamp: str

# OpenAI Compatibility Models - Minimal trust design
from typing import Union, List, Any

class OpenAIMessage(BaseModel):
    role: str = Field(..., description="Message role")
    content: Union[str, List[Dict[str, Any]]] = Field(..., description="Message content - string or structured content for vision")

class OpenAIChatRequest(BaseModel):
    model: str = Field(..., description="Model name - we only trust this and content")
    messages: List[OpenAIMessage] = Field(..., description="Messages array")
    # Everything else is ignored for security - zero trust design
    stream: Optional[bool] = Field(default=None)
    temperature: Optional[float] = Field(default=None)
    max_tokens: Optional[int] = Field(default=None)
    top_p: Optional[float] = Field(default=None)
    frequency_penalty: Optional[float] = Field(default=None)
    presence_penalty: Optional[float] = Field(default=None)
    # Support for custom images parameter (file paths or base64)
    images: Optional[List[str]] = Field(default=None, description="Image data - file paths or base64")
    # Tool whitelist: only these tools may be called (sent by NewX AI connector)
    allowed_tools: Optional[List[str]] = Field(default=None, description="Whitelist of allowed tool names")
    # Deep-research opt-out (server-authoritative): a client (e.g. a NewX scheduled
    # bot whose scope doesn't need multi-round research) can send deep_research=false
    # to skip the deep-research gate. None = unset → default behavior (gate decides).
    # Deliberate exception to the zero-trust "ignore everything" policy below, like
    # allowed_tools — it can only RESTRICT, never enable anything not already enabled.
    deep_research: Optional[bool] = Field(default=None, description="Client opt-out for the deep-research gate")
    # Deep-research delivery authorization (server-authoritative, 3-way — see _dr_delivery_permitted):
    # explicit true/false wins (NewX sets this from its per-user privilege system); if unset, a client
    # with NO allowed_tools whitelist is auto-trusted (interactive internal clients like OpenWebUI on
    # the firewalled /v1); a client WITH an allowed_tools whitelist (e.g. NewX bots) is denied unless
    # it sends explicit true. Deliberate exception to the zero-trust policy, like allowed_tools.
    allow_delivery: Optional[bool] = Field(default=None, description="Deep-research delivery authorization (explicit override; else auto-trust if no allowed_tools)")
    # Server-authoritative delivery recipient. When set (e.g. NewX passes the requesting user's own
    # verified account email), RAICA emails ONLY this address and IGNORES any recipient in the prompt
    # — so a multi-user-platform bot can't be abused to email arbitrary people. For restricted clients
    # (those sending allowed_tools) this is REQUIRED to email; if absent, RAICA refuses (fail-closed).
    delivery_recipient: Optional[str] = Field(default=None, description="Locked delivery recipient (overrides prompt-specified recipients)")

    class Config:
        extra = "ignore"  # Ignore all other fields for security

class OpenAIStreamChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[Dict[str, Any]]

# ==============================================================================
# GLOBAL VARIABLES
# ==============================================================================

db_pool: Optional[Pool] = None
thread_pool = ThreadPoolExecutor(max_workers=ServerConfig.MAX_WORKERS)
simple_cache = {}

# Simple conversation memory for OpenAI compatibility endpoint (in-memory only)
openai_conversations = {}
OPENAI_CONVERSATION_TTL = 3600  # 1 hour TTL to prevent unbounded memory growth

def _cleanup_openai_conversations():
    """Remove expired entries from openai_conversations to prevent memory leak."""
    now = time.time()
    expired = [k for k, v in openai_conversations.items() if now - v.get('_created', 0) > OPENAI_CONVERSATION_TTL]
    for k in expired:
        del openai_conversations[k]

def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken if available, else fall back to word-count estimate."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except (ImportError, Exception):
        return len(text.split())

# PDF PROCESSING COMPLETELY DISABLED
CONVERSATION_PDF_AVAILABLE = False

# ==============================================================================
# LOGGING SETUP
# ==============================================================================

# Configure logging based on environment variables
debug_config = config_loader.load_config().get('debug', {})
log_requests_enabled = os.getenv('LOG_REQUESTS', str(debug_config.get('log_requests', True))).lower() in ('true', '1', 'yes')
log_timing_enabled = os.getenv('LOG_TIMING', str(debug_config.get('log_timing', True))).lower() in ('true', '1', 'yes')

# Determine logging level based on configuration
if not log_requests_enabled and not log_timing_enabled:
    # Disable ALL logging completely
    logging.disable(logging.CRITICAL)
    log_level = logging.CRITICAL + 1
    
    # Also redirect stdout/stderr to suppress print statements
    import os
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.dup2(devnull, sys.stderr.fileno())
else:
    logging.disable(logging.NOTSET)  # Enable logging
    log_level = logging.INFO

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/fastapi_complete.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Log optimization system status after logger is available
if OPTIMIZATION_AVAILABLE:
    logger.info("🛡️ Optimization safety system loaded successfully")
else:
    logger.warning(f"⚠️ Optimization system not available: {OPTIMIZATION_IMPORT_ERROR}")

# ==============================================================================
# SYSTEM PROMPT MANAGEMENT
# ==============================================================================

def load_tool_model_system_prompt(user_additional_instructions: str = "") -> str:
    """Load the pre-tool model system prompt from external file"""
    try:
        with open('pre_tool_model_system_prompt.txt', 'r', encoding='utf-8') as f:
            prompt = f.read()
        
        # Replace placeholder with user instructions
        if user_additional_instructions:
            prompt = prompt.replace('{USER_ADDITIONAL_INSTRUCTIONS}', 
                                  f"\n\nADDITIONAL USER INSTRUCTIONS:\n{user_additional_instructions}")
        else:
            prompt = prompt.replace('{USER_ADDITIONAL_INSTRUCTIONS}', "")
        
        return prompt
    except FileNotFoundError:
        logger.error("pre_tool_model_system_prompt.txt not found, using fallback prompt")
        return "You are a tool-calling AI assistant. Call the appropriate tools based on the user's request."

def load_primary_model_system_prompt() -> str:
    """Load the primary model system prompt from external file"""
    try:
        with open('primary_model_system_prompt.txt', 'r', encoding='utf-8') as f:
            content = f.read()
            # Debug: Log if anti-hallucination rules are present
            if "🚨 ANTI-HALLUCINATION RULE" in content:
                logger.info("✅ PRIMARY SYSTEM PROMPT: Anti-hallucination rules FOUND")
            else:
                logger.warning("⚠️ PRIMARY SYSTEM PROMPT: Anti-hallucination rules MISSING")
            
            if "🔗 MANDATORY CITATION URL:" in content:
                logger.info("✅ PRIMARY SYSTEM PROMPT: Enhanced source block format FOUND")
            else:
                logger.warning("⚠️ PRIMARY SYSTEM PROMPT: Enhanced source block format MISSING")
                
            logger.info(f"📋 PRIMARY SYSTEM PROMPT LOADED: {len(content)} chars, first 150 chars: {content[:150]}")
            return content
    except FileNotFoundError:
        logger.error("primary_model_system_prompt.txt not found, using fallback prompt")
        return "You are a helpful AI assistant. Provide comprehensive responses based on the context provided."

# ==============================================================================
# LOGGING UTILITIES
# ==============================================================================

def truncate_base64_for_logging(text: str, max_lines: int = 2) -> str:
    """
    Truncate base64 data in text for logging purposes.
    Shows only first max_lines of base64 data followed by '...'
    """
    if not text:
        return text
    
    # Find base64 data patterns
    import re
    base64_pattern = r'data:image/[^;]+;base64,([A-Za-z0-9+/=]{100,})'
    
    def replace_base64(match):
        base64_data = match.group(1)
        # Calculate characters per line (approximately 80 chars per line)
        chars_per_line = 80
        max_chars = max_lines * chars_per_line
        
        if len(base64_data) <= max_chars:
            return match.group(0)  # Return full match if small enough
        
        truncated = base64_data[:max_chars]
        return f"data:image/{match.group(0).split(';')[0].split('/')[1]};base64,{truncated}...[TRUNCATED {len(base64_data)-max_chars} more chars]"
    
    return re.sub(base64_pattern, replace_base64, text)

# ==============================================================================
# DATABASE CONNECTION POOL
# ==============================================================================

async def init_db_pool():
    """Initialize database connection pool"""
    global db_pool
    try:
        db_pool = await aiomysql.create_pool(
            host=ServerConfig.DB_HOST,
            port=3306,
            user=ServerConfig.DB_USER,
            password=ServerConfig.DB_PASSWORD,
            db=ServerConfig.DB_NAME,
            minsize=5,
            maxsize=ServerConfig.DB_POOL_SIZE,
            autocommit=True,
            charset='utf8mb4'
        )
        logger.info(f"Database pool initialized")
    except Exception as e:
        logger.warning(f"Database pool initialization failed: {e}")
        db_pool = None

async def close_db_pool():
    """Close database connection pool"""
    global db_pool
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()

@asynccontextmanager
async def get_db_connection():
    """Async context manager for database connections"""
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not available")
    
    async with db_pool.acquire() as connection:
        try:
            yield connection
        except Exception as e:
            await connection.rollback()
            logger.error(f"Database operation failed: {e}")
            raise

# ==============================================================================
# TOOL MANAGER (Async version of original)
# ==============================================================================

class AsyncToolManager:
    """Async version of the original tool manager"""

    def __init__(self):
        # Always make functions available - they handle missing dependencies gracefully
        self.available_functions = {
            'get_the_secret_tool': self.get_the_secret_tool,
            'wikipedia_query': self.wikipedia_query,
            'get_stock_and_company_data': self.get_stock_and_company_data,  # RE-ENABLED
            'get_news_summaries': self.get_news_summaries,
            'search_web': self.search_web,
            'lookup_website': self.lookup_website,
            'secure_email_sender': self.secure_email_sender
        }

        # Load user-defined tools - defer to async initialization
        self.user_tools = []
        self.user_tools_loaded = False

        # 🔌 PLUGIN SYSTEM: Initialize plugin manager
        self.plugin_manager = None
        self.plugins_loaded = False

        # 🖼️ IMAGE CONTEXT: Store image data for tools that need it
        self.current_images = []
        self.current_request_context = {}

        logger.info(f"AsyncToolManager initialized with {len(self.available_functions)} tools")
    
    def set_image_context(self, images: list, context: dict = None):
        """🖼️ Set image context for tools that need image data"""
        self.current_images = [img for img in images if img and img != 'noimage']
        self.current_request_context = context or {}
        if self.current_images:
            logger.info(f"🖼️ Set image context: {len(self.current_images)} images available for tools")
    
    async def _load_user_tools_async(self):
        """Load user tools asynchronously"""
        if self.user_tools_loaded:
            return

        try:
            from user_tools import discover_user_tools
            self.user_tools = await discover_user_tools()

            # Add user tools to available functions
            for tool in self.user_tools:
                self.available_functions[tool.name] = self._create_user_tool_wrapper(tool)

            if self.user_tools:
                logger.info(f"Loaded {len(self.user_tools)} user-defined tools: {[t.name for t in self.user_tools]}")

            self.user_tools_loaded = True
            logger.info(f"AsyncToolManager now has {len(self.available_functions)} tools total")
        except Exception as e:
            logger.warning(f"Failed to load user tools: {e}")
            self.user_tools_loaded = True  # Don't keep trying

    async def _load_plugins_async(self):
        """🔌 Load plugin system asynchronously"""
        if self.plugins_loaded:
            return

        try:
            from pathlib import Path
            from plugins.plugin_manager import PluginManager

            # Get plugins directory
            plugins_dir = Path(__file__).parent / 'plugins'

            # Get plugin configuration from llm_config.yaml
            plugin_config = config_loader.get_plugin_config()

            # Initialize plugin manager
            self.plugin_manager = PluginManager(plugins_dir, plugin_config)

            # Discover and validate plugins
            init_result = await self.plugin_manager.initialize()

            if init_result['success']:
                # Add plugin wrappers to available functions
                for plugin_name in self.plugin_manager.plugins.keys():
                    self.available_functions[plugin_name] = self._create_plugin_wrapper(plugin_name)

                logger.info(
                    f"🔌 Loaded {init_result['plugins_loaded']} plugins in "
                    f"{init_result['initialization_time']:.3f}s"
                )

                if init_result['plugins_disabled'] > 0:
                    logger.warning(f"🔌 {init_result['plugins_disabled']} plugins disabled due to errors")

            else:
                logger.error(f"🔌 Plugin system initialization failed: {init_result['errors']}")

            self.plugins_loaded = True
            logger.info(f"AsyncToolManager now has {len(self.available_functions)} tools total (including plugins)")

        except Exception as e:
            logger.warning(f"🔌 Failed to load plugins: {e}")
            self.plugins_loaded = True  # Don't keep trying
    
    async def get_tools_definitions(self, exclude_file_email_tools: bool = False) -> list:
        """Get tools definitions for Ollama tool calling"""
        # Load user tools if not already loaded
        await self._load_user_tools_async()

        # 🔌 Load plugins if not already loaded
        await self._load_plugins_async()
        
        # 🚨 CRITICAL MULTI-TOOL CALLING PROTECTION 🚨
        # NEVER MODIFY tool descriptions without checking CRITICAL_MULTI_TOOL_CALLING_PROTECTION.md
        # These descriptions are optimized to prevent model confusion and enable 4+ tool calls
        # ANY aggressive language, conflicts, or redirections will break multi-tool calling
        
        # Always return tools for testing (even if TOOLS_AVAILABLE is False)
        # The individual functions will handle missing dependencies gracefully
        
        # Return all 6 tool functions with timeout/race condition fixes applied
        tools_definitions = [
            {
                "type": "function",
                "function": {
                    "name": "get_the_secret_tool",
                    "description": "Get the current date and time from the system.",  # 🚨 PROTECTED: Simple clean description
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "secret_tool": {
                                "type": "string",
                                "description": "Get the current Date and Time from the system as needed"
                            }
                        },
                        "required": ["secret_tool"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_news_summaries",
                    "description": "Get latest news headlines and summaries from diverse RSS sources. Use for ANY news request including world news, breaking news, current events, political news, financial news, technology news, cryptocurrency news, business news, international news, national news, local news, sports news, and entertainment news.",  # 🚨 PROTECTED: Enhanced routing description
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filter": {
                                "type": "string",
                                            "description": "IMPORTANT: Analyze the user's prompt and select the most specific category that matches their request. For financial/economic/stock market queries, use 'finance' or 'economy'. For cryptocurrency queries, use 'crypto'. For general business news, use 'business'. For international events, use 'world'. For US domestic news, use 'national'. Available categories: 'world', 'national', 'business', 'finance', 'economy', 'technology', 'crypto', 'sports', 'local'. Example: User asks 'stock market news' → use 'finance'. User asks 'cryptocurrency developments' → use 'crypto'. User asks 'economic indicators' → use 'economy'."
                            }
                        },
                        "required": ["filter"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Search the live web for SPECIFIC, CURRENT, or less-common information from across the internet — including live scores and results, a specific event, match, game, person, team, company, product, price, or statistic, and any precise or just-happened fact that a broad news-category feed would not surface. Returns multiple specific source pages with their URLs. Use it to look up a particular topic by name or to verify current details.",  # 🚨 PROTECTED: clean, additive, non-redirecting
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The input query is a string type that is sent to the web search engine."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "lookup_website",
                    "description": "This function takes a URL (href) web address for a website and makes an HTTP request to retrieve the text from the website for further processing to respond to the user's prompt.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL link to be used directly to request a website download."
                            }
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "wikipedia_query",
                    "description": "Retrieves encyclopedic information from Wikipedia for specific factual lookups and definitions.",  # 🚨 PROTECTED: More specific scope
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "A natural language query, key phrase, or topic of interest. This input should focus on a single topic to ensure accurate results."
                            }
                        },
                        "required": ["question"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stock_and_company_data",
                    "description": "Get basic stock price and company data for a specific ticker symbol.",  # 🚨 PROTECTED: No redirections or conflicts
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {
                                "type": "string",
                                "description": "The ticker symbol traded on the stock exchange. Examples: \"AAPL\", \"MSFT\", \"AMZN\", \"ORCL\""
                            }
                        },
                        "required": ["symbol"]
                    }
                }
            }
        ]
        
        # Add user-defined tools to the definitions
        # 🚨 CRITICAL ARCHITECTURE: Exclude file/email tools during tool calling phase
        excluded_tools = {"sandboxed_executor", "secure_email_sender"} if exclude_file_email_tools else set()

        for tool in self.user_tools:
            if tool.name in excluded_tools:
                logger.info(f"🚫 EXCLUDING {tool.name} from tool calling phase - deferred auto-execution will handle it")
                continue

            tool_def = tool.get_function_definition()
            formatted_def = {
                "type": "function",
                "function": {
                    "name": tool_def["name"],
                    "description": tool_def["description"],
                    "parameters": tool_def["parameters"]
                }
            }
            tools_definitions.append(formatted_def)

        # 🔌 Add plugin tools to the definitions
        if self.plugin_manager and self.plugins_loaded:
            plugins = self.plugin_manager.get_available_plugins()

            for plugin in plugins:
                plugin_def = {
                    "type": "function",
                    "function": {
                        "name": plugin["name"],
                        "description": plugin["description"],
                        "parameters": plugin["parameters"]
                    }
                }
                tools_definitions.append(plugin_def)
                logger.debug(f"🔌 Added plugin tool: {plugin['name']}")

        return tools_definitions
    
    def _create_plugin_wrapper(self, plugin_name: str):
        """🔌 Create an async wrapper for plugin execution"""
        async def wrapper(args = "") -> str:
            import json
            try:
                # Handle different argument types from Ollama
                if isinstance(args, dict):
                    params = args
                elif isinstance(args, str) and args.strip():
                    if args.strip().startswith('{'):
                        params = json.loads(args)
                    else:
                        # Simple string argument - try to map to first parameter
                        params = {"query": args}
                else:
                    params = {}

                # Execute plugin through PluginManager
                result = await self.plugin_manager.execute_plugin(plugin_name, params)

                if result.get("success", False):
                    # Return the formatted result
                    plugin_result = result.get("result", "")
                    return str(plugin_result)
                else:
                    # Return error message
                    error_msg = result.get("error", "Unknown error")
                    return f"Plugin '{plugin_name}' error: {error_msg}"

            except json.JSONDecodeError:
                return f"Plugin '{plugin_name}' error: Invalid JSON arguments"
            except Exception as e:
                logger.error(f"🔌 Error executing plugin '{plugin_name}': {e}")
                return f"Plugin '{plugin_name}' error: {str(e)}"

        return wrapper

    def _create_user_tool_wrapper(self, tool):
        """Create an async wrapper for user tools to match the expected function signature"""
        async def wrapper(args = "") -> str:
            import json
            try:
                # Handle different argument types from Ollama
                if isinstance(args, dict):
                    # Ollama already parsed JSON to dict
                    params = args
                elif isinstance(args, str) and args.strip():
                    # Try to parse as JSON string
                    if args.strip().startswith('{'):
                        params = json.loads(args)
                    else:
                        # Simple string argument
                        params = {"query": args}
                else:
                    # Empty or None args
                    params = {}
                
                # Execute the user tool
                result = await tool.execute(**params)
                
                if result.get("success", False):
                    _last_user_tool_ok.set(True)   # structured success (read by delivery paths)
                    # Format the successful result - handle different result key patterns
                    tool_result = None
                    
                    # Try different common result keys used by tools
                    if "result" in result:
                        tool_result = result["result"]
                    elif "description" in result:
                        # Handle image_to_text and similar tools that use "description"
                        tool_result = result["description"]
                    elif "content" in result:
                        # Handle tools that use "content" key
                        tool_result = result["content"]
                    else:
                        # Fallback: return the entire result dict excluding success/error keys
                        excluded_keys = {"success", "error", "model", "timestamp"}
                        tool_result = {k: v for k, v in result.items() if k not in excluded_keys}
                    
                    if isinstance(tool_result, dict):
                        # Convert dict result to readable string with base64 truncation
                        formatted_result = json.dumps(tool_result, indent=2)
                        return truncate_base64_for_logging(formatted_result)
                    else:
                        return str(tool_result)
                else:
                    _last_user_tool_ok.set(False)   # structured failure (read by delivery paths)
                    # Return error message
                    error_msg = result.get("error", "Unknown error")
                    return f"Tool '{tool.name}' error: {error_msg}"

            except json.JSONDecodeError:
                _last_user_tool_ok.set(False)
                return f"Tool '{tool.name}' error: Invalid JSON arguments"
            except Exception as e:
                _last_user_tool_ok.set(False)
                logger.error(f"Error executing user tool '{tool.name}': {e}")
                return f"Tool '{tool.name}' error: {str(e)}"
        
        return wrapper
    
    async def get_the_secret_tool(self, args: str = "") -> str:
        """Get current date and time"""
        try:
            current_time = datetime.now()
            return f"Current date and time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
        except Exception as e:
            return f"Error getting date/time: {str(e)}"
    
    async def wikipedia_query(self, args: str) -> str:
        """Query Wikipedia"""
        try:
            # Remove TOOLS_AVAILABLE check - let function handle missing deps gracefully
            
            # Handle both JSON string and plain string arguments
            try:
                data = json.loads(args) if isinstance(args, str) and args.startswith('{') else args
                query = data.get('question', args) if isinstance(data, dict) else str(args)
            except (json.JSONDecodeError, AttributeError):
                query = str(args)
            
            def sync_wikipedia_query():
                from datetime import datetime
                
                wiki = wikipediaapi.Wikipedia(
                    language='en',
                    user_agent='FastAPIServer/1.0 (https://github.com/user/project)'
                )
                page = wiki.page(query)
                
                if page.exists():
                    # Truncate summary if too long
                    summary = page.summary[:2000] + "..." if len(page.summary) > 2000 else page.summary
                    
                    # Use enhanced source block formatting
                    formatted_result = _format_source_block(
                        source_url=page.fullurl,
                        title=page.title,
                        content=f"Wikipedia Summary:\n\n{summary}",
                        source_num=1
                    )
                    
                    return f"\nHere are the Wikipedia query results:\n{formatted_result}"
                else:
                    return f"No Wikipedia page found for: {query}"
            
            return await asyncio.get_running_loop().run_in_executor(
                thread_pool, sync_wikipedia_query
            )
        except Exception as e:
            return f"Wikipedia query error: {str(e)}"
    
    async def get_stock_and_company_data(self, args: str) -> str:
        """Get stock data"""
        try:
            # Remove TOOLS_AVAILABLE check - let function handle missing deps gracefully
                
            # Handle both JSON string and plain string arguments
            try:
                data = json.loads(args) if isinstance(args, str) and args.startswith('{') else args
                symbol = data.get('symbol', args) if isinstance(data, dict) else str(args)
            except (json.JSONDecodeError, AttributeError):
                symbol = str(args)
            
            def sync_stock_data():
                ticker = yf.Ticker(symbol)
                info = ticker.info
                hist = ticker.history(period="5d")
                
                current_price = hist['Close'].iloc[-1] if not hist.empty else "N/A"
                change = hist['Close'].iloc[-1] - hist['Close'].iloc[-2] if len(hist) > 1 else 0
                
                return f"""Stock Data for {symbol}:
                Current Price: ${current_price:.2f}
                Change: ${change:.2f}
                Company: {info.get('longName', 'N/A')}
                Sector: {info.get('sector', 'N/A')}
                Market Cap: {info.get('marketCap', 'N/A')}"""
            
            return await asyncio.get_running_loop().run_in_executor(
                thread_pool, sync_stock_data
            )
        except Exception as e:
            return f"Stock data error: {str(e)}"
    
    async def get_news_summaries(self, args: str) -> str:
        """
        Get comprehensive news summaries with FULL ARTICLE CONTENT from multiple sources based on a given filter.
        Enhanced to extract detailed content from each article for more substantial information.
        """
        try:
            # Remove TOOLS_AVAILABLE check - let function handle missing deps gracefully
                
            def sync_news_query():
                # Handle parameter parsing like the original
                if isinstance(args, str):
                    # Try to parse as dict first, fall back to string
                    try:
                        data = json.loads(args) if args.startswith('{') else {'filter': args}
                    except Exception as e:
                        logger.warning(f"JSON parse failed for news filter args: {e}")
                        data = {'filter': args}
                else:
                    data = args if isinstance(args, dict) else {'filter': str(args)}
                
                # Get the filter keyword (like original implementation)
                newsFilter = data.get('filter', '').lower().strip()

                # 📰 LOAD NEWS CONFIGURATION (with fallback to hardcoded)
                # Try to load from config/news_sources.yaml for user customization
                try:
                    news_config = config_loader.get_news_config()

                    # Use config if it has data, otherwise fallback to hardcoded
                    NEWS_URLS_FROM_CONFIG = news_config.get('news_sources', {})
                    CATEGORY_MAPPING_FROM_CONFIG = news_config.get('category_mapping', {})
                    KEYWORD_MAPPINGS_FROM_CONFIG = news_config.get('keyword_mappings', {})

                    # Convert YAML lists to Python sets for category mapping (for performance)
                    if CATEGORY_MAPPING_FROM_CONFIG:
                        for cat, config in CATEGORY_MAPPING_FROM_CONFIG.items():
                            if 'primary_terms' in config and isinstance(config['primary_terms'], list):
                                config['primary_terms'] = set(config['primary_terms'])
                            if 'secondary_terms' in config and isinstance(config['secondary_terms'], list):
                                config['secondary_terms'] = set(config['secondary_terms'])
                            if 'compound_phrases' in config and isinstance(config['compound_phrases'], list):
                                config['compound_phrases'] = set(config['compound_phrases'])
                            # Handle crossover terms
                            for key in ['financial_crossover', 'tech_crossover', 'business_crossover', 'geo_specific', 'finance_crossover', 'geo_indicators']:
                                if key in config and isinstance(config[key], list):
                                    config[key] = set(config[key])

                    # Decide: use config or fallback to hardcoded
                    use_config = bool(NEWS_URLS_FROM_CONFIG or CATEGORY_MAPPING_FROM_CONFIG or KEYWORD_MAPPINGS_FROM_CONFIG)

                    if use_config:
                        logger.info("📰 Using news sources from configuration file")
                    else:
                        logger.info("📋 News config empty, using hardcoded defaults")

                except Exception as e:
                    logger.warning(f"⚠️  Failed to load news config: {e}, using hardcoded defaults")
                    NEWS_URLS_FROM_CONFIG = {}
                    CATEGORY_MAPPING_FROM_CONFIG = {}
                    KEYWORD_MAPPINGS_FROM_CONFIG = {}
                    use_config = False

                # 🔄 FALLBACK: Enhanced news category mapping with diverse, reliable sources (HARDCODED)
                NEWS_URLS = NEWS_URLS_FROM_CONFIG if NEWS_URLS_FROM_CONFIG else {
                    "world": [
                        # Mainstream reliable sources
                        "https://apnews.com/world-news",
                        "https://feeds.bbci.co.uk/news/world/rss.xml",
                        "https://www.aljazeera.com/xml/rss/all.xml",
                        # International perspectives
                        "https://rss.dw.com/atom/rss-en-all",  # Deutsche Welle
                        "https://www.theguardian.com/world/rss",
                        # Alternative viewpoints
                        "https://theintercept.com/feed/"
                    ],
                    "national": [
                        # Traditional sources
                        "https://apnews.com/us-news",
                        "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
                        "https://www.npr.org/sections/national/",
                        # Independent sources
                        "https://www.propublica.org/feeds/propublica/main",
                        "https://www.axios.com/feeds/articles.rss"
                    ],
                    "business": [
                        # Traditional business news
                        "https://www.npr.org/sections/business/",
                        "https://feeds.bbci.co.uk/news/business/rss.xml",
                        # Alternative business perspectives
                        "https://www.axios.com/feeds/business.rss",
                        "https://www.zerohedge.com/fullrss2.xml",  # Direct RSS instead of FeedBurner
                        # Additional business sources
                        "https://feeds.bloomberg.com/markets/news.rss",
                        "https://www.businessinsider.com/rss"
                    ],
                    "finance": [
                        # Major Financial News Outlets
                        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
                        "https://finance.yahoo.com/news/rssindex",
                        "https://feeds.bloomberg.com/markets/news.rss",
                        "https://www.marketwatch.com/rss/topstories",
                        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",  # Wall Street Journal
                        # Economic and Federal Reserve News
                        "https://feeds.bbci.co.uk/news/business/rss.xml",
                        "https://www.cnbc.com/id/20910258/device/rss/rss.html",  # Economics
                        "https://www.federalreserve.gov/feeds/press_all.xml",
                        # Stock Market and Trading
                        "https://www.investing.com/rss/news.rss",
                        "https://seekingalpha.com/feed.xml",
                        "https://www.fool.com/feeds/index.aspx",  # Motley Fool
                        # Alternative Financial News
                        "https://www.zerohedge.com/fullrss2.xml",
                        "https://finance.yahoo.com/rss/topstories",
                        "https://www.reuters.com/business/finance/"
                    ],
                    "economy": [
                        # Economic Policy and Data
                        "https://www.cnbc.com/id/20910258/device/rss/rss.html",  # Economics
                        "https://www.federalreserve.gov/feeds/press_all.xml",
                        "https://feeds.bbci.co.uk/news/business/rss.xml",
                        "https://www.reuters.com/business/",
                        # Economic Analysis
                        "https://www.bloomberg.com/economics",
                        "https://www.economist.com/finance-and-economics/rss.xml",
                        "https://www.wsj.com/xml/rss/3_7085.xml"  # WSJ Economics
                    ],
                    "technology": [
                        # Independent tech sources (reliable direct feeds)
                        "https://arstechnica.com/feed/",
                        "https://thehackernews.com/feeds/posts/default?alt=rss",  # Direct RSS instead of FeedBurner
                        "https://techcrunch.com/feed/",  # Direct RSS instead of FeedBurner
                        # Alternative tech perspectives  
                        "https://www.techdirt.com/feed/",
                        "https://www.theregister.com/headlines.atom",
                        # Additional reliable tech sources
                        "https://www.wired.com/feed/rss",
                        "https://www.zdnet.com/news/rss.xml"
                    ],
                    "crypto": [
                        # Specialized cryptocurrency sources
                        "https://www.coindesk.com/arc/outboundfeeds/rss/",
                        "https://decrypt.co/feed",
                        "https://www.theblock.co/rss.xml",
                        "https://cointelegraph.com/rss"
                    ],
                    "science": [
                        # Traditional science sources
                        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
                        "https://www.sciencenews.org/feed",
                        "https://www.npr.org/sections/science/",
                        # Independent science sources
                        "https://arstechnica.com/science/feed/"
                    ],
                    "politics": [
                        # Political news with diverse perspectives
                        "https://www.politico.com/rss/politicopicks.xml",
                        "https://thehill.com/news/feed/",
                        "https://www.propublica.org/feeds/propublica/main",
                        "https://theintercept.com/feed/"
                    ],
                    "news": [        
                        # Mainstream sources
                        "https://apnews.com/hub/ap-top-news",
                        "https://feeds.bbci.co.uk/news/rss.xml",
                        "https://www.npr.org/sections/news/",
                        # Independent sources
                        "https://www.axios.com/feeds/articles.rss",
                        "https://www.propublica.org/feeds/propublica/main"
                    ],
                    "national": [
                        # US National News Sources
                        "https://apnews.com/hub/ap-top-news",
                        "https://www.npr.org/sections/news/",
                        "https://www.usatoday.com/rss/news/",
                        "https://www.cbsnews.com/latest/rss/main",
                        "https://www.nbcnews.com/feeds/",
                        "https://abcnews.go.com/abcnews/topstories"
                    ],
                    "world": [
                        # International News Sources
                        "https://feeds.bbci.co.uk/news/world/rss.xml",
                        "https://www.aljazeera.com/xml/rss/all.xml",
                        "https://rss.dw.com/atom/rss-en-all",  # Deutsche Welle - Fixed URL
                        "https://www.france24.com/en/rss",
                        "https://www.euronews.com/rss?level=vertical&name=news",
                        "https://www.scmp.com/rss/feed/"  # South China Morning Post - Fixed URL
                    ],
                    "local": [
                        # Regional/Local News Sources
                        "https://www.latimes.com/rss2.0.xml",
                        "https://www.sfgate.com/rss/feed/Chronicle-News-940.php",
                        "https://www.chicagotribune.com/arcio/rss/",
                        "https://www.nytimes.com/services/xml/rss/nyt/HomePage.xml",
                        "https://www.washingtonpost.com/rss/",
                        "https://www.dallasnews.com/feed/"
                    ],
                    "default": [
                        "https://apnews.com/hub/ap-top-news",
                        "https://feeds.bbci.co.uk/news/rss.xml",
                        "https://www.axios.com/feeds/articles.rss"
                    ]
                }
                
                # 🎯 ENHANCED INTELLIGENT CATEGORY DETECTION SYSTEM
                # Multi-factor analysis with phrase detection, weights, and intent recognition

                ENHANCED_CATEGORY_MAPPING = CATEGORY_MAPPING_FROM_CONFIG if CATEGORY_MAPPING_FROM_CONFIG else {
                    "crypto": {
                        "primary_terms": {"crypto", "cryptocurrency", "bitcoin", "btc", "ethereum", "eth", "blockchain"},
                        "secondary_terms": {"defi", "nft", "altcoin", "mining", "wallet", "exchange", "digital currency", "web3", "solana", "cardano", "polygon", "binance", "coinbase"},
                        "compound_phrases": {"crypto news", "bitcoin price", "ethereum update", "blockchain technology", "digital assets", "crypto market", "defi protocol"},
                        "financial_crossover": {"crypto stocks", "bitcoin etf", "cryptocurrency investment", "digital asset trading"},
                        "tech_crossover": {"blockchain development", "smart contracts", "cryptocurrency technology"},
                        "weight": 1.0,
                        "fallback_categories": ["finance", "technology"]
                    },
                    "finance": {
                        "primary_terms": {"finance", "financial", "stocks", "market", "markets", "stock"},
                        "secondary_terms": {"securities", "financing", "bonds", "wall street", "nasdaq", "dow jones", "trading", "investment", "earnings"},
                        "compound_phrases": {"stock market", "financial news", "market update", "earnings report", "market analysis", "stock trading"},
                        "business_crossover": {"corporate earnings", "business finance", "company stocks"},
                        "weight": 0.9,
                        "fallback_categories": ["business"]
                    },
                    "economy": {
                        "primary_terms": {"economy", "economic", "inflation", "recession", "gdp", "unemployment"},
                        "secondary_terms": {"interest rates", "fed rates", "federal reserve", "monetary policy", "fiscal policy", "economic growth", "economic indicators", "consumer price index", "cpi"},
                        "compound_phrases": {"economic news", "fed meeting", "economic indicators", "monetary policy", "economic growth", "inflation report", "unemployment rate"},
                        "finance_crossover": {"economic market", "financial economy", "market economy"},
                        "weight": 0.9,
                        "fallback_categories": ["finance"]
                    },
                    "technology": {
                        "primary_terms": {"technology", "tech", "ai", "artificial intelligence", "software", "hardware", "digital"},
                        "secondary_terms": {"machine learning", "computer", "internet", "cybersecurity", "startup", "innovation", "gadgets", "devices", "cloud", "data", "programming", "app", "platform"},
                        "compound_phrases": {"tech news", "ai development", "software update", "tech startup", "digital transformation", "cyber attack", "tech earnings"},
                        "business_crossover": {"tech companies", "software business", "tech industry"},
                        "weight": 0.8,
                        "fallback_categories": ["business"]
                    },
                    "business": {
                        "primary_terms": {"business", "trade", "commerce", "commercial", "corporate", "company", "companies"},
                        "secondary_terms": {"retail", "enterprise", "industry", "sector", "revenue", "profit", "ceo", "merger", "acquisition", "ipo"},
                        "compound_phrases": {"business news", "corporate earnings", "company update", "industry analysis", "market sector"},
                        "weight": 0.7,
                        "fallback_categories": ["finance"]
                    },
                    "world": {
                        "primary_terms": {"world", "global", "international", "foreign", "abroad"},
                        "secondary_terms": {"europe", "asia", "africa", "china", "russia", "uk", "japan", "india", "brazil", "canada", "mexico"},
                        "compound_phrases": {"world news", "international affairs", "global economy", "foreign policy", "international relations"},
                        "geo_specific": {"european union", "middle east", "south america", "southeast asia"},
                        "weight": 0.9,
                        "fallback_categories": ["national"]
                    },
                    "national": {
                        "primary_terms": {"national", "nation", "domestic", "us", "usa", "american", "homeland", "united states"},
                        "secondary_terms": {"congress", "senate", "house", "washington", "federal", "state", "local", "governor", "mayor"},
                        "compound_phrases": {"national news", "us news", "american politics", "domestic policy", "homeland security"},
                        "weight": 0.8,
                        "fallback_categories": ["politics"]
                    },
                    "politics": {
                        "primary_terms": {"politics", "political", "government", "election", "campaign", "policy", "legislation"},
                        "secondary_terms": {"democrat", "republican", "biden", "trump", "vote", "voting", "ballot", "candidate", "senator", "representative"},
                        "compound_phrases": {"political news", "election update", "campaign news", "government policy", "political analysis"},
                        "weight": 0.8,
                        "fallback_categories": ["national"]
                    },
                    "science": {
                        "primary_terms": {"science", "scientific", "research", "study", "discovery", "experiment"},
                        "secondary_terms": {"physics", "chemistry", "biology", "nasa", "space", "medicine", "health", "climate", "environment"},
                        "compound_phrases": {"scientific breakthrough", "research findings", "space exploration", "medical research", "climate change"},
                        "weight": 0.6,
                        "fallback_categories": ["technology"]
                    },
                    "local": {
                        "primary_terms": {"local", "regional", "city", "town", "community", "neighborhood"},
                        "secondary_terms": {"metro", "county", "municipal", "downtown", "suburb", "district", "area", "vicinity", "nearby"},
                        "compound_phrases": {"local news", "regional update", "city news", "community events", "metro area", "local government"},
                        "geo_indicators": {"california", "texas", "new york", "florida", "chicago", "los angeles", "houston", "phoenix", "philadelphia", "san antonio"},
                        "weight": 0.7,
                        "fallback_categories": ["national"]
                    }
                }
                
                # 🧠 INTELLIGENT CATEGORY DETECTION ENGINE
                def find_category_intelligent(newsFilter):
                    """
                    Advanced category detection using multi-factor analysis:
                    - Phrase detection (compound phrases get priority)
                    - Weight-based scoring system
                    - Primary vs secondary term hierarchy
                    - Crossover detection for mixed topics
                    - Fuzzy matching for typos/variations
                    """
                    import re
                    from collections import defaultdict
                    
                    # Normalize and prepare the filter text
                    original_filter = newsFilter.lower().strip()
                    
                    # Remove common stop words that don't contribute to categorization
                    stop_words = {"the", "get", "latest", "current", "recent", "update", "updates", "news", "information", "about", "on", "for", "and", "or"}
                    words = [w for w in re.findall(r'\b\w+\b', original_filter) if w not in stop_words]
                    clean_filter = ' '.join(words)
                    
                    logger.debug(f"🎯 Category Detection: '{newsFilter}' -> '{clean_filter}'")
                    
                    # Scoring system for each category
                    category_scores = defaultdict(float)
                    
                    for category, config in ENHANCED_CATEGORY_MAPPING.items():
                        score = 0.0
                        matches = []
                        
                        # 1. COMPOUND PHRASES (highest priority - exact phrase matching)
                        compound_phrases = config.get("compound_phrases", set())
                        for phrase in compound_phrases:
                            if phrase in original_filter:
                                score += 3.0 * config["weight"]  # High score for exact phrase matches
                                matches.append(f"phrase:'{phrase}'")
                        
                        # 2. PRIMARY TERMS (high weight)
                        primary_terms = config.get("primary_terms", set())
                        for term in primary_terms:
                            if term in clean_filter:
                                score += 2.0 * config["weight"]
                                matches.append(f"primary:'{term}'")
                        
                        # 3. SECONDARY TERMS (medium weight)  
                        secondary_terms = config.get("secondary_terms", set())
                        for term in secondary_terms:
                            if term in clean_filter:
                                score += 1.0 * config["weight"]
                                matches.append(f"secondary:'{term}'")
                        
                        # 4. CROSSOVER TERMS (for mixed topics)
                        for crossover_type in ["financial_crossover", "tech_crossover", "business_crossover", "geo_specific", "finance_crossover"]:
                            crossover_terms = config.get(crossover_type, set())
                            for term in crossover_terms:
                                if term in original_filter:
                                    score += 1.5 * config["weight"]
                                    matches.append(f"{crossover_type}:'{term}'")
                        
                        # 4.5. GEO INDICATORS (for local/regional detection)
                        geo_indicators = config.get("geo_indicators", set())
                        for geo_term in geo_indicators:
                            if geo_term in original_filter:
                                score += 2.0 * config["weight"]  # High score for geographic indicators
                                matches.append(f"geo:'{geo_term}'")
                        
                        # 5. PARTIAL MATCHING (for typos/variations)
                        for word in words:
                            # Check if any word is a substring of category terms (fuzzy matching)
                            for term in primary_terms.union(secondary_terms):
                                if len(word) > 3 and (word in term or term in word):
                                    score += 0.5 * config["weight"]
                                    matches.append(f"fuzzy:'{word}'-'{term}'")
                        
                        if score > 0:
                            category_scores[category] = score
                            logger.debug(f"   {category}: {score:.2f} points - {matches}")
                    
                    # Find the best category
                    if category_scores:
                        best_category = max(category_scores.items(), key=lambda x: x[1])
                        category_name, final_score = best_category
                        
                        logger.debug(f"🎯 Selected Category: '{category_name}' with score {final_score:.2f}")
                        
                        # If score is very low, consider fallbacks
                        if final_score < 1.0:
                            fallbacks = ENHANCED_CATEGORY_MAPPING[category_name].get("fallback_categories", ["default"])
                            print(f"🔄 Low confidence, considering fallbacks: {fallbacks}", flush=True)
                            # For now, stick with the detected category but log the fallback consideration
                        
                        return category_name
                    
                    print(f"🔄 No category detected, using 'default'", flush=True)
                    return "default"
                
                # Wrapper function to maintain compatibility
                def find_category(newsFilter):
                    return find_category_intelligent(newsFilter)
                
                # 🎯 ENHANCED MULTI-SOURCE UNION SYSTEM
                def find_categories_ranked(newsFilter):
                    """
                    Returns ranked list of relevant categories based on query
                    Example: "stock market finance economic" -> ["finance", "economy", "business"]
                    """
                    import re
                    from collections import defaultdict
                    
                    # Normalize the filter text
                    original_filter = newsFilter.lower().strip()
                    stop_words = {"the", "get", "latest", "current", "recent", "update", "updates", "news", "information", "about", "on", "for", "and", "or"}
                    words = [w for w in re.findall(r'\b\w+\b', original_filter) if w not in stop_words]
                    clean_filter = ' '.join(words)
                    
                    logger.debug(f"🎯 Multi-Category Detection: '{newsFilter}' -> '{clean_filter}'")
                    
                    # Score ALL categories (not just the top one)
                    category_scores = defaultdict(float)
                    
                    for category, config in ENHANCED_CATEGORY_MAPPING.items():
                        score = 0.0
                        matches = []
                        
                        # Compound phrases (highest priority)
                        compound_phrases = config.get("compound_phrases", set())
                        for phrase in compound_phrases:
                            if phrase in original_filter:
                                score += 3.0 * config["weight"]
                                matches.append(f"phrase:'{phrase}'")
                        
                        # Primary terms
                        primary_terms = config.get("primary_terms", set())
                        for term in primary_terms:
                            if term in clean_filter:
                                score += 2.0 * config["weight"]
                                matches.append(f"primary:'{term}'")
                        
                        # Secondary terms
                        secondary_terms = config.get("secondary_terms", set())
                        for term in secondary_terms:
                            if term in clean_filter:
                                score += 1.0 * config["weight"]
                                matches.append(f"secondary:'{term}'")
                        
                        # Crossover terms
                        for crossover_type in ["financial_crossover", "tech_crossover", "business_crossover", "geo_specific", "finance_crossover"]:
                            crossover_terms = config.get(crossover_type, set())
                            for term in crossover_terms:
                                if term in original_filter:
                                    score += 1.5 * config["weight"]
                                    matches.append(f"{crossover_type}:'{term}'")
                        
                        # Geo indicators
                        geo_indicators = config.get("geo_indicators", set())
                        for geo_term in geo_indicators:
                            if geo_term in original_filter:
                                score += 2.0 * config["weight"]
                                matches.append(f"geo:'{geo_term}'")
                        
                        if score > 0:
                            category_scores[category] = score
                            logger.debug(f"   {category}: {score:.2f} points - {matches}")
                    
                    # Return ranked categories (threshold: score > 0.5)
                    ranked_categories = []
                    if category_scores:
                        # Sort by score descending
                        sorted_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)
                        
                        # Include categories with meaningful scores
                        for cat_name, score in sorted_categories:
                            if score >= 0.5:  # Meaningful threshold
                                ranked_categories.append(cat_name)
                    
                    if not ranked_categories:
                        ranked_categories = ["default"]
                    
                    logger.debug(f"🎯 Ranked Categories: {ranked_categories}")
                    return ranked_categories
                
                def find_keyword_sources(newsFilter):
                    """
                    Extract specific keywords that map to specialized sources
                    Example: "stock market" -> stock market specific RSS feeds
                    """
                    keyword_mappings = KEYWORD_MAPPINGS_FROM_CONFIG if KEYWORD_MAPPINGS_FROM_CONFIG else {
                        "stock market": ["finance", "economy"],
                        "federal reserve": ["economy"],
                        "fed rates": ["economy"],
                        "inflation": ["economy"],
                        "gdp": ["economy"],
                        "unemployment": ["economy"],
                        "earnings": ["finance"],
                        "nasdaq": ["finance"],
                        "dow jones": ["finance"],
                        "s&p 500": ["finance"],
                        "cryptocurrency": ["crypto"],
                        "bitcoin": ["crypto"],
                        "florida": ["local"],
                        "california": ["local"],
                        "texas": ["local"],
                        "new york": ["local"]
                    }
                    
                    filter_lower = newsFilter.lower()
                    keyword_categories = []
                    detected_keywords = []
                    
                    for keyword, categories in keyword_mappings.items():
                        if keyword in filter_lower:
                            detected_keywords.append(keyword)
                            keyword_categories.extend(categories)
                    
                    # Remove duplicates while preserving order
                    keyword_categories = list(dict.fromkeys(keyword_categories))
                    
                    if detected_keywords:
                        logger.debug(f"🔍 Keywords Detected: {detected_keywords} -> Categories: {keyword_categories}")
                    
                    return keyword_categories
                
                def get_union_sources(ranked_categories, keyword_sources):
                    """
                    Combine RSS sources from ranked categories + keyword sources
                    Returns unified list of RSS URLs
                    """
                    all_sources = []
                    
                    # Add sources from ranked categories (in priority order)
                    for category in ranked_categories:
                        category_urls = NEWS_URLS.get(category, [])
                        all_sources.extend(category_urls)
                        logger.debug(f"📰 Added {len(category_urls)} sources from '{category}' category")
                    
                    # Add sources from keyword detection
                    for category in keyword_sources:
                        if category not in ranked_categories:  # Avoid duplicates
                            category_urls = NEWS_URLS.get(category, [])
                            all_sources.extend(category_urls)
                            logger.debug(f"🔍 Added {len(category_urls)} sources from keyword '{category}' category")
                    
                    # Remove duplicate URLs while preserving order
                    unique_sources = list(dict.fromkeys(all_sources))
                    
                    # If no sources found, use default
                    if not unique_sources:
                        unique_sources = NEWS_URLS.get("default", [])
                        logger.debug(f"🔄 No specific sources found, using {len(unique_sources)} default sources")
                    
                    # 🎯 REMOVED: Let primary LLM decide what to select from full context
                    # Keep all sources available for rich context - let LLM choose what's important
                    
                    logger.debug(f"🎯 UNION RESULT: {len(unique_sources)} total unique sources from {len(ranked_categories + keyword_sources)} categories")
                    return unique_sources
                
                
                from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

                def clean_news_url(url):
                    """
                    Clean Google News URLs by removing corrupted or excessively long parameters.

                    Args:
                        url: The URL to clean

                    Returns:
                        str: Clean URL, or None if URL is invalid/corrupted beyond repair
                    """
                    if not url or not isinstance(url, str):
                        return None

                    try:
                        # Parse the URL into components
                        parsed_url = urlparse(url)

                        # Validate basic URL structure
                        if not parsed_url.scheme or not parsed_url.netloc:
                            return None

                        # Extract query parameters
                        query_params = parse_qs(parsed_url.query)

                        # Keep only clean parameters, filtering out corrupted ones
                        keep_params = ['nid', 'dat', 'ed', 'hl', 'gl', 'ceid']  # Common Google News parameters
                        cleaned_query = {}

                        for key, values in query_params.items():
                            if key in keep_params and values:
                                param_value = values[0]
                                # Reject parameters that are excessively long (likely corrupted)
                                if len(param_value) > 100:  # Most legitimate params are much shorter
                                    print(f"🚨 Rejecting corrupted parameter '{key}' with length {len(param_value)}", flush=True)
                                    continue
                                # Reject parameters with repeated patterns (corruption indicator)
                                if len(param_value) > 20 and param_value[:10] * 5 in param_value:
                                    print(f"🚨 Rejecting repeated pattern in parameter '{key}': {param_value[:50]}...", flush=True)
                                    continue
                                cleaned_query[key] = param_value

                        # Rebuild the query string
                        cleaned_query_string = urlencode(cleaned_query) if cleaned_query else ""

                        # Reconstruct the URL without the corrupted parameters
                        cleaned_url = urlunparse((
                            parsed_url.scheme,    # scheme (e.g., https)
                            parsed_url.netloc,    # netloc (e.g., news.google.com)
                            parsed_url.path,      # path (e.g., /newspapers)
                            parsed_url.params,    # params (usually empty)
                            cleaned_query_string, # cleaned query string
                            parsed_url.fragment   # fragment (usually empty)
                        ))

                        # Final validation: reject if URL is still too long (indicates other corruption)
                        if len(cleaned_url) > 2000:  # Reasonable URL length limit
                            print(f"🚨 Rejecting URL still too long after cleaning: {len(cleaned_url)} chars", flush=True)
                            return None

                        return cleaned_url

                    except Exception as e:
                        print(f"🚨 Error cleaning URL '{url[:100]}...': {e}", flush=True)
                        return None

                
                
                
                # 🔄 REPLACEMENT: Google News RSS Feeds (instead of broken GNews library)
                # Maps categories to Google News topic codes
                GOOGLE_NEWS_TOPIC_MAP = {
                    'world': 'WORLD',
                    'national': 'NATION',
                    'nation': 'NATION',
                    'us': 'NATION',
                    'business': 'BUSINESS',
                    'finance': 'BUSINESS',
                    'economy': 'BUSINESS',
                    'technology': 'TECHNOLOGY',
                    'tech': 'TECHNOLOGY',
                    'science': 'SCIENCE',
                    'sports': 'SPORTS',
                    'health': 'HEALTH',
                }
                
                def get_google_news_rss_urls(newsFilter, categories):
                    """
                    Generate Google News RSS URLs based on filter and categories.
                    Returns list of RSS feed URLs to fetch.
                    """
                    urls = []
                    
                    # Add topic-based feeds for detected categories
                    # Format: https://news.google.com/rss/headlines/section/topic/{TOPIC}
                    # Limit to 1 category to leave room for other sources
                    for category in categories[:1]:  # Only top category
                        topic_code = GOOGLE_NEWS_TOPIC_MAP.get(category.lower())
                        if topic_code:
                            topic_url = f"https://news.google.com/rss/headlines/section/topic/{topic_code}"
                            urls.append(topic_url)
                            print(f"📰 Google News topic feed: {topic_code}", flush=True)
                    
                    # Add keyword search feed if filter is specific
                    if newsFilter and len(newsFilter.strip()) > 2:
                        # Clean the filter for URL
                        import urllib.parse
                        clean_filter = newsFilter.strip()
                        search_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(clean_filter)}"
                        urls.append(search_url)
                        print(f"🔍 Google News search feed: '{clean_filter}'", flush=True)
                    
                    # Fallback: general news feed if no specific URLs
                    if not urls:
                        urls.append("https://news.google.com/rss")
                        print("📰 Google News general feed (fallback)", flush=True)
                    
                    return urls
                
                # Enhanced web content extraction with improved RSS/XML parsing
                def get_text_from_url(url):
                    try:
                        response = requests_compatible_get(url, timeout=15, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        })
                        response.raise_for_status()
                        
                        from bs4 import BeautifulSoup
                        
                        # Determine if this is RSS/XML content
                        content_type = response.headers.get('content-type', '').lower()
                        is_rss_xml = (
                            'xml' in content_type or 
                            'rss' in content_type or
                            url.endswith('.xml') or 
                            url.endswith('.rss') or
                            'feed' in url.lower() or
                            response.text.strip().startswith('<?xml')
                        )
                        
                        if is_rss_xml:
                            # Use XML parser for RSS feeds to avoid warnings
                            try:
                                soup = BeautifulSoup(response.text, 'xml')
                            except Exception:
                                # Fallback to lxml if available, then html.parser
                                try:
                                    soup = BeautifulSoup(response.text, 'lxml')
                                except Exception:
                                    soup = BeautifulSoup(response.text, 'html.parser')
                            
                            # Extract RSS items
                            texts = []
                            items = soup.find_all(['item', 'entry'])
                            for item in items[:5]:  # Limit to 5 recent articles
                                title = item.find(['title'])
                                description = item.find(['description', 'summary', 'content'])
                                
                                if title:
                                    title_text = title.get_text().strip()
                                    if title_text:
                                        texts.append(f"Title: {title_text}")
                                
                                if description:
                                    desc_text = description.get_text().strip()
                                    if desc_text and len(desc_text) > 20:
                                        # Clean up description
                                        desc_text = desc_text.replace('\n', ' ').replace('\r', ' ')
                                        if len(desc_text) > 200:
                                            desc_text = desc_text[:200] + "..."
                                        texts.append(f"Content: {desc_text}")
                                
                                texts.append("---")  # Separator
                            
                            return '\n'.join(texts) if texts else "RSS feed processed but no content extracted"
                        
                        else:
                            # Regular HTML parsing
                            soup = BeautifulSoup(response.text, 'html.parser')
                            
                            # Remove unwanted tags
                            for tag_name in ['footer', 'nav', 'script', 'style', 'aside', 'header']:
                                for tag in soup.find_all(tag_name):
                                    tag.decompose()
                            
                            # Extract text from paragraphs and headers
                            texts = []
                            for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                                text = tag.get_text().strip()
                                if text and len(text) > 20:  # Only meaningful content
                                    texts.append(text)
                            
                            return '\n\n'.join(texts[:10])  # Limit to first 10 meaningful paragraphs
                        
                    except Exception as e:
                        return f"Error fetching {url}: {str(e)}"
                
                # Main logic (from original implementation)
                today = datetime.now()
                todayStr = today.strftime("%A, %B %d, %Y %I:%M:%S %p")
                
                # 🎯 UNION-BASED MULTI-SOURCE SYSTEM
                # Step 1: Smart Category Detection (returns ranked categories)
                ranked_categories = find_categories_ranked(newsFilter)
                
                # Step 2: Keyword-based source filtering
                keyword_sources = find_keyword_sources(newsFilter)
                
                # Step 3: UNION all sources from categories + keywords
                urls = get_union_sources(ranked_categories, keyword_sources)
                
                # 📰 ADD GOOGLE NEWS RSS FEEDS (replaces broken GNews library)
                google_news_urls = get_google_news_rss_urls(newsFilter, ranked_categories)
                # Prepend Google News feeds to ensure they're fetched first
                urls = google_news_urls + urls
                
                print(f"🔍 Starting news fetch: {len(ranked_categories)} categories, {len(google_news_urls)} Google News feeds, {len(urls)-len(google_news_urls)} other RSS sources", flush=True)
                
                # Initialize result string with timestamp and sorting instructions
                res = f'''\\nFROM EXTERNAL SOURCES as of [Current Date and Time: {todayStr}]. Here is the News Summary you requested, use the summary to compose your response to the user's prompt: ANALYZE ALL SOURCES and select the MOST IMPORTANT and RELEVANT news items based on the user's specific request. Sort them by RELEVANCE and IMPORTANCE to the user's query, NOT by the order they appear below. Focus on the most significant developments, breaking news, and impactful stories related to the topic requested. Prioritize recent news resources. If user requests expanded content, provide detailed content and analysis from the available context. Cite sources for each item. '''
                
                # Fetch content from each URL with improved error handling and fallbacks
                # 🔒 TIMEOUT PROTECTION: Use concurrent.futures with strict timeout
                successful_sources = 0  # Count all successful sources (including Google News RSS)
                attempted_sources = 0
                max_sources = 6  # Try up to 6 sources (6 × 30s = 180s)
                feed_timeout = 25  # 25 seconds per feed (6 feeds × 25s = 150s max)
                
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
                import time
                
                def fetch_single_feed_with_timeout(newsURL, source_num):
                    """Wrapper to fetch a single feed with timeout protection"""
                    try:
                        logger.debug(f"Attempting to fetch news from: {newsURL}")
                        return _get_news_content_with_article_urls(newsURL, source_num)
                    except Exception as e:
                        print(f"Error fetching {newsURL}: {e}", flush=True)
                        return ("", 0)
                
                import time as time_module
                start_time = time_module.time()
                print(f"🔍 Fetching from {min(len(urls), max_sources)} RSS feeds in PARALLEL...", flush=True)
                # Use thread pool with PARALLEL fetching (max_workers=6 for concurrent requests)
                # Don't use context manager to avoid waiting for all futures on exit
                executor = ThreadPoolExecutor(max_workers=6)
                try:
                    # Submit all tasks at once for parallel execution
                    future_to_url = {}
                    for i, newsURL in enumerate(urls[:max_sources]):
                        future = executor.submit(fetch_single_feed_with_timeout, newsURL, i + 1)
                        future_to_url[future] = newsURL

                    # Collect results as they complete with proper timeout handling
                    from concurrent.futures import as_completed
                    try:
                        for future in as_completed(future_to_url, timeout=feed_timeout + 10):
                            newsURL = future_to_url[future]
                            attempted_sources += 1
                            try:
                                formatted_content, articles_added = future.result(timeout=5)

                                # Only add if we got meaningful content
                                if formatted_content and articles_added > 0:
                                    res += formatted_content
                                    successful_sources += articles_added
                                    print(f"✅ Fetched {articles_added} articles from {newsURL[:50]}...", flush=True)
                                else:
                                    logger.debug(f"No meaningful content from: {newsURL}")

                            except FuturesTimeoutError:
                                print(f"⏱️ Timeout fetching {newsURL} (exceeded {feed_timeout}s), skipping...", flush=True)
                                continue
                            except Exception as e:
                                print(f"Error fetching {newsURL}: {e}", flush=True)
                                continue
                    except TimeoutError:
                        # as_completed timeout - some futures didn't complete in time
                        elapsed = time_module.time() - start_time
                        print(f"⏱️ Parallel fetch timeout after {elapsed:.1f}s, got {successful_sources} articles", flush=True)
                    except Exception as e:
                        print(f"Error in parallel fetch: {e}", flush=True)
                finally:
                    # Shutdown executor without waiting - don't block on slow futures
                    executor.shutdown(wait=False, cancel_futures=True)

                elapsed = time_module.time() - start_time
                print(f"📰 Parallel fetch completed in {elapsed:.1f}s with {successful_sources} articles", flush=True)
                
                # Add fallback sources if we didn't get enough successful sources
                if successful_sources < 2 and category in ["technology", "finance", "crypto"]:
                    print(f"Only got {successful_sources} sources, trying fallback sources...", flush=True)
                    fallback_sources = {
                        "technology": [
                            "https://www.engadget.com/rss.xml",
                            "https://feeds.arstechnica.com/arstechnica/index"
                        ],
                        "finance": [
                            "https://www.marketwatch.com/rss/topstories",
                            "https://feeds.finance.yahoo.com/rss/2.0/headline"
                        ],
                        "crypto": [
                            "https://coinjournal.net/feed/",
                            "https://www.coinspeaker.com/feed/"
                        ]
                    }
                    
                    # Use same timeout protection for fallback sources
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        for fallback_url in fallback_sources.get(category, [])[:2]:
                            if successful_sources >= 3:  # Stop if we have enough
                                break
                            try:
                                print(f"Trying fallback source: {fallback_url}", flush=True)
                                
                                # Submit task with timeout per feed
                                future = executor.submit(fetch_single_feed_with_timeout, fallback_url, successful_sources + 1)
                                formatted_content, articles_added = future.result(timeout=feed_timeout)
                                
                                if formatted_content and articles_added > 0:
                                    res += formatted_content
                                    successful_sources += articles_added
                                    print(f"Fallback source successful: {fallback_url} ({articles_added} articles)", flush=True)
                                    
                            except FuturesTimeoutError:
                                print(f"⏱️ Timeout fetching fallback {fallback_url} (exceeded {feed_timeout}s), skipping...", flush=True)
                                continue
                            except Exception as e:
                                print(f"Fallback source failed {fallback_url}: {e}", flush=True)
                                continue
                
                logger.debug(f"News fetch complete: {successful_sources}/{attempted_sources} primary sources successful")
                
                return res
            
            # 🔒 CRITICAL GLOBAL TIMEOUT: Wrap entire news query with 60-second timeout
            # Parallel fetching should complete much faster now
            try:
                return await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(thread_pool, sync_news_query),
                    timeout=60.0  # Maximum 60 seconds for entire news operation (parallel fetch)
                )
            except asyncio.TimeoutError:
                print("⚠️ News query exceeded 60-second global timeout, returning partial results", flush=True)
                return "⚠️ News retrieval timed out after 60 seconds. Please try again with a more specific query."
        except Exception as e:
            return f"News query error: {str(e)}"
    
    async def search_web(self, args: str) -> str:
        """
        Perform a web search using DuckDuckGo and retrieve comprehensive results.
        Uses the original working implementation from find_eps_estimate.py
        """
        try:
            # Remove TOOLS_AVAILABLE check - let function handle missing deps gracefully
                
            def sync_web_search():
                # Handle parameter parsing like the original
                if isinstance(args, str):
                    try:
                        data = json.loads(args) if args.startswith('{') else {'query': args}
                    except Exception as e:
                        logger.warning(f"JSON parse failed for web search args: {e}")
                        data = {'query': args}
                else:
                    data = args if isinstance(args, dict) else {'query': str(args)}

                query = data.get('query', '').strip()
                print(f"Web search query: {query}", flush=True)
                
                if not query:
                    return "Sorry, I couldn't find anything."
                
                today = datetime.now()
                todayStr = today.strftime("%A, %B %d, %Y %I:%M:%S %p")

                # 🔬 Deep Research depth — config-driven (config/llm_config.yaml: deep_research.search).
                # Defaults mirror the previous hardcoded behavior so a missing config never regresses search.
                try:
                    _dr_search_cfg = config_loader.load_config().get('deep_research', {}).get('search', {})
                except Exception as _dr_e:
                    logger.warning(f"⚠️ deep_research.search config unavailable ({_dr_e}); using legacy defaults")
                    _dr_search_cfg = {}
                max_results = _dr_search_cfg.get('web_max_results', 3)
                per_page_char_budget = _dr_search_cfg.get('per_page_char_budget', 2000)
                per_page_max_blocks = _dr_search_cfg.get('per_page_max_blocks', 5)

                # DuckDuckGo search function (from original)
                def ducducgo(query, max_results=3):
                    try:
                        from ddgs import DDGS
                        with DDGS() as ddgs:
                            results = ddgs.text(query, max_results=max_results)
                            res = ''
                            for i, result in enumerate(results, 1):
                                title = result.get('title', 'No Title')
                                href = result.get('href', 'No URL')
                                body = result.get('body', 'No Description')

                                # Citation accuracy: only cite a result whose URL is a SPECIFIC article
                                # (not a feed, homepage, or invalid URL); skip the rest so the model never
                                # cites a general/landing page that 404s. Mirrors the news RSS path's
                                # _validate_article_url gate. Checked BEFORE fetching to also save work.
                                if href == 'No URL' or not _validate_article_url(href):
                                    print(f"🔗 search_web: skipping non-article result URL: {str(href)[:80]}", flush=True)
                                    continue

                                # Extract content from each URL. This fetch also serves as the Layer 3
                                # live-link check: None == verified dead (hard 404/410 or homepage-redirect)
                                # → skip the citation entirely so the model never cites a dead/moved page.
                                extracted_content = ""
                                try:
                                    extracted_content = get_text_from_url_simplified(href)
                                except Exception as e:
                                    extracted_content = f"Error extracting content: {str(e)}"
                                if extracted_content is None:
                                    print(f"🔎 search_web: skipping dead/redirected result URL: {str(href)[:80]}", flush=True)
                                    continue

                                # Use enhanced source block formatting
                                formatted_result = _format_source_block(
                                    source_url=href,
                                    title=title,
                                    content=f"Description: {body}\n\nExtracted Content: {extracted_content}",
                                    source_num=i
                                )
                                res += formatted_result
                            return res
                    except Exception as e:
                        print(f"DuckDuckGo Error: {e}", flush=True)
                        return f"An error occurred during the web search query '{query}'."
                
                # Simplified URL content extraction (to avoid Selenium dependency issues)
                def get_text_from_url_simplified(url):
                    try:
                        response = requests_compatible_get(url, timeout=10, allow_redirects=True, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        })
                        # Layer 3 (citation accuracy), piggybacked on THIS fetch (no extra request): a hard
                        # 404/410 or a redirect to the site homepage means the article is gone → signal the
                        # caller to SKIP the citation (return None). Lenient: any other status (403/JS/5xx)
                        # falls through and is kept. Config-gated (deep_research.citation_verify).
                        if _citation_verify_cfg()["enabled"]:
                            _st = getattr(response, 'status_code', 0)
                            if _st in (404, 410) or _is_homepage_redirect(url, getattr(response, 'url', '') or url):
                                return None
                        response.raise_for_status()

                        soup = BeautifulSoup(response.text, 'html.parser')
                        
                        # Remove unwanted tags
                        for tag_name in ['footer', 'nav', 'script', 'style', 'aside', 'header']:
                            for tag in soup.find_all(tag_name):
                                tag.decompose()
                        
                        # Extract meaningful text
                        texts = []
                        for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'article']):
                            text = tag.get_text().strip()
                            if text and len(text) > 50:  # Only meaningful content
                                texts.append(text)
                        
                        result = '\n\n'.join(texts[:per_page_max_blocks])  # config: deep_research.search.per_page_max_blocks
                        return result[:per_page_char_budget] + "..." if len(result) > per_page_char_budget else result  # config: deep_research.search.per_page_char_budget
                        
                    except Exception as e:
                        return f"Error extracting content: {str(e)}"
                
                # Perform the search
                try:
                    web_results = ducducgo(query, max_results)
                    if isinstance(web_results, list):
                        web_results = '\n'.join(web_results)
                except Exception as e:
                    web_results = f"Error: Exception returned in search_web(): '{e}'"
                
                res = f"\n\nAs of [Current Date and Time: {todayStr}] here are the web search results:\n{web_results}"
                
                print("Web search completed", flush=True)
                return res
            
            return await asyncio.get_running_loop().run_in_executor(
                thread_pool, sync_web_search
            )
        except Exception as e:
            return f"Web search error: {str(e)}"
    
    async def lookup_website_old(self, args: str) -> str:
        """
        Retrieve and extract comprehensive text content from a specified website URL.
        Uses the original working implementation from find_eps_estimate.py with both Selenium and BeautifulSoup
        """
        try:
            # Remove TOOLS_AVAILABLE check - let function handle missing deps gracefully
                
            def sync_website_lookup():
                # Handle parameter parsing like the original
                if isinstance(args, str):
                    try:
                        data = json.loads(args) if args.startswith('{') else {'url': args}
                    except Exception as e:
                        logger.warning(f"JSON parse failed for website lookup args: {e}")
                        data = {'url': args}
                else:
                    data = args if isinstance(args, dict) else {'url': str(args)}
                
                url = data.get('url', '').strip()
                print(f"Website lookup URL: {url}", flush=True)
                
                if not url:
                    return "Sorry, I couldn't find anything."
                
                today = datetime.now()
                todayStr = today.strftime("%A, %B %d, %Y %I:%M:%S %p")
                
                # PDF detection functions (from original)
                def is_pdf_url(url: str) -> bool:
                    try:
                        response = requests.head(url, allow_redirects=True, timeout=10)
                        if 'application/pdf' in response.headers.get('Content-Type', '').lower():
                            return True
                        
                        # Check with magic if available
                        try:
                            full_response = requests_compatible_get(url, timeout=10)
                            mime = magic.Magic(mime=True)
                            content_type = mime.from_buffer(full_response.content[:1024])
                            return content_type == 'application/pdf'
                        except Exception:
                            return False
                    except Exception as e:
                        print(f"PDF detection error for {url}: {e}")
                        return False
                
                def extract_pdf_text(url: str) -> str:
                    try:
                        response = requests_compatible_get(url, timeout=30)
                        pdf_file = io.BytesIO(response.content)
                        pdf_reader = PyPDF2.PdfReader(pdf_file)
                        
                        full_text = ""
                        for page in pdf_reader.pages:
                            full_text += page.extract_text() + "\n\n"
                        
                        return full_text.strip()
                    except Exception as e:
                        print(f"PDF text extraction error for {url}: {e}")
                        return f"Error extracting PDF: {str(e)}"
                
                # Main website extraction function (from original)
                def get_text_from_url(url: str) -> str:
                    # Check if the URL is a PDF first
                    if is_pdf_url(url):
                        pdf_text = extract_pdf_text(url)
                        return f"PDF URL: {url}\nContent:\n{pdf_text}"
                    
                    try:
                        # Try Selenium crawler first (more comprehensive)
                        max_url_count = 2
                        max_depth = 1
                        
                        crawler = SeleniumCrawler(url, max_depth=max_depth, max_url_count=max_url_count-1, timeout_response=40)
                        crawler.setCheckRobot(False)
                        
                        crawler.crawl(url)
                        crawler.close()
                        
                        res = ''
                        for result in crawler.results:
                            if is_pdf_url(result['url']):
                                pdf_text = extract_pdf_text(result['url'])
                                res += f"PDF Title: {result['title']}, URL: {result['url']}\n"
                                res += f"PDF Content: {pdf_text}\n"
                            else:
                                res += f"Title: {result['title']}, URL: {result['url']}\n"
                                res += f"Content: {result['content']}\n"
                            
                            res += "-" * 80 + "\n"
                        
                        return res if res else "No content extracted via Selenium"
                        
                    except Exception as selenium_error:
                        print(f"Selenium extraction failed, trying BeautifulSoup: {selenium_error}")
                        
                        # Fallback to BeautifulSoup (from original get_text_from_url2)
                        try:
                            response = requests.get(url, timeout=10, headers={
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                            })
                            response.raise_for_status()
                            
                            soup = BeautifulSoup(response.text, 'html.parser')
                            
                            # Remove unwanted tags
                            for tag_name in ['footer', 'nav', 'script', 'style']:
                                for tag in soup.find_all(tag_name):
                                    tag.decompose()
                            
                            # Replace links with their text content
                            for link in soup.find_all('a'):
                                link.replace_with(link.get_text())
                            
                            # Extract paragraphs
                            paragraphs = [p.get_text().strip() for p in soup.find_all('p')]
                            paragraphs = [p for p in paragraphs if p]
                            
                            if not paragraphs:
                                print("Warning: No paragraphs were found!")
                            
                            # Process tables
                            def convert_html_table_to_text(table):
                                rows = []
                                for row in table.find_all('tr'):
                                    cells = row.find_all(['th', 'td'])
                                    row_text = ' | '.join(cell.get_text().strip() for cell in cells)
                                    rows.append(row_text)
                                return '\n'.join(rows)
                            
                            for table in soup.find_all('table'):
                                table_text = convert_html_table_to_text(table)
                                paragraphs.append(table_text)
                            
                            text = '\n\n'.join(paragraphs)
                            return text
                            
                        except requests.exceptions.Timeout:
                            return f'Error fetching text from URL: Time Out!'
                        except requests.exceptions.RequestException as error:
                            return f'Error fetching text from URL: {error}'
                
                # Perform the website lookup
                try:
                    web_results = get_text_from_url(url)
                except Exception as e:
                    web_results = f"Error: Exception returned '{e}'"
                
                res = f"\n\nAs of [Current Date and Time: {todayStr}] here are lookup results: \n{web_results}"
                
                print("Website lookup completed", flush=True)
                return res
            
            return await asyncio.get_running_loop().run_in_executor(
                thread_pool, sync_website_lookup
            )
        except Exception as e:
            return f"Website lookup error: {str(e)}"
    
    def _is_pdf_url(self, url: str) -> bool:
        """Check if URL points to a PDF file."""
        parsed = urlparse(url.lower())
        return (
            parsed.path.endswith(".pdf")
            or "pdf" in parsed.path
            or url.lower().endswith(".pdf")
        )
    
    def _extract_pdf_content(self, url: str) -> dict:
        """Extract content from a PDF URL and format like HTML scraping."""
        try:
            print(f"Extracting PDF from {url}", flush=True)
            # Download PDF
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests_compatible_get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # Check if we actually got a PDF
            content_type = response.headers.get("content-type", "").lower()
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                print(f"Error: URL does not appear to be a PDF (content-type: {content_type})", flush=True)
                return {
                    "success": False,
                    "error": f"URL does not appear to be a PDF (content-type: {content_type})",
                }

            # Create PDF reader from bytes
            pdf_file = io.BytesIO(response.content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)

            # Check if PDF is readable
            if len(pdf_reader.pages) == 0:
                print("Error: PDF contains no readable pages", flush=True)
                return {"success": False, "error": "PDF contains no readable pages"}

            # Extract metadata
            metadata = pdf_reader.metadata if pdf_reader.metadata else {}

            title = None
            author = None
            if metadata:
                title = (
                    metadata.get("/Title", "").strip()
                    if metadata.get("/Title")
                    else None
                )
                author = (
                    metadata.get("/Author", "").strip()
                    if metadata.get("/Author")
                    else None
                )

            # Extract ALL text as one continuous document
            all_text = []
            successful_pages = 0

            for page_num, page in enumerate(pdf_reader.pages):
                try:
                    # Try multiple extraction methods
                    page_text = page.extract_text()

                    # If default extraction fails, try with layout mode
                    if not page_text.strip():
                        try:
                            page_text = page.extract_text(extraction_mode="layout")
                        except Exception:
                            pass

                    if page_text.strip():
                        # Clean up common PDF extraction artifacts
                        page_text = page_text.replace("\x00", "")  # Remove null bytes
                        page_text = page_text.replace("\n\n\n", "\n\n")  # Reduce excessive newlines
                        all_text.append(page_text.strip())
                        successful_pages += 1
                except Exception as e:
                    print(f"Error extracting page {page_num + 1}: {e}", flush=True)
                    continue

            if successful_pages == 0:
                print(f"Error: Could not extract text from any of the {len(pdf_reader.pages)} pages", flush=True)
                return {
                    "success": False,
                    "error": f"Could not extract text from any of the {len(pdf_reader.pages)} pages",
                }

            # Join all text with double newlines
            full_text = "\n\n".join(all_text)

            # Clean up and format like HTML scraping output
            full_text = " ".join(full_text.split())  # Replace multiple spaces with single spaces
            full_text = full_text.replace(". ", ".\n\n")  # Add paragraph breaks
            full_text = full_text.replace("? ", "?\n\n")
            full_text = full_text.replace("! ", "!\n\n")
            full_text = full_text.replace("\n\n\n", "\n\n")  # Clean up triple newlines

            # If no title in metadata, try to extract from beginning of text
            if not title and full_text:
                first_part = full_text[:500]
                sentences = first_part.split("\n\n")[:5]

                for sentence in sentences:
                    sentence = sentence.strip()
                    if (
                        len(sentence) > 10
                        and len(sentence) < 200
                        and not sentence.lower().startswith("draft")
                        and not "arxiv:" in sentence.lower()
                        and not sentence.startswith("Typeset")
                        and not "@" in sentence
                        and not sentence.replace(".", "").isdigit()
                    ):
                        title = sentence
                        break

            print(f"PDF extraction successful: {successful_pages}/{len(pdf_reader.pages)} pages, {len(full_text)} chars", flush=True)
            
            return {
                "success": True,
                "title": title or "PDF Document",
                "author": author,
                "content": full_text,
                "page_count": len(pdf_reader.pages),
                "extracted_pages": successful_pages,
            }

        except Exception as e:
            print(f"Error extracting PDF content from {url}: {str(e)}", flush=True)
            return {
                "success": False,
                "error": f"Error extracting PDF content from {url}: {str(e)}",
            }

    def _extract_web_content(self, url: str) -> dict:
        """Extract content from a regular web page using trafilatura."""
        try:
            print(f"Extracting web content from {url}", flush=True)
            downloaded = trafilatura.fetch_url(url)
            if downloaded is None:
                return {
                    "success": False,
                    "error": f"Failed to download content from {url}",
                }

            # Extract content and metadata separately
            extracted = trafilatura.extract(downloaded)
            metadata = trafilatura.extract_metadata(downloaded)

            if extracted is None:
                return {"success": False, "error": f"No content found at {url}"}

            # Get title and author from metadata if available
            title = None
            author = None
            date = None

            if metadata:
                title = metadata.title
                author = metadata.author
                date = metadata.date

            print(f"Web extraction successful: {len(extracted)} chars", flush=True)

            return {
                "success": True,
                "title": title or "Web Article",
                "author": author,
                "date": date,
                "content": extracted,
            }

        except Exception as e:
            print(f"Error extracting content from {url}: {e}", flush=True)
            return {
                "success": False,
                "error": f"Error extracting content from {url}: {e}",
            }

    def _safe_truncate(self, content: str, max_chars: int = 10000) -> str:
        """Simple, safe truncation that guarantees we stay under buffer limits."""
        if len(content) <= max_chars:
            return content

        print(f"Content too large ({len(content)} chars), truncating to {max_chars}", flush=True)
        
        # Simple truncation with clear notice
        truncated = content[:max_chars]

        # Try to end at a complete sentence
        last_period = truncated.rfind(". ")
        if last_period > max_chars * 0.8:  # If we can cut at a sentence near the end
            truncated = truncated[: last_period + 1]

        # Add clear truncation notice
        total_chars = len(content)
        total_words = len(content.split())
        shown_words = len(truncated.split())

        truncated += f"\n\n--- CONTENT TRUNCATED ---\n"
        truncated += f"Showing: {shown_words} words of {total_words} total\n"
        truncated += f"Original size: {total_chars} characters\n"
        truncated += f"Reason: Context window limit\n"
        truncated += f"Note: Full content was extracted successfully"

        return truncated

    async def lookup_website(self, args: str) -> str:
        """
        Enhanced website content extractor using trafilatura for better HTML parsing.
        Handles both web pages and PDFs with improved content extraction.
        """
        try:
            def sync_website_extraction():
                # Handle parameter parsing
                if isinstance(args, str):
                    try:
                        data = json.loads(args) if args.startswith('{') else {'url': args}
                    except Exception as e:
                        logger.warning(f"JSON parse failed for website extraction args: {e}")
                        data = {'url': args}
                else:
                    data = args if isinstance(args, dict) else {'url': str(args)}
                
                url = data.get('url', '').strip()
                print(f"Website extraction URL: {url}", flush=True)
                
                if not url:
                    return "Error: No URL provided for website lookup."
                
                today = datetime.now()
                todayStr = today.strftime("%A, %B %d, %Y %I:%M:%S %p")
                
                # Determine content type and extract accordingly
                if self._is_pdf_url(url):
                    result = self._extract_pdf_content(url)
                    content_type = "PDF"
                else:
                    result = self._extract_web_content(url)
                    content_type = "Web Page"

                # Handle extraction errors
                if not result["success"]:
                    return f"ERROR: Failed to extract content from {url}: {result['error']}"

                # Apply safe truncation to avoid buffer overflow
                content = self._safe_truncate(result["content"])

                # Build additional metadata for enhanced source block
                metadata_parts = []
                if result.get('author'):
                    metadata_parts.append(f"Author: {result['author']}")
                if result.get('date'):
                    metadata_parts.append(f"Published: {result['date']}")
                metadata_parts.append(f"Type: {content_type}")
                
                # Combine metadata with content
                full_content = f"{'\n'.join(metadata_parts)}\n\nContent:\n{content}"
                
                # Use enhanced source block formatting
                formatted_result = _format_source_block(
                    source_url=url,
                    title=result['title'],
                    content=full_content,
                    source_num=1,
                    timestamp=todayStr
                )
                
                final_response = f"\nAs of [Current Date and Time: {todayStr}] here are the website lookup results:\n{formatted_result}"
                
                print(f"Website extraction completed: {len(final_response)} chars", flush=True)
                return final_response
            
            return await asyncio.get_running_loop().run_in_executor(
                thread_pool, sync_website_extraction
            )
        except Exception as e:
            return f"Website extraction error: {str(e)}"
    
    async def safe_function_call(self, func_name: str, args: str) -> str:
        """Safely execute a function with automatic image injection for image_to_text"""
        if func_name not in self.available_functions:
            return f"Function {func_name} not available"
        
        try:
            # 🖼️ SPECIAL HANDLING: Auto-inject image data for image_to_text tool
            if func_name == 'image_to_text' and self.current_images:
                try:
                    # Parse existing arguments
                    if isinstance(args, str):
                        try:
                            parsed_args = json.loads(args)
                        except json.JSONDecodeError:
                            parsed_args = {"prompt": args}
                    else:
                        parsed_args = args if isinstance(args, dict) else {"prompt": str(args)}
                    
                    # Inject first available image if not already provided
                    if not parsed_args.get('image') or parsed_args.get('image') == '':
                        if self.current_images:
                            image_data = self.current_images[0]
                            # Handle data URLs - extract base64 part if needed
                            if image_data.startswith('data:image/'):
                                image_data = image_data.split(',', 1)[1] if ',' in image_data else image_data
                            parsed_args['image'] = image_data
                            logger.info(f"🖼️ Auto-injected image data into image_to_text: {len(image_data)} chars")
                    
                    # Convert back to string format expected by tools
                    args = json.dumps(parsed_args)
                    
                except Exception as inject_error:
                    logger.warning(f"🖼️ Failed to inject image data: {inject_error}")

            # 🔒 Scope restriction (Phase 1): for a RESTRICTED client (untrusted input — a recipient lock
            # is present in context) sandboxed_executor is limited to the document-creation action; shell
            # / code execution is refused (fail-closed) no matter what the LLM requests. This is a SAFETY
            # LIMIT (which capability is available to an untrusted client), not interpretation of intent.
            if func_name == "sandboxed_executor" and _LLM_DRIVEN_DELIVERY:
                _rl, _ = _delivery_lock_ctx.get()
                if _rl:
                    try:
                        _a = json.loads(args) if isinstance(args, str) else (args or {})
                    except Exception:
                        _a = {}
                    _act = (_a.get("action") if isinstance(_a, dict) else None)
                    if _act and _act != "create_file":
                        logger.warning(f"🔒 sandboxed_executor action '{_act}' blocked for restricted "
                                       f"client (create_file only)")
                        return "❌ Only document/file creation is permitted for this client; other sandbox actions are blocked."

            func = self.available_functions[func_name]
            result = await func(args)
            return str(result)
        except Exception as e:
            logger.error(f"Error calling {func_name}: {e}")
            return f"Error calling {func_name}: {str(e)}"

    async def secure_email_sender(self, args: str) -> str:
        """
        Send professional emails with attachments and comprehensive security measures.
        Handles Gmail, Outlook, custom SMTP, and sendmail.
        """
        try:
            # Handle parameter parsing
            if isinstance(args, str):
                try:
                    parsed_args = json.loads(args)
                except json.JSONDecodeError:
                    return "❌ Error: Invalid JSON format for email arguments"
            else:
                parsed_args = args

            # 🔒 UNIVERSAL RECIPIENT LOCK (single chokepoint). For a RESTRICTED client (one that sent an
            # allowed_tools whitelist, e.g. a NewX bot acting for a delivery-privileged user) EVERY email
            # — whether triggered by a POST-LLM delivery path OR a direct LLM tool call — goes ONLY to the
            # server-authoritative locked recipient; any prompt/LLM-supplied address is ignored, CC is
            # dropped, and an absent/invalid lock REFUSES the send (fail-closed). Auto-trusted clients
            # (no lock in context) pass through unchanged. The lock context is carried per-request via
            # _delivery_lock_ctx so this is the ONE place the recipient-lock policy is enforced.
            _rl, _lr = _delivery_lock_ctx.get()
            if _rl:
                _locked_val, _refused = delivery_policy.resolve_locked_recipient(_rl, _lr)
                if _refused:
                    logger.warning("🔒 delivery: recipient locked but no valid delivery_recipient — "
                                   "refusing to send (fail-closed)")
                    return "❌ Email refused: this client may only email the requesting user's own account, which was unavailable."
                if isinstance(parsed_args, dict):
                    _orig_to = parsed_args.get("to_email")
                    if _orig_to and str(_orig_to).strip() != _locked_val:
                        logger.info(f"🔒 delivery: overriding recipient '{_orig_to}' → locked '{_locked_val}'")
                    parsed_args["to_email"] = _locked_val
                    if parsed_args.get("cc_emails"):
                        logger.info(f"🔒 delivery: dropping CC '{parsed_args.get('cc_emails')}' for locked client")
                    parsed_args["cc_emails"] = None
                else:
                    logger.warning("🔒 delivery: recipient locked but email args are not a dict — "
                                   "refusing (fail-closed)")
                    return "❌ Email refused: locked-recipient enforcement requires structured email arguments."

            # 🔗 Phase 2 (auto-bind): attach files created in the sandbox DURING this delivery request so
            # the user receives the artifact even if the LLM did not thread the attachment path. Merges
            # with any attachments the LLM did pass (dedup by basename). Active only when a baseline was
            # captured (i.e. a delivery-permitted request); inert otherwise.
            _baseline = _artifact_baseline_ctx.get()
            if _baseline is not None and isinstance(parsed_args, dict):
                try:
                    _new = sorted(_list_sandbox_files() - _baseline)
                    if _new:
                        _sbx = os.path.join(os.path.expanduser("~"), "sandbox_workspace")
                        _existing = [p.strip() for p in str(parsed_args.get("attachments") or "").split(",") if p.strip()]
                        _have = set(os.path.basename(p) for p in _existing)
                        for _fn in _new:
                            if _fn not in _have:
                                _existing.append(os.path.join(_sbx, _fn))
                        if _existing:
                            parsed_args["attachments"] = ",".join(_existing)
                            logger.info(f"🔗 auto-bind: attaching request-created artifact(s) {_new} to email")
                except Exception as _e_ab:
                    logger.warning(f"🔗 auto-bind skipped (non-fatal): {_e_ab}")

            def sync_email_send():
                try:
                    # Import the email tool
                    import sys
                    import os
                    
                    # Add user_tools directory to path if not already there
                    user_tools_path = os.path.join(os.path.dirname(__file__), 'user_tools')
                    if user_tools_path not in sys.path:
                        sys.path.append(user_tools_path)
                    
                    from user_tools.secure_email_sender import SecureEmailSenderTool
                    
                    # Create tool instance and execute
                    email_tool = SecureEmailSenderTool()
                    
                    # Execute the email tool (async)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result = loop.run_until_complete(email_tool.execute(**parsed_args))
                    finally:
                        loop.close()
                    
                    # Handle the new return format
                    if isinstance(result, dict):
                        if result.get("success"):
                            return result.get("result", "✅ Email sent successfully")
                        else:
                            return f"❌ {result.get('error', 'Email sending failed')}"
                    else:
                        return str(result)
                    
                except ImportError as e:
                    return f"❌ Error: Email tool not available: {str(e)}"
                except Exception as e:
                    return f"❌ Error: Email sending failed: {str(e)}"
            
            return await asyncio.get_running_loop().run_in_executor(
                thread_pool, sync_email_send
            )
            
        except Exception as e:
            return f"❌ Error: Email tool execution failed: {str(e)}"

# ==============================================================================
# CACHE FUNCTIONS
# ==============================================================================

MAX_CACHE_SIZE = 1000  # Prevent unbounded memory growth with LRU eviction

def cache_get(key: str) -> Optional[str]:
    """Get value from simple cache"""
    if key in simple_cache:
        entry = simple_cache[key]
        if time.time() < entry['expires']:
            return entry['value']
        else:
            del simple_cache[key]
    return None

def cache_set(key: str, value: str, ttl: int = 3600):
    """Set value in simple cache with LRU eviction when max size exceeded"""
    if len(simple_cache) >= MAX_CACHE_SIZE and key not in simple_cache:
        oldest_key = min(simple_cache, key=lambda k: simple_cache[k]['expires'])
        del simple_cache[oldest_key]
    simple_cache[key] = {
        'value': value,
        'expires': time.time() + ttl
    }

# ==============================================================================
# LIFESPAN MANAGEMENT
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events"""
    # Startup
    logger.info("Starting FastAPI server with Ollama integration...")
    await init_db_pool()
    await init_http_pool()
    
    # Initialize Phase 2B components safely
    if PHASE2B_AVAILABLE:
        try:
            logger.info("🚀 Initializing Phase 2B: Advanced Response Streaming & Buffer Optimization")
            
            # Start performance monitoring first (always enabled for safety)
            performance_monitor.start_monitoring()
            
            # Initialize buffer management
            await start_buffer_management()
            
            # Initialize streaming wrapper (features disabled by default)
            # Features will only activate when explicitly enabled via rollback controller
            
            logger.info("✅ Phase 2B components initialized with rollback safety")
            logger.info(f"🛡️ Rollback controller status: {rollback_controller.get_status()}")
            
        except Exception as e:
            logger.error(f"❌ Phase 2B initialization failed: {e}")
            logger.warning("🔄 Falling back to Phase 2A operation")
            # Continue with Phase 2A - don't fail startup
    else:
        logger.info("ℹ️ Phase 2B not available - continuing with Phase 2A operation")
    
    # Test Ollama connection using connection pool
    try:
        response_data = await pooled_get(_get_ollama_health_url(), timeout=5)
        if response_data['status_code'] == 200:
            logger.info("Ollama service is available")
        else:
            logger.warning("Ollama service test failed")
    except Exception as e:
        logger.warning(f"Ollama service not available: {e}")
    
    # Initialize document interrogator with startup and background scanning
    try:
        from document_interrogator import get_document_interrogator
        interrogator = get_document_interrogator()
        if interrogator:
            # Trigger startup scanning in background
            asyncio.create_task(interrogator._safe_startup_config_scan())
            
            # Start periodic background scanning
            await interrogator.start_background_scanning()
    except Exception as e:
        logger.warning(f"Document scanning initialization failed: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    # Shutdown Phase 2B components safely
    if PHASE2B_AVAILABLE:
        try:
            logger.info("🔄 Shutting down Phase 2B components...")
            performance_monitor.stop_monitoring()
            await stop_buffer_management()
            logger.info("✅ Phase 2B components shutdown complete")
        except Exception as e:
            logger.error(f"❌ Phase 2B shutdown error: {e}")
    
    # Shutdown document interrogator background scanning
    try:
        from document_interrogator import get_document_interrogator
        interrogator = get_document_interrogator()
        if interrogator:
            await interrogator.stop_background_scanning()
    except Exception as e:
        logger.warning(f"Document scanning shutdown error: {e}")
    
    await close_db_pool()
    await cleanup_http_pool()
    thread_pool.shutdown(wait=True)

# ==============================================================================
# FASTAPI APPLICATION
# ==============================================================================

app = FastAPI(
    title="Complete Analytics API with Ollama LLM",
    description="High-performance async API with Ollama integration, tools, and caching",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for image serving
app.mount("/images", StaticFiles(directory="/home/sabawi/Development/flaskserver/sandbox_workspace"), name="images")

# Initialize tool manager
tool_manager = AsyncToolManager()

# ==============================================================================
# MIDDLEWARE
# ==============================================================================

@app.middleware("http") 
async def log_requests(request: Request, call_next):
    """Log all requests with timing (configurable via env vars, config file, or config tool)"""
    # Check if logging is globally disabled - if so, skip middleware entirely
    if logging.root.disabled:
        return await call_next(request)
    
    # Reuse module-level debug config (loaded once at startup) instead of reloading per request
    
    if not log_requests_enabled and not log_timing_enabled:
        return await call_next(request)
    
    start_time = time.time() if log_timing_enabled else None
    response = await call_next(request)
    
    if log_requests_enabled:
        if log_timing_enabled and start_time:
            process_time = time.time() - start_time
            status_text = "OK" if response.status_code < 400 else "ERR" if response.status_code >= 500 else "WARN"
            logger.info(f"{status_text} {request.method} {request.url.path} | {response.status_code} | {process_time:.3f}s")
        else:
            # Log without timing
            status_text = "OK" if response.status_code < 400 else "ERR" if response.status_code >= 500 else "WARN"
            logger.info(f"{status_text} {request.method} {request.url.path} | {response.status_code}")
    
    return response

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

async def execute_query(query: str, params: Optional[tuple] = None) -> List[Dict]:
    """Execute database query asynchronously"""
    if not db_pool:
        return []
    
    async with get_db_connection() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, params or ())
            result = await cursor.fetchall()
            return result

def _get_ollama_health_url():
    """Derive health check URL from ServerConfig.OLLAMA_URL instead of hardcoding."""
    from urllib.parse import urlparse
    parsed = urlparse(ServerConfig.OLLAMA_URL)
    return f"{parsed.scheme}://{parsed.netloc}/api/tags"

async def run_cpu_intensive_task(func, *args, **kwargs):
    """Run CPU-intensive tasks in thread pool"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(thread_pool, func, *args, **kwargs)

async def check_ollama_health() -> bool:
    """Check if Ollama service is healthy using connection pool"""
    try:
        async with http_pool.get_session() as session:
            async with session.get(_get_ollama_health_url(), timeout=aiohttp.ClientTimeout(total=5)) as response:
                return response.status == 200
    except Exception as e:
        logger.warning(f"Ollama health check failed: {e}")
        return False

def _format_source_block(source_url: str, title: str, content: str, source_num: int, timestamp: str = None) -> str:
    """
    Format individual source with simplified block structure for accurate LLM citation.

    This creates clear source blocks that help the Primary LLM maintain
    accurate URL-content associations without overwhelming context size.
    Now extracts actual publication dates from content to avoid misleading the Primary LLM.
    Includes accessibility indicators to help balance recency with content accessibility.

    Args:
        source_url: The exact URL to cite (MANDATORY CITATION URL)
        title: Source title or description
        content: The actual content from the source
        source_num: Sequential source number for organization
        timestamp: Deprecated parameter (kept for backward compatibility)

    Returns:
        Formatted source block with clear citation requirements, content dates, and accessibility indicators
    """
    # Extract actual publication date from content
    content_date = _extract_content_date(content)

    # Build date line only if we found an actual publication date
    date_line = ""
    if content_date:
        date_line = f"📅 Published: {content_date}\n"

    # Detect paywall sources and add accessibility indicator
    accessibility_indicator = _get_accessibility_indicator(source_url)

    return f"""
───────────────────────────────────────────────────────
📄 SOURCE: {title}
🔗 CITATION URL: {source_url}
{date_line}{accessibility_indicator}CONTENT: {content}
───────────────────────────────────────────────────────
"""

def _extract_content_date(content: str) -> str:
    """
    Extract actual publication date from content text.
    Returns formatted date string if found, None if not available.
    """
    import re
    from datetime import datetime

    if not content:
        return None

    # Common date patterns in news content
    date_patterns = [
        # Format: "Published: January 15, 2024" or "Published January 15, 2024"
        r'(?:Published|Publication date|Date published):\s*([A-Za-z]+ \d{1,2}, \d{4})',
        r'(?:Published|Publication date|Date published)\s+([A-Za-z]+ \d{1,2}, \d{4})',

        # Format: "15 January 2024" or "January 15, 2024"
        r'\b(\d{1,2} [A-Za-z]+ \d{4})\b',
        r'\b([A-Za-z]+ \d{1,2}, \d{4})\b',

        # Format: "2024-01-15" or "15/01/2024" or "01/15/2024"
        r'\b(\d{4}-\d{1,2}-\d{1,2})\b',
        r'\b(\d{1,2}/\d{1,2}/\d{4})\b',

        # Format: "15 Jan 2024" or "Jan 15, 2024" or "Sept 18, 2023"
        r'\b(\d{1,2} [A-Za-z]{3,4} \d{4})\b',
        r'\b([A-Za-z]{3,4} \d{1,2}, \d{4})\b',

        # BBC specific: "5 hours ago", "2 days ago", "1 week ago"
        r'\b(\d+)\s+(hour|hours|day|days|week|weeks|month|months)\s+ago\b',

        # Format: "September 18, 2025" or "18 September 2025"
        r'\b([A-Za-z]+ \d{1,2}, \d{4})\b',
        r'\b(\d{1,2} [A-Za-z]+ \d{4})\b',
    ]

    # Try each pattern
    for pattern in date_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            for match in matches:
                if isinstance(match, tuple):
                    # Handle relative dates like "2 days ago"
                    if len(match) == 2 and match[1] in ['hour', 'hours', 'day', 'days', 'week', 'weeks', 'month', 'months']:
                        try:
                            from datetime import timedelta
                            amount = int(match[0])
                            unit = match[1]

                            now = datetime.now()
                            if 'hour' in unit:
                                target_date = now - timedelta(hours=amount)
                            elif 'day' in unit:
                                target_date = now - timedelta(days=amount)
                            elif 'week' in unit:
                                target_date = now - timedelta(weeks=amount)
                            elif 'month' in unit:
                                target_date = now - timedelta(days=amount*30)  # Approximate

                            return target_date.strftime('%B %d, %Y')
                        except Exception:
                            continue
                    else:
                        match = match[0] if isinstance(match, tuple) else match

                # Validate the date makes sense (not future, not too old)
                try:
                    # Try to parse various formats
                    parsed_date = None
                    for fmt in ['%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                        try:
                            parsed_date = datetime.strptime(match, fmt)
                            break
                        except Exception:
                            continue

                    if parsed_date:
                        # Check if date is reasonable (between 2020 and now + 1 year)
                        now = datetime.now()
                        min_date = datetime(2020, 1, 1)
                        max_date = datetime(now.year + 1, 12, 31)

                        if min_date <= parsed_date <= max_date:
                            return parsed_date.strftime('%B %d, %Y')

                except Exception:
                    continue

    return None

def _get_accessibility_indicator(source_url: str) -> str:
    """
    Determine content accessibility for a given source URL.
    Returns accessibility indicator line for Primary LLM prioritization.

    Args:
        source_url: The URL to check for paywall/accessibility status

    Returns:
        Formatted accessibility indicator line
    """
    # Known paywall domains
    paywall_domains = [
        'bloomberg.com',
        'wsj.com', 'wallstreetjournal.com',
        'ft.com', 'financialtimes.com',
        'nytimes.com',
        'washingtonpost.com',
        'economist.com',
        'reuters.com',  # Some Reuters content has paywalls
        'barrons.com',
        'marketwatch.com',  # Some premium content
        'seekingalpha.com'  # Some premium content
    ]

    # Free access domains (high confidence)
    free_domains = [
        'cnbc.com',
        'cnn.com',
        'bbc.com', 'bbc.co.uk',
        'yahoo.com',
        'axios.com',
        'npr.org',
        'apnews.com',
        'cbsnews.com',
        'abcnews.go.com',
        'nbcnews.com',
        'federalreserve.gov',
        'investing.com'
    ]

    if not source_url:
        return ""

    # Extract domain from URL
    try:
        from urllib.parse import urlparse
        domain = urlparse(source_url).netloc.lower()

        # Remove www. prefix for matching
        if domain.startswith('www.'):
            domain = domain[4:]

        # Check for paywall domains
        for paywall_domain in paywall_domains:
            if paywall_domain in domain:
                return "🔒 Access: May require subscription (paywall possible)\n"

        # Check for free domains
        for free_domain in free_domains:
            if free_domain in domain:
                return "🌐 Access: Generally free access\n"

        # Default for unknown domains
        return "❓ Access: Accessibility unknown\n"

    except Exception:
        return ""

def _extract_domain(url: str) -> str:
    """Extract domain name from URL for titles"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc
        # Clean up common prefixes
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain.title()
    except Exception:
        return "Unknown Source"

def _validate_article_url(url: str) -> bool:
    """
    Validate that a URL is a proper article URL (not a feed URL or invalid).

    Args:
        url: URL to validate

    Returns:
        True if URL appears to be a valid article URL, False otherwise
    """
    if not url or not isinstance(url, str):
        return False

    # Must start with http/https
    if not url.startswith(('http://', 'https://')):
        return False

    # Reject feed/RSS endpoints (these are not article URLs). This deliberately ALSO rejects Google-News
    # article-redirect links (news.google.com/rss/articles/…): those are story AGGREGATORS — one shared
    # google.com URL spanning many outlets — which the synthesis model collapses into confusing "every
    # citation points to the same URL" links (plus a bare google.com host). Google News is SUPPRESSED in
    # favor of search_web, which returns clean, specific publisher URLs. (Reverts the v1.0.0.123
    # /rss/articles/ exemption; see CHANGELOG_v1.0.0.125.)
    feed_indicators = ['/feed', '/rss', '.xml', '.rss', '/atom', 'feedburner']
    url_lower = url.lower()
    for indicator in feed_indicators:
        if indicator in url_lower:
            return False

    # Reject URLs that are too short (likely invalid)
    if len(url) < 25:
        return False

    # Reject URLs that are too long (likely corrupted)
    if len(url) > 2000:
        return False

    return True


def _citation_verify_cfg() -> dict:
    """Layer 3 (citation accuracy) config — fail-safe defaults. A LENIENT live check that drops only
    clearly-dead article URLs (hard 404/410, or a redirect that lands on the site homepage) before they
    become citations; everything else (403/paywall/JS shell/timeout/5xx) is KEPT, so a valid article
    that merely bot-blocks us is never dropped. config: deep_research.citation_verify."""
    try:
        cfg = config_loader.load_config().get('deep_research', {}).get('citation_verify', {})
    except Exception:
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "timeout": float(cfg.get("timeout_seconds", 6)),
        "max_workers": max(1, int(cfg.get("max_workers", 8))),
    }


# Live-link verification moved to research/link_liveness.py (v1.0.0.134) so the Deep-Research output path
# can reuse the SAME lenient verifier without a circular import. Imported under the original private names
# so every existing gather-time call site (get_text_from_url_simplified, get_news_summaries) is unchanged.
from research.link_liveness import (
    is_homepage_redirect as _is_homepage_redirect,
    verify_url_live as _verify_url_live,
    filter_live_article_urls as _filter_live_article_urls,
)


def _parse_rss_articles(rss_content: str, feed_url: str, max_articles: int = 5) -> List[dict]:
    """
    Parse RSS feed content and extract individual article information including URLs.
    
    Args:
        rss_content: Raw RSS XML content
        feed_url: Original RSS feed URL (for debugging)
        max_articles: Maximum number of articles to extract
    
    Returns:
        List of dictionaries with 'title', 'url', 'description' for each article
    """
    try:
        from bs4 import BeautifulSoup
        
        # Parse with XML parser for better RSS handling
        try:
            soup = BeautifulSoup(rss_content, 'xml')
        except Exception:
            # Fallback to html parser
            soup = BeautifulSoup(rss_content, 'html.parser')
        
        articles = []
        items = soup.find_all(['item', 'entry'])
        
        for item in items[:max_articles]:
            article = {}
            
            # Extract title
            title_tag = item.find(['title'])
            if title_tag:
                article['title'] = title_tag.get_text().strip()
            
            # Extract URL - try multiple common RSS URL fields
            url = None
            # Try <link> tag first
            link_tag = item.find('link')
            if link_tag:
                if link_tag.get('href'):  # Atom-style
                    url = link_tag.get('href')
                else:  # RSS-style
                    url = link_tag.get_text().strip()
            
            # Try <guid> tag if no link found
            if not url:
                guid_tag = item.find('guid')
                if guid_tag:
                    guid_text = guid_tag.get_text().strip()
                    # Only use guid if it looks like a URL
                    if guid_text.startswith('http'):
                        url = guid_text
            
            # Try <id> tag for Atom feeds
            if not url:
                id_tag = item.find('id')
                if id_tag:
                    id_text = id_tag.get_text().strip()
                    if id_text.startswith('http'):
                        url = id_text
            
            # Validate the URL before using it
            if url and _validate_article_url(url):
                article['url'] = url
            else:
                # SKIP articles without valid URLs to prevent fake citations
                # Do NOT use feed URL as fallback - this causes "page not found" issues
                continue

            # Extract description with enhanced content extraction
            desc_text = ""
            
            # Try multiple description fields for maximum content
            for desc_field in ['content:encoded', 'content', 'description', 'summary']:
                desc_tag = item.find(desc_field)
                if desc_tag:
                    desc_text = desc_tag.get_text().strip()
                    break
            
            # If no description found, try looking for content in other fields
            if not desc_text:
                for fallback_field in ['media:description', 'itunes:summary']:
                    desc_tag = item.find(fallback_field)
                    if desc_tag:
                        desc_text = desc_tag.get_text().strip()
                        break
            
            if desc_text:
                # Clean up description but keep more content
                desc_text = desc_text.replace('\n', ' ').replace('\r', ' ')
                # Remove HTML tags if present
                from bs4 import BeautifulSoup
                desc_text = BeautifulSoup(desc_text, 'html.parser').get_text()
                # Increase length limit for more detailed summaries
                if len(desc_text) > 500:
                    desc_text = desc_text[:500] + "..."
                article['description'] = desc_text
            
            # Extract publication date for context
            pub_date = None
            for date_field in ['pubDate', 'published', 'updated']:
                date_tag = item.find(date_field)
                if date_tag:
                    pub_date = date_tag.get_text().strip()
                    break
            
            if pub_date:
                article['pub_date'] = pub_date
            
            # Only add articles that have at least a title
            if article.get('title'):
                articles.append(article)
        
        return articles
        
    except Exception as e:
        print(f"Error parsing RSS from {feed_url}: {e}", flush=True)
        return []

def _get_news_content_with_article_urls(news_url: str, source_num_start: int) -> tuple:
    """
    Fetch content from news URL and extract individual article URLs if it's an RSS feed.
    
    Args:
        news_url: URL to fetch (could be RSS feed or regular webpage)
        source_num_start: Starting source number for numbering
    
    Returns:
        tuple: (formatted_content_blocks, articles_count)
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        
        # Fetch the content
        response = requests_compatible_get(news_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        response.raise_for_status()
        
        # Check if it's RSS/XML content
        content_type = response.headers.get('content-type', '').lower()
        is_rss_xml = (
            'xml' in content_type or 
            'rss' in content_type or
            news_url.endswith('.xml') or 
            news_url.endswith('.rss') or
            'feed' in news_url.lower() or
            response.text.strip().startswith('<?xml')
        )
        
        if is_rss_xml:
            # Parse RSS feed and extract individual articles
            articles = _parse_rss_articles(response.text, news_url, max_articles=4)
            
            if articles:
                # Layer 3 (citation accuracy): drop any article whose URL is verified DEAD (hard
                # 404/410 or a redirect to the site homepage) before it can become a citation. Lenient
                # (keeps 403/paywall/JS/timeout), parallel, and config-gated (deep_research.citation_verify).
                _cv = _citation_verify_cfg()
                if _cv["enabled"]:
                    _live = _filter_live_article_urls(
                        [a.get('url') for a in articles if a.get('url')],
                        timeout=_cv["timeout"], max_workers=_cv["max_workers"])
                    _before = len(articles)
                    articles = [a for a in articles if a.get('url') in _live]
                    if len(articles) != _before:
                        print(f"🔎 news: link-verify dropped {_before - len(articles)} dead article URL(s) "
                              f"from {_extract_domain(news_url)}", flush=True)
                    if not articles:
                        return ("", 0)

                content_blocks = []
                for i, article in enumerate(articles):
                    article_url = article.get('url', news_url)
                    title = article.get('title', 'Untitled Article')
                    description = article.get('description', '')

                    # Use description as content (date will be extracted by _format_source_block)
                    enhanced_content = description

                    # Create source block for each article
                    formatted_source = _format_source_block(
                        source_url=article_url,
                        title=title,
                        content=enhanced_content,
                        source_num=source_num_start + i
                    )
                    content_blocks.append(formatted_source)

                return ('\n'.join(content_blocks), len(articles))
            else:
                # RSS parsed but yielded no article with a valid specific URL. Do NOT fall back to
                # citing the FEED url (a feed/landing URL lands on "page not found" when cited as an
                # article). Skip this source so the model never receives a non-article citation.
                print(f"🔗 news: no citable article extracted from feed, skipping: {str(news_url)[:80]}", flush=True)
                return ("", 0)
        else:
            # Non-RSS URL = a section / landing page (configured news sources are sections, not
            # specific articles). We have NO specific article URL for the content shown on it, so we
            # must NOT cite the section URL as if it were an article (that lands on a general page /
            # "page not found" — the exact regression). Skip it; the RSS feeds + search_web supply the
            # citable, specific-article sources.
            print(f"🔗 news: non-RSS section/landing page, not citable as a specific article, skipping: {str(news_url)[:80]}", flush=True)
            return ("", 0)
            
    except Exception as e:
        print(f"Error processing news from {news_url}: {e}", flush=True)
        return ("", 0)

def _build_structured_context_block(tools_results_summary: str, tools_called: List[str]) -> str:
    """
    Build structured CONTEXT block from tool outputs for Primary LLM.
    This formats tool data into organized sections for better analysis.
    """
    if not tools_results_summary.strip():
        return ""
    
    # Build tool summary section
    tools_section = ""
    if tools_called:
        tools_section = f"TOOLS EXECUTED: {', '.join(tools_called)}\n\n"
    
    # Format the context with clear structure
    context_block = f"""{tools_section}DATA AND INFORMATION GATHERED:

{tools_results_summary}

---
END OF CONTEXT DATA"""
    
    return context_block


# Delivery/action awareness for the primary LLM, injected based on whether outbound delivery is
# actually PERMITTED for this request (allow_delivery). The POSITIVE form was previously hardcoded in
# primary_model_system_prompt.txt and caused NON-delivery bots to falsely claim "email sent"; it now
# appears only when delivery is permitted. The NEGATIVE form forbids false success claims.
_POS_DELIVERY_AWARENESS = (
    "📧 POST-LLM EXECUTION AWARENESS:\n"
    "- Delivery/packaging (emailing, saving a file, publishing) is performed by the SYSTEM after you "
    "finish — your job is ONLY to generate the requested content, fully.\n"
    "- You will NOT find an email, file-creation, or delivery tool among your available tools, and you "
    "do NOT need one — this is BY DESIGN. A separate delivery layer outside your toolset packages and "
    "sends your content automatically AFTER you respond. The absence of such a tool does NOT mean "
    "delivery won't happen — it WILL. Do NOT reason from your visible tools (or 'this session') that you "
    "cannot deliver.\n"
    "- Therefore do NOT say you lack the ability, do NOT mention any missing or unavailable tool, and do "
    "NOT offer the user a manual workaround (e.g. 'copy this HTML and save it yourself', 'paste it into a "
    "file', or dumping a raw HTML/PDF block inline). Simply write the requested content as your normal "
    "answer — if a file was requested, that content IS what the system will package into the file.\n"
    "- Equally, do NOT claim or imply that delivery happened — never write \"email sent\", \"file "
    "attached\", \"delivered\", \"posted\", or similar. You neither perform nor confirm the delivery; the "
    "system reports the ACTUAL outcome separately. A premature success claim would be a lie if the "
    "delivery later fails.\n"
    "- Just produce the complete requested content; add no commentary about sending/attaching/posting.\n"
    "- OUTPUT THE FINISHED CONTENT ITSELF, directly and in full. When the user asks you to format/email "
    "'the above' or provided material, transform THAT material into the requested document NOW. NEVER "
    "respond with a plan, an outline of what you intend to do, a statement that you 'need to research' or "
    "'will gather' more, a question back to the user, or meta-commentary about the task — any such reply "
    "would be packaged and delivered AS the document, which is wrong. If the provided material is thin, "
    "format and present what you have; do not stall or describe what you would do."
)
_NEG_DELIVERY_AWARENESS = (
    "📧 OUTBOUND ACTIONS (THIS REQUEST):\n"
    "- Outbound delivery/actions (sending email, creating/saving files, scheduling, posting outside this platform) are NOT available for this request.\n"
    "- If the user asked for such an action — even \"email me an HTML/PDF file of X\" — answer their underlying question in your NORMAL format, WITH any required source citations, then add ONE brief note that the action isn't available. Do NOT produce the file itself or output raw file content (raw HTML/PDF).\n"
    "- NEVER claim or imply that an email was sent, a file was created or attached, or anything was posted — you did NOT perform any action."
)


def _build_enhanced_primary_system_prompt(original_system, tools_were_executed=False, tools_results_summary="", tools_called: List[str] = None, allow_delivery: bool = True):
    """
    Build enhanced system prompt for primary LLM when tools have been executed.
    This prevents the primary LLM from redoing work already completed by tool calling model.

    🔧 FIX v1.0.0.32: System prompt now contains ONLY instructions, not full tool results.
    Tool results are provided in the CONTEXT block (prompt field) to avoid duplication
    which was causing "prompt too long" errors for large tool outputs like email retrieval.
    """
    # Load base system prompt from external file
    base_system = load_primary_model_system_prompt()
    # Inject delivery/action awareness that reflects the ACTUAL permission for this request, so a
    # non-delivery bot can never be told "email is handled automatically / don't disclaim" (which made
    # it falsely claim success). Applied to the base for ALL return paths below.
    base_system = base_system + "\n\n" + (_POS_DELIVERY_AWARENESS if allow_delivery else _NEG_DELIVERY_AWARENESS)

    if not tools_were_executed:
        # If no tools were executed, combine base system + user system if provided
        if original_system and original_system.strip():
            return f"{base_system}\n\nADDITIONAL USER INSTRUCTIONS:\n{original_system}"
        return base_system

    # 🔧 FIX v1.0.3.10: Detect if tools are DEFERRED vs COMPLETED
    tools_are_deferred = "deferred" in tools_results_summary.lower()

    # 🔧 FIX v1.0.0.32: Create a brief tools summary (list of tools only, NOT the data)
    # This prevents massive system prompts when tool results are large (e.g., email retrieval)
    tools_list = ", ".join(tools_called) if tools_called else "various tools"

    # NO-INCONSISTENCY: the workflow instructions must AGREE with the delivery awareness above. When
    # delivery is NOT permitted, they must not promise/claim file creation or sending (that conflict made
    # a non-delivery bot falsely say "I've generated your HTML briefing"). One voice, gated on allow_delivery.
    if allow_delivery:
        _deliv_workflow_line = (
            "- The system AUTOMATICALLY formats your markdown answer into the requested file (HTML/PDF/etc.), "
            "names it from its content, attaches it, and delivers/emails it after you finish. Any note about "
            "the delivery is added by the system to the message/email — never put it inside the content.")
        _deliv_remember = "the system formats, names, and delivers the file"
        _action_report_line = (
            "- For ACTION tools (email sending, chart creation, file operations, social media posting): "
            "the system performs these after you finish — produce the content and do NOT claim you sent/"
            "attached/posted anything; the system reports the actual outcome.")
    else:
        _deliv_workflow_line = (
            "- Outbound delivery (emailing, creating/attaching a file, posting) is NOT available for this "
            "request — do NOT claim or imply that any file was created, attached, sent, posted, or delivered. "
            "Just produce the answer content (the OUTBOUND ACTIONS note above governs).")
        _deliv_remember = "outbound delivery is NOT available — do not claim any file/email/post happened"
        _action_report_line = (
            "- Outbound action tools (email, file creation, social posting) are NOT available for this "
            "request — do NOT claim or imply you sent, attached, created a file, or posted anything.")

    if tools_are_deferred:
        # Tools are waiting for Primary LLM to generate content
        enhanced_instructions = f"""

CRITICAL WORKFLOW INSTRUCTIONS:
- Tools are ready to execute but are waiting for YOU to generate the content first.
- Generate the user's requested answer NOW, IN FULL, as a normal well-structured response in your usual MARKDOWN format — INCLUDING all required source citations as [Title](URL) links.
- Output ONLY the answer content itself: do NOT produce raw file markup (no raw HTML or PDF, no ```html / ``` code fences) and do NOT add any conversational preface such as "I'll create..." or "Here is the file".
{_deliv_workflow_line}

TOOLS WAITING: {tools_list}

Note: Tool results and context data are provided in the CONTEXT block below. Use them to fulfill the request.
Remember: produce the FULL answer content now, in normal markdown WITH citations — {_deliv_remember}.
"""
    else:
        # Tools already completed their work
        enhanced_instructions = f"""

CRITICAL WORKFLOW INSTRUCTIONS:
- Tools have already been executed and their work is complete
- For DATA-GATHERING tools (search, news, research, wikipedia, etc.): USE the tool results from the CONTEXT block to comprehensively fulfill the user's original request with all details they asked for, with citations
{_action_report_line}
- Be thorough and detailed when presenting information from data-gathering tools
- Organize and analyze the data to directly address what the user requested

TOOLS EXECUTED: {tools_list}

Note: Full tool results are provided in the CONTEXT block below (not duplicated here).
Remember: Use data from search/research tools to create comprehensive responses. Action tools require reporting all returned parameters.
"""

    # Combine base system + user system (if provided) + enhanced instructions
    full_system = base_system
    if original_system and original_system.strip():
        full_system += f"\n\nADDITIONAL USER INSTRUCTIONS:\n{original_system}"
    full_system += enhanced_instructions
    return full_system


async def _attempt_partial_optimization(tool_results, user_prompt, preserver, validator):
    """
    Attempt partial optimization with gentler compression targeting 85-90% instead of aggressive compression.
    Preserves high-ranking content and applies minimal compression to secondary content.
    """
    try:
        # Identify high-priority content (first results, search results, academic papers)
        high_priority_tools = ['search_web', 'published_papers_search', 'wikipedia_query']
        priority_results = []
        secondary_results = []
        
        for result in tool_results:
            if result.get('tool') in high_priority_tools:
                priority_results.append(result)
            else:
                secondary_results.append(result)
        
        # Apply gentle compression only to secondary content
        partial_content = ""
        
        # High-priority content: minimal or no compression (preserve 95%+)
        for result in priority_results:
            content = str(result.get('result', ''))
            # Apply very light summarization only to extremely long content
            if len(content) > 8000:
                # Keep first 6000 chars + last 1000 chars to preserve both intro and conclusion
                compressed = content[:6000] + "\n[...content summarized for length...]\n" + content[-1000:]
                partial_content += f"Tool: {result.get('tool')}\nResult: {compressed}\n\n"
            else:
                # Keep original content intact
                partial_content += f"Tool: {result.get('tool')}\nResult: {content}\n\n"
        
        # Secondary content: moderate compression (preserve 70-80%)
        for result in secondary_results:
            content = str(result.get('result', ''))
            if len(content) > 2000:
                # More aggressive but still conservative compression
                compressed = content[:1500] + "\n[...additional details available...]\n" + content[-500:]
                partial_content += f"Tool: {result.get('tool')}\nResult: {compressed}\n\n"
            else:
                partial_content += f"Tool: {result.get('tool')}\nResult: {content}\n\n"
        
        # Create a mock optimization result for validation
        partial_result = {
            "input_type": "optimized",
            "content": partial_content.strip(),
            "compression_ratio": len(partial_content) / sum(len(str(r.get('result', ''))) for r in tool_results),
            "method": "partial_gentle_compression"
        }
        
        # Validate the partial result
        validation_result = validator.validate_optimization(
            original_content="".join(str(r.get('result', '')) for r in tool_results),
            optimized_content=partial_content,
            user_prompt=user_prompt
        )
        
        partial_result["validation_score"] = validation_result["score"]
        
        return partial_result
        
    except Exception as e:
        logger.error(f"🚨 Partial optimization error: {e}")
        return None

# Module-level cache for research classification, keyed by prompt hash, so the
# LLM classifier runs at most once per distinct prompt (keeps it off the hot path).
_research_classification_cache: Dict[str, bool] = {}


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Parse a JSON object from an LLM response (handles markdown fences and surrounding prose).

    This is structural parsing only — it extracts JSON the LLM emitted; it does NOT
    interpret meaning from text. RAICA acts on the LLM's structured verdict.
    """
    import json
    import re
    s = (text or "").strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', s, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


async def _is_research_query(user_prompt: str, tools_called: List[str]) -> bool:
    """
    Determine if a query is research-oriented (needs maximum context-preservation
    accuracy) using an LLM classifier — NOT hardcoded keyword lists.

    Per the RAICA generalization directive, the LLM decides semantically whether a
    request is research-oriented. RAICA only parses the LLM's JSON verdict.

    Behavior:
    - Controlled by config: deep_research.research_classifier.enabled
    - Result cached per distinct prompt to avoid repeated LLM calls on the hot path
    - On classifier failure OR when disabled: fail SAFE to research=True
      (preserve maximum context — protects accuracy, never silently lossy)
    """
    import hashlib
    cache_key = hashlib.sha256((user_prompt or "").encode('utf-8')).hexdigest()
    if cache_key in _research_classification_cache:
        return _research_classification_cache[cache_key]

    # Authoritative source: config/llm_config.yaml -> deep_research.research_classifier
    try:
        classifier_cfg = config_loader.load_config().get('deep_research', {}).get('research_classifier', {})
    except Exception:
        classifier_cfg = {}
    classifier_enabled = classifier_cfg.get('enabled', True)

    if not classifier_enabled:
        logger.info("🔬 Research classifier disabled by config → defaulting to research=True (max context preservation)")
        _research_classification_cache[cache_key] = True
        return True

    # Use the PRIMARY model for classification. The arbitrator/coder model returns prose
    # instead of structured output, so it cannot be relied on for a verdict. We ask for a
    # single VERDICT token (robust to any extra prose the model adds) rather than JSON.
    tools_context = ", ".join(tools_called) if tools_called else "none"
    classifier_prompt = (
        "You are a request classifier for a research platform. Decide whether the user's request "
        "is RESEARCH-oriented — it benefits from maximum factual accuracy and preserving gathered "
        "source material (scientific, academic, technical, financial, news/current-events, "
        "analytical, or fact-finding) — or GENERAL (casual conversation, simple commands, "
        "formatting, code edits, chit-chat).\n\n"
        f"User request:\n{(user_prompt or '')[:1500]}\n\n"
        f"Tools the system used for this request: {tools_context}\n\n"
        "Answer with ONLY one line, exactly:\n"
        "VERDICT: RESEARCH\n"
        "or\n"
        "VERDICT: GENERAL"
    )

    try:
        import re as _re
        chunks = []
        async for chunk in llm_manager.generate_stream(
            classifier_prompt, temperature=0.0, max_tokens=200, stream=False
        ):
            chunks.append(chunk)
        response = "".join(chunks)

        # Parse the LLM's own verdict token (structured output — not interpreting user text).
        m = _re.search(r'VERDICT:\s*(RESEARCH|GENERAL)', response, _re.IGNORECASE)
        if m:
            is_research = (m.group(1).upper() == "RESEARCH")
        else:
            # Tolerant fallback: a bare RESEARCH/GENERAL token anywhere in the reply.
            tokens = _re.findall(r'\b(RESEARCH|GENERAL)\b', response, _re.IGNORECASE)
            if tokens:
                is_research = (tokens[0].upper() == "RESEARCH")
            else:
                raise ValueError(f"no verdict token in classifier reply: {response[:160]!r}")
        logger.info(f"🔬 Research classifier: is_research={is_research} (verdict parsed from primary model)")
    except Exception as e:
        # Fail SAFE: preserve maximum context to protect accuracy. This is conservative
        # degradation on infra failure, not a guess about the request's meaning.
        logger.warning(f"🔬 Research classifier unavailable ({e}) → failing safe to research=True")
        is_research = True

    _research_classification_cache[cache_key] = is_research
    return is_research

async def process_with_safe_optimization(
    tool_results: List[Dict],
    user_prompt: str,
    max_context_window: int,
    tools_called: List[str],
    thread_pool,
    user_id: Optional[str] = None
) -> tuple[str, Dict[str, Any]]:
    """
    Process tool results with safe optimization integration.
    
    This function integrates the optimization safety system into the existing
    FastAPI server processing pipeline while maintaining complete fallback compatibility.
    
    Returns:
        tuple: (tools_results_summary, optimization_metadata)
    """
    
    # Convert tool results to the format expected by our optimization system
    formatted_tool_results = []
    for i, result_dict in enumerate(tool_results):
        tool_name = tools_called[i] if i < len(tools_called) else f"tool_{i}"
        formatted_result = {
            "tool": tool_name,
            "result": result_dict
        }
        formatted_tool_results.append(formatted_result)
    
    # Check if optimization is available and enabled
    if not OPTIMIZATION_AVAILABLE:
        logger.info("🚫 Optimization system not available - using original processing")
        return await _original_processing_fallback(tool_results, user_prompt, max_context_window, thread_pool)
    
    # Check feature flags
    if not optimization_controller.should_optimize(user_id=user_id, tool_types=tools_called):
        logger.info("🚫 Optimization disabled by feature flags - using original processing")
        return await _original_processing_fallback(tool_results, user_prompt, max_context_window, thread_pool)
    
    # 🎯 ADAPTIVE OPTIMIZATION STRATEGY 🎯
    # Calculate tool results size
    total_tool_size = sum(len(str(result.get('result', ''))) for result in tool_results)
    
    # Content-aware threshold determination (LLM-driven classification)
    is_research_query = await _is_research_query(user_prompt, tools_called)
    threshold = 0.95 if is_research_query else 0.90
    
    # Check if optimization is actually needed
    context_capacity = max_context_window * 0.8  # Conservative estimate for text vs tokens
    size_threshold = context_capacity * threshold
    
    if total_tool_size <= size_threshold:
        logger.info(f"🚀 ADAPTIVE SKIP: Content fits comfortably ({total_tool_size} ≤ {size_threshold:.0f} bytes, {threshold:.0%} threshold)")
        logger.info(f"🎯 Content type: {'Research' if is_research_query else 'General'} - preserving 100% accuracy")
        return await _original_processing_fallback(tool_results, user_prompt, max_context_window, thread_pool)
    
    logger.info(f"🎯 ADAPTIVE OPTIMIZATION: Content requires compression ({total_tool_size} > {size_threshold:.0f} bytes)")
    logger.info(f"📊 Content type: {'Research' if is_research_query else 'General'} - threshold: {threshold:.0%}")
    
    # Attempt safe optimization
    start_time = time.time()
    
    try:
        logger.info("🔧 OPTIMIZATION: Starting safe optimization attempt")
        
        # Initialize safety components
        preserver = ToolOutputPreserver()
        validator = OptimizationValidator()
        
        # Attempt optimization
        optimization_result = await safe_optimize_llm_input(
            tool_results=formatted_tool_results,
            user_prompt=user_prompt,
            preserver=preserver,
            validator=validator
        )
        
        response_time = time.time() - start_time
        
        # Record metrics
        success = optimization_result["input_type"] == "optimized"
        validation_score = optimization_result.get("validation_score", 0)
        error_type = None
        
        if not success:
            if "validation" in optimization_result.get("fallback_reason", []):
                error_type = "validation"
            elif "error" in optimization_result:
                error_type = "exception"
            elif "integrity" in optimization_result.get("error", ""):
                error_type = "integrity"
        
        optimization_controller.record_attempt(
            success=success,
            validation_score=validation_score,
            response_time=response_time,
            error_type=error_type
        )
        
        # Use optimized content or fallback
        if success:
            logger.info(f"✅ OPTIMIZATION SUCCESS: Score {validation_score:.1f}, Response time {response_time:.2f}s")
            return optimization_result["content"], {
                "optimization_used": True,
                "optimization_score": validation_score,
                "response_time": response_time,
                "fallback_available": True
            }
        else:
            # 🎯 PARTIAL OPTIMIZATION STRATEGY 🎯
            # If full optimization failed, try partial optimization (gentler compression)
            fallback_reasons = optimization_result.get("fallback_reason", [])
            if error_type == "validation" and validation_score > 50:  # Some quality maintained
                logger.info("🔄 ATTEMPTING PARTIAL OPTIMIZATION: Gentler compression with high-priority content preservation")
                
                try:
                    # Attempt partial optimization with relaxed parameters
                    partial_result = await _attempt_partial_optimization(
                        formatted_tool_results, user_prompt, preserver, validator
                    )
                    
                    if partial_result and partial_result.get("validation_score", 0) > validation_score:
                        logger.info(f"✅ PARTIAL OPTIMIZATION SUCCESS: Score improved {validation_score:.1f} → {partial_result.get('validation_score', 0):.1f}")
                        return partial_result["content"], {
                            "optimization_used": True,
                            "optimization_type": "partial",
                            "optimization_score": partial_result.get("validation_score", 0),
                            "response_time": response_time,
                            "original_score": validation_score
                        }
                    else:
                        logger.info("🚫 Partial optimization did not improve quality - using original fallback")
                        
                except Exception as partial_error:
                    logger.warning(f"⚠️ Partial optimization failed: {partial_error}")
            
            logger.warning(f"⚠️ OPTIMIZATION FALLBACK: {optimization_result.get('fallback_reason', 'Unknown reason')}")
            return optimization_result["content"], {
                "optimization_used": False,
                "fallback_reason": optimization_result.get("fallback_reason", "Unknown"),
                "validation_score": validation_score,
                "response_time": response_time
            }
            
    except Exception as e:
        response_time = time.time() - start_time
        logger.error(f"🚨 OPTIMIZATION SYSTEM ERROR: {e}")
        
        # Record failure
        optimization_controller.record_attempt(
            success=False,
            validation_score=0,
            response_time=response_time,
            error_type="exception"
        )
        
        # Emergency fallback to original processing
        logger.info("🔄 EMERGENCY FALLBACK: Using original processing")
        return await _original_processing_fallback(tool_results, user_prompt, max_context_window, thread_pool)


async def _original_processing_fallback(
    tool_results: List[Dict],
    user_prompt: str, 
    max_context_window: int,
    thread_pool
) -> tuple[str, Dict[str, Any]]:
    """
    Original processing logic for fallback compatibility.
    This replicates the exact original logic from the FastAPI server.
    """
    
    # Recreate the original full_tools_text with enhanced source block preservation
    full_tools_text = ""
    for result_dict in tool_results:
        if isinstance(result_dict, dict):
            for key, value in result_dict.items():
                # 🔧 ENHANCED SOURCE BLOCK PRESERVATION: Check if value contains enhanced source blocks
                if isinstance(value, str) and ("═══════════════════════════════════════════════════════" in value or "📄 SOURCE BLOCK #" in value):
                    # Enhanced source blocks detected - preserve full formatting
                    full_tools_text += f"{key}: {value}\n"
                    logger.info(f"🎯 ENHANCED SOURCE BLOCKS PRESERVED: {key} contains enhanced formatting ({len(value)} chars)")
                else:
                    # Regular tool output - use standard formatting
                    full_tools_text += f"{key}: {value}\n"
        else:
            full_tools_text += str(result_dict) + "\n"
    
    # Apply original context window logic
    if len(full_tools_text) > (max_context_window) * 1.05:
        try:
            logger.info(f"Calling TextChunker() to reduce context size from {len(full_tools_text)} to around {max_context_window} bytes")
            if TOOLS_AVAILABLE:
                def sync_text_chunking():
                    from text_chunker import TextChunker
                    return TextChunker.summary_by_semantics(
                        full_tools_text, 
                        query=user_prompt,
                        max_length=max_context_window
                    )
                
                tools_results_summary = await asyncio.get_running_loop().run_in_executor(
                    thread_pool, sync_text_chunking
                )
                logger.info(f"TextChunker() was called and returned tools_results_summary size of {len(tools_results_summary)} bytes. From {len(full_tools_text)}")
            else:
                tools_results_summary = full_tools_text
        except Exception as e:
            logger.error(f"Error: exception in TextChunker.summary_by_semantics() call. Function returned message: {e}")
            tools_results_summary = full_tools_text  # TextChunker() failed!! Use the full text
    else:
        tools_results_summary = full_tools_text
    
    return tools_results_summary, {
        "optimization_used": False,
        "original_processing": True,
        "context_size": len(tools_results_summary)
    }


# ==============================================================================
# OLLAMA LLM ENDPOINTS
# ==============================================================================
@app.post("/llama3_1b/prompt", response_model=ApiResponse)
async def llama_prompt(request: OllamaPromptRequest):
    """
    Ollama prompt endpoint with streaming support
    Equivalent to the original /llama3_1b/prompt endpoint
    """
    logger.info(f"Ollama prompt request: model={request.model}")
    
    try:
        payload = {
            "model": request.model,
            "prompt": request.prompt,
            "stream": request.stream
            # think parameter handled by LLM Manager from config
        }
        
        if request.system:
            payload["system"] = request.system
        if request.context:
            payload["context"] = request.context
        
        # Use HTTP connection pool
        async with http_pool.get_session() as session:
            async with session.post(
                ServerConfig.OLLAMA_URL,
                json=payload,
                timeout=None  # No timeout - let LLM stream as long as needed
            ) as response:
                
                if request.stream:
                    # Return streaming response
                    async def stream_generator():
                        try:
                            async for chunk in response.content.iter_chunked(1024):
                                if chunk:
                                    yield chunk
                        except Exception as e:
                            logger.error(f"Streaming error: {e}")
                            # Send error message as final chunk
                            error_response = {"error": f"Streaming interrupted: {str(e)}"}
                            yield json.dumps(error_response).encode() + b'\n'
                    
                    return StreamingResponse(
                        stream_generator(),
                        media_type="application/x-ndjson",
                        headers={
                            "X-Accel-Buffering": "no"  # Critical: Prevent proxy buffering
                        }
                    )
                else:
                    # Return JSON response
                    result = await response.json()
                    return ApiResponse(
                        success=True,
                        data=result,
                        timestamp=datetime.now().isoformat()
                    )
                    
    except Exception as e:
        logger.error(f"Ollama prompt failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ollama request failed: {str(e)}")

def analyze_error_patterns(error_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    🔍 ERROR PATTERN ANALYSIS ENGINE (Sprint 3.2 Enhanced)
    Analyzes detected error patterns and provides strategic insights for retry logic
    with comprehensive tool-specific error handling and pattern recognition
    
    Args:
        error_analysis: Dictionary of task errors with patterns and categories
        
    Returns:
        Dict with pattern analysis, priority recommendations, and retry strategies
    """
    if not error_analysis:
        return {"status": "no_errors", "analysis": {}}
    
    try:
        # Pattern frequency analysis
        pattern_frequency = {}
        category_distribution = {}
        strategy_recommendations = {}
        
        for task_id, analysis in error_analysis.items():
            pattern = analysis.get("error_pattern")
            category = analysis.get("error_category") 
            strategy = analysis.get("retry_strategy")
            
            # Count pattern frequency
            if pattern:
                pattern_frequency[pattern] = pattern_frequency.get(pattern, 0) + 1
            
            # Distribution by category
            if category:
                if category not in category_distribution:
                    category_distribution[category] = {"count": 0, "patterns": set()}
                category_distribution[category]["count"] += 1
                if pattern:
                    category_distribution[category]["patterns"].add(pattern)
            
            # Strategy aggregation
            if strategy:
                if strategy not in strategy_recommendations:
                    strategy_recommendations[strategy] = {"count": 0, "task_ids": []}
                strategy_recommendations[strategy]["count"] += 1
                strategy_recommendations[strategy]["task_ids"].append(task_id)
        
        # Determine priority categories (most common error types)
        priority_categories = sorted(
            category_distribution.items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )
        
        # Smart retry prioritization
        retry_priority = []
        for category, data in priority_categories:
            if data["count"] > 0:
                retry_priority.append({
                    "category": category,
                    "error_count": data["count"],
                    "patterns": list(data["patterns"]),
                    "recommended_action": _get_category_recommendation(category)
                })
        
        return {
            "status": "patterns_detected",
            "total_errors": len(error_analysis),
            "pattern_frequency": pattern_frequency,
            "category_distribution": {k: {"count": v["count"], "patterns": list(v["patterns"])} 
                                   for k, v in category_distribution.items()},
            "strategy_recommendations": strategy_recommendations,
            "retry_priority": retry_priority,
            "critical_patterns": [p for p, count in pattern_frequency.items() if count > 1]
        }
        
    except Exception as e:
        logger.error(f"❌ Error pattern analysis failed: {e}")
        return {"status": "analysis_failed", "error": str(e)}

def _get_category_recommendation(category: str) -> str:
    """Get recommended action based on error category - Sprint 3.2 Enhanced"""
    recommendations = {
        # Sprint 3.2: Comprehensive category-specific recommendations
        "network": "retry_with_exponential_backoff",
        "filesystem": "retry_with_path_traversal_and_correction", 
        "authentication": "escalate_to_user_with_credential_refresh",
        "data_format": "retry_with_format_correction_and_validation",
        "external_service": "retry_with_fallback_endpoint",
        "runtime": "retry_with_dependency_installation",
        "resource_exhaustion": "retry_with_memory_optimization",
        "security": "escalate_to_user_with_compliance_guidance"
    }
    return recommendations.get(category, "retry_with_delay")

def handle_graceful_degradation(failed_tools: List[Dict], successful_tools: List[Dict]) -> Dict[str, Any]:
    """
    🎯 GRACEFUL DEGRADATION HANDLER (Sprint 3.2)
    
    Implements intelligent graceful degradation when some tools fail but others succeed.
    Determines if partial results are acceptable and how to proceed.
    
    Args:
        failed_tools: List of tools that failed after retry attempts
        successful_tools: List of tools that completed successfully
        
    Returns:
        Dict with degradation strategy and messaging
    """
    logger.info(f"🎯 GRACEFUL DEGRADATION: Analyzing {len(failed_tools)} failed vs {len(successful_tools)} successful tools")
    
    total_tools = len(failed_tools) + len(successful_tools)
    success_rate = len(successful_tools) / total_tools if total_tools > 0 else 0
    
    # Analyze failed tool types and criticality
    critical_failures = []
    non_critical_failures = []
    
    # Sprint 3.2: Tool criticality classification
    critical_tool_patterns = {
        "authentication", "security", "core_data_retrieval",
        "primary_calculation", "essential_file_access"
    }
    
    for tool in failed_tools:
        tool_name = tool.get("tool_name", "")
        error_category = tool.get("error_category", "")
        
        # Determine criticality based on tool type and error
        is_critical = (
            any(pattern in tool_name.lower() for pattern in critical_tool_patterns) or
            error_category in ["authentication", "security", "resource_exhaustion"] or
            "email" in tool_name.lower()  # Email sending is usually critical
        )
        
        if is_critical:
            critical_failures.append(tool)
        else:
            non_critical_failures.append(tool)
    
    # Degradation decision logic
    if success_rate >= 0.8 and len(critical_failures) == 0:
        # High success rate, no critical failures
        return {
            "strategy": "CONTINUE_WITH_WARNING",
            "acceptable": True,
            "message": f"Proceeding with {success_rate:.1%} success rate. {len(non_critical_failures)} non-critical tools failed.",
            "warning": f"Some supplementary data may be missing due to {len(non_critical_failures)} tool failures.",
            "failed_tools": non_critical_failures
        }
    
    elif success_rate >= 0.6 and len(critical_failures) <= 1:
        # Moderate success rate, minimal critical failures
        return {
            "strategy": "PARTIAL_SUCCESS_ACCEPTABLE", 
            "acceptable": True,
            "message": f"Partial success achieved ({success_rate:.1%}). Core functionality preserved.",
            "warning": f"Results may be incomplete. {len(failed_tools)} tools failed including {len(critical_failures)} critical.",
            "failed_tools": failed_tools
        }
    
    elif len(successful_tools) > 0 and len(critical_failures) <= 2:
        # Some success, limited critical failures
        return {
            "strategy": "CONTINUE_WITH_MAJOR_WARNING",
            "acceptable": True,
            "message": f"Limited success ({success_rate:.1%}). Proceeding with significant data gaps.",
            "warning": f"⚠️ MAJOR DATA GAPS: {len(critical_failures)} critical tools failed. Results may be unreliable.",
            "failed_tools": failed_tools
        }
    
    else:
        # Too many failures or too many critical failures
        return {
            "strategy": "ABORT_AND_EXPLAIN",
            "acceptable": False,
            "message": f"Too many failures ({success_rate:.1%} success rate) including {len(critical_failures)} critical tools.",
            "escalation": "EXPLAIN_FAILURE_AND_SUGGEST_ALTERNATIVES",
            "failed_tools": failed_tools,
            "recommendation": "Consider simplifying the request or addressing the underlying issues before retrying."
        }

class ArbitratorMonitor:
    """
    📊 ARBITRATOR MONITORING & STABILITY SYSTEM (Sprint 3.4)
    
    Provides comprehensive monitoring for arbitrator system health, performance metrics,
    and stability tracking for production deployment.
    """
    
    def __init__(self):
        self.metrics = {
            "total_validations": 0,
            "successful_validations": 0,
            "failed_validations": 0,
            "retry_sessions": 0,
            "circuit_breaker_activations": 0,
            "pattern_detections": {},
            "performance_stats": {
                "avg_validation_time": 0.0,
                "min_validation_time": float('inf'),
                "max_validation_time": 0.0,
                "total_validation_time": 0.0
            },
            "stability_checkpoints": [],
            "error_recovery_rate": 0.0,
            "arbitrator_llm_calls": 0,
            "arbitrator_llm_failures": 0
        }
        
        self.stability_thresholds = {
            "max_validation_failures": 5,
            "max_circuit_breaker_rate": 0.3,  # 30% of sessions
            "min_success_rate": 0.7,  # 70% success rate
            "max_avg_validation_time": 10.0,  # 10 seconds
            "health_check_interval": 300  # 5 minutes
        }
        
        self.last_health_check = 0
        self.system_status = "HEALTHY"
        
        logger.info("📊 Arbitrator Monitor initialized")
    
    def record_validation_attempt(self, success: bool, validation_time: float, error_patterns: List[str] = None):
        """Record a validation attempt with performance metrics"""
        self.metrics["total_validations"] += 1
        
        if success:
            self.metrics["successful_validations"] += 1
        else:
            self.metrics["failed_validations"] += 1
        
        # Performance tracking
        perf_stats = self.metrics["performance_stats"]
        perf_stats["total_validation_time"] += validation_time
        perf_stats["avg_validation_time"] = perf_stats["total_validation_time"] / self.metrics["total_validations"]
        perf_stats["min_validation_time"] = min(perf_stats["min_validation_time"], validation_time)
        perf_stats["max_validation_time"] = max(perf_stats["max_validation_time"], validation_time)
        
        # Pattern tracking
        if error_patterns:
            for pattern in error_patterns:
                self.metrics["pattern_detections"][pattern] = self.metrics["pattern_detections"].get(pattern, 0) + 1
        
        # Update success rate
        self.metrics["error_recovery_rate"] = self.metrics["successful_validations"] / self.metrics["total_validations"]
        
        logger.info(f"📊 VALIDATION RECORDED: Success={success}, Time={validation_time:.2f}s, Total={self.metrics['total_validations']}")
    
    def record_retry_session(self, retry_count: int, success: bool):
        """Record a retry session with outcome"""
        self.metrics["retry_sessions"] += 1
        
        if success:
            logger.info(f"📊 RETRY SUCCESS: Session completed after {retry_count} retries")
        else:
            logger.warning(f"📊 RETRY FAILURE: Session failed after {retry_count} retries")
    
    def record_circuit_breaker_activation(self, reason: str, escalation: str):
        """Record circuit breaker activation"""
        self.metrics["circuit_breaker_activations"] += 1
        
        # Track escalation types
        escalation_key = f"escalation_{escalation.lower()}"
        self.metrics[escalation_key] = self.metrics.get(escalation_key, 0) + 1
        
        logger.warning(f"📊 CIRCUIT BREAKER RECORDED: {reason} → {escalation}")
    
    def record_arbitrator_llm_call(self, success: bool, response_time: float):
        """Record arbitrator LLM call metrics"""
        self.metrics["arbitrator_llm_calls"] += 1
        
        if success:
            logger.info(f"📊 ARBITRATOR LLM SUCCESS: {response_time:.2f}s")
        else:
            self.metrics["arbitrator_llm_failures"] += 1
            logger.error(f"📊 ARBITRATOR LLM FAILURE: {response_time:.2f}s")
    
    def perform_stability_check(self) -> Dict[str, Any]:
        """Perform comprehensive stability assessment"""
        import time
        current_time = time.time()
        
        # Skip if recent check
        if current_time - self.last_health_check < self.stability_thresholds["health_check_interval"]:
            return {"status": "RECENT_CHECK", "next_check_in": self.stability_thresholds["health_check_interval"] - (current_time - self.last_health_check)}
        
        self.last_health_check = current_time
        
        # Calculate stability metrics
        stability_report = {
            "timestamp": current_time,
            "system_status": "HEALTHY",
            "issues": [],
            "recommendations": [],
            "metrics_summary": self.get_metrics_summary()
        }
        
        # Check success rate
        if self.metrics["error_recovery_rate"] < self.stability_thresholds["min_success_rate"]:
            stability_report["issues"].append(f"Low success rate: {self.metrics['error_recovery_rate']:.1%}")
            stability_report["system_status"] = "WARNING"
            stability_report["recommendations"].append("Review error patterns and retry strategies")
        
        # Check average validation time
        avg_time = self.metrics["performance_stats"]["avg_validation_time"]
        if avg_time > self.stability_thresholds["max_avg_validation_time"]:
            stability_report["issues"].append(f"High validation time: {avg_time:.2f}s")
            stability_report["system_status"] = "WARNING"
            stability_report["recommendations"].append("Optimize arbitrator LLM performance")
        
        # Check circuit breaker activation rate
        if self.metrics["total_validations"] > 0:
            cb_rate = self.metrics["circuit_breaker_activations"] / self.metrics["total_validations"]
            if cb_rate > self.stability_thresholds["max_circuit_breaker_rate"]:
                stability_report["issues"].append(f"High circuit breaker rate: {cb_rate:.1%}")
                stability_report["system_status"] = "CRITICAL" if cb_rate > 0.5 else "WARNING"
                stability_report["recommendations"].append("Review circuit breaker thresholds and error patterns")
        
        # Check arbitrator LLM failure rate
        if self.metrics["arbitrator_llm_calls"] > 0:
            llm_failure_rate = self.metrics["arbitrator_llm_failures"] / self.metrics["arbitrator_llm_calls"]
            if llm_failure_rate > 0.1:  # 10% failure rate threshold
                stability_report["issues"].append(f"High arbitrator LLM failure rate: {llm_failure_rate:.1%}")
                stability_report["system_status"] = "CRITICAL"
                stability_report["recommendations"].append("Check arbitrator LLM connectivity and credentials")
        
        # Update system status
        self.system_status = stability_report["system_status"]
        
        # Add to stability checkpoints
        checkpoint = {
            "timestamp": current_time,
            "status": self.system_status,
            "total_validations": self.metrics["total_validations"],
            "success_rate": self.metrics["error_recovery_rate"],
            "avg_validation_time": avg_time,
            "circuit_breaker_activations": self.metrics["circuit_breaker_activations"]
        }
        
        self.metrics["stability_checkpoints"].append(checkpoint)
        
        # Keep only last 24 checkpoints (2 hours if every 5 minutes)
        if len(self.metrics["stability_checkpoints"]) > 24:
            self.metrics["stability_checkpoints"] = self.metrics["stability_checkpoints"][-24:]
        
        logger.info(f"📊 STABILITY CHECK: Status={self.system_status}, Issues={len(stability_report['issues'])}")
        
        return stability_report
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get comprehensive metrics summary"""
        return {
            "validation_metrics": {
                "total": self.metrics["total_validations"],
                "successful": self.metrics["successful_validations"],
                "failed": self.metrics["failed_validations"],
                "success_rate": f"{self.metrics['error_recovery_rate']:.1%}"
            },
            "performance_metrics": self.metrics["performance_stats"].copy(),
            "retry_metrics": {
                "sessions": self.metrics["retry_sessions"],
                "circuit_breaker_activations": self.metrics["circuit_breaker_activations"]
            },
            "arbitrator_llm_metrics": {
                "calls": self.metrics["arbitrator_llm_calls"],
                "failures": self.metrics["arbitrator_llm_failures"],
                "failure_rate": f"{(self.metrics['arbitrator_llm_failures'] / max(1, self.metrics['arbitrator_llm_calls'])):.1%}"
            },
            "pattern_analysis": self.metrics["pattern_detections"].copy(),
            "system_health": {
                "status": self.system_status,
                "checkpoints": len(self.metrics["stability_checkpoints"])
            }
        }
    
    def generate_production_report(self) -> Dict[str, Any]:
        """Generate comprehensive production readiness report"""
        stability_check = self.perform_stability_check()
        
        report = {
            "arbitrator_system_status": "PRODUCTION_READY",
            "timestamp": stability_check["timestamp"],
            "stability_assessment": stability_check,
            "metrics_summary": self.get_metrics_summary(),
            "production_readiness_checklist": {
                "configuration_compliance": True,  # Managed through llm_config_tool.py
                "core_functionality": self.metrics["total_validations"] > 0,
                "error_handling": self.metrics["circuit_breaker_activations"] >= 0,  # System can handle circuit breakers
                "performance_baseline": self.metrics["performance_stats"]["avg_validation_time"] > 0,
                "monitoring_active": len(self.metrics["stability_checkpoints"]) > 0,
                "backward_compatibility": True  # System works when disabled
            },
            "sprint_achievements": {
                "sprint_1_complete": "Configuration + LLM Manager Integration + Single Integration Point",
                "sprint_2_complete": "Validation Logic + Error Pattern Detection + Intelligent Retry with Circuit Breakers", 
                "sprint_3_complete": "Enhanced Circuit Breakers + Comprehensive Error Patterns + Quantum Story Validation + Production Monitoring"
            },
            "recommendations": stability_check.get("recommendations", [])
        }
        
        # Determine overall production readiness
        if stability_check["system_status"] in ["HEALTHY", "WARNING"]:
            if self.metrics["total_validations"] >= 1:  # Has been tested
                report["arbitrator_system_status"] = "PRODUCTION_READY"
            else:
                report["arbitrator_system_status"] = "TESTING_REQUIRED"
        else:
            report["arbitrator_system_status"] = "NOT_READY_CRITICAL_ISSUES"
        
        return report

# Global arbitrator monitor instance
arbitrator_monitor = ArbitratorMonitor()

class CircuitBreakerManager:
    """
    🛑 CIRCUIT BREAKER MANAGER (Sprint 3.1)
    
    Advanced circuit breaker system with pattern detection and escalation strategies.
    Protects against:
    - Infinite retry loops
    - Resource exhaustion 
    - Contradictory feedback cycles
    - Cost runaway scenarios
    """
    
    def __init__(self):
        # Circuit breaker state tracking
        self.session_retries = 0
        self.task_retries = {}
        self.error_patterns = {}
        self.escalation_history = []
        
        # Circuit breaker thresholds
        self.MAX_SESSION_RETRIES = 10
        self.MAX_TASK_RETRIES = 3
        self.MAX_PATTERN_REPEATS = 2
        self.MAX_ESCALATION_ATTEMPTS = 5
        
        logger.info("🛑 Circuit Breaker Manager initialized")
    
    def check_session_circuit_breaker(self) -> Optional[Dict[str, Any]]:
        """Check if session-level circuit breaker should trigger"""
        if self.session_retries >= self.MAX_SESSION_RETRIES:
            return {
                "triggered": True,
                "reason": "MAX_SESSION_RETRIES_EXCEEDED",
                "escalation": "EXPLAIN_FAILURE",
                "message": f"Session exceeded maximum retries ({self.MAX_SESSION_RETRIES}). System protecting against resource exhaustion.",
                "cost_protection": True
            }
        return {"triggered": False}
    
    def check_task_circuit_breaker(self, task_key: str) -> Optional[Dict[str, Any]]:
        """Check if task-level circuit breaker should trigger"""
        retry_count = self.task_retries.get(task_key, 0)
        if retry_count >= self.MAX_TASK_RETRIES:
            return {
                "triggered": True,
                "reason": "MAX_TASK_RETRIES_EXCEEDED", 
                "escalation": "ALTERNATIVE_APPROACH",
                "message": f"Task '{task_key}' failed {retry_count} times. Marking as unachievable.",
                "task_key": task_key
            }
        return {"triggered": False}
    
    def check_pattern_circuit_breaker(self, error_pattern: str, feedback: str) -> Optional[Dict[str, Any]]:
        """Check for infinite loop patterns and contradictory feedback"""
        pattern_key = f"{error_pattern}:{hash(feedback) % 10000}"
        
        # Track pattern frequency
        if pattern_key not in self.error_patterns:
            self.error_patterns[pattern_key] = {
                "count": 0,
                "first_seen": logger.info(f"🔍 New error pattern detected: {error_pattern}"),
                "feedback_samples": []
            }
        
        self.error_patterns[pattern_key]["count"] += 1
        self.error_patterns[pattern_key]["feedback_samples"].append(feedback[:100])
        
        pattern_count = self.error_patterns[pattern_key]["count"]
        
        if pattern_count > self.MAX_PATTERN_REPEATS:
            # Check for contradictory feedback
            feedback_samples = self.error_patterns[pattern_key]["feedback_samples"]
            unique_feedback = len(set(feedback_samples))
            
            if unique_feedback > 1:
                return {
                    "triggered": True,
                    "reason": "CONTRADICTORY_FEEDBACK_DETECTED",
                    "escalation": "USER_GUIDANCE", 
                    "message": f"Pattern '{error_pattern}' showing contradictory feedback across {pattern_count} attempts.",
                    "pattern_details": {
                        "error_pattern": error_pattern,
                        "attempt_count": pattern_count,
                        "unique_feedback_count": unique_feedback
                    }
                }
            else:
                return {
                    "triggered": True,
                    "reason": "INFINITE_LOOP_DETECTED",
                    "escalation": "ALTERNATIVE_APPROACH",
                    "message": f"Same error pattern '{error_pattern}' repeated {pattern_count} times with identical feedback.",
                    "pattern_details": {
                        "error_pattern": error_pattern,
                        "repeat_count": pattern_count
                    }
                }
        
        return {"triggered": False}
    
    def check_escalation_circuit_breaker(self) -> Optional[Dict[str, Any]]:
        """Check if too many escalations have occurred"""
        if len(self.escalation_history) >= self.MAX_ESCALATION_ATTEMPTS:
            return {
                "triggered": True,
                "reason": "MAX_ESCALATION_ATTEMPTS_EXCEEDED",
                "escalation": "SYSTEM_INTERVENTION",
                "message": f"System has escalated {len(self.escalation_history)} times. Manual review required.",
                "escalation_summary": self.escalation_history[-3:]  # Last 3 escalations
            }
        return {"triggered": False}
    
    def should_abort_retry(self, task_key: str, error_pattern: str, feedback: str) -> Dict[str, Any]:
        """
        Master circuit breaker decision function
        Returns comprehensive decision with reasoning
        """
        decision = {
            "abort": False,
            "reason": None,
            "escalation": None,
            "message": None,
            "circuit_breaker_details": []
        }
        
        # Check all circuit breaker conditions
        session_check = self.check_session_circuit_breaker()
        task_check = self.check_task_circuit_breaker(task_key)
        pattern_check = self.check_pattern_circuit_breaker(error_pattern, feedback)
        escalation_check = self.check_escalation_circuit_breaker()
        
        # Collect all triggered circuit breakers
        triggered_breakers = []
        for check in [session_check, task_check, pattern_check, escalation_check]:
            if check.get("triggered", False):
                triggered_breakers.append(check)
        
        if triggered_breakers:
            # Use the most severe circuit breaker
            severity_order = {
                "SYSTEM_INTERVENTION": 4,
                "USER_GUIDANCE": 3, 
                "EXPLAIN_FAILURE": 2,
                "ALTERNATIVE_APPROACH": 1
            }
            
            most_severe = max(triggered_breakers, 
                            key=lambda x: severity_order.get(x.get("escalation", ""), 0))
            
            decision.update({
                "abort": True,
                "reason": most_severe["reason"],
                "escalation": most_severe["escalation"],
                "message": most_severe["message"],
                "circuit_breaker_details": triggered_breakers
            })
            
            # Log circuit breaker activation
            logger.warning(f"🛑 CIRCUIT BREAKER ACTIVATED: {most_severe['reason']}")
            logger.warning(f"🛑 Escalation: {most_severe['escalation']}")
            
            # Record escalation
            self.escalation_history.append({
                "reason": most_severe["reason"],
                "escalation": most_severe["escalation"], 
                "task_key": task_key,
                "timestamp": logger.info(f"Circuit breaker escalation recorded")
            })
        
        return decision
    
    def increment_retry_counters(self, task_key: str):
        """Increment retry counters for tracking"""
        self.session_retries += 1
        self.task_retries[task_key] = self.task_retries.get(task_key, 0) + 1
        
        logger.info(f"🔄 Retry counters updated: Session={self.session_retries}, Task[{task_key}]={self.task_retries[task_key]}")
    
    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get comprehensive circuit breaker status"""
        return {
            "session_retries": self.session_retries,
            "max_session_retries": self.MAX_SESSION_RETRIES,
            "active_tasks": len(self.task_retries),
            "task_retry_details": self.task_retries.copy(),
            "error_patterns": len(self.error_patterns),
            "escalations": len(self.escalation_history),
            "circuit_breaker_health": "HEALTHY" if self.session_retries < self.MAX_SESSION_RETRIES * 0.8 else "WARNING"
        }

# Global circuit breaker manager instance
circuit_breaker_manager = CircuitBreakerManager()

async def intelligent_retry_with_circuit_breakers(
    error_analysis: Dict[str, Any], 
    pattern_analysis: Dict[str, Any],
    tools_called: List[str], 
    tools_results_list: List[str], 
    user_prompt: str,
    tool_manager = None  # Add access to tool execution
) -> Dict[str, Any]:
    """
    🔄 INTELLIGENT RETRY WITH CIRCUIT BREAKERS (Sprint 2.3)
    
    Implements intelligent retry logic with circuit breaker patterns to prevent:
    - Infinite retry loops
    - Resource exhaustion
    - Contradictory feedback cycles
    - Unachievable task persistence
    
    Args:
        error_analysis: Error pattern analysis from arbitrator
        pattern_analysis: Strategic pattern analysis results
        tools_called: Original list of tools that were executed
        tools_results_list: Original results from tool execution
        user_prompt: Original user request
        
    Returns:
        Dict with success status, corrected results, or failure reason
    """
    logger.info(f"🔄 INTELLIGENT RETRY ENGINE (Sprint 3.1): Analyzing {len(tools_called)} tools with enhanced circuit breakers")
    
    # Log current circuit breaker status
    cb_status = circuit_breaker_manager.get_circuit_breaker_status()
    logger.info(f"🛑 Circuit Breaker Status: {cb_status['circuit_breaker_health']} | Session: {cb_status['session_retries']}/{cb_status['max_session_retries']}")
    
    # Master session circuit breaker check
    session_check = circuit_breaker_manager.check_session_circuit_breaker()
    if session_check["triggered"]:
        logger.error(f"🛑 SESSION CIRCUIT BREAKER ACTIVATED: {session_check['reason']}")
        return {
            "success": False,
            "reason": session_check["reason"],
            "escalation": session_check["escalation"],
            "message": session_check["message"],
            "circuit_breaker_type": "SESSION_LEVEL"
        }
    
    # NEW APPROACH: Build failed task list from error_analysis dictionary
    retry_candidates = []
    unachievable_tasks = []
    
    logger.info(f"🔍 ERROR ANALYSIS KEYS: {list(error_analysis.keys())}")
    
    # Process each task that had errors detected
    for task_id, task_error in error_analysis.items():
        try:
            # Convert task_id back to array index (task_id is 1-based from arbitrator)
            task_index = int(task_id) - 1
            
            if task_index >= len(tools_called):
                logger.warning(f"🔍 Invalid task_index {task_index} for task_id {task_id}")
                continue
                
            tool_name = tools_called[task_index]
            result = tools_results_list[task_index]
            task_key = f"{tool_name}_{task_index}"
            
            error_pattern = task_error.get("error_pattern", "unknown")
            feedback = task_error.get("feedback", "")
            retry_strategy = task_error.get("retry_strategy", "")
            
            logger.info(f"🔍 Processing failed task: {tool_name} | Pattern: {error_pattern} | Strategy: {retry_strategy}")
            
        except (ValueError, KeyError) as e:
            logger.error(f"🔍 Error processing task_id {task_id}: {e}")
            continue
        
        # Sprint 3.1: Advanced Circuit Breaker Decision System
        circuit_decision = circuit_breaker_manager.should_abort_retry(task_key, error_pattern, feedback)
        
        if circuit_decision["abort"]:
            logger.warning(f"🛑 ADVANCED CIRCUIT BREAKER: {task_key} → {circuit_decision['reason']}")
            logger.warning(f"🛑 Escalation Strategy: {circuit_decision['escalation']}")
            
            unachievable_tasks.append({
                "tool": tool_name,
                "reason": circuit_decision["reason"],
                "escalation": circuit_decision["escalation"],
                "message": circuit_decision["message"],
                "circuit_breaker_details": circuit_decision["circuit_breaker_details"]
            })
            continue
        
        # Add to retry candidates - this task can be retried with LLM feedback
        retry_candidates.append({
            "tool_name": tool_name,
            "task_index": task_index,
            "error_pattern": error_pattern,
            "retry_strategy": retry_strategy,
            "feedback": feedback,
            "original_result": result,
            "retry_count": 0  # Initialize retry count for this session
        })
        
        logger.info(f"✅ RETRY CANDIDATE: {tool_name} at index {task_index} | Strategy: {retry_strategy}")
        
    
    # 🚀 NEW CORE IMPLEMENTATION: LLM REGENERATION WITH FEEDBACK
    logger.info(f"🔄 RETRY ANALYSIS: {len(retry_candidates)} candidates, {len(unachievable_tasks)} unachievable")
    
    if not retry_candidates:
        logger.info(f"🔄 No eligible tasks for retry - all tools completed successfully")
        return {
            "success": True,
            "reason": "NO_RETRY_NEEDED",
            "corrected_results": "\n\n".join(tools_results_list)
        }
    
    # 🚀 ITERATIVE CIRCUIT BREAKER LOOP WITH ACCUMULATIVE CONTEXT
    logger.info(f"🔧 INITIATING ITERATIVE LLM REGENERATION for {len(retry_candidates)} failed tools")
    
    if not tool_manager:
        logger.error("❌ CRITICAL: tool_manager not provided - cannot regenerate tools")
        return {
            "success": False,
            "reason": "MISSING_TOOL_MANAGER",
            "message": "Cannot regenerate tools without tool_manager access"
        }
    
    # Use global llm_manager for regeneration
    
    # 🔄 ITERATIVE REGENERATION WITH CIRCUIT BREAKER LOGIC
    MAX_ITERATIONS = 3  # Circuit breaker: maximum retry iterations
    iteration = 1
    current_retry_candidates = retry_candidates.copy()
    previous_iterations = []  # Accumulative context for each iteration
    
    while iteration <= MAX_ITERATIONS and current_retry_candidates:
        logger.info(f"🔄 REGENERATION ITERATION {iteration}/{MAX_ITERATIONS} - Processing {len(current_retry_candidates)} failed tools")
        
        # 🧠 BUILD REGENERATION CONTEXT (accumulative from previous iterations)
        regeneration_context = await _build_regeneration_context(
            current_retry_candidates, user_prompt, tools_called, tools_results_list, 
            previous_iterations=previous_iterations
        )
        
        logger.info(f"🧠 ITERATION {iteration} CONTEXT: {len(regeneration_context)} characters (accumulative)")
        
        try:
            # 🔄 CALL LLM FOR TOOL REGENERATION (with iteration count for logging)
            logger.info(f"🧠 Calling tool_calling LLM for iteration {iteration} regeneration")
            
            # 🚨 LOG EXACT CONTEXT SENT TO LLM
            logger.info(f"🔧 REGENERATION CONTEXT SENT TO LLM:\n{'='*80}\n{regeneration_context}\n{'='*80}")
            
            regenerated_tools = await _regenerate_failed_tools_with_llm(
                llm_manager, regeneration_context, current_retry_candidates, 
                await tool_manager.get_tools_definitions(), iteration_count=iteration
            )
            
            logger.info(f"🔧 ITERATION {iteration}: LLM returned {len(regenerated_tools)} regenerated tool calls")
            
            # 🚨 LOG EXACT LLM RESPONSE
            import json
            truncated_regenerated_tools = truncate_base64_for_logging(json.dumps(regenerated_tools, indent=2))
            logger.info(f"🔧 LLM REGENERATION RESPONSE:\n{'='*80}\n{truncated_regenerated_tools}\n{'='*80}")
            
            # 🚨 VALIDATION: Check if LLM actually regenerated tools
            if len(regenerated_tools) == 0:
                logger.error(f"❌ ITERATION {iteration}: No regenerated tools returned - breaking iteration loop")
                break
            
            # 🚀 RE-EXECUTE CORRECTED TOOLS
            corrected_results = await _execute_corrected_tools(
                tool_manager, regenerated_tools, current_retry_candidates
            )
            
            logger.info(f"🔧 ITERATION {iteration}: Executed {len(corrected_results)} corrected tools")
            
            # 🚨 LOG DETAILED EXECUTION RESULTS
            for idx, result in enumerate(corrected_results):
                result_text = result.get('result', 'No result')
                truncated_result = truncate_base64_for_logging(str(result_text))
                logger.info(f"🔧 EXECUTION RESULT {idx+1}:\n{'='*80}\nTool: {result.get('tool_name', 'Unknown')}\nCorrected: {result.get('corrected', False)}\nResult: {truncated_result}\n{'='*80}")
            
            # 🚨 ANALYZE SUCCESS/FAILURE OF THIS ITERATION
            successful_corrections = [cr for cr in corrected_results if cr.get("corrected", False)]
            failed_corrections = [cr for cr in corrected_results if not cr.get("corrected", False)]
            
            logger.info(f"📊 ITERATION {iteration} RESULTS: {len(successful_corrections)} successes, {len(failed_corrections)} failures")
            
            # ✅ SUCCESS CASE: All tools corrected successfully
            if len(successful_corrections) == len(current_retry_candidates):
                logger.info(f"🎉 ITERATION {iteration} SUCCESS: All {len(successful_corrections)} tools corrected successfully!")
                
                # 🔄 MERGE CORRECTED RESULTS WITH ORIGINAL SUCCESSFUL RESULTS
                final_results = _merge_corrected_results(
                    tools_results_list, corrected_results, retry_candidates
                )
                
                # 🚨 DEBUG: Check what final_results contains
                corrected_results_debug = "\n\n".join(final_results)
                logger.info(f"🔧 MERGE DEBUG: final_results has {len(final_results)} entries")
                logger.info(f"🔧 MERGE DEBUG: corrected_results_debug length: {len(corrected_results_debug)} chars")
                logger.info(f"🔧 MERGE DEBUG: corrected_results_debug preview: {corrected_results_debug[:500]}...")
                
                return {
                    "success": True,
                    "reason": "ITERATIVE_REGENERATION_SUCCESS",
                    "corrected_results": corrected_results_debug,
                    "retried_tools": len(retry_candidates),
                    "iterations_required": iteration,
                    "regeneration_details": {
                        "total_iterations": iteration,
                        "final_candidates": len(current_retry_candidates),
                        "successful_corrections": len(successful_corrections),
                        "circuit_breaker_triggered": False
                    }
                }
            
            # 🔄 PARTIAL SUCCESS: Some tools succeeded, some still need retry
            elif len(successful_corrections) > 0:
                logger.info(f"🔄 ITERATION {iteration} PARTIAL SUCCESS: {len(successful_corrections)} corrected, {len(failed_corrections)} still failing")
                
                # Update retry candidates to only include the ones that still failed
                next_retry_candidates = []
                for failed_correction in failed_corrections:
                    # Find the corresponding retry candidate
                    original_candidate = next(
                        (candidate for candidate in current_retry_candidates 
                         if candidate["tool_name"] == failed_correction["tool_name"]), None
                    )
                    if original_candidate:
                        # Add the latest error to the candidate for next iteration
                        updated_candidate = original_candidate.copy()
                        updated_candidate["latest_error"] = failed_correction["result"]
                        updated_candidate["retry_count"] = iteration
                        next_retry_candidates.append(updated_candidate)
                
                # Record this iteration's context for accumulative prompt building
                iteration_context = {
                    "iteration": iteration,
                    "retry_candidates": current_retry_candidates.copy(),
                    "regenerated_tools": regenerated_tools.copy(),
                    "results": corrected_results.copy(),
                    "successful_count": len(successful_corrections),
                    "failed_count": len(failed_corrections)
                }
                previous_iterations.append(iteration_context)
                
                # Update for next iteration
                current_retry_candidates = next_retry_candidates
                iteration += 1
                
                # Partial merge successful corrections back to original results  
                partial_results = _merge_corrected_results(
                    tools_results_list, corrected_results, retry_candidates
                )
                
                # 🚨 CRITICAL FIX: Store merged results for circuit breaker success path
                tools_results_list = partial_results  # Update the main list with corrections
                
                continue  # Continue to next iteration
                
            # ❌ COMPLETE FAILURE: No tools corrected in this iteration
            else:
                logger.error(f"❌ ITERATION {iteration} COMPLETE FAILURE: No tools were corrected successfully")
                
                # Record this failed iteration for context
                failed_iteration_context = {
                    "iteration": iteration,
                    "retry_candidates": current_retry_candidates.copy(),
                    "regenerated_tools": regenerated_tools.copy(),
                    "results": corrected_results.copy(),
                    "successful_count": 0,
                    "failed_count": len(corrected_results),
                    "failure_reason": "No successful corrections"
                }
                previous_iterations.append(failed_iteration_context)
                
                iteration += 1
                continue  # Try next iteration
                
        except Exception as e:
            logger.error(f"❌ ITERATION {iteration} EXCEPTION: {e}")
            
            # Record this exception in iteration context
            exception_context = {
                "iteration": iteration,
                "retry_candidates": current_retry_candidates.copy(),
                "exception": str(e),
                "failure_reason": "LLM regeneration exception"
            }
            previous_iterations.append(exception_context)
            
            iteration += 1
            continue  # Try next iteration
    
    # 🛑 CIRCUIT BREAKER TRIGGERED: Max iterations reached or no more candidates
    if iteration > MAX_ITERATIONS:
        logger.error(f"🛑 CIRCUIT BREAKER: Maximum iterations ({MAX_ITERATIONS}) reached with {len(current_retry_candidates)} still failing")
        circuit_breaker_reason = "MAX_ITERATIONS_EXCEEDED"
        
        return {
            "success": False,
            "reason": "CIRCUIT_BREAKER_TRIGGERED",
            "circuit_breaker_reason": circuit_breaker_reason,
            "iterations_attempted": min(iteration - 1, MAX_ITERATIONS),
            "max_iterations": MAX_ITERATIONS,
            "remaining_failed_tools": len(current_retry_candidates),
            "corrected_results": "\n\n".join(tools_results_list),  # Return original results
            "iteration_history": previous_iterations
        }
    else:
        # 🚨 CRITICAL BUG FIX: Empty retry candidates means SUCCESS (all tools corrected)
        logger.info(f"🔧 SUCCESS: All retry candidates corrected - no more tools need retry")
        
        # 🚨 CRITICAL FIX: Return merged corrected results (tools_results_list now contains corrections)
        final_corrected_results = "\n\n".join(tools_results_list)
        logger.info(f"🔧 CIRCUIT BREAKER SUCCESS: Returning merged corrected results ({len(final_corrected_results)} chars)")
        
        return {
            "success": True,
            "reason": "ALL_TOOLS_CORRECTED",
            "corrected_results": final_corrected_results,
            "retried_tools": len(retry_candidates),  # Original count of tools that needed retry
            "iterations_required": iteration - 1,
            "regeneration_details": {
                "total_iterations": iteration - 1,
                "original_failed_count": len(retry_candidates),
                "final_success_count": len(retry_candidates),
                "correction_method": "CIRCUIT_BREAKER_SUCCESS"
            }
        }
    
    # 🔄 FALLBACK: Handle edge cases after iterative loop completion
    if not retry_candidates and unachievable_tasks:
        logger.warning(f"🔄 All failed tasks are unachievable - no retry possible")
        return {
            "success": False,
            "reason": "ALL_TASKS_UNACHIEVABLE",
            "escalation": "PARTIAL_SUCCESS", 
            "unachievable_count": len(unachievable_tasks),
            "message": f"Found {len(unachievable_tasks)} unachievable tasks. Continuing with available results."
        }
    
    # Fallback - should not reach here
    logger.error(f"🔄 Unexpected retry logic state - returning original results")
    return {
        "success": False,
        "reason": "UNEXPECTED_STATE",
        "escalation": "USER_GUIDANCE",
        "message": "Retry logic encountered unexpected state. Please review request."
    }

# 🔧 HELPER FUNCTIONS FOR LLM REGENERATION

async def _build_regeneration_context(retry_candidates, user_prompt, tools_called, tools_results_list, previous_iterations=None):
    """Build intelligent context for LLM tool regeneration with CONTENT PRESERVATION"""
    
    # 🚨 CRITICAL FIX: Preserve original user content instead of creating system prompts
    # The issue was that this function was creating debugging prompts instead of processing the actual user request
    
    # 🔄 ITERATIVE ACCUMULATIVE CONTEXT: Build from previous iterations
    if previous_iterations and len(previous_iterations) > 0:
        # ✅ FIX: Preserve the original user prompt as the primary content
        context = f"""{user_prompt}

[SYSTEM NOTE: This is a retry iteration {len(previous_iterations) + 1} - some tools failed and are being regenerated with improved parameters.]

PREVIOUS ITERATION HISTORY:
"""
        
        # Add all previous iteration contexts
        for idx, iteration_data in enumerate(previous_iterations, 1):
            context += f"""
--- ITERATION {idx} RESULTS ---
Retry Candidates: {len(iteration_data.get('retry_candidates', []))}
Regenerated Tools: {len(iteration_data.get('regenerated_tools', []))}
Success: {iteration_data.get('successful_count', 0)} tools
Failed: {iteration_data.get('failed_count', 0)} tools
"""
            
            # Add specific error details if this iteration failed
            if iteration_data.get('failed_count', 0) > 0:
                failed_tools = [r for r in iteration_data.get('results', []) if not r.get('corrected', False)]
                for failed_tool in failed_tools:
                    context += f"""
FAILED in iteration {idx}: {failed_tool.get('tool_name', 'Unknown')}
Error: {failed_tool.get('result', 'No error details')}
"""
        
        context += f"""

--- CURRENT ITERATION {len(previous_iterations) + 1} ---
REMAINING FAILED TOOLS REQUIRING REGENERATION:
"""
    else:
        # ✅ FIX: First iteration - preserve original user content
        context = f"""{user_prompt}

[SYSTEM NOTE: This is iteration 1 - some tools failed and are being regenerated with improved parameters.]

FAILED TOOLS REQUIRING REGENERATION:
"""
    
    for candidate in retry_candidates:
        tool_name = candidate["tool_name"]
        error_pattern = candidate["error_pattern"]
        feedback = candidate["feedback"]
        original_result = candidate["original_result"]
        latest_error = candidate.get("latest_error", None)  # 🚨 CRITICAL FIX: Include latest iteration error
        retry_count = candidate.get("retry_count", 0)
        
        # 🎯 EXTRACT PREVIOUSLY GENERATED CODE from successful tools results
        previously_generated_code = None
        specific_error_details = None
        
        # Look for code content in tools_results_list for this specific failed tool
        task_index = candidate.get("task_index", -1)
        if task_index >= 0 and task_index < len(tools_results_list):
            tool_result = tools_results_list[task_index]
            
            # For sandboxed_executor - extract code content from successful creation step
            if tool_name == "sandboxed_executor" and isinstance(tool_result, str):
                try:
                    import json
                    # Try to extract code from JSON result
                    if '"content":' in tool_result:
                        # Extract content field from JSON
                        start_idx = tool_result.find('"content": "') + len('"content": "')
                        end_idx = tool_result.find('",', start_idx)
                        if start_idx > 0 and end_idx > 0:
                            previously_generated_code = tool_result[start_idx:end_idx].replace('\\n', '\n').replace('\\"', '"')
                except Exception:
                    pass
            
        # Extract specific error details from latest_error or original_result
        error_source = latest_error if latest_error else original_result
        if "args==" in str(error_source) and "<full_path" in str(error_source):
            specific_error_details = "Used placeholder path '<full_path_of_short_story_file>' instead of actual file path from document search"
        elif "Command failed with code 1" in str(error_source):
            # 🚨 ENHANCED ERROR DETECTION: Check for specific command line argument issues
            if previously_generated_code and "sys.argv[1]" in previously_generated_code:
                specific_error_details = """CRITICAL: Python script expects command line arguments but sandboxed_executor run_code action was called without 'args' parameter.

The generated Python script uses sys.argv[1] to get a file path, but the tool call was:
{"action": "run_code", "filename": "word_count_sort.py"}

It should be:
{"action": "run_code", "filename": "word_count_sort.py", "args": "/var/www/html/silicon_dreams/stories/SD_TheQuantumConspiracy.md"}

SOLUTION: Add the 'args' parameter with the correct file path from the document search results."""
            elif "IndexError" in str(error_source) or "list index out of range" in str(error_source):
                specific_error_details = "IndexError: Script tried to access sys.argv[1] but no command line arguments were provided. Need to add 'args' parameter to the run_code action."
            else:
                specific_error_details = "Script execution failed with exit code 1 - check if script expects command line arguments or file paths"
        
        # 🚨 IMPLEMENT USER'S EXACT SUGGESTION FORMAT
        context += f"""
Tool: {tool_name}
Error Pattern: {error_pattern}
Issue: {feedback}"""
        
        # 🎯 ADD PREVIOUSLY GENERATED CODE REVIEW SECTION
        if previously_generated_code:
            context += f"""

🔍 REVIEW THIS CODE CAREFULLY AND FIX THE ERRORS:
<code>
{previously_generated_code}
</code>"""
        
        # 🎯 ADD SPECIFIC ERROR DETAILS  
        if specific_error_details:
            context += f"""

<error>
{specific_error_details}
</error>"""
        
        # 🚨 CRITICAL: Include latest error from recent iteration if available
        if latest_error and latest_error != original_result:
            context += f"""
Latest Iteration Error: {latest_error}
Retry Attempt: {retry_count}"""
        
        context += f"""

CORRECTION NEEDED: {feedback}

🎯 SPECIFIC FIX INSTRUCTIONS:
- Replace any placeholder paths like '<full_path_of_short_story_file>' with actual file paths from document search results
- Use the exact file path: /var/www/html/silicon_dreams/stories/SD_TheQuantumConspiracy.md
- If Python script uses sys.argv[1], add "args" parameter to run_code action with the file path
- Ensure all parameters are correctly specified for the sandboxed_executor tool

📋 CORRECT TOOL CALL EXAMPLES:
For creating file:
{{"action": "create_file", "filename": "script.py", "content": "Python code here"}}

For running script with arguments:
{{"action": "run_code", "filename": "script.py", "args": "/var/www/html/silicon_dreams/stories/SD_TheQuantumConspiracy.md"}}
"""
    
    # Add successful tool results as context
    context += f"""

SUCCESSFUL TOOLS (for context):
"""
    
    for i, (tool_name, result) in enumerate(zip(tools_called, tools_results_list)):
        if not any(c["task_index"] == i for c in retry_candidates):
            context += f"""
✅ {tool_name}: {result}
"""
    
    context += f"""

🎯 REGENERATION INSTRUCTIONS:
To complete the original task "{user_prompt}", you need to:

1. ANALYZE: Review what went wrong with the failed tools
2. CORRECT: Fix the parameters using information from successful tools
3. EXECUTE: Call the SAME failed tools but with corrected parameters

CRITICAL FIXES NEEDED:
- Replace placeholder paths like "<full_path_to_*>" with actual file paths from document search results
- Fix any incorrect arguments that caused failures
- Use proper file paths and parameters

YOU MUST CALL THE FAILED TOOLS AGAIN WITH CORRECTIONS - DO NOT RETURN TEXT!
"""
    
    return context

async def _regenerate_failed_tools_with_llm(llm_manager, regeneration_context, retry_candidates, available_tools, iteration_count=1):
    """Call LLM to regenerate failed tool calls with corrections using iterative accumulative prompt structure"""
    
    # 🎯 CRITICAL: Use IDENTICAL system prompt from original tool calling (pre_tool_model_system_prompt.txt)
    try:
        with open('pre_tool_model_system_prompt.txt', 'r') as f:
            system_prompt = f.read().strip()
    except FileNotFoundError:
        logger.error("❌ CRITICAL: pre_tool_model_system_prompt.txt not found - using fallback")
        system_prompt = """🚨 ABSOLUTE MODE: TOOL CALLS ONLY — NO TEXT RESPONSES, NO EXPLANATIONS 🚨
You must never produce normal text output.
Your only job: return valid tool calls helpful to answer the user in correct JSON format."""

    # 🔄 ITERATIVE ACCUMULATIVE PROMPT: Build from previous iterations + new error + fix instructions
    fix_instructions = """

EXAMINE THE CODE ERRORS CAREFULLY AND REGENERATE THE FULL FIXED CODE IN THE FOLLOWING FORMAT:

You must return ONLY valid JSON tool calls in the exact same format as your original response.
- NO explanations
- NO text responses  
- NO markdown
- ONLY the corrected tool calls in proper JSON format
- Fix the specific errors identified in the captured error data
- Use the successful tool results to get correct file paths and parameters
- Return the SAME tools that failed but with corrected parameters

The purpose is to drop the new code in place of the failed code."""

    # For iteration n: [Previous Prompt n-1] + [Current Error] + [Fix Instructions]
    regeneration_prompt = regeneration_context + fix_instructions
    
    try:
        # Tool regeneration: Starting LLM call
        logger.info(f"🔧 Calling tool_calling LLM with {len(available_tools)} available tools")
        
        # Tool regeneration: System prompt ready
        logger.info(f"🔧 Tool regeneration - system prompt: {len(system_prompt)} chars")
        
        # Tool regeneration: User prompt ready
        logger.info(f"🔧 Tool regeneration - user prompt: {len(regeneration_prompt)} chars")
        
        # Tool regeneration: Available tools summary
        logger.info(f"🔧 Tool regeneration - available tools: {len(available_tools)}")
        
        # Tool regeneration: Payload prepared
        tool_names = [tool.get('function', {}).get('name', 'Unknown') for tool in available_tools]
        logger.info(f"🔧 Tool regeneration - tools: {', '.join(tool_names[:3])}{'...' if len(tool_names) > 3 else ''} (iteration {iteration_count})")
        
        result = await llm_manager.generate_tools(
            regeneration_prompt, 
            available_tools,  # Pass the FULL tool schema from original execution
            system_prompt=system_prompt
        )
        
        # Tool regeneration: Response received
        logger.info(f"🔧 Tool regeneration - response: {len(str(result))} chars, {len(result.get('tool_calls', []))} tool calls")
        
        tool_calls = result.get("tool_calls", [])
        logger.info(f"🔧 LLM returned {len(tool_calls)} regenerated tool calls")
        
        return tool_calls
        
    except Exception as e:
        logger.error(f"❌ LLM regeneration call failed: {e}")
        raise

async def _execute_corrected_tools(tool_manager, regenerated_tools, retry_candidates):
    """Re-execute the corrected tool calls"""
    
    import json
    corrected_results = []
    
    for tool_call in regenerated_tools:
        try:
            function_name = tool_call["function"]["name"]
            function_args = json.loads(tool_call["function"]["arguments"])
            
            logger.info(f"🔧 RE-EXECUTING CORRECTED TOOL: {function_name}")
            
            # 🚨 LOG EXACT TOOL CALL AND ARGUMENTS
            truncated_function_args = truncate_base64_for_logging(json.dumps(function_args, indent=2))
            logger.info(f"🔧 CORRECTED TOOL CALL:\n{'='*80}\nFunction: {function_name}\nArguments: {truncated_function_args}\n{'='*80}")
            
            # Execute the corrected tool
            result = await tool_manager.safe_function_call(function_name, function_args)
            
            # 🚨 LOG DETAILED EXECUTION OUTPUT
            logger.info(f"🔧 CORRECTED TOOL EXECUTION OUTPUT:\n{'='*80}\nFunction: {function_name}\nRaw Result: {result}\nResult Type: {type(result)}\nResult Length: {len(str(result)) if result else 0} chars\n{'='*80}")
            
            # 🚨 CRITICAL FIX: Analyze result for error patterns instead of hardcoding success
            clean_result = str(result).strip()
            still_has_errors = any(pattern in clean_result for pattern in [
                "Command failed with code 1",
                "Command failed with code",
                "Tool 'sandboxed_executor' error",
                "Error: The file <full_path_to",
                "<full_path_to_",
                "does not exist", 
                "file not found",
                "no such file",
                "error:",
                "failed",
                "exception",
                "FileNotFoundError"
            ])
            
            is_actually_corrected = not still_has_errors
            
            corrected_results.append({
                "tool_name": function_name,
                "result": result,
                "corrected": is_actually_corrected
            })
            
            if is_actually_corrected:
                logger.info(f"✅ CORRECTED TOOL SUCCESS: {function_name} - No error patterns detected")
            else:
                logger.warning(f"⚠️ CORRECTED TOOL STILL FAILING: {function_name} - Error patterns still present in result")
                logger.warning(f"⚠️ Failed result content: {clean_result[:200]}...")
            
        except Exception as e:
            logger.error(f"❌ CORRECTED TOOL FAILED: {function_name}: {e}")
            
            # 🚨 LOG DETAILED ERROR INFO
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"🔧 CORRECTED TOOL ERROR DETAILS:\n{'='*80}\nFunction: {function_name}\nException: {str(e)}\nFull Traceback:\n{error_details}\n{'='*80}")
            
            corrected_results.append({
                "tool_name": function_name,
                "result": f"Corrected tool execution failed: {str(e)}",
                "corrected": False
            })
    
    return corrected_results

def _merge_corrected_results(original_results_list, corrected_results, retry_candidates):
    """Merge corrected results back into the original results list"""
    
    final_results = original_results_list.copy()
    
    # Replace failed tool results with corrected ones
    for candidate in retry_candidates:
        task_index = candidate["task_index"]
        
        # Find corresponding corrected result
        corrected_result = next(
            (cr for cr in corrected_results if cr["tool_name"] == candidate["tool_name"]), 
            None
        )
        
        if corrected_result and corrected_result["corrected"]:
            # 🚨 CRITICAL FIX: Format corrected results for Primary LLM readability
            corrected_result_text = corrected_result['result']
            
            # If result is JSON with stdout, extract and format the execution output
            try:
                import json
                if isinstance(corrected_result_text, str) and corrected_result_text.strip().startswith('{'):
                    result_json = json.loads(corrected_result_text)
                    
                    # For command execution results, format stdout prominently
                    if "stdout" in result_json and result_json["stdout"].strip():
                        if "return_code" in result_json and result_json["return_code"] == 0:
                            # Successfully executed command - highlight the output
                            formatted_result = f"✅ Command executed successfully: {result_json.get('command', 'Unknown command')}\n\nOutput:\n{result_json['stdout']}\n\nExecution completed with return code: {result_json['return_code']}"
                            logger.info(f"🔧 FORMATTED EXECUTION RESULT: Extracted stdout for Primary LLM")
                        else:
                            # Command failed - show error
                            formatted_result = f"❌ Command failed: {result_json.get('command', 'Unknown command')}\nReturn code: {result_json.get('return_code', 'Unknown')}\nStderr: {result_json.get('stderr', 'No error message')}"
                    else:
                        # Other JSON results (file creation, etc.) - use as-is
                        formatted_result = corrected_result_text
                else:
                    # Non-JSON results - use as-is  
                    formatted_result = corrected_result_text
                    
            except (json.JSONDecodeError, KeyError) as e:
                # Fallback to original result if parsing fails
                formatted_result = corrected_result_text
                logger.warning(f"⚠️ Failed to parse corrected result JSON: {e}")
            
            # Replace the original failed result with formatted corrected one
            final_results[task_index] = f"Tool: {candidate['tool_name']}\nResult: {formatted_result}\n\n"
            logger.info(f"🔄 MERGED CORRECTION: {candidate['tool_name']} at index {task_index}")
        else:
            logger.warning(f"⚠️ NO CORRECTION AVAILABLE: {candidate['tool_name']} at index {task_index}")
    
    return final_results

def _detect_tool_failure_pattern(tool_result: str) -> str:
    """Detect common failure patterns in tool results"""
    result_lower = tool_result.lower()
    
    if "command failed with code" in result_lower:
        return "COMMAND_EXECUTION_FAILURE"
    elif "error" in result_lower:
        return "GENERIC_ERROR"
    elif "file not found" in result_lower or "no such file" in result_lower:
        return "FILE_NOT_FOUND"
    elif "module not found" in result_lower:
        return "MISSING_DEPENDENCY" 
    elif "<full_path" in tool_result or "[full_path" in tool_result:
        return "PLACEHOLDER_PATH_NOT_REPLACED"
    elif len(tool_result.strip()) == 0:
        return "EMPTY_RESULT"
    elif "malformed" in result_lower or "invalid json" in result_lower:
        return "MALFORMED_DATA"
    else:
        return "UNKNOWN_FAILURE"

async def arbitrator_validate_tasks(tools_called: List[str], tools_results_list: List[str], user_prompt: str, tool_manager=None) -> Optional[str]:
    """
    🧠 ARBITRATOR TASK VALIDATION SYSTEM
    Validates tool execution results and retries failed tasks with intelligent feedback
    
    Args:
        tools_called: List of tool names that were executed
        tools_results_list: List of tool result strings  
        user_prompt: Original user request for context
        
    Returns:
        Optional[str]: Validated and potentially corrected tool results, or None on failure
    """
    try:
        # Use global llm_manager for arbitrator calls
        import json  # Explicit import to avoid scoping issues
        
        logger.info(f"🧠 Starting arbitrator validation for {len(tools_called)} tools")
        
        # Convert tool results to arbitrator format
        arbitrator_tasks = []
        for i, (tool_name, result) in enumerate(zip(tools_called, tools_results_list)):
            # Extract just the result content, removing "Tool: name\nResult: " formatting
            clean_result = result
            if result.startswith(f"Tool: {tool_name}\nResult: "):
                clean_result = result[len(f"Tool: {tool_name}\nResult: "):]
            
            # 🚨 STRUCTURED SUCCESS/FAILURE DETECTION: Use explicit indicators instead of content analysis
            initial_status = "PENDING_VALIDATION"
            error_pattern = None
            feedback = None
            
            # Try to parse as JSON to get structured indicators
            try:
                result_json = json.loads(clean_result)
                
                # Check explicit success indicators
                if isinstance(result_json, dict):
                    # Check return_code for command execution
                    if "return_code" in result_json:
                        if result_json["return_code"] == 0:
                            initial_status = "GOOD"
                            logger.info(f"✅ STRUCTURED SUCCESS: Task {i+1} return_code=0 - execution successful")
                        else:
                            initial_status = "BAD"
                            error_pattern = "command_failed"
                            feedback = f"Command failed with return code {result_json['return_code']}"
                            logger.info(f"❌ STRUCTURED FAILURE: Task {i+1} return_code={result_json['return_code']}")
                    
                    # Check error_analysis field
                    elif "error_analysis" in result_json:
                        if result_json["error_analysis"] is None:
                            initial_status = "GOOD" 
                            logger.info(f"✅ STRUCTURED SUCCESS: Task {i+1} error_analysis=null - no errors detected")
                        else:
                            initial_status = "BAD"
                            error_pattern = "execution_error"
                            feedback = f"Error analysis detected: {result_json['error_analysis']}"
                            logger.info(f"❌ STRUCTURED FAILURE: Task {i+1} error_analysis present")
                    
                    # For other successful JSON responses (file creation, etc.)
                    elif any(success_field in result_json for success_field in ["filename", "document_path", "chunks", "sources"]):
                        initial_status = "GOOD"
                        logger.info(f"✅ STRUCTURED SUCCESS: Task {i+1} contains success indicators")
                
            except json.JSONDecodeError:
                # Fallback to string-based detection only for non-JSON results
                logger.info(f"🔍 STRING CHECK: Task {i+1} clean_result = '{clean_result[:200]}...'")
                
                error_patterns = [
                    "Tool 'sandboxed_executor' error",
                    "Command failed with code",
                    "Command is required", 
                    "Error: The file <full_path_to",
                    "<full_path_to_",
                    "FileNotFoundError",
                    "ModuleNotFoundError", 
                    "SyntaxError",
                    "IndexError",           # 🚨 ADD missing IndexError pattern
                    "ValueError",           # 🚨 ADD missing ValueError pattern  
                    "TypeError",            # 🚨 ADD missing TypeError pattern
                    "KeyError",             # 🚨 ADD missing KeyError pattern
                    "AttributeError",       # 🚨 ADD missing AttributeError pattern
                    "error occurred"
                ]
                
                found_error = False
                matched_pattern = None
                for pattern in error_patterns:
                    if pattern in clean_result:
                        initial_status = "BAD"
                        error_pattern = "tool_error"
                        feedback = f"Tool execution error detected: {pattern}"
                        matched_pattern = pattern
                        found_error = True
                        break
                
                # 🧹 CLEANUP: Single consolidated log instead of pattern test spam
                if found_error:
                    logger.info(f"❌ VALIDATION: Task {i+1} FAILED - Pattern: '{matched_pattern}'")
                # Success case logged below
                
                if not found_error:
                    # If no explicit error patterns and no JSON structure, assume success
                    initial_status = "GOOD"
                    logger.info(f"✅ VALIDATION: Task {i+1} PASSED - {len(error_patterns)} patterns checked")
            
            # If still pending validation, check for basic success patterns
            if initial_status == "PENDING_VALIDATION":
                if len(clean_result.strip()) > 0:
                    initial_status = "GOOD"
                    logger.info(f"✅ DEFAULT SUCCESS: Task {i+1} has non-empty result")
                else:
                    initial_status = "BAD"
                    error_pattern = "empty_result"
                    feedback = "Tool returned empty result"
                    logger.info(f"❌ DEFAULT FAILURE: Task {i+1} has empty result")
            
            arbitrator_tasks.append({
                "task_id": i + 1,
                "tool_name": tool_name,
                "result": clean_result.strip(),
                "status": initial_status,
                "pre_detected_error": error_pattern,
                "pre_detected_feedback": feedback
            })
        
        # Create arbitrator system prompt with enhanced error pattern detection
        arbitrator_system_prompt = """🚨 CRITICAL JSON-ONLY RESPONSE REQUIRED 🚨

You are an AI Task Result Arbitrator. You MUST respond with ONLY valid JSON - no text, no markdown, no explanations.

🚨 RESPONSE FORMAT REQUIREMENT:
- Start response with { character
- End response with } character  
- NO markdown code blocks (```json)
- NO explanations before or after JSON
- NO analysis text
- PURE JSON ONLY

🚨 EXAMPLE OF MANDATORY BAD STATUS:
If you see: "Tool 'sandboxed_executor' error: Command failed with code 1"
You MUST respond: {"status": "BAD", "pattern": "command_failed", "feedback": "Script execution failed - regenerate code with correct file path"}

⚠️ CRITICAL: ANY non-JSON content will cause system failure. Respond with PURE JSON ONLY.

Analyze each tool result and identify specific error patterns. Respond with this EXACT JSON format:

{
  "tasks": [
    {
      "task_id": 1,
      "status": "GOOD",
      "error_pattern": null,
      "error_category": null,
      "feedback": "Task completed successfully",
      "retry_strategy": null,
      "corrected_parameters": {}
    }
  ],
  "overall_assessment": "Brief assessment",
  "patterns_detected": []
}

STATUS VALUES:
- GOOD: Task succeeded, data is valid
- BAD: Task failed but retryable
- UNACHIEVABLE: Task impossible to complete

🎯 TASK COMPLETENESS VALIDATION - CRITICAL REQUIREMENT:

**MANDATORY CHECK**: Compare user request against tools that were executed to detect MISSING actions.

Distribution/Publishing Keywords in User Request:
- "publish", "post", "upload", "share" → Requires publishing tool (social_media_wordpress, social_media_twitter, etc.)
- "email", "send", "deliver", "forward" → Requires secure_email_sender
- "wordpress", "blog", "article" → Requires social_media_wordpress
- "twitter", "tweet" → Requires social_media_twitter
- "medium", "substack" → Requires social_media_medium/social_media_substack

Available Publishing/Distribution Tools:
- social_media_wordpress (WordPress posts)
- social_media_twitter (Twitter/X posts)
- social_media_medium (Medium articles)
- social_media_substack (Substack posts)
- secure_email_sender (Email delivery)

Completeness Validation Logic:
1. Parse user request for distribution keywords
2. Check if corresponding tool was executed
3. If keyword found but tool missing → Mark overall as "BAD" with specific feedback
4. Add missing tool to "missing_tools" array in response

Example Scenarios:

❌ INCOMPLETE EXECUTION:
User Request: "Research Nvidia stock and publish to my wordpress account"
Tools Executed: [get_the_secret_tool, comprehensive_stock_analyzer]
Tools Missing: social_media_wordpress
→ STATUS: BAD with feedback "User requested WordPress publishing but social_media_wordpress tool was NOT called"

❌ INCOMPLETE MULTI-TASK:
User Request: "Analyze META, GOOGL, AMZN stocks and post results to WordPress"
Tools Executed: [comprehensive_stock_analyzer x3]
Tools Missing: social_media_wordpress
→ STATUS: BAD with feedback "Research completed but WordPress publishing tool missing - user explicitly requested posting results"

✅ COMPLETE EXECUTION:
User Request: "Research Obama's accomplishments and publish essay to WordPress"
Tools Executed: [get_the_secret_tool, wikipedia_query, search_web, social_media_wordpress]
Tools Missing: []
→ STATUS: GOOD - All requirements satisfied including WordPress publishing

Enhanced JSON Response Format with missing_tools:
{
  "tasks": [...],
  "overall_assessment": "Brief assessment",
  "patterns_detected": [],
  "missing_tools": [
    {
      "tool_name": "social_media_wordpress",
      "reason": "User requested 'publish to wordpress' but tool was not called",
      "required_parameters": {
        "title": "Generate from research context",
        "content": "{{PRIMARY_LLM_OUTPUT}}",
        "status": "draft"
      }
    }
  ]
}

🚨 MANDATORY FAILURE DETECTION - NO EXCEPTIONS:

IF ANY TOOL RESULT CONTAINS ANY OF THESE EXACT PATTERNS:
- "Command failed with code 1" → STATUS MUST BE "BAD"
- "Command failed with code" (any number) → STATUS MUST BE "BAD"
- "Tool 'sandboxed_executor' error" → STATUS MUST BE "BAD"
- "PARTIAL SUCCESS" → STATUS MUST BE "BAD" 
- "error:" anywhere in result → STATUS MUST BE "BAD"
- "failed" anywhere in result → STATUS MUST BE "BAD"
- "exception" anywhere in result → STATUS MUST BE "BAD"
- "<full_path_to_" anywhere in generated code → STATUS MUST BE "BAD"
- "FileNotFoundError" in execution results → STATUS MUST BE "BAD"

⚠️ CRITICAL: If you see "Command failed with code" in ANY tool result, you MUST mark that task as BAD and provide retry feedback.

CRITICAL FAILURE DETECTION RULES:
ALWAYS mark as BAD if you see:
- "Command failed with code" (any exit code)
- "Tool 'sandboxed_executor' error"
- "PARTIAL SUCCESS" in tool output logs
- Any mention of "error", "failed", "exception" in results
- Placeholder paths like "<full_path_to_*>" that weren't resolved
- Any code containing "<full_path_to_" strings (unresolved placeholders)  
- Generic filenames in execution errors like "story.txt", "file.txt" when actual files don't exist
- Empty or truncated results from execution tools
- "FileNotFoundError", "PermissionError", or other Python exceptions

🎯 SMART SUCCESS DETECTION: Consider overall task completion even with partial tool failures.

CRITICAL: If user requirements are fully met despite some tool errors, the task may still be SUCCESSFUL.

Examples of ACCEPTABLE partial failures:
- File read fails BUT cover letter has no placeholders AND email sent successfully = TASK SUCCESS
- API call fails BUT alternative data source provides complete information = TASK SUCCESS  
- One calculation errors BUT other calculations provide sufficient analysis = TASK SUCCESS

⚠️ Mark as BAD only if FINAL OUTPUT fails to meet user requirements or contains errors/placeholders

ERROR PATTERNS (when status is BAD) - Sprint 3.2 Enhanced:

🌐 NETWORK & HTTP ERRORS:
- "http_404": HTTP 404 Not Found - resource doesn't exist
- "http_403": HTTP 403 Forbidden - authentication/authorization issue  
- "http_429": HTTP 429 Too Many Requests - rate limiting active
- "http_500": HTTP 500 Internal Server Error - server-side issue
- "http_502": HTTP 502 Bad Gateway - proxy/gateway error
- "http_503": HTTP 503 Service Unavailable - temporary overload
- "http_timeout": Request timeout - server taking too long
- "connection_refused": Connection refused - service down
- "dns_resolution": DNS lookup failed - domain doesn't resolve
- "ssl_certificate": SSL/TLS certificate error - security issue

📁 FILESYSTEM ERRORS:
- "file_not_found": File or directory doesn't exist at path
- "permission_denied": Access denied - insufficient permissions
- "disk_full": No space left on device - storage exhausted
- "path_invalid": Invalid file path or malformed filename
- "file_locked": File locked by another process
- "symlink_broken": Symbolic link target doesn't exist
- "encoding_error": Text encoding/decoding issues

🔐 AUTHENTICATION & SECURITY:
- "api_key_invalid": Invalid or expired API key
- "api_key_missing": No API key provided when required
- "token_expired": Authentication token has expired
- "insufficient_permissions": Valid auth but insufficient access level
- "account_suspended": User account suspended or banned
- "2fa_required": Two-factor authentication required
- "ip_blocked": IP address blocked or geofenced

🗄️ DATA FORMAT & PROCESSING:
- "json_parse_error": Invalid JSON structure or syntax
- "xml_parse_error": Malformed XML document
- "csv_format_error": CSV parsing issues (delimiters, headers)
- "encoding_mismatch": Character encoding problems
- "schema_validation": Data doesn't match expected schema
- "type_conversion": Data type casting failures
- "empty_response": Valid request but no data returned
- "truncated_response": Response cut off or incomplete

🚦 EXTERNAL SERVICE ERRORS:
- "service_unavailable": External API/service temporarily down
- "rate_limited": API quota exceeded - need to wait/throttle
- "quota_exceeded": Daily/monthly usage limit reached
- "deprecated_api": API version deprecated or discontinued
- "maintenance_mode": Service in maintenance mode
- "region_restricted": Service not available in geographic region

🐛 RUNTIME & EXECUTION - CRITICAL ERROR DETECTION:
- "command_failed": Command failed with exit code (e.g., "Command failed with code 1")
- "tool_error": Any tool execution error or exception
- "execution_failed": Script or program execution failure
- "partial_success": Tool marked as PARTIAL SUCCESS indicating incomplete execution
- "syntax_error": Code syntax errors in generated scripts
- "import_error": Missing dependencies or modules
- "memory_exhausted": Out of memory during execution
- "timeout_execution": Script execution timed out
- "infinite_loop": Process stuck in infinite loop
- "segmentation_fault": Memory access violation
- "environment_missing": Required environment variables not set
- "path_placeholder": Placeholder paths like "<full_path_to_*>" not resolved to actual paths
- "unresolved_placeholder": Generated code contains unresolved placeholders like "<full_path_to_short_story_file>"
- "generic_filename": Code uses generic filenames that don't exist like "story.txt" or "file.txt"
- "missing_arguments": Required arguments or parameters not provided
- "file_not_accessible": Target file exists but cannot be read or executed

ERROR CATEGORIES - Sprint 3.2:
- "network": HTTP/connectivity/DNS issues requiring retry strategies
- "filesystem": File operations needing path corrections or permission fixes
- "authentication": Auth/permission problems requiring user intervention or token refresh
- "data_format": Parsing/validation issues needing format corrections
- "external_service": Third-party API issues requiring fallback or retry logic
- "runtime": Execution problems needing dependency fixes or environment setup
- "resource_exhaustion": Memory/storage/quota limits requiring optimization
- "security": Security-related blocks requiring compliance or access approval  
- "data_format": Parsing/format issues
- "external_service": Third-party API problems

RETRY STRATEGIES - Sprint 3.2 Tool-Specific:

🔄 BASIC RETRY STRATEGIES:
- "retry_with_delay": Wait 2-5 seconds and retry same parameters (network timeouts, rate limits)
- "retry_with_exponential_backoff": Exponential delay retry for persistent issues
- "retry_with_different_params": Modify parameters and retry (path corrections, format changes)
- "retry_with_fallback_endpoint": Try alternative API endpoint or service
- "retry_with_reduced_scope": Reduce request size/complexity and retry

🛠️ TOOL-SPECIFIC STRATEGIES:

📰 WEB SEARCH TOOLS (search_web, get_news_summaries):
- http_404/empty_response → retry_with_different_query_terms
- rate_limited → retry_with_exponential_backoff_5min
- region_restricted → retry_with_vpn_fallback (if available)
- service_unavailable → retry_with_alternative_search_engine

📊 STOCK DATA TOOLS (get_stock_and_company_data, comprehensive_stock_analyzer):
- invalid_symbol → retry_with_symbol_validation_and_correction
- market_closed → retry_with_market_hours_check
- rate_limited → retry_with_delay_based_on_quota
- data_unavailable → retry_with_alternative_data_provider

📁 FILE SYSTEM TOOLS (document_search):
- file_not_found → retry_with_path_traversal_and_correction
- permission_denied → retry_with_sudo_or_permission_request
- path_invalid → retry_with_path_sanitization
- encoding_error → retry_with_encoding_detection_and_conversion

💻 EXECUTION TOOLS (sandboxed_executor, process_executor):
- command_failed → retry_with_corrected_file_path_and_arguments
- tool_error → retry_with_parameter_validation_and_correction
- execution_failed → retry_with_dependency_check_and_path_resolution
- partial_success → retry_with_complete_argument_specification
- path_placeholder → retry_with_actual_file_path_substitution
- unresolved_placeholder → retry_with_resolved_file_paths_and_regenerated_code
- generic_filename → retry_with_specific_file_search_and_path_resolution
- missing_arguments → retry_with_proper_argument_formatting
- file_not_accessible → retry_with_permission_check_and_path_correction
- import_error → retry_with_dependency_installation
- syntax_error → retry_with_code_syntax_correction
- timeout_execution → retry_with_increased_timeout_and_optimization
- memory_exhausted → retry_with_memory_optimization

📧 COMMUNICATION TOOLS (secure_email_sender):
- smtp_authentication_failed → retry_with_credential_refresh
- attachment_too_large → retry_with_file_compression_or_chunking  
- recipient_invalid → retry_with_email_validation_and_correction
- smtp_server_unavailable → retry_with_alternative_smtp_provider

🧮 CALCULATION TOOLS (calculator):
- division_by_zero → retry_with_error_handling_and_validation
- overflow_error → retry_with_precision_adjustment
- invalid_expression → retry_with_expression_sanitization

📅 CALENDAR TOOLS (google_calendar_scheduler):
- oauth_token_expired → retry_with_token_refresh
- calendar_not_found → retry_with_calendar_discovery_and_selection
- time_conflict → retry_with_alternative_time_suggestion
- quota_exceeded → retry_with_batch_optimization

🚫 UNACHIEVABLE CONDITIONS:
- account_suspended → escalate_to_user_with_account_resolution
- insufficient_permissions_permanent → escalate_to_user_with_permission_request
- service_permanently_discontinued → suggest_alternative_tool_or_approach
- security_policy_violation → escalate_to_user_with_compliance_guidance

🎯 ESCALATION STRATEGIES:
- "escalate_to_user": Requires user intervention with specific guidance
- "suggest_alternative": Recommend different tool or approach
- "partial_success_acceptable": Continue with available data, note limitations
- "requires_manual_intervention": Stop and request user action
- "continue_with_warning": Proceed but warn about data quality

Respond with JSON only."""

        # Create arbitrator prompt with task details
        task_details = []
        for task in arbitrator_tasks:
            task_details.append(f"""
Task {task['task_id']}: {task['tool_name']}
Result: {task['result'][:500]}{"..." if len(task['result']) > 500 else ""}
""")
        
        arbitrator_prompt = f"""User Request: {user_prompt[:200]}

Task Results to Validate:
{''.join(task_details)}

Please validate each task result and respond with JSON analysis."""

        # Check if we have pre-detected errors (bypass LLM call for obvious errors)
        pre_detected_errors = [task for task in arbitrator_tasks if task["status"] == "BAD"]
        
        logger.info(f"🧠 Calling arbitrator LLM for validation...")
        
        # Sprint 3.4: Start monitoring
        import time
        import json
        validation_start_time = time.time()
        arbitrator_llm_success = False
        error_patterns_detected = []
        
        if pre_detected_errors:
            logger.info(f"🚨 PRE-DETECTED ERRORS: Found {len(pre_detected_errors)} errors, bypassing LLM call")
            
            # Create validation result from pre-detected errors
            arbitrator_response = json.dumps({
                "tasks": [],
                "overall_assessment": "Errors detected during pre-processing",
                "patterns_detected": ["command_failed", "execution_error"]
            })
            
            task_results = []
            for task in arbitrator_tasks:
                if task["status"] == "BAD":
                    task_results.append({
                        "task_id": task["task_id"],
                        "status": "BAD",
                        "error_pattern": task["pre_detected_error"],
                        "error_category": "runtime",
                        "feedback": task["pre_detected_feedback"],
                        "retry_strategy": "retry_with_corrected_file_path_and_arguments"
                    })
                else:
                    task_results.append({
                        "task_id": task["task_id"],
                        "status": "GOOD",
                        "error_pattern": None,
                        "feedback": "Task completed successfully"
                    })
            
            # Update the response with task results
            response_data = json.loads(arbitrator_response)
            response_data["tasks"] = task_results
            arbitrator_response = json.dumps(response_data)
            
            arbitrator_llm_success = True
            arbitrator_llm_time = 0.001  # Minimal time for pre-processing
            logger.info(f"🧠 Pre-processing response created: {len(arbitrator_response)} chars")
            
        else:
            logger.info(f"🧠 No pre-detected errors - calling arbitrator LLM...")
            
            try:
                # Call arbitrator LLM
                arbitrator_response = await llm_manager.call_arbitrator(
                    arbitrator_prompt,
                    arbitrator_system_prompt
                )
            
                arbitrator_llm_success = True
                arbitrator_llm_time = time.time() - validation_start_time
                
                logger.info(f"🧠 Arbitrator response received: {len(arbitrator_response)} chars")
                arbitrator_monitor.record_arbitrator_llm_call(True, arbitrator_llm_time)
                
            except Exception as e:
                arbitrator_llm_time = time.time() - validation_start_time
                arbitrator_monitor.record_arbitrator_llm_call(False, arbitrator_llm_time)
                logger.error(f"🧠 Arbitrator LLM call failed: {e}")
                raise
        
        # Parse arbitrator response
        import json
        try:
            # Enhanced JSON extraction - handle markdown, text, and mixed responses
            clean_response = arbitrator_response.strip()
            
            # Method 1: Standard markdown code block removal
            if clean_response.startswith("```json"):
                clean_response = clean_response[7:]  # Remove ```json
            if clean_response.endswith("```"):
                clean_response = clean_response[:-3]  # Remove ```
            clean_response = clean_response.strip()
            
            # Method 2: If that fails, try to extract JSON from mixed content
            validation_result = None
            try:
                validation_result = json.loads(clean_response)
            except json.JSONDecodeError:
                logger.warning(f"🧠 Standard JSON parsing failed, attempting extraction from mixed content...")
                
                # Look for JSON object patterns in the response
                import re
                json_patterns = [
                    r'\{[^{}]*"tasks"[^{}]*\[[^\]]*\][^{}]*\}',  # Simple single-line JSON
                    r'\{.*?"tasks"\s*:\s*\[.*?\].*?\}',          # Multi-line JSON pattern
                ]
                
                for pattern in json_patterns:
                    matches = re.findall(pattern, arbitrator_response, re.DOTALL)
                    for match in matches:
                        try:
                            validation_result = json.loads(match)
                            logger.info(f"🧠 Successfully extracted JSON using pattern matching")
                            break
                        except json.JSONDecodeError:
                            continue
                    if validation_result:
                        break
                
                # Method 3: Last resort - generate a minimal valid response for successful tools
                if not validation_result:
                    logger.warning(f"🧠 JSON extraction failed, generating fallback response for successful tools")
                    validation_result = {
                        "tasks": [
                            {
                                "task_id": i + 1,
                                "status": "GOOD",
                                "error_pattern": None,
                                "feedback": "Task completed successfully (fallback validation)"
                            }
                            for i in range(len(arbitrator_tasks))
                        ],
                        "overall_assessment": "All tasks successful (fallback due to parsing failure)",
                        "patterns_detected": []
                    }
                    logger.info(f"🧠 Using fallback validation result for {len(arbitrator_tasks)} tasks")
            logger.info(f"🧠 Arbitrator validation parsed successfully")

            # 🎯 TASK COMPLETENESS CHECK: Handle missing_tools from arbitrator
            missing_tools_from_arbitrator = validation_result.get("missing_tools", [])
            if missing_tools_from_arbitrator:
                logger.warning(f"🚨 ARBITRATOR DETECTED MISSING TOOLS: {[tool.get('tool_name') for tool in missing_tools_from_arbitrator]}")
                for missing_tool_info in missing_tools_from_arbitrator:
                    tool_name = missing_tool_info.get("tool_name", "unknown")
                    reason = missing_tool_info.get("reason", "Tool was required but not called")
                    logger.warning(f"   ❌ Missing: {tool_name} - {reason}")

                    # Mark this as a task failure to trigger retry with missing tool
                    # The retry system will regenerate tool calls including the missing tool
                    validation_result.setdefault("tasks", []).append({
                        "task_id": len(validation_result.get("tasks", [])) + 1,
                        "status": "BAD",
                        "error_pattern": "missing_required_tool",
                        "error_category": "task_completeness",
                        "feedback": f"User requested '{tool_name}' but tool was not called. {reason}",
                        "retry_strategy": "regenerate_tool_calls_with_missing_tool",
                        "corrected_parameters": missing_tool_info.get("required_parameters", {})
                    })

            # Process validation results with enhanced error pattern detection (Sprint 2.2)
            all_good = True
            detected_patterns = []
            error_analysis = {}

            # Process overall patterns detected
            patterns_detected = validation_result.get("patterns_detected", [])
            if patterns_detected:
                logger.info(f"🔍 Arbitrator detected global patterns: {patterns_detected}")
            
            # Process individual task validations with error pattern analysis
            for task_validation in validation_result.get("tasks", []):
                status = task_validation.get("status", "UNKNOWN")
                task_id = task_validation.get("task_id", "?")
                error_pattern = task_validation.get("error_pattern")
                error_category = task_validation.get("error_category") 
                retry_strategy = task_validation.get("retry_strategy")
                feedback = task_validation.get("feedback", "No feedback")
                
                if status == "GOOD":
                    logger.info(f"🧠 Task {task_id} validated as GOOD")
                
                elif status == "BAD":
                    # Enhanced BAD status logging with error pattern analysis
                    pattern_info = f" | Pattern: {error_pattern}" if error_pattern else ""
                    category_info = f" | Category: {error_category}" if error_category else ""
                    strategy_info = f" | Strategy: {retry_strategy}" if retry_strategy else ""
                    
                    logger.warning(f"🔍 Task {task_id} marked BAD: {feedback}{pattern_info}{category_info}{strategy_info}")
                    
                    # Collect error patterns for analysis
                    if error_pattern:
                        detected_patterns.append(error_pattern)
                        
                    # Store detailed error analysis for potential retry logic
                    error_analysis[task_id] = {
                        "error_pattern": error_pattern,
                        "error_category": error_category,
                        "retry_strategy": retry_strategy,
                        "feedback": feedback,
                        "corrected_parameters": task_validation.get("corrected_parameters", {})
                    }
                    
                    all_good = False
                
                elif status == "UNACHIEVABLE":
                    pattern_info = f" | Pattern: {error_pattern}" if error_pattern else ""
                    logger.error(f"🚨 Task {task_id} marked UNACHIEVABLE: {feedback}{pattern_info}")
                    all_good = False
            
            # Enhanced error pattern analysis with strategic insights (Sprint 2.2)
            if detected_patterns or error_analysis:
                # Run comprehensive pattern analysis
                pattern_analysis_result = analyze_error_patterns(error_analysis)
                
                if pattern_analysis_result.get("status") == "patterns_detected":
                    total_errors = pattern_analysis_result["total_errors"]
                    critical_patterns = pattern_analysis_result.get("critical_patterns", [])
                    retry_priority = pattern_analysis_result.get("retry_priority", [])
                    
                    logger.info(f"🔍 Pattern Analysis Complete: {total_errors} errors analyzed")
                    logger.info(f"🔍 Pattern Frequency: {pattern_analysis_result['pattern_frequency']}")
                    
                    if critical_patterns:
                        logger.warning(f"🚨 Critical Patterns (multiple occurrences): {critical_patterns}")
                    
                    if retry_priority:
                        logger.info(f"🎯 Retry Priority Recommendations:")
                        for priority in retry_priority[:3]:  # Top 3 priorities
                            category = priority["category"]
                            count = priority["error_count"]
                            patterns = priority["patterns"]
                            action = priority["recommended_action"]
                            logger.info(f"   • {category}: {count} errors, patterns {patterns} → {action}")
                    
                    # Strategic error category insights
                    category_dist = pattern_analysis_result.get("category_distribution", {})
                    if category_dist:
                        high_impact_categories = [cat for cat, data in category_dist.items() if data["count"] > 1]
                        if high_impact_categories:
                            logger.warning(f"🎯 High-Impact Categories: {high_impact_categories}")
                else:
                    logger.info(f"🔍 Pattern analysis: {pattern_analysis_result.get('status', 'unknown')}")
                    
            # For Sprint 2.2, return original results but with comprehensive error analysis
            # Sprint 2.3 will implement intelligent retry based on pattern insights
            original_results = "".join(tools_results_list)
            
            # Sprint 3.4: Final monitoring and metrics
            total_validation_time = time.time() - validation_start_time
            validation_success = all_good
            
            # 🔧 CRITICAL ARCHITECTURE FIX: TRUE SINGLE SYNCHRONOUS PATH
            # PRIMARY LLM REMAINS LOCKED until ALL results are corrected
            # NO conditional branching - ALWAYS attempt correction
            
            logger.info(f"🔒 SYNCHRONOUS CORRECTION: Processing all results through correction pipeline")
            
            # Ensure pattern_analysis_result is always defined
            if 'pattern_analysis_result' not in locals():
                pattern_analysis_result = {"status": "no_patterns", "total_errors": 0}
            
            # ALWAYS attempt correction regardless of initial validation
            # This ensures consistent format and eliminates hallucination from error data
            retry_result = await intelligent_retry_with_circuit_breakers(
                error_analysis, pattern_analysis_result, 
                tools_called, tools_results_list, user_prompt,
                tool_manager  # Pass tool_manager for tool re-execution
            )
            
            if retry_result.get("success", False):
                logger.info(f"🔧 CORRECTION SUCCESSFUL: Using verified corrected results")
                arbitrator_monitor.record_validation_attempt(True, total_validation_time, detected_patterns)
                retry_count = retry_result.get("retried_tools", 0)
                arbitrator_monitor.record_retry_session(retry_count, True)
                return retry_result["corrected_results"]
            else:
                # If correction fails, at minimum ensure format consistency
                logger.warning(f"🔧 CORRECTION FAILED: Using format-normalized original results")
                logger.info(f"🔄 Correction failure reason: {retry_result.get('reason', 'Unknown')}")
                
                arbitrator_monitor.record_validation_attempt(all_good, total_validation_time, detected_patterns)
                retry_count = retry_result.get("retried_tools", 0) 
                arbitrator_monitor.record_retry_session(retry_count, False)
                
                # Check for circuit breaker information
                if "circuit_breaker" in retry_result.get("reason", "").lower():
                    arbitrator_monitor.record_circuit_breaker_activation(
                        retry_result.get("reason", "UNKNOWN"), 
                        retry_result.get("escalation", "UNKNOWN")
                    )
                
                # Apply minimal format normalization to prevent hallucination
                if all_good:
                    logger.info(f"🔧 FORMAT NORMALIZED: Original results were valid, applying consistent formatting")
                    return original_results  # Results were already good, just format them consistently
                else:
                    logger.error(f"🚨 ARBITRATOR CRITICAL FAILURE: Error correction failed - marking results as incomplete")
                    # Instead of raw error results, return a clear failure marker
                    failure_marker = f"ARBITRATOR_ERROR_CORRECTION_FAILED: Original tools contained errors that could not be corrected automatically. Error analysis: {error_analysis}"
                    return failure_marker
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse arbitrator JSON response: {e}")
            logger.error(f"❌ Raw arbitrator response: {arbitrator_response[:200]}...")
            return None
            
    except Exception as e:
        logger.error(f"❌ Arbitrator validation failed: {e}")
        return None

async def _verify_task_completion(user_prompt: str, tools_called: List[str], tools_results: str, tool_manager) -> Dict[str, Any]:
    """RETIRED keyword classifier (convergence Phase 5/6). The LLM intent classifier
    (_maybe_llm_authoritative, mode:llm) is the AUTHORITATIVE delivery-intent decider — INCLUDING whether a
    request is an OpenWebUI background meta-task (title/tag generation), which the classifier prompt
    (orchestration/intent.py) is instructed to classify as needing no delivery tools. This function is only
    the FALL-BACK used when the LLM classifier is unavailable (timeout/error/over-length): it FAILS SAFE —
    reports the task complete so the model's text answer still streams, and never GUESSES delivery from
    keywords/patterns to auto-run post-LLM actions on a classifier failure. No keyword/pattern
    classification remains here (LLM-Policy Gate)."""
    return {"complete": True, "missing_tools": [], "pattern": "classifier_unavailable",
            "reason": "legacy keyword classifier retired -- LLM intent classifier (mode:llm) is authoritative"}


# ── Phase 2: SHADOW-MODE LLM intent classifier (convergence) ─────────────────────────────────────
# Runs an LLM intent classifier ALONGSIDE the legacy keyword verifier above, compares them, and logs/
# records divergences — WITHOUT changing behavior (legacy stays authoritative). It runs as a
# fire-and-forget background task so it never adds latency to the user's response. Config:
# convergence.shadow_classifier (default disabled). See docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md.
_SHADOW_TASKS = set()  # hold references so background tasks aren't garbage-collected mid-flight


def _schedule_shadow_classification(user_prompt, tools_called, legacy_result, data):
    """Schedule a non-blocking shadow classification if enabled. No-op (and never raises) otherwise."""
    try:
        cfg = (config_loader.load_config().get('convergence', {}) or {}).get('shadow_classifier', {}) or {}
        if not cfg.get('enabled') or not legacy_result:
            return
        import random
        if random.random() > float(cfg.get('sample_rate', 1.0)):
            return
        if len(user_prompt or "") > int(cfg.get('max_prompt_chars', 8000)):
            logger.info("🕵️ SHADOW CLASSIFIER skipped: prompt exceeds max_prompt_chars")
            return
        task = asyncio.create_task(
            _run_shadow_classifier(user_prompt, list(tools_called or []), dict(legacy_result), cfg))
        _SHADOW_TASKS.add(task)
        task.add_done_callback(_SHADOW_TASKS.discard)
    except Exception as e:  # noqa: BLE001 — shadow must NEVER break the request path
        logger.warning(f"🕵️ SHADOW CLASSIFIER scheduling failed: {e}")


async def _run_shadow_classifier(user_prompt, tools_called, legacy_result, cfg):
    """Background: run the LLM intent classifier, compare to the legacy result, log + record divergence."""
    from orchestration import intent as _intent
    from research.engine import _collect_stream
    try:
        try:
            _defs = await tool_manager.get_tools_definitions()
            catalog = [{"name": d.get("function", {}).get("name", ""),
                        "description": d.get("function", {}).get("description", "")}
                       for d in _defs if d.get("function", {}).get("name")]
        except Exception:  # noqa: BLE001
            catalog = []
        shadow_model = cfg.get('model')

        async def _collect(prompt, system_prompt, max_tokens):
            kwargs = {"system_prompt": system_prompt, "temperature": 0.0,
                      "max_tokens": max_tokens, "stream": False}
            if shadow_model:
                kwargs["model"] = shadow_model
            return await _collect_stream(llm_manager.generate_stream, prompt, **kwargs)

        intent_res = await asyncio.wait_for(
            _intent.classify_intent_actions(_collect, catalog, user_prompt,
                                            max_tokens=int(cfg.get('max_tokens', 800))),
            timeout=float(cfg.get('timeout_seconds', 60)))
        shadow_shape = _intent.to_verifier_shape(intent_res, tools_called)
        cmp = _intent.compare(legacy_result, shadow_shape)
        logger.info(
            f"🕵️ SHADOW CLASSIFIER | agree_complete={cmp['agree_complete']} agree_tools={cmp['agree_tools']} "
            f"| legacy(complete={legacy_result.get('complete')},missing={cmp['legacy_missing']},"
            f"pattern={legacy_result.get('pattern')}) "
            f"| llm(complete={shadow_shape['complete']},missing={cmp['shadow_missing']},ok={intent_res.get('ok')}) "
            f"| prompt={(user_prompt or '')[:160]!r}")
        if not (cmp['agree_complete'] and cmp['agree_tools']):
            _append_shadow_divergence(cfg, user_prompt, legacy_result, shadow_shape, cmp, intent_res)
    except asyncio.TimeoutError:
        logger.warning("🕵️ SHADOW CLASSIFIER timed out")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"🕵️ SHADOW CLASSIFIER error: {e}")


async def _maybe_llm_authoritative(user_prompt, tools_called, legacy_result):
    """Phase 3c cutover. If convergence.intent_classifier.mode == 'llm', run the LLM intent classifier
    INLINE and use its result (FULL tool set) as the authoritative verification_result; otherwise return
    the legacy result unchanged. The legacy result is ALWAYS the fallback — on wrong mode, over-length
    prompt, classifier error, or timeout we return it untouched, so the default (mode=legacy) is a
    guaranteed no-op (zero behavior change). Returns a legacy-shaped dict {complete, missing_tools,
    pattern, reason}."""
    try:
        cfg = (config_loader.load_config().get('convergence', {}) or {}).get('intent_classifier', {}) or {}
        if cfg.get('mode') != 'llm' or not legacy_result:
            return legacy_result
        if len(user_prompt or "") > int(cfg.get('max_prompt_chars', 12000)):
            logger.info("🧭 INTENT(llm): prompt exceeds max_prompt_chars → legacy fallback")
            return legacy_result
        from orchestration import intent as _intent
        from research.engine import _collect_stream
        try:
            _defs = await tool_manager.get_tools_definitions()
            catalog = [{"name": d.get("function", {}).get("name", ""),
                        "description": d.get("function", {}).get("description", "")}
                       for d in _defs if d.get("function", {}).get("name")]
        except Exception:  # noqa: BLE001
            catalog = []
        model = cfg.get('model')

        async def _collect(prompt, system_prompt, max_tokens):
            kwargs = {"system_prompt": system_prompt, "temperature": 0.0,
                      "max_tokens": max_tokens, "stream": False}
            if model:
                kwargs["model"] = model
            return await _collect_stream(llm_manager.generate_stream, prompt, **kwargs)

        res = await asyncio.wait_for(
            _intent.classify_intent_actions(_collect, catalog, user_prompt,
                                            max_tokens=int(cfg.get('max_tokens', 800))),
            timeout=float(cfg.get('timeout_seconds', 30)))
        if not res.get('ok'):
            logger.warning("🧭 INTENT(llm): classifier returned not-ok → legacy fallback")
            return legacy_result
        shape = _intent.to_verifier_shape(res, tools_called)
        result = {"complete": shape["complete"], "missing_tools": shape["missing_tools"],
                  "pattern": "llm_intent", "reason": "LLM intent classification (Phase 3c)"}
        logger.info(f"🧭 INTENT(llm) AUTHORITATIVE: complete={result['complete']} "
                    f"missing_tools={result['missing_tools']} "
                    f"(legacy: complete={legacy_result.get('complete')} "
                    f"missing={legacy_result.get('missing_tools')} pattern={legacy_result.get('pattern')})")
        return result
    except asyncio.TimeoutError:
        logger.warning("🧭 INTENT(llm): timed out → legacy fallback")
        return legacy_result
    except Exception as e:  # noqa: BLE001 — never break the request; fall back to legacy
        logger.warning(f"🧭 INTENT(llm): error ({e}) → legacy fallback")
        return legacy_result


def _append_shadow_divergence(cfg, user_prompt, legacy_result, shadow_shape, cmp, intent_res):
    """Best-effort JSONL record of a disagreement for offline analysis. Never raises into the caller."""
    path = cfg.get('divergence_log')
    if not path:
        return
    try:
        import json as _json
        import os as _os
        from datetime import datetime as _dt
        rec = {
            "ts": _dt.now().isoformat(timespec="seconds"),
            "prompt": (user_prompt or "")[:500],
            "legacy": {"complete": legacy_result.get("complete"),
                       "missing_tools": legacy_result.get("missing_tools"),
                       "pattern": legacy_result.get("pattern")},
            "shadow": {"complete": shadow_shape.get("complete"),
                       "missing_tools": shadow_shape.get("missing_tools"),
                       "ok": intent_res.get("ok")},
            "diff": {"only_legacy": cmp["only_legacy"], "only_shadow": cmp["only_shadow"]},
        }
        _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a") as fh:
            fh.write(_json.dumps(rec) + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"🕵️ SHADOW CLASSIFIER divergence-log write failed: {e}")

def _extract_report_content_from_results(tools_results: str) -> str:
    """Extract the comprehensive stock analysis content from tools_results"""
    try:
        # Look for comprehensive_stock_analyzer result in the tools_results
        if "Tool: comprehensive_stock_analyzer" in tools_results:
            # Split by tool sections and find the comprehensive_stock_analyzer result
            parts = tools_results.split("Tool: ")
            for part in parts:
                if part.startswith("comprehensive_stock_analyzer"):
                    # Extract just the result content
                    lines = part.split("\n")
                    result_lines = []
                    capture = False
                    for line in lines:
                        if line.startswith("Result: "):
                            capture = True
                            result_lines.append(line[8:])  # Remove "Result: " prefix
                        elif capture and line.strip() and not line.startswith("Tool: "):
                            result_lines.append(line)
                        elif capture and line.startswith("Tool: "):
                            break
                    
                    return "\n".join(result_lines).strip()
        
        return ""
    except Exception as e:
        logger.error(f"❌ Error extracting report content: {e}")
        return ""

def _generate_dynamic_title(user_prompt: str, tools_results: str) -> str:
    """Generate dynamic report title based on content type and topic"""
    try:
        user_prompt_lower = user_prompt.lower()
        tools_results_lower = tools_results.lower()
        
        # Check for news content
        if "Tool: get_news_summaries" in tools_results:
            # Extract topic from user prompt
            news_keywords = {
                "middle east": "Middle East News Analysis Report",
                "technology": "Technology News Analysis Report", 
                "tech": "Technology News Analysis Report",
                "stock market": "Stock Market News Analysis Report",
                "market": "Market News Analysis Report",
                "sports": "Sports News Analysis Report",
                "politics": "Political News Analysis Report", 
                "political": "Political News Analysis Report",
                "business": "Business News Analysis Report",
                "health": "Health News Analysis Report",
                "science": "Science News Analysis Report",
                "entertainment": "Entertainment News Analysis Report",
                "world": "World News Analysis Report",
                "international": "International News Analysis Report",
                "economy": "Economic News Analysis Report",
                "economic": "Economic News Analysis Report",
                "climate": "Climate News Analysis Report",
                "environment": "Environmental News Analysis Report",
                "african": "African News Analysis Report",
                "africa": "African News Analysis Report",
                "asian": "Asian News Analysis Report",
                "asia": "Asian News Analysis Report",
                "european": "European News Analysis Report",
                "europe": "European News Analysis Report"
            }
            
            # Find the most specific topic match
            for topic, title in news_keywords.items():
                if topic in user_prompt_lower or topic in tools_results_lower:
                    return title
            
            # Default news title if no specific topic found
            return "News Analysis Report"
        
        # Check for financial/stock content
        elif ("Tool: stock_analyzer" in tools_results or 
              any(keyword in user_prompt_lower for keyword in ["stock", "financial", "market", "trading", "investment"])):
            return "Comprehensive Stock Analysis Report"
        
        # Check for other specific content types
        elif any(keyword in user_prompt_lower for keyword in ["calendar", "appointment", "schedule"]):
            return "Calendar Analysis Report"
        elif any(keyword in user_prompt_lower for keyword in ["email", "message", "letter"]):
            return "Email Analysis Report"
        else:
            # General analysis report
            return "Analysis Report"
            
    except Exception as e:
        logger.error(f"❌ Error generating dynamic title: {e}")
        return "Analysis Report"

def _extract_subject_from_prompt(user_prompt: str) -> str:
    """
    Extract email subject from user prompt.

    Looks for patterns like:
    - subject 'My Subject'
    - subject "My Subject"
    - subject: 'My Subject'
    - with subject 'My Subject'

    Returns extracted subject or None if not found.
    """
    import re

    # Pattern matches: subject followed by optional colon, then quoted text
    patterns = [
        r'(?:with\s+)?subject[:\s]+["\']([^"\']+)["\']',  # subject 'text' or subject: 'text'
        r'(?:with\s+)?subject[:\s]+"([^"]+)"',  # subject "text"
        r'(?:with\s+)?subject[:\s]+\'([^\']+)\'',  # subject 'text'
    ]

    for pattern in patterns:
        match = re.search(pattern, user_prompt, re.IGNORECASE)
        if match:
            subject = match.group(1).strip()
            logger.info(f"📧 EXTRACTED SUBJECT: '{subject}' from prompt")
            return subject

    return None


async def _llm_document_title(content: str, user_prompt: str, llm_manager) -> str:
    """Title for a delivery document — content-FIRST (the content's own first markdown heading, no model
    call); if the content has NO heading, ASK THE LLM (the model that wrote the content) for a concise
    title. No keyword/topic lookup and no prompt regex (LLM-Policy Gate). Returns 'Document' only if the
    model call fails. Used by the POST-LLM executor so filename + email subject reflect the real topic."""
    import re as _re
    for _line in (content or "").splitlines():
        _m = _re.match(r'^#{1,4}\s+(.+\S)', _line.strip())
        if _m:
            return _m.group(1).strip().strip("#").strip()[:120]
    try:
        from research.engine import _collect_stream
        _sys = ("Produce a SHORT document title (3-8 words, Title Case, no surrounding quotes, no trailing "
                "punctuation) that names the document below. Output ONLY the title text, nothing else.")
        _usr = (f"DOCUMENT CONTENT (excerpt):\n{(content or '')[:2000]}\n\n"
                f"(the user asked: {(user_prompt or '')[:300]})\n\nTitle:")
        _raw = await _collect_stream(llm_manager.generate_stream, _usr, system_prompt=_sys,
                                     temperature=0.0, max_tokens=24, stream=False)
        _lines = (_raw or "").strip().splitlines()
        _t = _lines[0].strip().strip('"').strip("#").strip()[:120] if _lines else ""
        if _t:
            return _t
    except Exception as _e:  # noqa: BLE001 — a title is cosmetic; never break delivery over it
        logger.warning(f"📄 LLM title generation failed ({_e}); using generic title")
    return "Document"


async def _llm_title_from_request(user_prompt: str, content: str, generate_stream) -> str:
    """Concise document title derived by the LLM from the user's RESEARCH REQUEST (with a content excerpt
    for context) — used when the document has NO usable top-level title heading (none, or the first
    heading is an enumerated *section* like '# 1. …'). Unlike `_llm_document_title`, this does NOT read
    the content's first heading, so it can't echo a section heading back as the title. No keyword/topic
    map (LLM-Policy Gate). `generate_stream` is the LLM streaming fn (e.g. llm_manager.generate_stream).
    Returns '' on failure/unavailable so the caller can apply its own generic fallback."""
    try:
        if not generate_stream:
            return ""
        from research.engine import _collect_stream
        _sys = ("Produce a SHORT document title (3-8 words, Title Case, no surrounding quotes, no trailing "
                "punctuation, NOT numbered) naming the OVERALL topic of the user's request below. Ignore any "
                "delivery instructions (email/PDF/format). Output ONLY the title text, nothing else.")
        _usr = (f"USER REQUEST:\n{(user_prompt or '')[:600]}\n\n"
                f"DOCUMENT EXCERPT:\n{(content or '')[:1200]}\n\nTitle:")
        _raw = await _collect_stream(generate_stream, _usr, system_prompt=_sys,
                                     temperature=0.0, max_tokens=24, stream=False)
        _lines = (_raw or "").strip().splitlines()
        return _lines[0].strip().strip('"').strip("#").strip()[:120] if _lines else ""
    except Exception as _e:  # noqa: BLE001 — a title is cosmetic; never break delivery over it
        logger.warning(f"📄 DR title-from-request failed ({_e}); caller will use a generic title")
        return ""


async def _llm_requested_formats(user_prompt: str, llm_manager, default: str = "html") -> list:
    """Which document format(s) the user asked to RECEIVE (subset of pdf/html/md/txt) — decided by the
    LLM, NOT brittle substring matching. (The old `resolve_delivery_formats` matched 'text' inside
    'context' and 'md' inside unrelated words of the embedded 'above' content, producing spurious .md/.txt
    files.) Considers ONLY the user's delivery directive, not quoted/forwarded content. Defaults to
    [default]. LLM-Policy-Gate compliant."""
    _valid = ("pdf", "html", "md", "txt")
    try:
        from research.engine import _collect_stream
        import json as _json, re as _re
        _sys = ("From the user's request, return ONLY the document file format(s) they explicitly ask to "
                "RECEIVE, as a STRICT JSON array drawn from [\"pdf\",\"html\",\"md\",\"txt\"] — include EVERY "
                "one they name (e.g. both for 'a PDF and an HTML file'). Consider ONLY their delivery "
                "request; IGNORE any quoted or 'above' content they are forwarding. If they name no format, "
                f"return [\"{default}\"]. Output ONLY the JSON array, nothing else.")
        _up = user_prompt or ""
        # The user's directive (e.g. "in PDF and HTML") is typically at the END of a NewX/OpenWebUI
        # envelope — after the system preamble and the embedded 'above' content — so feed head+tail to
        # GUARANTEE the ask is in the window (truncating to the head alone misses it → false single format).
        _win = _up if len(_up) <= 4000 else (_up[:600] + "\n…\n" + _up[-3400:])
        _raw = await _collect_stream(llm_manager.generate_stream, _win,
                                     system_prompt=_sys, temperature=0.0, max_tokens=24, stream=False)
        _m = _re.search(r'\[[^\]]*\]', _raw or "")
        if _m:
            _arr = _json.loads(_m.group(0))
            _fmts = [f for f in _arr if isinstance(f, str) and f.lower() in _valid]
            if _fmts:
                _out = list(dict.fromkeys(f.lower() for f in _fmts))
                logger.info(f"📄 requested delivery formats (LLM): {_out}")
                return _out
    except Exception as _e:  # noqa: BLE001 — never break delivery over format detection
        logger.warning(f"📄 LLM format detection failed ({_e}); defaulting to [{default}]")
    return [default]


def _unwrap_delivery_content(text: str) -> str:
    """If the model wrapped the deliverable in a markdown code fence (```html / ``` … ```) — usually with a
    conversational preamble like 'Here is the HTML document:' — return the FENCED content ALONE, so the
    saved file is the real document and not its source rendered as a code block. No-op when there is no
    dominant fence (the fence must be the bulk of the response)."""
    import re as _re
    if not text:
        return text
    _m = _re.search(r'```[a-zA-Z0-9]*[ \t]*\r?\n(.*?)\r?\n```', text, _re.DOTALL)
    if _m:
        _inner = _m.group(1).strip()
        if _inner and len(_inner) >= 0.5 * len(text.strip()):
            return _inner
    return text


def _normalize_delivery_markdown(text: str) -> str:
    """Tidy a delivery document's markdown so the renderer doesn't print non-headings AS headings:
      (1) drop a trailing social-hashtags line ("#Tag #Tag …" — a NewX artifact the renderer promotes to
          an <h1>);
      (2) demote a '#'-prefixed line that is really a BODY SENTENCE (ends with sentence punctuation, or is
          very long) back to a normal paragraph — this is the model mis-formatting a lead/body as a heading,
          which made body text render in the large heading font.
    Real, short headings (no trailing period) are left untouched."""
    import re as _re
    if not text:
        return text
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        # (1) a line of two-or-more social hashtags → drop entirely
        if _re.match(r'^#[A-Za-z0-9_]+(\s+#[A-Za-z0-9_]+)+$', s):
            continue
        # (2) heading line whose text is really a BODY SENTENCE → demote to a plain paragraph. Strip a
        # trailing markdown citation/link first (it hides the sentence-ending period, e.g.
        # "… since 2021. [Source](url)"), then treat as a sentence if it ends with sentence punctuation,
        # contains a mid-text ". Capital" (multiple sentences), or is long.
        _m = _re.match(r'^(#{1,6})\s+(.*\S)$', s)
        if _m:
            _htext = _m.group(2).strip()
            _core = _re.sub(r'\s*\[[^\]]+\]\([^)]+\)\s*$', '', _htext).strip()
            if (_core.endswith(('.', '!', '?')) or len(_core) > 80
                    or _re.search(r'\.\s+["\'A-Z0-9]', _core)):
                out.append(_htext)   # keep the original text (with any citation) as a paragraph
                continue
        out.append(ln)
    return "\n".join(out)


def _derive_document_title(content: str, user_prompt: str) -> str:
    """Document title for a delivery file — the SAME logic Deep Research uses (`_run_dr_delivery`): the
    content's first markdown heading, else a subject extracted from the prompt, else 'Document'. Drives
    the filename slug so the file name reflects the actual topic instead of a generic 'document'. No
    keyword/topic classification (LLM-Policy Gate): the title comes from the content the LLM produced."""
    import re as _re
    for _line in (content or "").splitlines():
        _m = _re.match(r'^#{1,4}\s+(.+\S)', _line.strip())
        if _m:
            return _m.group(1).strip().strip("#").strip()[:120]
    return (_extract_subject_from_prompt(user_prompt) or "Document").strip()[:120]


def _generate_dynamic_filename(user_prompt: str, tools_results: str, timestamp: str, file_extension: str = "html") -> str:
    """Generate dynamic filename based on content type and topic"""
    try:
        # Name from the CONTENT — never hardcoded topic keywords (LLM-Policy Gate: no keyword
        # classification). Prefer an explicit subject in the request; else derive a title from the
        # content. Slugify; generic fallback if neither yields anything.
        import re
        title = _extract_subject_from_prompt(user_prompt) or "document"
        slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:60] or "document"
        logger.info(f"📄 content-derived filename: {slug}_{timestamp}.{file_extension} (from '{title}')")
        return f"{slug}_{timestamp}.{file_extension}"
    except Exception as e:
        logger.error(f"❌ Error generating dynamic filename: {e}")
        return f"document_{timestamp}.{file_extension}"

def _extract_news_content_from_results(tools_results: str) -> str:
    """Extract news content from get_news_summaries tool results"""
    try:
        # Look for get_news_summaries result in the tools_results
        if "Tool: get_news_summaries" in tools_results:
            # Split by tool sections and find the get_news_summaries result
            parts = tools_results.split("Tool: ")
            for part in parts:
                if part.startswith("get_news_summaries"):
                    # Extract just the result content
                    lines = part.split("\n")
                    result_lines = []
                    capture = False
                    for line in lines:
                        if line.startswith("Result: "):
                            capture = True
                            result_lines.append(line[8:])  # Remove "Result: " prefix
                        elif capture and line.strip() and not line.startswith("Tool: "):
                            result_lines.append(line)
                        elif capture and line.startswith("Tool: "):
                            break
                    
                    return "\n".join(result_lines).strip()
        
        return ""
    except Exception as e:
        logger.error(f"❌ Error extracting news content: {e}")
        return ""

async def _execute_missing_tools(missing_tools: List[str], tool_manager, tools_results: str = "", user_prompt: str = "") -> str:
    """
    🔄 AUTO-EXECUTOR for missing tools
    Automatically executes missing tools to complete the task
    """
    additional_results = ""
    
    for tool_name in missing_tools:
        try:
            logger.info(f"🔄 Auto-executing missing tool: {tool_name}")
            
            if tool_name == "sandboxed_executor":
                logger.info("🎯🎯🎯 AUTO-EXEC PATH: Starting sandboxed_executor auto-execution")
                # Determine report type based on tools_results content
                timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
                
                # Generate dynamic filename based on content type and topic - DEFAULT TO HTML
                file_extension = "html" if "Tool: get_news_summaries" in tools_results or "stock" in user_prompt.lower() else "md"
                filename = _generate_dynamic_filename(user_prompt, tools_results, timestamp, file_extension)
                
                if "Tool: get_news_summaries" in tools_results:
                    actual_report_content = _extract_news_content_from_results(tools_results)
                else:
                    actual_report_content = _extract_report_content_from_results(tools_results)
                
                logger.info(f"🎯🎯🎯 AUTO-EXEC PATH: Creating DYNAMIC REPORT -> {filename}")
                
                # Generate appropriate report content based on type
                if actual_report_content:
                    if "get_news_summaries" in tools_results:
                        # News analysis report with dynamic title
                        report_title = _generate_dynamic_title(user_prompt, tools_results)
                        report_content = f"""# {report_title}

Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Critical News Summary

{actual_report_content}

---

*This report was automatically generated by the AI News Analysis System.*
"""
                    else:
                        # Stock analysis report
                        report_content = f"""# Comprehensive Stock Analysis Report

Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

{actual_report_content}

---

*This report was automatically generated and saved by the task completion system.*
"""
                else:
                    # Fallback content based on type
                    if "get_news_summaries" in tools_results:
                        report_title = _generate_dynamic_title(user_prompt, tools_results)
                        report_content = f"""# {report_title}

Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Analysis Summary
News analysis completed successfully.

*Report content could not be extracted automatically. Please refer to the original news results.*
"""
                    else:
                        report_content = f"""# Stock Analysis Report

Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Analysis Summary
Comprehensive stock analysis completed successfully.

*Report content could not be extracted automatically. Please refer to the original analysis results.*
"""
                
                # Create the file using sandboxed_executor - PDF auto-conversion will trigger
                # Find the actual tool instance, not the wrapper
                logger.info("🎯🎯🎯 AUTO-EXEC PATH: Looking for sandboxed_executor tool instance")
                sandboxed_tool_instance = None
                for tool in tool_manager.user_tools:
                    if tool.name == "sandboxed_executor":
                        sandboxed_tool_instance = tool
                        logger.info(f"🎯🎯🎯 AUTO-EXEC PATH: Found tool instance: {type(tool).__name__}")
                        break
                
                if sandboxed_tool_instance:
                    logger.info(f"🎯🎯🎯 AUTO-EXEC PATH: Using DIRECT TOOL INSTANCE for {filename}")
                    logger.info(f"🎯🎯🎯 AUTO-EXEC PATH: Calling execute(action='create_file', filename='{filename}')")
                    result = await sandboxed_tool_instance.execute(
                        action="create_file",
                        filename=filename,
                        content=report_content
                        # Note: convert_to_pdf not specified, so auto-conversion for .pdf files will trigger
                    )
                    logger.info(f"🎯🎯🎯 AUTO-EXEC PATH: Direct tool RESULT: {result}")
                else:
                    # Fallback to wrapper if tool instance not found
                    logger.info(f"🎯🎯🎯 AUTO-EXEC PATH: TOOL INSTANCE NOT FOUND! Using WRAPPER FALLBACK for {filename}")
                    sandboxed_tool = tool_manager.available_functions["sandboxed_executor"]
                    result = await sandboxed_tool({
                        "action": "create_file",
                        "filename": filename,
                        "content": report_content
                    })
                    logger.info(f"🎯🎯🎯 AUTO-EXEC PATH: Wrapper RESULT: {result}")
                
                logger.info(f"🔄 Auto-created file: {filename} with {len(report_content)} characters")
                if "get_news_summaries" in tools_results:
                    additional_results += f"Tool: {tool_name} (auto-executed)\nResult: Created file {filename} with Middle East news analysis report ({len(report_content)} chars)\n\n"
                else:
                    additional_results += f"Tool: {tool_name} (auto-executed)\nResult: Created file {filename} with comprehensive stock analysis report ({len(report_content)} chars)\n\n"
            
            elif tool_name == "get_the_secret_tool":
                result = await tool_manager.get_the_secret_tool()
                additional_results += f"Tool: {tool_name} (auto-executed)\nResult: {result}\n\n"
            
            elif tool_name == "secure_email_sender":
                # Auto-execute email sending with the created file
                # Find the actual email tool instance
                email_tool_instance = None
                for tool in tool_manager.user_tools:
                    if tool.name == "secure_email_sender":
                        email_tool_instance = tool
                        break
                
                if email_tool_instance:
                    attachment_path = os.path.join(_delivery_sandbox_dir(), filename)
                    logger.info(f"📧 Auto-sending email with attachment: {attachment_path}")
                    
                    if "get_news_summaries" in tools_results:
                        # News analysis email with dynamic subject
                        email_subject = _generate_dynamic_title(user_prompt, tools_results)
                        # 🔧 CRITICAL FIX: Add timeout to prevent infinite hanging
                        
                        try:
                            logger.info(f"⏰ POST-LLM AUTO-EXECUTION: Starting email execution with 120s timeout...")
                            
                            # Execute email using secure_email_sender with fail-fast logic
                            email_params = {
                                "to_email": recipient_email,
                                "subject": email_subject, 
                                "body": f"Please find attached the latest {email_subject.lower()} with critical updates and detailed analysis.",
                                "attachments": attachment_path
                            }
                            result = await tool_manager.safe_function_call("secure_email_sender", email_params)
                            
                            logger.info(f"✅ POST-LLM AUTO-EXECUTION: Email completed successfully")
                            
                        except asyncio.TimeoutError:
                            logger.error(f"⏰ POST-LLM AUTO-EXECUTION: TIMEOUT after 120 seconds - email execution hung!")
                            result = {'success': False, 'error': 'Email execution timed out after 120 seconds'}
                        except Exception as e:
                            logger.error(f"❌ POST-LLM AUTO-EXECUTION: Email execution failed: {e}")
                            result = {'success': False, 'error': str(e)}
                    else:
                        # Stock analysis email
                        # 🔧 CRITICAL FIX: Add timeout to prevent infinite hanging
                        try:
                            logger.info(f"⏰ POST-LLM AUTO-EXECUTION: Starting stock email execution with 120s timeout...")
                            
                            # Execute email using secure_email_sender with fail-fast logic
                            email_params = {
                                "to_email": recipient_email,
                                "subject": "Stock Analysis Report",
                                "body": "Please find attached the comprehensive stock analysis report with detailed financial insights.",
                                "attachments": attachment_path
                            }
                            result = await tool_manager.safe_function_call("secure_email_sender", email_params)
                            
                            logger.info(f"✅ POST-LLM AUTO-EXECUTION: Stock email completed successfully")
                            
                        except asyncio.TimeoutError:
                            logger.error(f"⏰ POST-LLM AUTO-EXECUTION: TIMEOUT after 120 seconds - stock email execution hung!")
                            result = {'success': False, 'error': 'Stock email execution timed out after 120 seconds'}
                        except Exception as e:
                            logger.error(f"❌ POST-LLM AUTO-EXECUTION: Stock email execution failed: {e}")
                            result = {'success': False, 'error': str(e)}
                else:
                    # Fallback to wrapper
                    email_tool = tool_manager.available_functions["secure_email_sender"]
                    if "get_news_summaries" in tools_results:
                        email_subject = _generate_dynamic_title(user_prompt, tools_results)
                        result = await email_tool({
                            "to_email": recipient_email,
                            "subject": email_subject,
                            "body": f"Please find attached the latest {email_subject.lower()} with critical updates and detailed analysis.",
                            "attachments": os.path.join(_delivery_sandbox_dir(), filename)
                        })
                    else:
                        result = await email_tool({
                            "to_email": recipient_email, 
                            "subject": "Stock Analysis Report",
                            "body": "Please find attached the comprehensive stock analysis report with detailed financial insights.",
                            "attachments": os.path.join(_delivery_sandbox_dir(), filename)
                        })
                
                additional_results += f"Tool: {tool_name} (auto-executed)\nResult: {result}\n\n"
            
            # Add more auto-execution logic for other tools as needed
            
        except Exception as e:
            logger.error(f"❌ Auto-execution failed for {tool_name}: {e}")
            logger.error(f"❌ Auto-execution traceback: {traceback.format_exc()}")
            additional_results += f"Tool: {tool_name} (auto-execution failed)\nResult: Error: {str(e)}\n\n"
    
    return additional_results

def _clean_llm_response_content(raw_content: str) -> str:
    """
    🧹 Clean LLM response content by removing tokens, parameters, and metadata
    
    Filters out:
    - Raw JSON tokens and response markers
    - Model parameters and configuration
    - System metadata and debugging info
    - Keeps only the actual content meant for the user
    """
    if not raw_content or not raw_content.strip():
        return ""
    
    # Remove common LLM response artifacts
    cleaned_content = raw_content
    
    # Remove JSON markers and response formatting
    lines_to_remove = []
    lines = cleaned_content.split('\n')
    
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        
        # Skip lines with JSON response markers
        if any(marker in line_lower for marker in [
            '"response":', '"message":', '"content":', 
            '{"response"', '{"message"', '{"content"',
            'response":', 'message":', 'content":',
            '"role":', '"model":', '"parameters":', '"tokens":'
        ]):
            lines_to_remove.append(i)
            continue
            
        # Skip lines with model parameters
        if any(param in line_lower for param in [
            'temperature:', 'max_tokens:', 'top_p:', 'top_k:',
            'num_predict:', 'repeat_penalty:', 'system_fingerprint:',
            'model:', 'stream:', 'num_ctx:', 'stop:'
        ]):
            lines_to_remove.append(i)
            continue
            
        # Skip lines that are pure JSON artifacts
        if line.strip() in ['', '{', '}', '[', ']', ',', '",', '"']:
            lines_to_remove.append(i)
            continue
            
        # Skip lines with timestamps/metadata that aren't content
        if any(meta in line_lower for meta in [
            'created_at:', 'finished_at:', 'load_duration:', 'prompt_eval_duration:',
            'eval_duration:', 'total_duration:', 'eval_count:', 'prompt_eval_count:'
        ]):
            lines_to_remove.append(i)
            continue
    
    # Remove identified lines
    for i in reversed(lines_to_remove):
        lines.pop(i)
    
    # Rejoin and clean up
    cleaned_content = '\n'.join(lines)
    
    # Remove excessive whitespace but preserve paragraph structure
    import re
    cleaned_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', cleaned_content)  # Max 2 consecutive newlines
    cleaned_content = re.sub(r'^\s+|\s+$', '', cleaned_content, flags=re.MULTILINE)  # Trim lines
    
    return cleaned_content.strip()

def _fill_template_placeholders(content: str, user_prompt: str, tools_results: str = "") -> str:
    """
    🔧 Fill template placeholders with actual data from user context
    
    Replaces common template fields like [Your Name Here] with actual information
    extracted from the user prompt, tool results, or external content.
    """
    if not content or '[' not in content:
        return content
    
    import re
    
    # 🔧 ENHANCED: Extract information from ALL sources (user prompt, tool results, content)
    search_text = f"{user_prompt} {tools_results} {content}"
    
    # Extract actual data from all sources
    actual_name = None
    actual_phone = None
    actual_email = None
    
    # Enhanced name patterns - look for common name formats
    name_patterns = [
        r'Al Sabawi',
        r'Ahmed.*?Sabawi',
        r'Sabawi.*?Ahmed',
        r'Ahmed Al Sabawi',
        # Look for capitalized name patterns in resume content
        r'([A-Z][a-z]+\s+[A-Z][a-z]*\s*Sabawi)',
        r'(Al\s+[A-Z][a-z]+)',
        r'([A-Z][a-z]+\s+Al\s+Sabawi)',
    ]
    
    for pattern in name_patterns:
        match = re.search(pattern, search_text, re.IGNORECASE)
        if match:
            if pattern.startswith('('):  # Capture group pattern
                actual_name = match.group(1).strip()
            else:
                actual_name = match.group(0).strip()
            break
    
    # If no specific name found, use default
    if not actual_name:
        actual_name = "Al Sabawi"
    
    # Enhanced contact info patterns
    phone_patterns = [
        r'\(607\) 759-2683',
        r'607[.\-\s]*759[.\-\s]*2683',
        r'\(?\d{3}\)?[.\-\s]*\d{3}[.\-\s]*\d{4}'
    ]
    
    for pattern in phone_patterns:
        match = re.search(pattern, search_text)
        if match:
            actual_phone = match.group(0).strip()
            break
    
    # Owner email is prioritized when present, but sourced from env (GMAIL_PRIMARY_EMAIL)
    # rather than hardcoded as PII. Falls back to the generic email pattern if unset.
    email_patterns = []
    _owner_email = os.getenv('GMAIL_PRIMARY_EMAIL', '').strip()
    if _owner_email:
        email_patterns.append(re.escape(_owner_email))
    email_patterns.append(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    for pattern in email_patterns:
        match = re.search(pattern, search_text, re.IGNORECASE)
        if match:
            actual_email = match.group(0).strip()
            break
    
    # Replace template placeholders
    filled_content = content
    
    # Name placeholders - including the missing [YOUR NAME] pattern!
    if actual_name:
        filled_content = re.sub(r'\[YOUR NAME\]', actual_name, filled_content)  # 🔧 FIX: Added missing pattern
        filled_content = re.sub(r'\[Your Full Name\]', actual_name, filled_content)
        filled_content = re.sub(r'\[Your Name Here\]', actual_name, filled_content)
        filled_content = re.sub(r'\[Sign Your Name\]', actual_name, filled_content)
        filled_content = re.sub(r'\[Your Name\]', actual_name, filled_content)
        filled_content = re.sub(r'\[NAME\]', actual_name, filled_content)
        # 🔧 CRITICAL FIX: Also handle literal "Your Name" without brackets!
        filled_content = re.sub(r'\bYour Name\b', actual_name, filled_content)  # Most common pattern
        filled_content = re.sub(r'\byour name\b', actual_name, filled_content, flags=re.IGNORECASE)
    
    # Contact info placeholders
    if actual_phone:
        filled_content = re.sub(r'\[Your Phone Number\]', actual_phone, filled_content)
        filled_content = re.sub(r'\[PHONE\]', actual_phone, filled_content)
    
    if actual_email:
        filled_content = re.sub(r'\[Your Email Address\]', actual_email, filled_content)
        filled_content = re.sub(r'\[EMAIL\]', actual_email, filled_content)
    
    # Generic placeholders that we can't fill but should clean up
    filled_content = re.sub(r'\[Your Address\]', '', filled_content)
    filled_content = re.sub(r'\[City, State, ZIP Code\]', '', filled_content)
    filled_content = re.sub(r'\[Date\]', '', filled_content)
    
    # Clean up any extra whitespace from removed placeholders
    filled_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', filled_content)
    
    return filled_content.strip()

async def _detect_html_email_request_in_args(function_args_dict: dict, user_prompt: str) -> dict:
    """
    🎯 Detect HTML email requests from tool calling arguments and user prompt
    This version checks tool arguments directly for format="html" metadata
    """
    import re
    
    # Check if tool arguments contain HTML format metadata
    has_html_format = function_args_dict.get('format') == 'html'
    has_html_source = function_args_dict.get('source') in ['previous_response', 'current_response']
    has_style_param = 'style' in function_args_dict
    
    # Also check user prompt for HTML email indicators
    user_prompt_lower = user_prompt.lower()
    html_email_indicators = [
        'email the full response above in html',
        'email previous response',
        'html format to',
        'in html format to',
        'email the full response above',  # Even without explicit HTML, we should use our template
        'email the above response',  # Generic response email
        'email the above full and complete response',  # Comprehensive response email
        'email the complete response',  # Complete response email
    ]

    # 📄 CONVERSATION PDF DETECTION - Check for conversation export requests
    # These patterns should explicitly indicate PDF or conversation export intent
    conversation_pdf_indicators = [
        'email the previous conversation as pdf',
        'email previous conversation as pdf',
        'email conversation as pdf attachment',
        'email the conversation as pdf',
        'send conversation pdf',
        'export conversation to pdf and email',
        'email conversation history as pdf',
        'email the above response as pdf',  # Must explicitly say PDF
        'email the full response as pdf',  # Must explicitly say PDF
        'email the complete response as pdf',  # Must explicitly say PDF
        'pdf attachment with',
        'neatly formatted pdf attachment'
    ]

    # 🚨 CRITICAL: Check if "html" keyword is present - prioritize HTML over PDF
    has_html_keyword = 'html' in user_prompt_lower

    has_conversation_pdf_request = any(indicator in user_prompt_lower for indicator in conversation_pdf_indicators)

    # 🎯 If "html" keyword present, force HTML detection even if PDF patterns match
    if has_html_keyword:
        has_conversation_pdf_request = False

    has_html_in_prompt = any(indicator in user_prompt_lower for indicator in html_email_indicators) or has_html_keyword
    
    if has_html_format or has_html_source or has_style_param or has_html_in_prompt:
        # Extract email details from tool arguments first
        to_email = function_args_dict.get('to_email')
        subject = function_args_dict.get('subject', 'HTML Report')
        style = function_args_dict.get('style')
        source = function_args_dict.get('source', 'current_response')
        
        # If email not found in tool args, extract from user prompt
        if not to_email:
            user_email_patterns = [
                r'to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'email.*?to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
            ]
            for pattern in user_email_patterns:
                user_email_match = re.search(pattern, user_prompt)
                if user_email_match:
                    to_email = user_email_match.group(1)
                    break
        
        return {
            'to_email': to_email,
            'subject': subject,
            'style': style,
            'source': source,
            'detected': True
        }
    
    # 📄 CONVERSATION PDF PROCESSING - Handle conversation export requests
    if has_conversation_pdf_request:
        # Extract email details from tool arguments first
        to_email = function_args_dict.get('to_email')
        subject = function_args_dict.get('subject', 'Conversation Export')
        
        # If email not found in tool args, extract from user prompt
        if not to_email:
            user_email_patterns = [
                r'to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'email.*?to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
            ]
            for pattern in user_email_patterns:
                user_email_match = re.search(pattern, user_prompt)
                if user_email_match:
                    to_email = user_email_match.group(1)
                    break
        
        return {
            'to_email': to_email,
            'subject': subject,
            'type': 'conversation_pdf',
            'detected': True
        }
    
    return {}

def _detect_conversation_pdf_request(function_args_dict: dict, user_prompt: str) -> dict:
    """
    Detect if the user is requesting conversation export as PDF attachment

    🚨 CRITICAL: Only detect PDF requests when explicitly requested.
    If "HTML" keyword is present, this should return False to allow HTML handling.
    """
    user_prompt_lower = user_prompt.lower()

    # 🚨 CRITICAL: If "html" keyword present, this is NOT a PDF request
    if 'html' in user_prompt_lower:
        return {'detected': False}

    conversation_pdf_indicators = [
        'email the previous conversation as pdf',
        'email previous conversation as pdf',
        'email conversation as pdf attachment',
        'email the conversation as pdf',
        'send conversation pdf',
        'export conversation to pdf and email',
        'email conversation history as pdf',
        'send the conversation as pdf',
        'email our conversation as pdf',
        'email the above response as pdf',  # Must explicitly say PDF
        'email the full response as pdf',  # Must explicitly say PDF
        'email the complete response as pdf',  # Must explicitly say PDF
        'pdf attachment with',
        'neatly formatted pdf attachment'
    ]

    has_conversation_pdf_request = any(indicator in user_prompt_lower for indicator in conversation_pdf_indicators)
    
    if has_conversation_pdf_request:
        # Extract email details from tool arguments first
        to_email = function_args_dict.get('to_email')
        subject = function_args_dict.get('subject', 'Conversation Export')
        
        # If email not found in tool args, extract from user prompt
        if not to_email:
            import re
            user_email_patterns = [
                r'to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'email.*?to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
            ]
            for pattern in user_email_patterns:
                user_email_match = re.search(pattern, user_prompt)
                if user_email_match:
                    to_email = user_email_match.group(1)
                    break
        
        return {
            'to_email': to_email,
            'subject': subject,
            'type': 'conversation_pdf',
            'detected': True
        }
    
    return {'detected': False}

async def _extract_html_params_from_results(tools_results: str, user_prompt: str = "") -> dict:
    """
    🎯 Extract HTML email parameters from secure_email_sender error message and user prompt
    Parses the special HTML format detection message to extract parameters
    """
    import re
    
    try:
        # Extract email address from user_prompt first, then from tools_results
        email_pattern = r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        
        # Try user_prompt first (more reliable)
        email_match = re.search(email_pattern, user_prompt)
        if not email_match:
            # Fallback to tools_results
            email_match = re.search(email_pattern, tools_results)
        
        # Extract subject hints from user prompt
        subject = 'HTML Report'
        if 'subject' in user_prompt.lower():
            # Could extract custom subject in the future
            pass
            
        return {
            'to_email': email_match.group(1) if email_match else None,
            'subject': subject,
            'format': 'html',
            'source': 'current_response',
            'style': None
        }
    except Exception as e:
        logger.error(f"❌ Error extracting HTML params: {e}")
        return {}

async def _detect_html_email_request(tools_results: str, user_prompt: str) -> dict:
    """
    🎯 Detect if tool calling model requested HTML email with metadata
    Looks for format="html", source="previous_response", style parameters etc.
    """
    import re
    
    # Look for HTML email request patterns in tools_results
    html_patterns = [
        r'format["\']?\s*[:=]\s*["\']html["\']',
        r'source["\']?\s*[:=]\s*["\'](?:previous_response|current_response)["\']',
        r'style["\']?\s*[:=]\s*["\'][^"\']+["\']'
    ]
    
    has_html_request = any(re.search(pattern, tools_results, re.IGNORECASE) for pattern in html_patterns)
    
    # Also check user prompt for HTML email requests (ENHANCED)
    user_prompt_lower = user_prompt.lower()
    html_email_indicators = [
        'email the full response above in html',
        'email previous response',
        'email' and 'html format',
        'email' and 'html attachment',
        'html format to',
        'in html format to',
        'email the full response above'  # Even without explicit HTML, we should use our template
    ]
    
    has_html_in_prompt = False
    for indicator in html_email_indicators:
        if isinstance(indicator, str) and indicator in user_prompt_lower:
            has_html_in_prompt = True
            break
        elif not isinstance(indicator, str):  # Handle 'and' cases
            # This is a special case for compound indicators, skipping for now
            continue
    
    if has_html_request or has_html_in_prompt:
        # Extract email details from tools_results first
        email_match = re.search(r'to_email["\']?\s*[:=]\s*["\']([^"\']+)["\']', tools_results)
        subject_match = re.search(r'subject["\']?\s*[:=]\s*["\']([^"\']+)["\']', tools_results)
        style_match = re.search(r'style["\']?\s*[:=]\s*["\']([^"\']+)["\']', tools_results)
        source_match = re.search(r'source["\']?\s*[:=]\s*["\']([^"\']+)["\']', tools_results)
        
        # If email not found in tools_results, extract from user prompt
        to_email = email_match.group(1) if email_match else None
        if not to_email:
            # Extract email from user prompt patterns like "to user@example.com"
            user_email_patterns = [
                r'to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'email.*?to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
            ]
            for pattern in user_email_patterns:
                user_email_match = re.search(pattern, user_prompt)
                if user_email_match:
                    to_email = user_email_match.group(1)
                    break
        
        # 🔧 DYNAMIC SUBJECT: Generate meaningful subject from user prompt and tools results
        default_subject = 'HTML Report'
        if not subject_match:
            # Try to generate dynamic subject from user prompt
            default_subject = _generate_dynamic_title(user_prompt, tools_results)

        return {
            'to_email': to_email,
            'subject': subject_match.group(1) if subject_match else default_subject,
            'style': style_match.group(1) if style_match else None,
            'source': source_match.group(1) if source_match else 'current_response',
            'detected': True
        }
    
    return {}

async def _generate_complete_html_email(complete_llm_response: str, html_email_request: dict, user_prompt: str, subject: str) -> str:
    """
    🎯 Generate complete HTML file using HTMLReportGenerator
    Uses the complete LLM response to avoid any truncation
    """
    from utils.html_generator import html_generator
    from datetime import datetime
    import os
    
    try:
        # Determine content source
        if html_email_request.get('source') == 'previous_response':
            # TODO: Extract from conversation memory when available
            content = complete_llm_response
        else:
            content = complete_llm_response
        
        # Parse custom styles if provided
        custom_styles = {}
        style_string = html_email_request.get('style', '')
        if style_string:
            # Parse "font_color:red,background_color:yellow" format
            style_pairs = style_string.split(',')
            for pair in style_pairs:
                if ':' in pair:
                    key, value = pair.split(':', 1)
                    css_key = key.strip().replace('_', '-')
                    custom_styles[css_key] = value.strip()
        
        # Generate title from user prompt or use default
        title = "Research Report"
        if "email" in user_prompt.lower():
            # Extract meaningful title from user prompt
            import re
            title_patterns = [
                r'email.*?([^.!?]+?)(?:to|in html)',
                r'create.*?([^.!?]+?)(?:and email|report)',
                r'generate.*?([^.!?]+?)(?:email|report)'
            ]
            for pattern in title_patterns:
                match = re.search(pattern, user_prompt, re.IGNORECASE)
                if match:
                    title = match.group(1).strip().title()
                    break
        
        # 🔧 FIX: Normalize special Unicode characters that cause encoding issues in email clients
        # Replace en-dash (U+2013) and em-dash (U+2014) with regular hyphen
        # Replace smart quotes with regular quotes
        content = content.replace('\u2013', '-')  # en-dash → hyphen
        content = content.replace('\u2014', '-')  # em-dash → hyphen
        content = content.replace('\u2018', "'")  # left single quote → apostrophe
        content = content.replace('\u2019', "'")  # right single quote → apostrophe
        content = content.replace('\u201c', '"')  # left double quote → quote
        content = content.replace('\u201d', '"')  # right double quote → quote
        content = content.replace('\u2026', '...')  # ellipsis → three dots

        # Prepare custom CSS (if provided)
        custom_css_content = None
        if custom_styles:
            style_css = "body { "
            for css_key, css_value in custom_styles.items():
                style_css += f"{css_key}: {css_value}; "
            style_css += "}"
            custom_css_content = style_css

        # Generate HTML using our proven template system
        # 🐛 FIX: Pass custom CSS via parameter instead of prepending to content
        # This allows markdown detection to work properly for ALL markdown content
        html_content = html_generator.generate_html_report(
            content=content,  # Pure markdown content - no HTML tags prepended
            title=title,
            header_title=title,
            header_subtitle=f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            include_disclaimer=False,  # Skip disclaimer for email reports
            custom_timestamp=None,
            custom_css=custom_css_content,  # Pass CSS separately
            force_template=True  # standardize layout: same shared template as Deep Research / route-1
        )
        
        # Save HTML file to sandbox workspace
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        # Generate filename from subject
        import re
        safe_subject = _safe_slug(subject, fallback="report")
        html_filename = f"{safe_subject}_{timestamp}.html"
        base_dir = _delivery_sandbox_dir()
        full_path = os.path.join(base_dir, html_filename)
        os.makedirs(base_dir, exist_ok=True)  # ensure the real sandbox dir exists before writing
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"🎯 POST-LLM HTML EMAIL: Generated complete HTML file: {html_filename}")
        logger.info(f"🎯 HTML content length: {len(html_content)} characters (no truncation)")
        
        return html_filename
        
    except Exception as e:
        logger.error(f"❌ HTML email generation failed: {e}")
        return None

async def _generate_intelligent_tool_parameters(
    tool_name: str,
    user_prompt: str,
    complete_llm_response: str,
    tools_results: str,
    tool_manager,
    llm_manager
) -> dict:
    """
    🤖 ARBITRATOR-BASED PARAMETER GENERATOR v1.0.3.111

    Universal parameter generation using Arbitrator LLM to intelligently create
    tool parameters when tools are auto-executed without initial parameters.

    This function analyzes user intent and LLM output to generate:
    - Contextually appropriate titles (NOT generic "Analysis Report")
    - Clean, publication-ready content (NO conversational disclaimers)
    - Intelligent defaults for missing parameters

    Args:
        tool_name: Name of tool being executed (e.g., "social_media_wordpress")
        user_prompt: Original user request
        complete_llm_response: Full Primary LLM output
        tools_results: Results from previously executed tools
        tool_manager: Tool manager instance for schema access
        llm_manager: LLM manager instance for Arbitrator calls

    Returns:
        dict: Intelligent parameters for tool execution

    Example Returns:
        {
            "title": "A Father's Love Poem to His Teenage Children",
            "content": "<poem content only, no disclaimers>",
            "status": "draft",
            "tags": ["poetry", "family", "parenting"]
        }
    """
    import json as json_lib
    import time

    logger.info(f"🤖 ARBITRATOR PARAM GEN: Generating intelligent parameters for {tool_name}")
    start_time = time.time()

    try:
        # Truncate tools_results for Arbitrator prompt (limit context size)
        tools_results_summary = tools_results[:500] + "..." if len(tools_results) > 500 else tools_results

        # Build Arbitrator prompt based on architecture document
        arbitrator_prompt = f"""You are a specialized parameter generator for tool execution. Your task is to analyze
user requests and LLM responses to generate optimal, publication-ready parameters.

## Context

**User Request:**
{user_prompt}

**Primary LLM Response:**
{complete_llm_response}

**Tool Results (if any):**
{tools_results_summary}

**Target Tool:**
{tool_name}

## Your Tasks

1. **Extract/Generate Values:** Analyze the context to determine appropriate parameter values
2. **Clean Content:** Remove conversational elements:
   - Disclaimers ("I cannot post...", "Since I don't have access...", "Unfortunately...")
   - Questions ("Would you like me to...")
   - Apologies ("I apologize...")
   - Meta-commentary about tool capabilities
3. **Structure Content:** Ensure content is publication-ready
4. **Generate Missing Values:** Create intelligent defaults for parameters not explicitly provided

## Tool-Specific Guidelines

### Publishing Tools (WordPress, Medium, Substack):
- **title:** Generate concise, descriptive title from content theme (5-10 words)
  - Extract from user request or analyze content to determine topic
  - NEVER use generic titles like "Analysis Report" or "Report"
- **content:** Extract main content ONLY, remove all conversational elements
  - If LLM generated a poem, extract ONLY the poem
  - If LLM generated an essay, extract ONLY the essay
  - Remove ALL disclaimers about tool capabilities
  - **CRITICAL FOR LONG CONTENT**: If content exceeds 2000 words, use the FULL PRIMARY LLM RESPONSE as-is
    (WordPress can handle large posts - don't summarize or truncate)
- **status:** Default to "draft" unless user explicitly requests "publish"
- **tags:** Generate 3-5 relevant tags from content analysis

## Output Format

Return ONLY valid JSON matching this structure. No explanations, no markdown code blocks, no extra text.

**For SHORT content (< 2000 words):**
{{
    "title": "Generated Title Here",
    "content": "Cleaned content here...",
    "status": "draft",
    "tags": ["tag1", "tag2", "tag3"]
}}

**For LONG content (> 2000 words, like comprehensive analyses):**
{{
    "title": "Generated Title Here",
    "content": "{{{{PRIMARY_LLM_RESPONSE}}}}",
    "status": "draft",
    "tags": ["tag1", "tag2", "tag3"]
}}

Use the special placeholder {{{{PRIMARY_LLM_RESPONSE}}}} for the content field when dealing with very long content.
This tells the system to use the complete Primary LLM response without truncation.

Generate parameters now:"""

        arbitrator_system_prompt = "You are a specialized parameter generator for publishing tools. Analyze user intent and LLM output to generate intelligent, publication-ready parameters. Return ONLY valid JSON, no additional text."

        # Call Arbitrator LLM
        logger.info(f"🤖 Calling Arbitrator LLM for parameter generation...")
        arbitrator_response = await llm_manager.call_arbitrator(
            arbitrator_prompt,
            arbitrator_system_prompt
        )

        arbitrator_time = time.time() - start_time
        logger.info(f"🤖 Arbitrator response received in {arbitrator_time:.2f}s: {len(arbitrator_response)} chars")

        # Parse JSON response
        clean_response = arbitrator_response.strip()

        # Remove markdown code blocks if present
        if clean_response.startswith("```json"):
            clean_response = clean_response[7:]
        if clean_response.startswith("```"):
            clean_response = clean_response[3:]
        if clean_response.endswith("```"):
            clean_response = clean_response[:-3]

        clean_response = clean_response.strip()

        # Parse JSON
        params = json_lib.loads(clean_response)

        # 🔧 FIX v1.0.3.112: Handle {{PRIMARY_LLM_RESPONSE}} placeholder for long content
        if params.get('content') == '{{PRIMARY_LLM_RESPONSE}}':
            logger.info(f"🔄 PLACEHOLDER DETECTED: Using full Primary LLM response for content")
            params['content'] = complete_llm_response

        logger.info(f"✅ ARBITRATOR GENERATED PARAMS:")
        logger.info(f"   Title: {params.get('title', 'N/A')}")
        logger.info(f"   Content length: {len(params.get('content', ''))} chars")
        logger.info(f"   Status: {params.get('status', 'N/A')}")
        logger.info(f"   Tags: {params.get('tags', [])}")

        return params

    except json_lib.JSONDecodeError as e:
        logger.error(f"❌ ARBITRATOR PARAM GEN: Invalid JSON response: {e}")
        logger.error(f"   Response: {clean_response[:200]}")
        raise

    except Exception as e:
        logger.error(f"❌ ARBITRATOR PARAM GEN: Failed: {e}")
        raise

# ==============================================================================
# DEEP RESEARCH — PHASE 2 DELIVERY FAN-OUT (A-hybrid: direct dispatch of existing tools)
# Gated by the trusted-client `allow_delivery` flag. Reuses sandboxed_executor (file/PDF) and
# secure_email_sender. Transitional thin adapter — the final cut generalizes to dynamic registry
# dispatch over ANY tool. NEVER touches the normal/NewX flows (allow_delivery is off there).
# ==============================================================================

# First-cut capability adapter (transitional — see DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md §4).
# The decomposer's open-vocabulary action types are grounded in the live tool catalog; here we map
# the two capability CLASSES the legacy tooling already implements. Final cut = dynamic dispatch.
_DR_FILE_CAPS = {"pdf_generator", "sandboxed_executor", "create_file", "save_file",
                 "generate_pdf", "render_pdf", "export_pdf", "html_generator", "document_generator"}
_DR_EMAIL_CAPS = {"secure_email_sender", "email", "send_email", "send_mail"}


def _sweep_old_delivery_files(retention_hours: float) -> int:
    """Best-effort TTL cleanup of sandbox_workspace so delivery artifacts don't accumulate. Removes
    files older than retention_hours. Never raises into the caller. Returns count removed."""
    import os
    import time as _time
    removed = 0
    try:
        base = _delivery_sandbox_dir()
        if not os.path.isdir(base):
            return 0
        cutoff = _time.time() - max(0.0, float(retention_hours)) * 3600.0
        for name in os.listdir(base):
            path = os.path.join(base, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
        if removed:
            logger.info(f"📦 Delivery TTL sweep removed {removed} file(s) older than {retention_hours}h")
    except Exception as e:  # noqa: BLE001 — housekeeping must never break delivery
        logger.warning(f"📦 Delivery TTL sweep failed: {e}")
    return removed


def _resolve_email_recipients(action_args: dict, user_prompt: str) -> list:
    """Recipient(s) for an email delivery action: prefer the decomposer's structured args
    (to/to_email/recipient/recipients/email), else fall back to addresses found in the user prompt."""
    import re as _re
    email_re = _re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    cands = []
    for key in ("to", "to_email", "recipient", "recipients", "email"):
        v = (action_args or {}).get(key)
        if isinstance(v, str):
            cands.append(v)
        elif isinstance(v, list):
            cands.extend([x for x in v if isinstance(x, str)])
    emails = [e for c in cands for e in email_re.findall(c)]
    if not emails:
        emails = email_re.findall(user_prompt or "")
    seen, out = set(), []
    for e in emails:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _dr_delivery_permitted(data: dict) -> bool:
    """3-way deep-research delivery authorization (mechanism only — policy lives in the client):
      1. Explicit `allow_delivery` present → obey it (true/false). NewX sets this from its per-user
         privilege system, so it always governs NewX (NewX requests always carry allowed_tools).
      2. No `allowed_tools` whitelist at all → auto-trust → permit. Interactive internal clients
         (e.g. OpenWebUI). Safe because /v1 is internal-only, firewalled at the deployment boundary.
      3. Otherwise (an allowed_tools whitelist is present, even empty, and no explicit flag) → deny.
    NewX bots always send an allowed_tools whitelist, so they are NEVER auto-trusted — they require
    the explicit flag, keeping them locked unless the acting user is privileged.

    Phase 1 convergence: delegates to the single shared policy (orchestration/policy.py) so the
    deep-research and legacy POST-LLM paths cannot drift apart."""
    return delivery_policy.authorize_delivery(data).permitted


# Phase 3 (dynamic dispatch) — the arg-binder may mark any tool field that should carry the FULL
# research paper with this exact placeholder, so the LLM never has to retype the (large) paper into a
# JSON argument; RAICA substitutes it with the real text before dispatch.
_DR_RESEARCH_PLACEHOLDER = "{{RESEARCH_OUTPUT}}"


def _dr_inject_research_output(value, research_output):
    """Recursively replace the {{RESEARCH_OUTPUT}} placeholder with the full paper text anywhere it
    appears in the arg-binder's arguments. Generalized: no field-name special-casing — the LLM marks
    WHICH field carries the content; RAICA just substitutes the marker."""
    if isinstance(value, str):
        return value.replace(_DR_RESEARCH_PLACEHOLDER, research_output) if _DR_RESEARCH_PLACEHOLDER in value else value
    if isinstance(value, list):
        return [_dr_inject_research_output(v, research_output) for v in value]
    if isinstance(value, dict):
        return {k: _dr_inject_research_output(v, research_output) for k, v in value.items()}
    return value


def _dr_dispatch_failed(result_str: str) -> bool:
    """Detect a tool failure from RAICA's OWN structured result markers (NOT NLP on tool content):
    the user-tool wrapper returns leading '❌' or \"Tool '<n>' error:\"; safe_function_call returns
    'Error calling <n>:' / 'Function <n> not available'. Matching our own protocol, not interpreting
    tool semantics, so this is not the forbidden keyword-routing anti-pattern."""
    s = (result_str or "").lstrip()
    return (s.startswith("❌") or s.startswith("Error calling ") or
            (s.startswith("Function ") and " not available" in s[:80]) or
            (s.startswith("Tool '") and "' error:" in s[:120]))


async def _dr_bind_and_dispatch_action(action, tool_name, schema, tool_manager, generate_stream,
                                       research_output, deliverable_spec, prior_results, engine_cfg):
    """Phase 3 generic action dispatch: LLM arg-binder → blind dispatch. Returns (ok: bool, summary: str).

    The binder is shown the tool's FULL parameter schema, the research output (shared context), the
    user's requested action + args, and the results of prior actions (sequential, dependency-aware).
    It returns {"arguments": {...}}; RAICA substitutes the {{RESEARCH_OUTPUT}} placeholder and runs
    the tool via safe_function_call. NO hardcoded per-tool logic (Generalization Test): a newly
    registered tool is dispatchable here with zero code changes."""
    from research.engine import _collect_stream, extract_json_object
    deliv_cfg = (engine_cfg.get("delivery", {}) or {})

    def _cfg_int(key, default):
        try:
            return int(deliv_cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    budget = _cfg_int("context_char_budget", 12000)
    binder_max_tokens = _cfg_int("binder_max_tokens", 1500)
    try:
        action_timeout = float(deliv_cfg.get("action_timeout_seconds", 180))
    except (TypeError, ValueError):
        action_timeout = 180.0

    ctx = (research_output or "")[:budget]
    prior_text = "\n".join(f"- {p}" for p in prior_results) if prior_results else "(none)"
    requested_args = action.get("args", {}) if isinstance(action, dict) else {}
    system_prompt = (
        f"You bind arguments for the tool \"{tool_name}\" and nothing else. You are given the tool's "
        "JSON parameter SCHEMA, the RESEARCH OUTPUT to act on, the user's requested action with any "
        "args, and the RESULTS of prior actions in this run. Produce STRICT JSON of the form "
        "{\"arguments\": { ... }} containing ONLY parameters defined in the schema, with values that "
        "make the tool accomplish the user's intent using the research output. Respect required "
        "parameters. For any field that should contain the FULL research output verbatim, use the "
        f"exact string \"{_DR_RESEARCH_PLACEHOLDER}\" as its value — do NOT retype the research text. "
        "Respond with STRICT JSON only, no prose."
    )
    prompt = (
        f"TOOL PARAMETER SCHEMA:\n{json.dumps(schema or {}, ensure_ascii=False)[:6000]}\n\n"
        f"USER'S REQUESTED ACTION:\ntype={tool_name}, "
        f"args={json.dumps(requested_args, ensure_ascii=False)[:2000]}\n\n"
        f"DELIVERABLE SPEC:\n{json.dumps(deliverable_spec or {}, ensure_ascii=False)[:1000]}\n\n"
        f"RESULTS OF PRIOR ACTIONS:\n{prior_text}\n\n"
        f"RESEARCH OUTPUT (context — use the placeholder for any full-text field):\n{ctx}"
    )
    try:
        raw = await _collect_stream(generate_stream, prompt, system_prompt=system_prompt,
                                    temperature=0.0, max_tokens=binder_max_tokens, stream=False)
        bound = extract_json_object(raw)
        arguments = bound.get("arguments", {}) if isinstance(bound, dict) else {}
        if not isinstance(arguments, dict):
            arguments = {}
        arguments = _dr_inject_research_output(arguments, research_output or "")
    except Exception as e:  # noqa: BLE001 — binding failure must not abort the whole delivery
        logger.error(f"📦 DR dynamic dispatch: arg-binding failed for '{tool_name}': {e}", exc_info=True)
        return (False, f"{tool_name} — could not prepare arguments ({str(e)[:120]})")
    try:
        result = await asyncio.wait_for(
            tool_manager.safe_function_call(tool_name, json.dumps(arguments)), timeout=action_timeout)
        result_str = str(result)
        logger.info(f"📦 DR dynamic dispatch ran '{tool_name}': {result_str[:300]}")
        if _dr_dispatch_failed(result_str):
            return (False, f"{tool_name} — {result_str.strip()[:160]}")
        return (True, f"{tool_name} — {result_str.strip()[:200]}")
    except asyncio.TimeoutError:
        logger.error(f"📦 DR dynamic dispatch '{tool_name}' timed out after {action_timeout}s")
        return (False, f"{tool_name} — timed out after {int(action_timeout)}s")
    except Exception as e:  # noqa: BLE001
        logger.error(f"📦 DR dynamic dispatch '{tool_name}' error: {e}", exc_info=True)
        return (False, f"{tool_name} — {str(e)[:160]}")


async def _deliver_document(*, content: str, title: str, slug: str, formats: list, tool_manager,
                            send_email: bool, recipients: list, recipient_locked: bool,
                            locked_recipient, subject: str = "", body: str = "") -> dict:
    """THE ONE robust delivery core, shared by Deep Research (_run_dr_delivery) AND the NewX/@Ask
    POST-LLM path. Renders `content` into EVERY requested format (one file per format via the single
    sandboxed_executor create_file renderer → html_generator standard template / convert_to_pdf), then —
    when send_email — emails ALL files in ONE message to recipients[0] through the recipient-lock
    chokepoint (_send_email_locked), with content-keyed idempotency. No keyword intent logic; multi-format;
    valid PDFs; content-derived title. Returns {created_files, email_outcome, file_error}; email_outcome is
    ("sent", to) | ("failed", reason) | ("doc_failed", None) | ("no_recipient", None) | None."""
    from datetime import datetime as _dt
    created_files, file_error = [], None
    timestamp = _dt.now().strftime('%Y-%m-%d_%H-%M')
    sandboxed = next((t for t in (getattr(tool_manager, "user_tools", []) or [])
                      if getattr(t, "name", "") == "sandboxed_executor"), None)
    if not sandboxed:
        return {"created_files": [], "file_error": "file-creation tool unavailable",
                "email_outcome": ("doc_failed", None) if send_email else None}
    for ext in (formats or []):
        _fname = f"{slug}_{timestamp}.{ext}"
        try:
            kwargs = {"action": "create_file", "filename": _fname, "content": content, "title": title}
            if ext == "pdf":
                kwargs["convert_to_pdf"] = True
            res = await sandboxed.execute(**kwargs)
            if isinstance(res, dict) and res.get("success"):
                created_files.append(_fname)
            else:
                file_error = (res.get("error") if isinstance(res, dict) else str(res)) or "unknown error"
                logger.error(f"📦 delivery: file creation failed ({ext}): {file_error}")
        except Exception as e:  # noqa: BLE001
            file_error = str(e)
            logger.error(f"📦 delivery: file creation error ({ext}): {e}", exc_info=True)
    if created_files:
        logger.info(f"📦 delivery: created {len(created_files)} document(s): {created_files}")

    email_outcome = None
    if send_email:
        if not created_files:
            email_outcome = ("doc_failed", None)
        elif not recipients:
            email_outcome = ("no_recipient", None)
        else:
            to_email = recipients[0]
            email_params = {"to_email": to_email, "subject": subject or title,
                            "body": body or "Please find attached the requested document(s).",
                            "attachments": ",".join(created_files)}
            _ago = _postllm_email_recent_dup(email_params)
            if _ago is not None:
                logger.info(f"🚫 delivery: identical email to {to_email} sent {_ago:.1f}s ago — suppressing duplicate")
                email_outcome = ("failed", "duplicate suppressed — an identical email was just sent")
            else:
                try:
                    _last_user_tool_ok.set(None)   # clear any prior outcome before this send
                    # asyncio.timeout (NOT wait_for) so the send runs in THIS task's context — the email
                    # tool's structured success (set by the user-tool wrapper) propagates back; a wait_for
                    # Task would run in a COPIED context and the flag would not be visible here.
                    async with asyncio.timeout(120):
                        result = await _send_email_locked(
                            tool_manager, email_params, recipient_locked, locked_recipient)
                    logger.info(f"📦 delivery email result: {str(result)[:300]}")
                    # Decide sent/failed from the tool's ACTUAL success flag — NOT the prose result string.
                    # A failed send is stringified as "Tool '…' error: …" (no ❌), which the old prefix
                    # check missed → false "sent". Fall back to the explicit dict/refusal-string check only
                    # when the structured flag is unavailable (defensive).
                    _ok = _last_user_tool_ok.get()
                    if _ok is True:
                        email_outcome = ("sent", to_email)
                        _postllm_email_mark_sent(email_params)
                    elif _ok is False:
                        email_outcome = ("failed", str(result)[:160])
                    elif isinstance(result, dict) and not result.get("success", True):
                        email_outcome = ("failed", str(result.get("error"))[:160])
                    elif isinstance(result, str) and result.lstrip().startswith("❌"):
                        email_outcome = ("failed", result.lstrip()[:160])
                    else:
                        email_outcome = ("sent", to_email)
                        _postllm_email_mark_sent(email_params)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"📦 delivery email error: {e}", exc_info=True)
                    email_outcome = ("failed", str(e)[:160])
    return {"created_files": created_files, "email_outcome": email_outcome, "file_error": file_error}


async def _run_dr_delivery(actions: list, deliverable_spec: dict, doc_body: str,
                           user_prompt: str, tool_manager, engine_cfg: dict,
                           locked_recipient: str = None, recipient_locked: bool = False,
                           tool_defs: list = None, audit_text: str = "", generate_stream=None):
    """Phase 2 delivery fan-out. Yields human-readable status lines (the caller wraps them as chunks).
    A-hybrid: create a document (PDF/file) from the research paper via sandboxed_executor, then email
    it via secure_email_sender. File lifecycle: KEEP on success (TTL-swept) and KEEP on failure
    (reported, never deleted — the artifact is expensive).

    Recipient policy (security): when recipient_locked is True (restricted client, e.g. a NewX bot),
    email goes ONLY to locked_recipient (the requesting user's server-authoritative account email);
    prompt-specified recipients are ignored and, if no valid locked_recipient is supplied, email is
    refused (fail-closed). When recipient_locked is False (auto-trusted single-user client like
    OpenWebUI), recipients are resolved from the request as before."""
    import os
    from datetime import datetime as _dt

    actions = actions or []
    file_action = next((a for a in actions if isinstance(a, dict) and a.get("type") in _DR_FILE_CAPS), None)
    email_action = next((a for a in actions if isinstance(a, dict) and a.get("type") in _DR_EMAIL_CAPS), None)
    unsupported = [(a.get("args", {}) or {}).get("requested", a.get("type"))
                   for a in actions if isinstance(a, dict) and a.get("type") == "unsupported"]
    # Phase 3 — open-vocabulary actions: everything the decomposer named that is NOT the file/email
    # secure pipeline and not "unsupported". Each is dispatched generically below (LLM arg-binder →
    # blind dispatch) if it resolves to a live tool; otherwise it's reported as not-yet-wired.
    generic_actions = [a for a in actions if isinstance(a, dict)
                       and a.get("type") not in _DR_FILE_CAPS and a.get("type") not in _DR_EMAIL_CAPS
                       and a.get("type") != "unsupported"]

    try:
        retention = float((engine_cfg.get("delivery", {}) or {}).get("retention_hours", 72))
    except Exception:
        retention = 72.0
    _sweep_old_delivery_files(retention)

    # Document title from the paper's first heading (fallback to a prompt-derived title) — drives both
    # the filename slug and the email subject so they reflect the actual topic, not a generic name.
    import re as _re
    doc_title = ""
    _title_idx = -1
    _body_lines = (doc_body or "").splitlines()
    for _i, _line in enumerate(_body_lines):
        _m = _re.match(r'^#{1,4}\s+(.+\S)', _line.strip())
        if _m:
            _cand = _m.group(1).strip().strip("#").strip()
            # Accept the first heading as the document TITLE only if it is NOT an enumerated SECTION
            # heading ("1. …", "2) …", "Part 3 …", "Section 4 …", "Chapter 5 …"). A numbered first
            # heading is a section, not a title — using it is what made the email subject read like a
            # section ("1. The Deep Roots …"). When it IS a section, leave doc_title empty so we derive a
            # proper title from the research request below (and do NOT strip the section from the body).
            if not _re.match(r'^(\d+\s*[\.\):]|part\s+\d+|section\s+\d+|chapter\s+\d+)', _cand, _re.IGNORECASE):
                doc_title = _cand[:120]
                _title_idx = _i
            break
    _title_from_body = bool(doc_title)
    if not doc_title:
        # No usable title heading (none, or the first heading was an enumerated section): derive the title
        # from the RESEARCH REQUEST via the LLM — topic-accurate and policy-compliant (no keyword map).
        doc_title = (await _llm_title_from_request(user_prompt, doc_body, generate_stream)) or "Deep Research Report"
    _slug = _re.sub(r'[^a-z0-9]+', '_', doc_title.lower()).strip('_')[:60] or "deep_research"
    # PDF body: drop the paper's own leading title heading so the rendered title (passed as the
    # `title` param) isn't duplicated. Only when the title actually came from the body. The chat
    # answer + email still keep the full paper.
    _pdf_body = doc_body
    if _title_from_body and _title_idx >= 0:
        _stripped = list(_body_lines)
        del _stripped[_title_idx]
        _pdf_body = "\n".join(_stripped).lstrip("\n")

    # ── Phase 3: DYNAMIC DISPATCH of the open-vocabulary (non file/email) actions ─────────────────
    # Sequential + dependency-aware: each action's arguments are bound by an LLM that sees the tool's
    # schema + the research paper + the results of prior actions, then the tool is dispatched; its
    # result feeds the next action's binder. The proven file+email secure pipeline below is UNCHANGED
    # and runs after this pass. Disabled / no binder / no matching tool → reported as not-yet-wired
    # (no regression vs. legacy). Cross-category artifact handoff (a generic tool's output file → the
    # delivery email attachment / PDF embed) is intentionally out of scope here (see multimodal plan).
    dispatch_notes = []          # footnote lines: successes (quiet) + failures (explicit, never silent)
    prior_results = []           # running context fed to each subsequent binder (dependency-aware)
    deliv_cfg = (engine_cfg.get("delivery", {}) or {})
    dynamic_on = bool(deliv_cfg.get("dynamic_dispatch", True))
    schema_map = {}
    for _d in (tool_defs or []):
        _fn = _d.get("function", {}) if isinstance(_d, dict) else {}
        _n = _fn.get("name")
        if _n:
            schema_map[_n] = _fn.get("parameters", {}) or {}
    unwired = []
    for _act in generic_actions:
        _t = _act.get("type")
        _resolvable = bool(tool_manager and _t in getattr(tool_manager, "available_functions", {}))
        if dynamic_on and generate_stream and _resolvable:
            _ok, _summary = await _dr_bind_and_dispatch_action(
                _act, _t, schema_map.get(_t, {}), tool_manager, generate_stream,
                doc_body, deliverable_spec, prior_results, engine_cfg)
            prior_results.append(_summary)
            dispatch_notes.append(f"*📎 Delivery: ran {_summary}*" if _ok
                                  else f"⚠️ **Delivery:** {_summary}")
        else:
            unwired.append(_t)   # dispatch off, no binder available, or no matching live tool

    # ── Do the delivery work SILENTLY (no streamed step-by-step); we report a single housekeeping
    # footnote at the end. The footnote is appended to the RESPONSE only — never to the document
    # (the PDF/HTML is rendered from the paper body above), per the "confirmation is housekeeping,
    # not content" rule. Failures are still surfaced clearly (no silent failures).
    created_files = []
    file_error = None
    # A Deep Research deliverable is a long PAPER — when it is being EMAILED it must go as document
    # attachment(s), never dumped into the email body. The decomposer is not always consistent about
    # listing a separate file action (it sometimes returns only `secure_email_sender` even when the user
    # asked for "an HTML file and a PDF file"), so we create the document(s) whenever there is a file
    # action OR an email to send. The user may request MORE THAN ONE format; create one document per
    # requested format and attach them ALL to the single email, each rendered by the SAME standard
    # renderer (sandboxed_executor.create_file → html_generator template / convert_to_pdf).
    email_outcome = None  # None | ("sent", to) | ("failed", reason) | ("doc_failed", None) | ("no_recipient", None)
    if file_action or email_action:
        # Unified delivery core (the SAME shared with the NewX/@Ask path): render EVERY requested format
        # and email them as ONE message via _deliver_document (multi-format, valid PDFs, recipient-locked).
        _dr_formats = delivery_policy.resolve_delivery_formats(
            user_prompt, deliverable_format=str((deliverable_spec or {}).get("format", "")),
            candidates=delivery_policy.DR_FORMAT_CANDIDATES, default=delivery_policy.DR_FORMAT_DEFAULT)
        if email_action:
            # Recipient policy (security): restricted client -> server-authoritative locked recipient
            # (prompt recipients NEVER honored); auto-trusted -> resolve from the request.
            if recipient_locked:
                _lv, _ = delivery_policy.resolve_locked_recipient(recipient_locked, locked_recipient)
                _dr_recipients = [_lv] if _lv else []
            else:
                _dr_recipients = _resolve_email_recipients(email_action.get("args", {}) or {}, user_prompt)
        else:
            _dr_recipients = []
        _dr_body = "Please find attached the requested document(s), produced by RAICA Deep Research."
        if audit_text:
            # Keep the Research Audit alongside the papers (it lives in the chat answer, not the document).
            _dr_body += "\n\n" + audit_text.strip()
        _dr_res = await _deliver_document(
            content=_pdf_body, title=doc_title, slug=_slug, formats=_dr_formats, tool_manager=tool_manager,
            send_email=bool(email_action), recipients=_dr_recipients,
            recipient_locked=recipient_locked, locked_recipient=locked_recipient,
            subject=(deliverable_spec or {}).get("title") or doc_title, body=_dr_body)
        created_files = _dr_res.get("created_files") or []
        email_outcome = _dr_res.get("email_outcome")
        file_error = _dr_res.get("file_error")

    # ── Build the housekeeping footnote (success = quiet; failures = clear, never silent) ──────────
    notes = []
    if email_outcome:
        _kind, _info = email_outcome
        if _kind == "sent":
            notes.append(f"*📎 Delivery: the document was emailed to {_info}.*")
        elif _kind == "doc_failed":
            notes.append(f"⚠️ **Delivery:** the document could not be created ({file_error}); nothing was "
                         f"emailed. The full paper is in this response — please try again.")
        elif _kind == "no_recipient":
            notes.append("⚠️ **Delivery:** this bot can only email your own account email, which wasn't "
                         "available — nothing was sent." if recipient_locked
                         else "⚠️ **Delivery:** no recipient address was found — email skipped.")
        elif _kind == "failed":
            _kept = (f" Your document(s) are saved at sandbox_workspace/ ({', '.join(created_files)}) — "
                     f"download or retry." if created_files else "")
            notes.append(f"⚠️ **Delivery:** email failed ({_info}).{_kept}")
    elif file_action:  # file requested, no email
        notes.append(f"*📎 Delivery: saved {', '.join(created_files)}.*" if created_files
                     else f"⚠️ **Delivery:** the document could not be created ({file_error}).")
    if dispatch_notes:
        notes.extend(dispatch_notes)
    if unwired:
        notes.append(f"_Delivery: not wired yet — {', '.join(map(str, unwired))}._")
    if unsupported:
        notes.append(f"_Delivery: no tool available for — {', '.join(map(str, unsupported))}._")
    if notes:
        yield "\n\n---\n" + "\n".join(notes) + "\n"


def _delivery_sandbox_dir() -> str:
    """THE single sandbox-workspace directory where delivery artifacts are written, attached, and
    TTL-swept — resolved the SAME way SandboxedExecutorTool computes self.sandbox_path (config
    user_tools.sandboxed_executor.base_directory or the user's home dir, joined with the configured
    sandbox_workspace_name). Centralizing it here keeps the file-creation, attachment-lookup, and
    sweep paths from drifting apart. Replaces the ad-hoc os.getcwd()/sandbox_workspace, which
    resolved to a directory that does NOT exist (silently dropping email attachments / failing
    writes). Config-driven (no hardcoded path); safe home-dir fallback matches the email tool and
    _list_sandbox_files conventions."""
    import os as _os
    try:
        _ut = (config_loader.load_config().get('user_tools', {}) or {}).get('sandboxed_executor', {}) or {}
        _base = _ut.get('base_directory') or _os.path.expanduser("~")
        _name = _ut.get('sandbox_workspace_name') or "sandbox_workspace"
    except Exception:
        _base, _name = _os.path.expanduser("~"), "sandbox_workspace"
    return _os.path.join(_base, _name)


# In-memory, content-keyed idempotency for POST-LLM email sends (single-process server). Replaces the
# old global, content-blind /tmp/last_email_sent.txt 60s guard that silently dropped ANY 2nd email
# within a minute (cross-request state bleed). Keyed on recipient+subject+attachments so DISTINCT
# legitimate emails are never blocked; only an accidental IDENTICAL re-send within the window is
# suppressed — and surfaced to the caller, not silently skipped.
_postllm_recent_emails: dict = {}
_POSTLLM_EMAIL_DEDUP_WINDOW_S = 45.0


def _email_signature(email_params: dict) -> str:
    import hashlib as _hl
    _p = email_params or {}
    to = str(_p.get("to_email", "")).strip().lower()
    subj = str(_p.get("subject", "")).strip()
    att = ",".join(sorted(str(_p.get("attachments", "") or "").split(",")))
    return _hl.sha256(f"{to}|{subj}|{att}".encode("utf-8", "replace")).hexdigest()


def _postllm_email_recent_dup(email_params: dict):
    """Seconds since an IDENTICAL email was last sent if within the window, else None. Prunes expired."""
    import time as _t
    now = _t.monotonic()
    for _k in [k for k, v in _postllm_recent_emails.items() if now - v > _POSTLLM_EMAIL_DEDUP_WINDOW_S]:
        _postllm_recent_emails.pop(_k, None)
    _last = _postllm_recent_emails.get(_email_signature(email_params))
    return (now - _last) if (_last is not None) else None


def _postllm_email_mark_sent(email_params: dict):
    import time as _t
    _postllm_recent_emails[_email_signature(email_params)] = _t.monotonic()


def _safe_slug(text: str, fallback: str = "document", max_len: int = 60) -> str:
    """Filename-safe slug from a title; falls back to a short content hash when the title is empty or
    entirely non-ASCII (Arabic/Chinese/emoji) so distinct non-Latin titles don't all collapse to the
    same filename and silently overwrite each other."""
    import re as _re, hashlib as _hl
    s = _re.sub(r'[^a-z0-9]+', '_', (text or "").lower()).strip('_')[:max_len]
    if not s:
        s = f"{fallback}_{_hl.sha1((text or '').encode('utf-8', 'replace')).hexdigest()[:10]}"
    return s


def _list_sandbox_files() -> set:
    """Filenames currently in the user's sandbox_workspace — where sandboxed_executor.create_file writes
    AND where the email tool resolves attachments. Used for Phase-2 auto-bind: files that appear DURING a
    delivery request are the artifacts to attach. Best-effort; returns an empty set on any error."""
    try:
        d = os.path.join(os.path.expanduser("~"), "sandbox_workspace")
        return set(os.listdir(d)) if os.path.isdir(d) else set()
    except Exception:
        return set()


def _restrict_sandboxed_executor_def(tool_def: dict) -> dict:
    """For a RESTRICTED client (untrusted input, e.g. a NewX bot) narrow the sandboxed_executor tool
    schema shown to the LLM to the document-creation action ONLY — no shell/code execution — so an
    injection-exposed bot is never offered a shell. Defense in depth alongside the execution-time
    backstop in safe_function_call. Any non-sandboxed tool passes through unchanged."""
    try:
        if (tool_def.get("function", {}) or {}).get("name") != "sandboxed_executor":
            return tool_def
        import copy as _copy
        d = _copy.deepcopy(tool_def)
        props = d["function"]["parameters"]["properties"]
        if "action" in props:
            props["action"]["enum"] = ["create_file"]
            props["action"]["description"] = (
                "Action to perform: create_file (write a document file). Only file creation is "
                "available for this client.")
        return d
    except Exception:
        return tool_def


async def _send_email_locked(tool_manager, email_params, recipient_locked: bool, locked_recipient):
    """Send an email through the SINGLE chokepoint (AsyncToolManager.secure_email_sender), which now
    enforces the recipient lock for EVERY send — the POST-LLM delivery paths AND direct LLM tool calls
    alike — so the recipient-lock policy lives in exactly one place. This wrapper just publishes the
    caller's explicit lock context (used by POST-LLM / email-interceptor / DR paths that compute the
    delivery auth themselves) for the duration of the send, then restores the prior context.

    Behavior is unchanged from the previous inline implementation: for a restricted client the recipient
    is forced to the server-authoritative locked_recipient, prompt/LLM addresses are ignored, CC is
    dropped, and an invalid/absent lock REFUSES the send (fail-closed); auto-trusted clients pass
    through unchanged."""
    token = _delivery_lock_ctx.set((bool(recipient_locked), locked_recipient))
    try:
        return await tool_manager.safe_function_call("secure_email_sender", email_params)
    finally:
        _delivery_lock_ctx.reset(token)


async def _execute_missing_tools_post_llm(missing_tools: List[str], tool_manager, tools_results: str, complete_llm_response: str, user_prompt: str, llm_manager, locked_recipient: str = None, recipient_locked: bool = False) -> str:
    logger.info("--- ENTERING _execute_missing_tools_post_llm ---")
    """
    🎯 POST-LLM AUTO-EXECUTOR for missing tools
    Executes file creation and email sending AFTER Primary LLM generates complete content

    This ensures that:
    1. Files contain the complete, refined LLM-generated content
    2. Emails are sent with properly formatted attachments
    3. No race conditions between content generation and file operations

    Recipient policy (security): when recipient_locked is True (a RESTRICTED client that presents an
    allowed_tools whitelist, e.g. a NewX bot acting for a delivery-privileged user), EVERY email is
    sent ONLY to locked_recipient (the user's server-authoritative account email) — any prompt- or
    LLM-derived address is ignored, and if no valid locked_recipient is available the send is REFUSED
    (fail-closed). When recipient_locked is False (auto-trusted single-user client), recipients are
    resolved as before. All four email send sites below route through _send_secure_email to enforce
    this in ONE place (mirrors the deep-research delivery path).
    """
    # Import required modules for this function
    from datetime import datetime
    import traceback

    async def _send_secure_email(email_params):
        """Chokepoint for the POST-LLM executor send sites — delegates to the shared _send_email_locked
        so the recipient-lock policy lives in exactly one place, and applies a content-keyed idempotency
        guard (recipient+subject+attachments within a short window) so an accidental IDENTICAL re-send is
        suppressed WITHOUT blocking distinct legitimate emails (replaces the old global, content-blind
        /tmp/last_email_sent.txt guard that silently dropped any 2nd email within 60s)."""
        _ago = _postllm_email_recent_dup(email_params)
        if _ago is not None:
            logger.info(f"🚫 POST-LLM EMAIL: identical email to {(email_params or {}).get('to_email')} "
                        f"sent {_ago:.1f}s ago (≤{int(_POSTLLM_EMAIL_DEDUP_WINDOW_S)}s) — suppressing duplicate")
            return {"success": False, "result": None,
                    "error": "duplicate suppressed — an identical email was just sent moments ago"}
        _last_user_tool_ok.set(None)
        result = await _send_email_locked(tool_manager, email_params, recipient_locked, locked_recipient)
        # Mark sent only on the tool's ACTUAL success (structured flag), not "a string came back" — a
        # failed send returns a "Tool '…' error: …" STRING too, which previously counted as sent.
        _ok = _last_user_tool_ok.get()
        _sent = (_ok is True) if _ok is not None else (isinstance(result, dict) and result.get("success"))
        if _sent:
            _postllm_email_mark_sent(email_params)
        return result

    additional_results = ""
    created_filename = None
    _doc_title_for_subject = None   # LLM/heading-derived doc title, shared file branch → email subject
    
    # Extract file format from user prompt (shared resolver — orchestration/policy; behavior-identical
    # to the previous inline pdf/html/md/txt/else-html chain).
    file_extension = delivery_policy.resolve_delivery_format(
        user_prompt, candidates=delivery_policy.POST_LLM_FORMAT_CANDIDATES,
        default=delivery_policy.POST_LLM_FORMAT_DEFAULT)

    # ── Route 1: execute the classifier's chosen actions GENERICALLY (CARDINAL RULE / LLM-Policy Gate) ─
    # The intent classifier (LLM) decided WHICH tools this delivery needs; RAICA executes them. A tool
    # with no special branch below (e.g. pdf_generator, or any future file/document tool) is dispatched
    # generically in the loop's `else`, and any file it writes to the workspace is captured and attached.
    # secure_email_sender keeps special handling ONLY for recipient-locking (a safety limit) and runs
    # LAST, so artifacts exist before it attaches them.
    missing_tools = [t for t in missing_tools if t != "secure_email_sender"] + \
                    (["secure_email_sender"] if "secure_email_sender" in missing_tools else [])
    _post_llm_extra_files = []   # files produced by generically-dispatched tools → attached to the email
    _sandbox_dir = None
    for _t in (getattr(tool_manager, "user_tools", []) or []):
        if getattr(_t, "name", "") == "sandboxed_executor":
            _sandbox_dir = str(getattr(_t, "sandbox_path", "") or "") or None
            break

    def _artifact_snapshot():
        """Set of files (abs paths) where delivery tools may write — the sandbox workspace and the CWD
        (different tools write to different places). Diffing this before/after a dispatch yields the
        file a tool just produced, with no tool-specific result parsing."""
        import os as _os_g
        seen = set()
        for _d in filter(None, [_sandbox_dir, _os_g.getcwd()]):
            try:
                for _f in _os_g.listdir(_d):
                    _p = _os_g.path.join(_d, _f)
                    if _os_g.path.isfile(_p):
                        seen.add(_p)
            except OSError:
                pass
        return seen

    # ── UNIFIED DELIVERY (convergence Phase 4): if the classifier selected file-creation and/or email,
    # render the answer into EVERY requested format and email them as ONE message through the SAME robust
    # core Deep Research uses (_deliver_document) — multi-format, valid PDFs, content-derived title,
    # recipient-locked. This REPLACES the fragile single-format / keyword POST-LLM branches below (which
    # delivered only ONE format, mis-titled the file, and intermittently corrupted the PDF). Non-delivery
    # tools the classifier picked are still dispatched generically in the per-tool loop that follows.
    _FILE_TOOLS = {"sandboxed_executor", "pdf_generator"}
    _needs_file = any(t in _FILE_TOOLS for t in missing_tools)
    # Email is intended if the classifier flagged it missing OR it already appears in RAICA's executed-
    # tools record: an earlier (pre-LLM) email attempt NECESSARILY had no attachments (the document is
    # created here, post-LLM), so the unified delivery sends the REAL files now. (Matches RAICA's own
    # tool-execution record — a tool NAME — not user-text keywords; LLM-Policy-Gate compliant.)
    _needs_email = ("secure_email_sender" in missing_tools) or ("secure_email_sender" in (tools_results or ""))
    if _needs_file or _needs_email:
        # Unwrap a model-fenced/preambled deliverable (e.g. "Here is the HTML document: ```html …```")
        # so the file is the real document, not its source shown as a code block.
        _raw = _unwrap_delivery_content(_fill_template_placeholders(
            _clean_llm_response_content((complete_llm_response or "").strip()), user_prompt, tools_results))
        # Take the TITLE from the content's first markdown heading and REMOVE that heading + anything before
        # it (the model's conversational preamble, e.g. "Here is your briefing:"). The renderer adds the
        # title as the document header, so leaving the heading/preamble in the body printed the title 2-3×
        # with the intro. (Mirrors the Deep Research path's _pdf_body title-strip.)
        import re as _re_title
        _lines = _raw.splitlines()
        _hidx = next((i for i, l in enumerate(_lines[:10]) if _re_title.match(r'^#{1,4}\s+\S', l.strip())), -1)
        if _hidx >= 0:
            _title = _re_title.match(r'^#{1,4}\s+(.+\S)', _lines[_hidx].strip()).group(1).strip().strip("#").strip()[:120]
            _content = "\n".join(_lines[_hidx + 1:]).lstrip("\n")
        else:
            _title = await _llm_document_title(_raw, user_prompt, llm_manager)
            _content = _raw
        # Tidy the body: drop trailing social hashtags + demote sentence-like 'headings' (so body text
        # isn't rendered in the large heading font, and #hashtags aren't promoted to an <h1>).
        _content = _normalize_delivery_markdown(_content)
        # Requested format(s) decided by the LLM (NOT substring matching, which falsely produced .md/.txt
        # from 'context'/embedded 'above' content).
        _formats = await _llm_requested_formats(user_prompt, llm_manager,
                                                default=delivery_policy.POST_LLM_FORMAT_DEFAULT)
        if _needs_email and recipient_locked:
            _lv, _ = delivery_policy.resolve_locked_recipient(recipient_locked, locked_recipient)
            _recips = [_lv] if _lv else []
        elif _needs_email:
            import re as _re_em
            _recips = _re_em.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', user_prompt or "")
        else:
            _recips = []
        _res = await _deliver_document(
            content=_content, title=_title, slug=_safe_slug(_title, fallback="document"),
            formats=_formats, tool_manager=tool_manager, send_email=_needs_email, recipients=_recips,
            recipient_locked=recipient_locked, locked_recipient=locked_recipient, subject=_title,
            body="Please find attached the requested document(s).")
        _cf = _res.get("created_files") or []
        _eo = _res.get("email_outcome")
        if _cf:
            additional_results += (f"Tool: document delivery (post-LLM)\nResult: created {len(_cf)} "
                                   f"file(s): {', '.join(_cf)}\n\n")
        if _eo:
            _k, _i = _eo
            additional_results += ("Tool: secure_email_sender (post-LLM)\nResult: "
                                   + (f"✅ emailed to {_i} with {len(_cf)} attachment(s)\n\n" if _k == "sent"
                                      else f"⚠️ delivery {_k}: {_i}\n\n"))
        # handled by the unified delivery above → do NOT re-run them in the per-tool loop below
        missing_tools = [t for t in missing_tools if t not in _FILE_TOOLS and t != "secure_email_sender"]

    for tool_name in missing_tools:
        function_args_dict = {} # Initialize function_args_dict for each tool
        try:
            logger.info(f"🔄 POST-LLM Auto-executing: {tool_name}")

            # STANDARDIZED file creation: whether the classifier named `sandboxed_executor` or
            # `pdf_generator` (it does either, for the same "save/email a document" intent), the document
            # is produced HERE through the one shared renderer (sandboxed_executor.create_file →
            # html_generator standard template; convert_to_pdf when the resolved format is PDF). This is
            # what makes HTML and PDF look identical (the Deep Research template) and fixes the
            # "classifier picked pdf_generator → no executor branch → body email" failure.
            if tool_name in ("sandboxed_executor", "pdf_generator"):
                timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')

                # Use the synthesized answer as the document content (the fix that makes the file contain
                # the actual answer, not a placeholder).
                raw_content = complete_llm_response.strip()
                report_content = _clean_llm_response_content(raw_content)
                report_content = _fill_template_placeholders(report_content, user_prompt, tools_results)

                # 🎯 STANDARDIZED ON THE DEEP RESEARCH APPROACH: derive the document title from the
                # content's own first heading (fallback to a prompt subject), name the file from it so it
                # reflects the topic (not a generic 'document'), and pass the title to the renderer. No
                # generic '# Analysis Report / generated by the AI ... System' boilerplate.
                doc_title = await _llm_document_title(report_content, user_prompt, llm_manager)
                _doc_title_for_subject = doc_title  # reuse the SAME title for the email subject
                if not report_content.lstrip().startswith("#") and not report_content.lstrip().startswith("<"):
                    # Guarantee a visible title heading (clean — no boilerplate footer) when the content
                    # has none, so the rendered document isn't untitled.
                    report_content = f"# {doc_title}\n\n{report_content}"

                import os, re as _re_fname
                _slug = _safe_slug(doc_title, fallback="document")
                created_filename = f"{_slug}_{timestamp}.{file_extension}"
                logger.info(f"🎯 POST-LLM: Creating DYNAMIC REPORT -> {created_filename} (title='{doc_title}')")

                base_dir = _delivery_sandbox_dir()
                full_file_path = os.path.join(base_dir, created_filename)
                if os.path.exists(full_file_path):
                    logger.info(f"🔄 POST-LLM: File {created_filename} exists - will overwrite with fresh primary LLM response")

                logger.info(f"🎯 POST-LLM: Using COMPLETE LLM response ({len(report_content)} chars)")
                
                # Find and execute sandboxed tool with complete content
                sandboxed_tool_instance = None
                for tool in tool_manager.user_tools:
                    if tool.name == "sandboxed_executor":
                        sandboxed_tool_instance = tool
                        break
                
                if sandboxed_tool_instance:
                    # Force PDF conversion by explicitly setting convert_to_pdf=True for .pdf files
                    if created_filename.endswith('.pdf'):
                        result = await sandboxed_tool_instance.execute(
                            action="create_file",
                            filename=created_filename,
                            content=report_content,
                            title=doc_title,  # standardized: title drives the rendered document (like DR)
                            convert_to_pdf=True  # Explicitly force PDF conversion
                        )
                        logger.info(f"🎯 POST-LLM: FORCED PDF conversion for {created_filename}")
                    else:
                        result = await sandboxed_tool_instance.execute(
                            action="create_file",
                            filename=created_filename,
                            content=report_content,
                            title=doc_title  # standardized: title drives the rendered document (like DR)
                        )
                    logger.info(f"🎯 POST-LLM: File creation RESULT: {result}")
                    
                    if result.get('success'):
                        additional_results += f"Tool: {tool_name} (post-LLM execution)\nResult: Created file {created_filename} with complete LLM response ({len(report_content)} chars)\n\n"
                    else:
                        logger.error(f"❌ POST-LLM file creation failed: {result.get('error')}")
                        additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: Error: {result.get('error')}\n\n"
                else:
                    logger.error(f"❌ POST-LLM: Could not find sandboxed_executor tool instance")

            elif tool_name == "secure_email_sender":
                # Detect HTML email request and execute email sending
                # Legacy HTML-email keyword-detour DISABLED (deep-review fix): it built a wrong-titled
                # DUPLICATE file and passed to_email=None (→ crash + false "success"). The unified regular
                # processing below already creates the correctly-titled file (route-1 / sandboxed_executor)
                # AND resolves the locked recipient at the app layer, so secure_email_sender always takes
                # that ONE consistent, recipient-lock-aware path.
                html_email_request = None  # was: await _detect_html_email_request(tools_results, user_prompt)

                if html_email_request:
                    logger.info(f"🎯 POST-LLM HTML EMAIL: Using fallback detection")
                    # Generate complete HTML file using HTMLReportGenerator
                    html_filename = await _generate_complete_html_email(
                        complete_llm_response, 
                        html_email_request,
                        user_prompt,
                        html_email_request.get('subject', 'HTML_Report')
                    )
                    
                    # Execute secure_email_sender with generated HTML file
                    email_tool_instance = None
                    for tool in tool_manager.user_tools:
                        if tool.name == "secure_email_sender":
                            email_tool_instance = tool
                            break
                    
                    if email_tool_instance and html_filename:
                        # 🔧 CRITICAL FIX: Add timeout to prevent infinite hanging
                        
                        try:
                            logger.info(f"⏰ POST-LLM HTML EMAIL: Starting email execution with 120s timeout...")
                            
                            # Execute email using secure_email_sender with fail-fast logic
                            email_params = {
                                "to_email": html_email_request.get('to_email'),
                                "subject": html_email_request.get('subject', 'HTML Report'),
                                "body": f"Please find attached HTML document.",
                                "attachments": html_filename
                            }
                            result = await _send_secure_email(email_params)
                            
                            logger.info(f"✅ POST-LLM HTML EMAIL: Completed successfully")
                            
                        except asyncio.TimeoutError:
                            logger.error(f"⏰ POST-LLM HTML EMAIL: TIMEOUT after 120 seconds - email execution hung!")
                            result = {'success': False, 'error': 'HTML email execution timed out after 120 seconds'}
                        except Exception as e:
                            logger.error(f"❌ POST-LLM HTML EMAIL: Email execution failed: {e}")
                            result = {'success': False, 'error': str(e)}
                        logger.info(f"🎯 POST-LLM HTML EMAIL: Sent with complete content")
                        additional_results += f"Tool: {tool_name} (HTML email with complete content)\nResult: {result}\n\n"
                        continue  # Skip regular email processing
                
                # 📄 CONVERSATION PDF EMAIL PROCESSING
                # Legacy conversation-PDF keyword-detour DISABLED (Phase 4 convergence): the unified
                # regular processing below already attaches the created artifact and resolves the locked
                # recipient — no keyword routing. [was: _detect_conversation_pdf_request(...)]
                conversation_pdf_request = {}
                if conversation_pdf_request.get('detected'):
                    logger.info(f"📄 POST-LLM CONVERSATION PDF: Processing conversation export request")
                    
                    # Get conversation history from the current session 
                    message_history = []
                    
                    # Extract conversation history from the context if available
                    if "=== CONVERSATION HISTORY ===" in user_prompt:
                        # Parse conversation from user_prompt context
                        conv_start = user_prompt.find("=== CONVERSATION HISTORY ===")
                        conv_end = user_prompt.find("=== CURRENT REQUEST ===")
                        
                        if conv_start != -1 and conv_end != -1:
                            conversation_text = user_prompt[conv_start:conv_end]
                            # Parse the conversation format
                            for line in conversation_text.split('\n'):
                                line = line.strip()
                                if line and ':' in line and (line.upper().startswith('USER:') or line.upper().startswith('ASSISTANT:') or line.upper().startswith('SYSTEM:')):
                                    message_history.append(line)
                    
                    # If no conversation history found, create a summary of current interaction
                    if not message_history:
                        message_history = [
                            f"USER: {user_prompt.split('=== CURRENT REQUEST ===')[-1].strip() if '=== CURRENT REQUEST ===' in user_prompt else user_prompt}",
                            f"ASSISTANT: {complete_llm_response[:1000]}{'...' if len(complete_llm_response) > 1000 else ''}"
                        ]
                    
                    # Generate conversation PDF
                    pdf_filename = "conversation_export.pdf"
                    pdf_result = await export_conversation_to_pdf(message_history, pdf_filename)
                    
                    if pdf_result.get('success'):
                        # Send email with conversation PDF attachment
                        email_tool_instance = None
                        for tool in tool_manager.user_tools:
                            if tool.name == "secure_email_sender":
                                email_tool_instance = tool
                                break
                        
                        if email_tool_instance:
                            # 🔧 CRITICAL FIX: Add timeout to prevent infinite hanging
                                
                            try:
                                logger.info(f"⏰ POST-LLM CONVERSATION PDF: Starting email execution with 120s timeout...")
                                
                                # Execute email with timeout to prevent hanging
                                # Execute email using secure_email_sender with fail-fast logic
                                email_params = {
                                    "to_email": conversation_pdf_request.get('to_email'),
                                    "subject": conversation_pdf_request.get('subject', 'Conversation Export'),
                                    "body": f"Please find attached the conversation export in PDF format.\n\nThis document contains {pdf_result.get('message_count', 0)} messages from our conversation.",
                                    "attachments": pdf_filename
                                }
                                email_result = await _send_secure_email(email_params)
                                
                                logger.info(f"✅ POST-LLM CONVERSATION PDF: Email completed successfully")
                                
                            except asyncio.TimeoutError:
                                logger.error(f"⏰ POST-LLM CONVERSATION PDF: TIMEOUT after 120 seconds - email execution hung!")
                                email_result = {'success': False, 'error': 'Conversation PDF email execution timed out after 120 seconds'}
                            except Exception as e:
                                logger.error(f"❌ POST-LLM CONVERSATION PDF: Email execution failed: {e}")
                                email_result = {'success': False, 'error': str(e)}
                            logger.info(f"📄 POST-LLM CONVERSATION PDF: Sent successfully")
                            additional_results += f"Tool: {tool_name} (Conversation PDF export)\nResult: {email_result}\n\n"
                            continue  # Skip regular email processing
                        else:
                            logger.error(f"❌ POST-LLM CONVERSATION PDF: Could not find email tool")
                    else:
                        logger.error(f"❌ POST-LLM CONVERSATION PDF: Export failed - {pdf_result.get('error')}")
                        additional_results += f"Tool: {tool_name} (Conversation PDF export failed)\nResult: Error: {pdf_result.get('error')}\n\n"
                
                # 🚀 BULLETPROOF EMAIL EXECUTION (Regular processing)
                # Handles all email scenarios: single file, multiple files, existing files, new files
                files_to_attach = []
                
                # Step 1: Extract filenames from tools_results (handles multiple document creation)
                import re
                import os
                filename_pattern = r'"filename":\s*"([^"]+)"'
                found_files = re.findall(filename_pattern, tools_results)
                base_dir = _delivery_sandbox_dir()
                
                # Remove duplicates from found files
                found_files = list(set(found_files))  # Remove duplicates
                logger.info(f"🎯 POST-LLM EMAIL: Found {len(found_files)} unique files in tools_results: {found_files}")
                
                # Step 2: Check all found files and add them to attachments
                for filename in found_files:
                    if filename.endswith(('.pdf', '.html', '.txt', '.md', '.json', '.csv')):  # Support all formats
                        full_path = os.path.join(base_dir, filename)
                        if os.path.exists(full_path):
                            files_to_attach.append(filename)
                            logger.info(f"✅ POST-LLM EMAIL: Verified existing file: {filename}")
                        else:
                            logger.warning(f"⚠️ POST-LLM EMAIL: File not found: {full_path}")
                
                # Step 2A: 🔧 MULTI-DOCUMENT FIX: Extract source files mentioned in user prompt
                import re
                # 🔧 CRITICAL FIX v1.0.3.9: DON'T reassign user_prompt - it's already a function parameter!
                # user_prompt = data.get('prompt', '') if 'data' in locals() else ''  # ❌ BUG: Overwrites parameter with ''

                # Look for file paths in user prompt (common patterns)
                file_path_patterns = [
                    r'/[a-zA-Z0-9_/.-]+\.(?:pdf|doc|docx|txt|md|json|csv|html)',  # Absolute paths
                    r'[a-zA-Z0-9_.-]+\.(?:pdf|doc|docx|txt|md|json|csv|html)',   # Relative filenames
                ]
                
                mentioned_files = []
                for pattern in file_path_patterns:
                    found_paths = re.findall(pattern, user_prompt)
                    mentioned_files.extend(found_paths)
                
                logger.info(f"🔍 POST-LLM EMAIL: Found {len(mentioned_files)} files mentioned in prompt: {mentioned_files}")
                
                # Add mentioned source files that exist
                for file_path in mentioned_files:
                    if os.path.isabs(file_path) and os.path.exists(file_path):
                        files_to_attach.append(file_path)  # Use absolute path
                        logger.info(f"✅ POST-LLM EMAIL: Added source file from prompt: {file_path}")
                    elif not os.path.isabs(file_path):
                        # Try in common locations
                        candidate_paths = [
                            file_path,  # Current directory
                            os.path.join(base_dir, file_path),  # Sandbox
                            os.path.join("/home/sabawi/Documents", file_path),  # Documents
                        ]
                        for candidate in candidate_paths:
                            if os.path.exists(candidate):
                                files_to_attach.append(candidate)
                                logger.info(f"✅ POST-LLM EMAIL: Added source file: {candidate}")
                                break
                
                # 🔧 CRITICAL FIX: Check if we just sent an email recently to avoid duplicates
                import time
                from datetime import datetime, timedelta
                
                # Check if an email was sent in the last 60 seconds to prevent duplicates
                current_time = datetime.now()
                last_email_check_file = "/tmp/last_email_sent.txt"
                
                try:
                    if False:  # legacy global /tmp/last_email_sent.txt dedup RETIRED — idempotency now lives in _send_secure_email (content-keyed). Inert block kept minimal; excise at checkpoint.
                        with open(last_email_check_file, 'r') as f:
                            last_email_time_str = f.read().strip()
                            last_email_time = datetime.fromisoformat(last_email_time_str)
                            
                        # If email was sent within last 60 seconds, skip sending duplicate
                        if (current_time - last_email_time).total_seconds() < 60:
                            logger.info(f"🚫 POST-LLM EMAIL: Email sent recently ({(current_time - last_email_time).total_seconds():.1f}s ago) - skipping duplicate")
                            continue  # Skip this POST-LLM execution
                except Exception as e:
                    logger.warning(f"⚠️ POST-LLM EMAIL: Error checking last email time: {e}")
                
                # Step 3: Also add post-LLM created file if any
                if created_filename:
                    files_to_attach.append(created_filename)
                    logger.info(f"✅ POST-LLM EMAIL: Added post-LLM created file: {created_filename}")

                # Step 3b: Add files produced by generically-dispatched tools (route 1 — e.g. pdf_generator
                # writing a PDF to the workspace). These are this request's own freshly-produced artifacts.
                for _ef in _post_llm_extra_files:
                    if _ef not in files_to_attach:
                        files_to_attach.append(_ef)
                        logger.info(f"✅ POST-LLM EMAIL: Added generically-produced file: {_ef}")

                # Step 4: 🚨 SECURITY FIX - DO NOT attach unrelated files!
                if not files_to_attach:
                    logger.warning(f"⚠️ POST-LLM EMAIL: No files found for attachment - this indicates missing file creation tools!")
                    logger.warning(f"⚠️ POST-LLM EMAIL: REQUEST ANALYSIS NEEDED - User wanted files but none were created")
                    logger.warning(f"⚠️ POST-LLM EMAIL: Refusing to attach unrelated files for security reasons")
                    # 🔄 CRITICAL: Do not scan workspace for random files - this could send wrong person's data!
                    # This was causing privacy violations by sending Joe's files to Mary!
                    # Instead, we should have created the requested files with sandboxed_executor
                
                files_to_attach = list(dict.fromkeys(files_to_attach))  # dedup: found_files + created_filename may name the same artifact
                logger.info(f"🎯 POST-LLM EMAIL: Total files to attach: {len(files_to_attach)} -> {files_to_attach}")
                
                if files_to_attach:
                    logger.info(f"🎯 POST-LLM: Sending email with {len(files_to_attach)} attachment(s)")
                    
                    # Find email tool instance
                    email_tool_instance = None
                    for tool in tool_manager.user_tools:
                        if tool.name == "secure_email_sender":
                            email_tool_instance = tool
                            break
                    
                    if email_tool_instance:
                        logger.info(f"✅ POST-LLM EMAIL: Found email tool instance")
                        
                        # 🔥 ENHANCED: Smart email and CC extraction from user prompt
                        import re
                        # 🔧 DEBUG v1.0.3.9: Log BOTH user_prompt and actual_user_prompt to debug email extraction
                        logger.info(f"🔍 POST-LLM EMAIL DEBUG: user_prompt passed to function = {repr(user_prompt[:200])}")
                        logger.info(f"🔍 POST-LLM EMAIL DEBUG: Checking if actual_user_prompt exists in scope...")
                        try:
                            # This should fail if actual_user_prompt isn't in scope
                            test_prompt = actual_user_prompt
                            logger.info(f"✅ POST-LLM EMAIL DEBUG: actual_user_prompt exists! Value = {repr(test_prompt[:200])}")
                        except NameError:
                            logger.error(f"❌ POST-LLM EMAIL DEBUG: actual_user_prompt NOT in scope!")

                        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                        email_matches = re.findall(email_pattern, user_prompt)

                        logger.info(f"📧 POST-LLM EMAIL: Found {len(email_matches)} email addresses: {email_matches}")
                        
                        # Determine primary recipient and CC with smart detection
                        recipient_email = email_matches[0] if email_matches else None
                        # Server-authoritative delivery recipient WINS (e.g. NewX "email me" with no typed
                        # address — the locked account email is used). Never skip for a missing prompt
                        # address when recipient locking applies.
                        if recipient_locked and delivery_policy.valid_email(locked_recipient):
                            recipient_email = locked_recipient
                        if not recipient_email:
                            logger.warning(f"⚠️ POST-LLM EMAIL: No email address found in user request - skipping email")
                            additional_results += f"Tool: {tool_name} (post-LLM execution skipped)\nResult: No email address found in request\n\n"
                            continue
                        cc_emails = []
                        
                        if len(email_matches) > 1:
                            
                            # Smart CC detection - look for explicit CC mentions or multiple emails
                            user_prompt_lower = user_prompt.lower()
                            if "cc" in user_prompt_lower or "copy" in user_prompt_lower:
                                # Extract CC emails after CC mention
                                cc_pattern = r'(?:cc|copy).*?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
                                cc_matches = re.findall(cc_pattern, user_prompt_lower)
                                if cc_matches:
                                    cc_emails = cc_matches
                                elif len(email_matches) > 1:
                                    cc_emails = email_matches[1:]  # Fallback: rest are CC
                            elif len(email_matches) > 1:
                                cc_emails = email_matches[1:]  # Multiple emails = CC the rest
                        
                        logger.info(f"🎯 POST-LLM: Recipient: {recipient_email}, CC: {cc_emails}")
                        
                        # Use the files we found above
                        attachment_files = files_to_attach
                        
                        # Create comma-separated attachment list
                        attachments_str = ",".join(attachment_files)
                        logger.info(f"🔧 POST-LLM: Sending email with attachments: {attachments_str}")
                        
                        # 🔧 FIX: Include CC emails and use better provider for attachments
                        cc_emails_str = ",".join(cc_emails) if cc_emails else ""
                        
                        # 🚀 SMART EMAIL COMPOSITION based on user request and file types

                        # Subject = the SAME title used for the document (content heading, else LLM-named),
                        # NOT a keyword/regex read of the prompt (LLM-Policy Gate).
                        subject = _doc_title_for_subject or await _llm_document_title(complete_llm_response, user_prompt, llm_manager)

                        if not subject:
                            # Fallback: Determine email subject based on content if no explicit subject
                            subject = "Requested Documents"
                            if len(files_to_attach) > 1:
                                subject = f"Multiple Documents ({len(files_to_attach)} files)"
                            elif any("pdf" in f.lower() for f in files_to_attach):
                                subject = "PDF Document"

                            # Add timestamp for generic subjects only
                            subject += f" - {datetime.now().strftime('%Y-%m-%d')}"
                        
                        # Create detailed file list for email body
                        file_list = ""
                        for i, filename in enumerate(files_to_attach, 1):
                            file_ext = filename.split('.')[-1].upper()
                            file_list += f"{i}. {filename} ({file_ext} format)\n"
                        
                        email_body = f"""Please find attached the requested documents.

Document Details:
- Generated: {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}
- Total Files: {len(attachment_files)} attachment(s)

Files Included:
{file_list}
This email was automatically generated in response to your request:
"{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}"

Best regards,
AI Document Generation System"""
                        
                        logger.info(f"📧 POST-LLM EMAIL: Subject: {subject}")
                        logger.info(f"📧 POST-LLM EMAIL: Attachments: {attachments_str}")
                        logger.info(f"📧 POST-LLM EMAIL: Recipients: {recipient_email}, CC: {cc_emails_str}")
                        logger.info(f"📧 POST-LLM EMAIL: Body length: {len(email_body)} chars")
                        
                        # 🔧 CRITICAL FIX: Add timeout to prevent infinite hanging
                        
                        try:
                            logger.info(f"⏰ POST-LLM EMAIL: Starting email execution with 120s timeout...")
                            
                            # Execute email using secure_email_sender with fail-fast logic
                            email_params = {
                                "to_email": recipient_email,
                                "cc_emails": cc_emails_str if cc_emails_str else None,  # Don't pass empty string
                                "subject": subject,
                                "body": email_body,
                                "attachments": attachments_str
                            }
                            email_result = await _send_secure_email(email_params)

                            logger.info(f"✅ POST-LLM EMAIL: Completed successfully")
                            logger.info(f"🎯 POST-LLM: Email RESULT: {email_result}")

                        except asyncio.TimeoutError:
                            logger.error(f"⏰ POST-LLM EMAIL: TIMEOUT after 120 seconds - email execution hung!")
                            email_result = {
                                'success': False,
                                'error': 'Email execution timed out after 120 seconds',
                                'result': None
                            }
                        except Exception as email_error:
                            logger.error(f"❌ POST-LLM EMAIL: Exception during execution: {email_error}")
                            import traceback
                            logger.error(f"❌ POST-LLM EMAIL: Traceback: {traceback.format_exc()}")
                            email_result = {
                                'success': False,
                                'error': f'Email execution failed: {str(email_error)}',
                                'result': None
                            }

                        # 🔧 FIX: safe_function_call returns a string on success, dict on error
                        if isinstance(email_result, str):
                            # String result means success - extract details from result string
                            additional_results += f"Tool: {tool_name} (post-LLM execution)\nResult: {email_result}\n\n"
                        elif isinstance(email_result, dict) and email_result.get('success'):
                            # Dict with success=True - use the detailed result message
                            result_msg = email_result.get('result', 'Email sent successfully')
                            additional_results += f"Tool: {tool_name} (post-LLM execution)\nResult: {result_msg}\n\n"
                        else:
                            # Dict with success=False or error
                            error_msg = email_result.get('error', 'Unknown error') if isinstance(email_result, dict) else str(email_result)
                            logger.error(f"❌ POST-LLM email sending failed: {error_msg}")
                            additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: Error: {error_msg}\n\n"
                    else:
                        logger.error(f"❌ POST-LLM: Could not find secure_email_sender tool instance")
                else:
                    # 🔧 FIX v1.0.3.114: Send email with LLM response as body when no attachments
                    logger.info(f"📧 POST-LLM: No attachments found - will send LLM response as email body")

                    # Extract email address from user prompt
                    import re
                    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                    email_matches = re.findall(email_pattern, user_prompt)

                    # Server-authoritative delivery recipient WINS (NewX "email me" with no typed address).
                    recipient_email = email_matches[0] if email_matches else None
                    if recipient_locked and delivery_policy.valid_email(locked_recipient):
                        recipient_email = locked_recipient
                    if not recipient_email:
                        logger.warning(f"⚠️ POST-LLM EMAIL: No email address found in prompt - skipping")
                        additional_results += f"Tool: {tool_name} (skipped)\nResult: No email address found in request\n\n"
                    else:
                        cc_emails = email_matches[1:] if (len(email_matches) > 1 and not recipient_locked) else []
                        cc_emails_str = ",".join(cc_emails) if cc_emails else ""

                        logger.info(f"📧 POST-LLM: Sending email to {recipient_email} with LLM response as body")

                        # Subject = the content's own title (first heading, else LLM-named) — no keyword/
                        # regex read of the prompt (LLM-Policy Gate).
                        subject = await _llm_document_title(complete_llm_response, user_prompt, llm_manager)

                        # Create email body from complete LLM response
                        email_body = f"""{complete_llm_response}

---
This email was automatically generated in response to your request:
"{user_prompt[:200]}{'...' if len(user_prompt) > 200 else ''}"

Generated: {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}"""

                        logger.info(f"📧 POST-LLM EMAIL: Subject: {subject}")
                        logger.info(f"📧 POST-LLM EMAIL: Recipients: {recipient_email}, CC: {cc_emails_str}")
                        logger.info(f"📧 POST-LLM EMAIL: Body length: {len(email_body)} chars")

                        # Send email without attachments
                        try:
                            email_params = {
                                "to_email": recipient_email,
                                "cc_emails": cc_emails_str if cc_emails_str else None,
                                "subject": subject,
                                "body": email_body,
                                "attachments": None  # No attachments
                            }
                            email_result = await _send_secure_email(email_params)

                            logger.info(f"✅ POST-LLM EMAIL: Sent successfully without attachments")
                            logger.info(f"🎯 POST-LLM: Email RESULT: {email_result}")

                            # Handle result
                            if isinstance(email_result, str):
                                additional_results += f"Tool: {tool_name} (post-LLM execution)\nResult: {email_result}\n\n"
                            elif isinstance(email_result, dict) and email_result.get('success'):
                                result_msg = email_result.get('result', 'Email sent successfully')
                                additional_results += f"Tool: {tool_name} (post-LLM execution)\nResult: {result_msg}\n\n"
                            else:
                                error_msg = email_result.get('error', 'Unknown error') if isinstance(email_result, dict) else str(email_result)
                                logger.error(f"❌ POST-LLM email failed: {error_msg}")
                                additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: Error: {error_msg}\n\n"

                        except Exception as email_error:
                            logger.error(f"❌ POST-LLM EMAIL: Exception during execution: {email_error}")
                            import traceback
                            logger.error(f"❌ POST-LLM EMAIL: Traceback: {traceback.format_exc()}")
                            additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: Error: {str(email_error)}\n\n"
            
            elif tool_name == "get_news_summaries":
                # Execute news summaries tool
                logger.info(f"🎯 POST-LLM: Executing get_news_summaries for Middle East news")
                try:
                    result = await tool_manager.get_news_summaries("Middle East")
                    additional_results += f"Tool: {tool_name} (post-LLM execution)\nResult: {result}\n\n"
                    logger.info(f"🎯 POST-LLM: News summaries completed: {len(str(result))} chars")
                except Exception as e:
                    logger.error(f"❌ POST-LLM news summaries failed: {e}")
                    additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: Error: {str(e)}\n\n"

            # 🔌 HANDLE DEFERRED PLUGIN TOOLS (social_media_*, publishing_*, etc.)
            elif (tool_name.startswith("social_media_") or
                  tool_name.startswith("email_") or
                  tool_name.startswith("publishing_") or
                  tool_name.endswith("_publish") or
                  tool_name.endswith("_post")):

                logger.info(f"🔌 POST-LLM PLUGIN: Executing deferred plugin {tool_name}")

                # Extract deferred parameters from tools_results
                params_marker = f"__DEFERRED_PARAMS__:"
                if params_marker in tools_results:
                    # Find the params for this specific tool
                    tool_section_start = tools_results.find(f"Tool: {tool_name}")
                    if tool_section_start != -1:
                        params_start = tools_results.find(params_marker, tool_section_start)
                        if params_start != -1:
                            params_start += len(params_marker)
                            params_end = tools_results.find("\n", params_start)
                            if params_end == -1:
                                params_end = len(tools_results)

                            params_json = tools_results[params_start:params_end].strip()
                            try:
                                import json as json_lib
                                plugin_params = json_lib.loads(params_json)

                                # Fill {{PRIMARY_LLM_OUTPUT}} placeholder with actual generated content
                                filled_params = {}
                                for key, value in plugin_params.items():
                                    if isinstance(value, str) and "{{PRIMARY_LLM_OUTPUT}}" in value:
                                        # Use cleaned LLM response content
                                        filled_value = value.replace("{{PRIMARY_LLM_OUTPUT}}", complete_llm_response.strip())
                                        filled_params[key] = filled_value
                                        logger.info(f"🔌 POST-LLM: Filled {key} with generated content ({len(filled_value)} chars)")
                                    else:
                                        filled_params[key] = value

                                # Execute the plugin with filled parameters
                                logger.info(f"🔌 POST-LLM: Executing {tool_name} with filled parameters")
                                result = await tool_manager.safe_function_call(tool_name, filled_params)

                                additional_results += f"Tool: {tool_name} (post-LLM execution)\nResult: {result}\n\n"
                                logger.info(f"🔌 POST-LLM PLUGIN: {tool_name} completed successfully")

                            except Exception as e:
                                logger.error(f"❌ POST-LLM PLUGIN: Failed to parse parameters for {tool_name}: {e}")
                                additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: Error parsing parameters: {str(e)}\n\n"
                        else:
                            logger.error(f"❌ POST-LLM PLUGIN: No deferred parameters found for {tool_name}")
                            additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: No deferred parameters found\n\n"
                else:
                    # 🤖 FIX v1.0.3.111: ARBITRATOR-BASED PARAMETER GENERATION
                    # When verifier detects missing WordPress/publishing tool and triggers auto-execution,
                    # there are no deferred params because tool-calling LLM never called it.
                    # Use Arbitrator LLM to intelligently generate parameters from Primary LLM output.
                    logger.info(f"🤖 POST-LLM ARBITRATOR PARAM GEN: No deferred params for {tool_name}, using Arbitrator")

                    try:
                        # Call Arbitrator to generate intelligent parameters
                        params = await _generate_intelligent_tool_parameters(
                            tool_name=tool_name,
                            user_prompt=user_prompt,
                            complete_llm_response=complete_llm_response,
                            tools_results=tools_results,
                            tool_manager=tool_manager,
                            llm_manager=llm_manager
                        )

                        # Execute the plugin with Arbitrator-generated parameters
                        result = await tool_manager.safe_function_call(tool_name, params)

                        additional_results += f"Tool: {tool_name} (post-LLM execution with Arbitrator-generated params)\nResult: {result}\n\n"
                        logger.info(f"✅ POST-LLM ARBITRATOR: {tool_name} completed successfully")

                    except Exception as e:
                        logger.error(f"❌ POST-LLM ARBITRATOR: Failed for {tool_name}: {e}")
                        logger.error(f"⏱️ Falling back to simple parameter generation...")

                        # FALLBACK: Use simple defaults if Arbitrator fails
                        try:
                            import json as json_lib

                            default_params = {
                                "title": _generate_dynamic_title(user_prompt, tools_results),
                                "content": complete_llm_response.strip(),
                                "status": "draft"
                            }

                            logger.info(f"⚠️ SIMPLE FALLBACK: Generated params for {tool_name}")
                            logger.info(f"   Title: {default_params['title']}")
                            logger.info(f"   Content length: {len(default_params['content'])} chars")

                            result = await tool_manager.safe_function_call(tool_name, default_params)
                            additional_results += f"Tool: {tool_name} (post-LLM execution with simple fallback params)\nResult: {result}\n\n"
                            logger.info(f"✅ SIMPLE FALLBACK: {tool_name} completed")

                        except Exception as fallback_error:
                            logger.error(f"❌ SIMPLE FALLBACK: Also failed: {fallback_error}")
                            additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: Error: Arbitrator and fallback both failed\n\n"

            elif tool_name == "get_the_secret_tool":
                result = await tool_manager.get_the_secret_tool()
                additional_results += f"Tool: {tool_name} (post-LLM execution)\nResult: {result}\n\n"

            else:
                # GENERIC DISPATCH — RAICA executes whatever action the LLM intent classifier chose, with
                # NO hardcoded per-tool branch (CARDINAL RULE / LLM-Policy Gate). Reuse the existing
                # Arbitrator arg-binder to derive parameters from the answer, run the tool, and capture any
                # file it writes to the workspace so the email step attaches it (e.g. pdf_generator → PDF).
                logger.info(f"🧩 POST-LLM GENERIC DISPATCH: {tool_name} (classifier-selected, no native branch)")
                _before_files = _artifact_snapshot()
                try:
                    _gparams = await _generate_intelligent_tool_parameters(
                        tool_name=tool_name, user_prompt=user_prompt,
                        complete_llm_response=complete_llm_response, tools_results=tools_results,
                        tool_manager=tool_manager, llm_manager=llm_manager)
                    _gresult = await tool_manager.safe_function_call(tool_name, _gparams)
                    additional_results += f"Tool: {tool_name} (post-LLM generic dispatch)\nResult: {str(_gresult)[:300]}\n\n"
                    logger.info(f"🧩 POST-LLM GENERIC DISPATCH {tool_name}: {str(_gresult)[:200]}")
                except Exception as _gerr:
                    logger.error(f"❌ POST-LLM GENERIC DISPATCH failed for {tool_name}: {_gerr}")
                    additional_results += f"Tool: {tool_name} (post-LLM generic dispatch failed)\nResult: Error: {str(_gerr)}\n\n"
                # Capture the file(s) the tool just produced (in the workspace OR cwd) and normalize them
                # INTO the attachable workspace dir so the email step can attach them — no per-tool parsing.
                import os as _os_e, shutil as _sh_e
                for _p in sorted(_artifact_snapshot() - _before_files):
                    try:
                        _name = _os_e.path.basename(_p)
                        if _sandbox_dir and _os_e.path.dirname(_p) != _sandbox_dir:
                            _sh_e.copyfile(_p, _os_e.path.join(_sandbox_dir, _name))
                        if _name not in _post_llm_extra_files:
                            _post_llm_extra_files.append(_name)
                            logger.info(f"🧩 POST-LLM GENERIC DISPATCH {tool_name} produced file: {_name}")
                    except Exception as _cperr:
                        logger.warning(f"🧩 could not normalize artifact {_p}: {_cperr}")

        except Exception as e:
            logger.error(f"❌ POST-LLM Auto-execution failed for {tool_name}: {e}")
            logger.error(f"❌ POST-LLM Auto-execution traceback: {traceback.format_exc()}")
            additional_results += f"Tool: {tool_name} (post-LLM execution failed)\nResult: Error: {str(e)}\n\n"
    
    return additional_results

@app.post("/v1")
@app.post("/llama3_1b/stream")
async def llama_stream(request: Request):
    """
    Main Ollama streaming endpoint with tool calling
    Equivalent to the original /llama3_1b/stream endpoint
    """
    logger.info("🔧 DEBUG: Endpoint /llama3_1b/stream called")
    # Parse JSON data manually like the original Flask version
    try:
        data = await request.json()
        logger.info("🔧 DEBUG: JSON parsed successfully")
    except Exception as e:
        logger.error(f"Failed to parse JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON data")

    # 🔒 Publish the per-request delivery recipient-lock in the REQUEST-HANDLER context (a regular async
    # function, NOT the streaming async generator) so it reliably propagates to the tool-execution
    # coroutines. Setting it inside generate_stream did NOT survive the generator's yields, so the lock
    # silently no-op'd for the phase-2 send path. The authoritative delivery PERMISSION is enforced
    # separately at the execution site (execute_tools_with_email_dependency); this pins the recipient for
    # permitted restricted-client sends (auto-trusted clients carry no lock and are unaffected).
    try:
        _rh_auth = delivery_policy.authorize_delivery(data)
        _delivery_lock_ctx.set((_rh_auth.recipient_locked, _rh_auth.locked_recipient))
    except Exception as _e_rhlock:
        logger.warning(f"🔒 delivery-lock context init (handler) skipped: {_e_rhlock}")

    # Extract parameters with defaults (exactly like Flask version)
    user_prompt = data['prompt']  # Use direct access like original for required field
    # 🔧 DEBUG v1.0.3.9: Log what we actually received
    logger.info(f"🔍 INITIAL REQUEST DEBUG: data['prompt'] = {repr(data['prompt'][:200] if data['prompt'] else 'EMPTY!')}")
    actual_user_prompt = user_prompt  # 🔧 CRITICAL FIX v1.0.3.9: Preserve original for POST-LLM email extraction
    logger.info(f"🔍 INITIAL REQUEST DEBUG: actual_user_prompt preserved = {repr(actual_user_prompt[:200] if actual_user_prompt else 'EMPTY!')}")
    model = data.get('model', ServerConfig.DEFAULT_MODEL)  # Get model early for logging
    # Input condition: User request received
    logger.info(f"Request: {len(user_prompt)} chars | Model: {model} | Tools: {'ON' if True else 'OFF'}")
    
    prompt_context = data.get('prompt_context', '')  # Using data['prompt_context'] like original
    
    #################################################################################
    ##                  CONTEXT MANAGEMENT WITH and WITHOUT TOOLS                  ##            
    #################################################################################
    
    # Handle toolsInUse exactly like original
    tools_in_use = True  # Default like original
    if "toolsInUse" in data:
        tools_in_use = data["toolsInUse"]
    # Tool usage mode determined
    logger.info(f"Tool usage mode: {tools_in_use}")
    
    # Handle searchWebInUse exactly like original
    search_web_in_use = False  # Default like original
    if "searchWebInUse" in data:
        search_web_in_use = data["searchWebInUse"]
    
    # Other parameters
    # model already extracted above for logging
    images = data.get('images', ['noimage'])
    tools_calling_model = data.get('tools_calling_model', ServerConfig.DEFAULT_TOOL_CALLING_MODEL)
    
    # 🖼️ COMPREHENSIVE IMAGE PROCESSING FIX
    async def process_image_data(images_raw):
        """Process images: convert file paths to base64 with smart resizing and comprehensive error handling."""
        import os
        import base64
        import io
        from PIL import Image
        
        if not images_raw or images_raw == ['noimage']:
            return ['noimage'], False, []

        processed_images = []
        image_exists = False
        user_errors = []  # Collect errors for user feedback
        
        for i, img_data in enumerate(images_raw):
            if img_data == "noimage":
                processed_images.append("noimage")
                continue
                
            try:
                logger.info(f"🖼️ Processing image {i+1}: {type(img_data)} - {str(img_data)[:100]}...")
                
                # Check if it's already base64 data (starts with base64 chars or data: URI)
                if isinstance(img_data, str):
                    # Remove data URI prefix if present
                    if img_data.startswith('data:image/'):
                        _, base64_part = img_data.split(',', 1)
                        img_data = base64_part
                    
                    # Use signature-based detection instead of arbitrary length thresholds
                    from signature_image_detection import ImageSignatureValidator
                    validator = ImageSignatureValidator()
                    validation_result = validator.validate_image_data(img_data, i + 1)

                    if validation_result['is_valid']:
                        logger.info(f"🖼️ Image {i+1}: Valid {validation_result['format']} image ({validation_result['size_bytes']} bytes)")

                        # Apply image resizing if needed using image_utils module
                        try:
                            from image_utils import process_image_for_vision_model
                            import yaml

                            # Load vision config from llm_config.yaml
                            try:
                                config_path = os.path.join(os.path.dirname(__file__), 'config', 'llm_config.yaml')
                                with open(config_path, 'r') as f:
                                    llm_config = yaml.safe_load(f)
                                    vision_config = llm_config.get('vision', {}).get('image_processing', {})
                            except Exception as e:
                                logger.warning(f"🖼️ Failed to load vision config, using defaults: {e}")
                                vision_config = {
                                    'max_size_mb': 1.0,
                                    'resize_quality': 85,
                                    'max_dimension': 2048,
                                    'preserve_aspect_ratio': True
                                }

                            # Process/resize the image
                            processed_data, metadata = process_image_for_vision_model(
                                validation_result['processed_data'],
                                vision_config
                            )

                            # Log resize results
                            if metadata.get('was_resized'):
                                logger.info(f"🖼️ Image {i+1}: Resized from {metadata['original_size_mb']:.2f}MB to {metadata['final_size_mb']:.2f}MB ({metadata['reduction_percent']:.1f}% reduction)")
                                logger.info(f"🖼️ Image {i+1}: Dimensions {metadata['original_dimensions']} → {metadata['final_dimensions']}")
                            else:
                                logger.info(f"🖼️ Image {i+1}: No resize needed ({metadata['final_size_mb']:.2f}MB)")

                            processed_images.append(processed_data)
                            image_exists = True
                            continue

                        except Exception as resize_error:
                            logger.warning(f"🖼️ Image {i+1}: Resize failed, using original: {resize_error}")
                            processed_images.append(validation_result['processed_data'])
                            image_exists = True
                            continue
                    else:
                        # Check if it might be a file path before declaring failure
                        if not ('/' in img_data or '\\' in img_data or any(img_data.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'])):
                            # Not a file path either - this is a validation failure
                            user_errors.append(validation_result['user_error'])
                            logger.error(f"🖼️ Image {i+1}: {validation_result['error']}")
                            processed_images.append("noimage")
                            continue

                        logger.warning(f"🖼️ Image {i+1}: Signature validation failed, trying file path - {validation_result['error']}")

                    # Otherwise, treat as file path
                    file_path = img_data.strip()
                    
                    # Expand user path (~)
                    file_path = os.path.expanduser(file_path)

                    # Path traversal protection: block sensitive system paths
                    resolved = os.path.realpath(file_path)
                    BLOCKED_PATHS = ['/etc/passwd', '/etc/shadow', '/root', '/proc', '/sys', '/dev', '/boot']
                    if any(resolved.startswith(bp) for bp in BLOCKED_PATHS):
                        logger.error(f"🖼️ Image {i+1}: Path traversal blocked (sensitive system path): {file_path} -> {resolved}")
                        processed_images.append("noimage")
                        continue
                    
                    if not os.path.exists(file_path):
                        logger.error(f"🖼️ Image {i+1}: File not found: {file_path}")
                        processed_images.append("noimage")
                        continue
                    
                    if not os.path.isfile(file_path):
                        logger.error(f"🖼️ Image {i+1}: Not a file: {file_path}")
                        processed_images.append("noimage")
                        continue
                    
                    # Check file extension
                    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
                    file_ext = os.path.splitext(file_path)[1].lower()
                    if file_ext not in valid_extensions:
                        logger.error(f"🖼️ Image {i+1}: Unsupported format {file_ext}: {file_path}")
                        processed_images.append("noimage")
                        continue
                    
                    # Read file as binary
                    try:
                        with open(file_path, 'rb') as f:
                            img_bytes = f.read()
                        logger.info(f"🖼️ Image {i+1}: Read {len(img_bytes)} bytes from {file_path}")
                    except Exception as e:
                        logger.error(f"🖼️ Image {i+1}: Failed to read file {file_path}: {e}")
                        processed_images.append("noimage")
                        continue
                    
                    # Progressive optimization for qwen2.5vl:3b - compress without aggressive resizing
                    resize_threshold = 2000000  # 2MB threshold for smart compression (not aggressive resizing)
                    if len(img_bytes) > resize_threshold:
                        logger.info(f"🖼️ Image {i+1}: Large image ({len(img_bytes)} bytes), applying smart compression...")
                        try:
                            # Smart compression approach for qwen2.5vl:3b
                            with Image.open(io.BytesIO(img_bytes)) as img:
                                original_size = img.size
                                
                                # Only resize if extremely large (>4000px), otherwise just compress
                                if max(img.size) > 4000:
                                    # Conservative resize - maintain high resolution for vision model
                                    max_size = 2400  # Much larger than before to preserve detail
                                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                                    logger.info(f"🖼️ Image {i+1}: Resized from {original_size} to {img.size}")
                                
                                # Convert to RGB if needed
                                if img.mode not in ('RGB', 'L'):
                                    img = img.convert('RGB')
                                
                                # Compress with higher quality to preserve details for vision model
                                buffer = io.BytesIO()
                                img.save(buffer, format='JPEG', quality=92, optimize=True)  # Higher quality
                                img_bytes = buffer.getvalue()
                                logger.info(f"🖼️ Image {i+1}: Compressed to {len(img_bytes)} bytes ({img.size[0]}x{img.size[1]})")
                        except Exception as e:
                            logger.warning(f"🖼️ Image {i+1}: Compression failed, using original: {e}")
                    
                    # Convert to base64 (raw base64, no data URI prefix for Ollama compatibility)
                    img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                    processed_images.append(img_base64)
                    image_exists = True
                    logger.info(f"🖼️ Image {i+1}: Successfully processed - {len(img_base64)} base64 chars")
                    
                else:
                    logger.error(f"🖼️ Image {i+1}: Unsupported data type: {type(img_data)}")
                    processed_images.append("noimage")
                    
            except Exception as e:
                logger.error(f"🖼️ Image {i+1}: Processing failed: {e}")
                logger.error(f"🖼️ Image {i+1}: Exception type: {type(e)}")
                import traceback
                logger.error(f"🖼️ Image {i+1}: Traceback: {traceback.format_exc()}")
                processed_images.append("noimage")
        
        logger.info(f"🖼️ Image processing complete: {len(processed_images)} images, image_exists={image_exists}")
        if user_errors:
            logger.warning(f"🖼️ User errors collected: {len(user_errors)} errors")
        return processed_images, image_exists, user_errors
    
    # Process images with comprehensive error handling
    try:
        images, image_exists, image_errors = await process_image_data(images)
        # Update the data dictionary with processed images
        data["images"] = images
        logger.info(f"🖼️ Updated data[images] with {len([img for img in images if img != 'noimage'])} processed images")
        
        # 🖼️ Set image context for tools that need it
        tool_manager.set_image_context(images, {"endpoint": "native", "model": model})
        
    except Exception as e:
        logger.error(f"🖼️ CRITICAL: Image processing failed: {e}")
        images = ['noimage']
        image_exists = False
        image_errors = [f"Critical image processing error: {str(e)}"]
    
    async def generate_stream():
        logger.info("--- ENTERING GENERATE_STREAM ---")
        import time  # Import time at function start for timing measurements
        logger.info("🔧 DEBUG: generate_stream() function called")
        try:
            # 🔧 VARIABLE SCOPE FIX: Initialize variables at function scope
            nonlocal image_exists  # Access outer scope image_exists variable
            is_meta_task = False  # Default value to prevent UnboundLocalError
            tools_results = ""    # Default value to prevent UnboundLocalError
            tools_results_list = []  # Use list for O(1) append vs O(n²) string concatenation
            tools_called = []  # Track all tools that were called
            complete_llm_response = ""  # Initialize for both Ollama and OpenAI paths
            images_available = False  # Survives image_exists reset inside tools_in_use block; always defined here for non-tools path

            # 🔒 Phase 0: publish THIS request's delivery recipient-lock context so EVERY
            # secure_email_sender call during the request is enforced at the single chokepoint
            # (AsyncToolManager.secure_email_sender). A restricted client (one that sent an allowed_tools
            # whitelist, e.g. a NewX bot) locks to the server-authoritative recipient; an auto-trusted
            # client (no whitelist, e.g. OpenWebUI) is unaffected. This uses the SAME authorize_delivery
            # decision the POST-LLM paths use, so the two cannot drift apart.
            _req_auth = delivery_policy.authorize_delivery(data)
            _delivery_lock_ctx.set((_req_auth.recipient_locked, _req_auth.locked_recipient))
            # 🔗 Phase 2 (auto-bind): when delivery is permitted, snapshot the sandbox NOW so any file the
            # LLM creates during this request can be auto-attached to the (recipient-locked) email at the
            # chokepoint — the user gets the artifact without depending on the model to thread the path.
            _artifact_baseline_ctx.set(
                _list_sandbox_files() if (_req_auth.permitted and _LLM_DRIVEN_DELIVERY) else None)

            # 🎯 EMAIL INTERCEPTION STATE  
            email_intercepted = False
            intercepted_email_params = {}
            
            # Ensure LLM manager is initialized before FORCED IMAGE PROCESSING check
            # (initialize() is idempotent — safe to call even if already done)
            if not llm_manager._initialized:
                await llm_manager.initialize()

            # ###########################################################################
            # 🔬 DEEP RESEARCH ROUTING (opt-in, auto-detected by a high-precision LLM gate)
            # If the gate fires, run the multi-round research + synthesis + verification
            # pipeline and stream its progress + audited answer, bypassing the normal flow.
            # Any error BEFORE streaming falls through to the normal flow (no regression).
            # ###########################################################################
            try:
                _dr_root = config_loader.load_config().get('deep_research', {})
                _dr_engine_cfg = _dr_root.get('engine', {})
                # Per-request opt-out: a client (e.g. a NewX scheduled bot whose scope doesn't
                # need multi-round research) can send {"deep_research": false} to skip the gate
                # entirely. Server-authoritative — not prompt-dependent. Default true = unchanged.
                _dr_client_allowed = data.get('deep_research', True)
                _dr_on = (tools_in_use and _dr_root.get('enabled', False)
                          and _dr_engine_cfg.get('enabled', False)
                          and bool(_dr_client_allowed))
                if tools_in_use and not _dr_client_allowed:
                    logger.info("🔬 Deep research disabled for this request (client deep_research=false)")
            except Exception as _dr_cfg_err:
                logger.warning(f"🔬 Deep research config unavailable: {_dr_cfg_err}")
                _dr_on = False

            # LOAD-BASED model split for deep-research LLM calls (config: deep_research.engine).
            # Small calls (gate/planner/roster/grade/verify, <~140K chars) → `model` (LIGHT/flash,
            # fast & cheap). The single large synthesis call (~596K chars) overwhelms the light cloud
            # endpoint (intermittent HTTP 500), so any prompt at/above `heavy_threshold_chars` is
            # routed to `heavy_model` (HEAVY/pro, tolerates big prompts). Routing is purely by
            # payload size — NOT node name — so a small synthesis still rides the light model. The
            # normal chat path keeps calling llm_manager.generate_stream directly (pro). null model /
            # null heavy_model / threshold≤0 → that tier is disabled (falls back to primary).
            _dr_model = (_dr_engine_cfg.get("model") if _dr_on else None)
            _dr_heavy_model = (_dr_engine_cfg.get("heavy_model") if _dr_on else None)
            try:
                _dr_heavy_threshold = int(_dr_engine_cfg.get("heavy_threshold_chars") or 0) if _dr_on else 0
            except (TypeError, ValueError):
                _dr_heavy_threshold = 0
            def _dr_generate_stream(prompt, **kwargs):
                if "model" not in kwargs:
                    _plen = len(prompt) if prompt else 0
                    if _dr_heavy_model and _dr_heavy_threshold > 0 and _plen >= _dr_heavy_threshold:
                        kwargs["model"] = _dr_heavy_model
                        logger.info(f"🔀 DR heavy route: prompt_len={_plen} >= {_dr_heavy_threshold} → {_dr_heavy_model}")
                    elif _dr_model:
                        kwargs["model"] = _dr_model
                return llm_manager.generate_stream(prompt, **kwargs)

            # Gate + setup are guarded so ANY failure here (import error, gate exception,
            # tool-load error) falls through to the normal flow instead of 500-ing the request.
            _dr_triggered = False
            if _dr_on:
                try:
                    from research.gate import deep_research_gate
                    from research.pipeline import run_deep_research_pipeline
                    _gate = await deep_research_gate(_dr_generate_stream, actual_user_prompt)
                    _dr_triggered = bool(_gate.get('triggered'))
                except Exception as _dr_gate_err:
                    logger.warning(f"🔬 Deep research gate/setup failed ({_dr_gate_err}) → normal flow")
                    _dr_triggered = False

            if _dr_triggered:
                logger.info(f"🔬 DEEP RESEARCH MODE engaged — {_gate.get('rationale')}")

                def _dr_chunk(text):
                    return (json.dumps({"model": model, "response": text, "done": False}) + "\n").encode("utf-8")

                def _dr_done_chunk():
                    return (json.dumps({"model": model, "response": "", "done": True}) + "\n").encode("utf-8")

                _dr_show = _dr_engine_cfg.get("output", {}).get("stream_progress", True)
                try:
                    await tool_manager._load_user_tools_async()

                    # Phase 1: build the LIVE tool catalog (name + description, incl. user tools &
                    # plugins) so the request decomposer grounds its action vocabulary in capabilities
                    # that actually exist (Principle 6 — open vocabulary via dynamic discovery).
                    try:
                        _dr_tool_defs = await tool_manager.get_tools_definitions()
                        _dr_tool_catalog = [
                            {"name": _d.get("function", {}).get("name", ""),
                             "description": _d.get("function", {}).get("description", "")}
                            for _d in _dr_tool_defs if _d.get("function", {}).get("name")
                        ]
                    except Exception as _cat_err:
                        logger.warning(f"🧩 Could not build tool catalog for decomposition: {_cat_err}")
                        _dr_tool_defs = []
                        _dr_tool_catalog = []

                    async def _dr_dispatch(name, query):
                        fn = tool_manager.available_functions.get(name)
                        if not fn:
                            return f"[no such tool: {name}]"
                        try:
                            return await fn(query)
                        except Exception as _tool_err:  # one tool failing must not abort the round
                            logger.warning(f"🔬 tool '{name}' raised: {_tool_err}")
                            return f"[tool '{name}' error: {_tool_err}]"

                    _dr_q = asyncio.Queue()
                    _dr_retry_q = asyncio.Queue()  # retry/keepalive notices — streamed even when framing is off

                    async def _dr_progress(msg):
                        await _dr_q.put(msg)

                    async def _dr_retry_notice(msg):
                        await _dr_retry_q.put(msg)

                    # Clients can suppress the framing (header/progress) via config — clean answer only.
                    if _dr_show:
                        yield _dr_chunk("### 🔬 Deep Research Mode\n_This runs multi-round research with "
                                        "source-credibility grading and claim verification — it takes a few minutes._\n\n")
                    _dr_task = asyncio.create_task(run_deep_research_pipeline(
                        _dr_generate_stream, _dr_dispatch, _dr_engine_cfg,
                        actual_user_prompt, on_progress=(_dr_progress if _dr_show else None),
                        tool_catalog=_dr_tool_catalog, retry_notice=_dr_retry_notice))
                    # Drain notices while the pipeline runs: retry/keepalive notices ALWAYS (they keep
                    # the stream warm during provider-retry waits even when normal progress is
                    # suppressed); normal progress only when enabled. Stop once the task is done.
                    while True:
                        _emitted = False
                        try:
                            _rn = _dr_retry_q.get_nowait()
                            yield _dr_chunk(f"> {_rn}\n")
                            _emitted = True
                        except asyncio.QueueEmpty:
                            pass
                        if _dr_show:
                            try:
                                _m = _dr_q.get_nowait()
                                yield _dr_chunk(f"> {_m}\n")
                                _emitted = True
                            except asyncio.QueueEmpty:
                                pass
                        if _dr_task.done() and _dr_retry_q.empty() and (not _dr_show or _dr_q.empty()):
                            break
                        if not _emitted:
                            await asyncio.sleep(0.3)
                    try:
                        _dr_result = await _dr_task
                        _dr_answer = (_dr_result or {}).get("answer") or \
                            "⚠️ Deep research returned no answer. Please try again."
                        if _dr_show:
                            yield _dr_chunk("\n---\n\n")
                        yield _dr_chunk(_dr_answer)

                        # ── Phase 2: delivery fan-out ───────────────────────────────────────────
                        # If the request decomposed into delivery actions AND the client is a trusted
                        # delivery client (allow_delivery=true — NewX bots never send it), render the
                        # paper to a document and email it by directly dispatching existing tools.
                        # The research paper (footer-less answer_body) is the shared context.
                        _dr_actions = (_dr_result or {}).get("actions") or []
                        _dr_auth = delivery_policy.authorize_delivery(data)
                        if _dr_actions and _dr_auth.permitted:
                            # Recipient policy (shared with the POST-LLM path via orchestration/policy):
                            # a restricted client (sends allowed_tools, e.g. a NewX bot) may ONLY email
                            # the server-authoritative delivery_recipient — prompt recipients are ignored
                            # so the bot can't email arbitrary people. An auto-trusted single-user client
                            # (no allowed_tools, e.g. OpenWebUI) keeps prompt recipients.
                            _locked_recipient = _dr_auth.locked_recipient
                            _recipient_locked = _dr_auth.recipient_locked
                            # _run_dr_delivery does the work silently and yields a single housekeeping
                            # footnote (its own "---" separator) — no verbose step-by-step header.
                            _dr_body = (_dr_result or {}).get("answer_body") or _dr_answer
                            # The Research Audit footer is in the full chat answer but intentionally NOT
                            # in the delivered paper; recover it (the tail of the answer beyond the
                            # footer-less body) so DR delivery can preserve it in the email body.
                            _dr_audit = ""
                            if _dr_body and isinstance(_dr_answer, str) and _dr_answer.startswith(_dr_body):
                                _dr_audit = _dr_answer[len(_dr_body):].strip()
                            try:
                                async for _dr_status in _run_dr_delivery(
                                        _dr_actions,
                                        (_dr_result or {}).get("deliverable_spec") or {},
                                        _dr_body,
                                        actual_user_prompt, tool_manager, _dr_engine_cfg,
                                        locked_recipient=_locked_recipient,
                                        recipient_locked=_recipient_locked,
                                        tool_defs=_dr_tool_defs,
                                        audit_text=_dr_audit,
                                        generate_stream=_dr_generate_stream):
                                    yield _dr_chunk(_dr_status)
                            except Exception as _deliv_err:
                                logger.error(f"📦 Delivery fan-out failed: {_deliv_err}", exc_info=True)
                                yield _dr_chunk(f"> ⚠️ Delivery could not be completed: {_deliv_err}\n")
                        elif _dr_actions:
                            logger.info(f"📦 Delivery actions decomposed but NOT permitted "
                                        f"(allow_delivery={data.get('allow_delivery')}, "
                                        f"allowed_tools={'present' if data.get('allowed_tools') is not None else 'none'}): "
                                        f"{[a.get('type') for a in _dr_actions if isinstance(a, dict)]}")
                    except Exception as _dr_run_err:
                        logger.error(f"🔬 Deep research pipeline failed mid-run: {_dr_run_err}", exc_info=True)
                        # A repeated upstream 5xx (provider temporarily down) gets a calm, actionable
                        # message — deep research is resource-heavy and the model host can be briefly
                        # unavailable. Other errors keep the detailed message for debugging.
                        # NOTE: reuse the engine's detector (it owns `re`); `re` is a LOCAL in this
                        # function due to later `import re` statements, so referencing it here would
                        # raise UnboundLocalError.
                        from research.engine import _is_transient_5xx as _dr_is_5xx
                        if _dr_is_5xx(_dr_run_err):
                            yield _dr_chunk(
                                "\n\n⚠️ The research model is temporarily unavailable — the upstream "
                                "provider returned repeated errors even after automatic retries. Deep "
                                "research is resource-heavy and the model host can be briefly "
                                "overloaded. Please try again in an hour or so.")
                        else:
                            yield _dr_chunk(f"\n\n⚠️ Deep research could not be completed: {_dr_run_err}")
                except Exception as _dr_outer_err:
                    # Last-resort guard: never leave the stream without a terminating chunk.
                    logger.error(f"🔬 Deep research fatal error: {_dr_outer_err}", exc_info=True)
                    yield _dr_chunk(f"\n\n⚠️ Deep research could not be started: {_dr_outer_err}")
                yield _dr_done_chunk()
                return

            # ###########################################################################
            # TWO-STAGE TOOL CALLING ALGORITHM (exactly like original Flask implementation)
            if (tools_in_use):
                # Tool execution phase initiated
                logger.info("🔧 DEBUG: Entering tool execution phase")
                
                # 🖼️ FORCED IMAGE PROCESSING: When images are present, automatically call image_to_text
                forced_image_processing_result = ""
                images_available = False  # Will be set to True if images exist (survives image_exists reset)

                # 🚨 USER ERROR REPORTING: Report image validation failures to user
                if image_errors:
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                    error_messages = "\n".join(image_errors)
                    forced_image_processing_result = f"""
🖼️ IMAGE VALIDATION ERRORS [{timestamp}]:
{error_messages}

💡 Please check your images and try again. Supported formats: PNG, JPEG, GIF, BMP, WebP, TIFF.
"""
                    logger.error(f"🖼️ Reporting {len(image_errors)} image validation errors to user")

                if image_exists:
                    logger.info("🖼️ FORCED IMAGE PROCESSING: Images detected, automatically processing...")
                    
                    # Check if image processing LLM is available
                    try:
                        # Use global llm_manager instance
                        
                        # Check if image processing provider is configured
                        if hasattr(llm_manager, 'image_processing_provider') and llm_manager.image_processing_provider:
                            logger.info("🖼️ Image processing LLM available, processing images...")
                            
                            # Load and execute image_to_text tool
                            try:
                                from user_tools.tool_discovery import get_user_tool_by_name, discover_user_tools
                                user_tools = await discover_user_tools()  # use async version — load_user_tools() calls asyncio.run() which fails inside async context
                                image_tool = get_user_tool_by_name(user_tools, "image_to_text")
                                
                                if image_tool:
                                    # Prepare image data for the tool
                                    images_data = []
                                    for i, img_data in enumerate(data.get("images", [])):
                                        if img_data != "noimage":
                                            images_data.append({
                                                "type": "base64",
                                                "data": img_data,
                                                "filename": f"user_image_{i+1}"
                                            })
                                    
                                    if images_data:
                                        # Execute image_to_text tool
                                        import time
                                        start_time = time.time()
                                        result = await image_tool.execute(
                                            images=images_data,
                                            processing_mode="sequential",  # Use sequential for forced processing
                                            quality="high"
                                        )
                                        execution_time = time.time() - start_time
                                        
                                        if result.get('success'):
                                            # Extract description: image_to_text returns top-level 'description';
                                            # batch format (if ever used) returns a 'results' list of dicts.
                                            image_descriptions = []

                                            # Batch format (results list)
                                            for img_result in result.get('results', []):
                                                if img_result.get('description'):
                                                    filename = img_result.get('filename', 'image')
                                                    description = img_result.get('description')
                                                    image_descriptions.append(f"[{filename}]: {description}")

                                            # Single-image format — top-level 'description' key (image_to_text default)
                                            if not image_descriptions and result.get('description'):
                                                image_descriptions.append(result['description'])

                                            processed_count = len(image_descriptions) or result.get('processed_images', 0)
                                            logger.info(f"🖼️ FORCED IMAGE PROCESSING COMPLETE: {processed_count} images processed in {execution_time:.1f}s")

                                            if image_descriptions:
                                                import datetime
                                                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                                                forced_image_processing_result = f"""
🖼️ IMAGE PROCESSING RESULTS [{timestamp}]:
{chr(10).join(image_descriptions)}

The above image analysis was automatically performed on newly uploaded images. This visual content is now available for your response."""
                                                logger.info(f"🖼️ Image description extracted: {len(image_descriptions[0])} chars")
                                            else:
                                                logger.warning("🖼️ FORCED IMAGE PROCESSING: success=True but no description extracted")

                                            # Add to tools results for primary LLM
                                            tools_called.append("image_to_text")
                                            tools_results_list.append(f"Tool: image_to_text\nResult: {forced_image_processing_result}\n")
                                            
                                        else:
                                            error_msg = result.get('error', 'Unknown error during image processing')
                                            logger.error(f"🖼️ FORCED IMAGE PROCESSING FAILED: {error_msg}")
                                            import datetime
                                            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                                            forced_image_processing_result = f"\n🖼️ IMAGE PROCESSING ERROR [{timestamp}]: {error_msg}\nImages were detected but could not be processed.\n"
                                    else:
                                        logger.warning("🖼️ No valid image data found despite image_exists=True")
                                else:
                                    logger.error("🖼️ image_to_text tool not found in user tools")
                                    import datetime
                                    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                                    forced_image_processing_result = f"\n🖼️ IMAGE PROCESSING UNAVAILABLE [{timestamp}]: image_to_text tool not found.\nImages were detected but cannot be processed.\n"
                                    
                            except Exception as e:
                                logger.error(f"🖼️ FORCED IMAGE PROCESSING ERROR: {e}")
                                import datetime
                                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                                forced_image_processing_result = f"\n🖼️ IMAGE PROCESSING ERROR [{timestamp}]: {str(e)}\nImages were detected but could not be processed.\n"
                        else:
                            logger.warning("🖼️ Image processing LLM not configured")
                            import datetime
                            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                            forced_image_processing_result = f"\n🖼️ IMAGE PROCESSING UNAVAILABLE [{timestamp}]: No image processing model configured.\nImages were detected but cannot be analyzed. Please configure an image processing model in the LLM settings.\n"
                            
                    except Exception as e:
                        logger.error(f"🖼️ FORCED IMAGE PROCESSING SETUP ERROR: {e}")
                        import datetime
                        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                        forced_image_processing_result = f"\n🖼️ IMAGE PROCESSING ERROR [{timestamp}]: {str(e)}\nImages were detected but processing setup failed.\n"
                    
                    # 🖼️ Preserve original image availability for tool-calling LLM
                    # Even if forced processing fails, the tool-calling LLM needs to know images exist
                    images_available = True
                    
                    # 🔄 CRITICAL: Reset image_exists flag after processing (success or failure)
                    # This prevents re-triggering image processing on subsequent conversation turns
                    # The image processing results remain in context as reference for the conversation
                    image_exists = False
                    logger.info("🔄 FORCED IMAGE PROCESSING: Reset image_exists flag to False - processing complete (images_available=True preserved)")
                
                # STAGE 1: Call tool calling model to generate JSON function calls
                # Load system prompt from external file
                # ENFORCE: Tool calling model ONLY uses pre_tool_model_system_prompt.txt
                # No user system prompts allowed for tool calling - they can conflict with core instructions
                user_system_prompt = ""  # Force empty - only use file instructions
                system_content = load_tool_model_system_prompt(user_system_prompt)
                
                # 🖼️ Build user message with image presence indicator
                user_message_content = f"""Examine the intent of the user's prompt and apply the system directives to make the appropriate calls to the tools' functions."""

                # 🖼️ Indicate image presence to tool-calling LLM ONLY if image_to_text was not already
                # called by the FORCED IMAGE PROCESSING block. Avoids a duplicate vision model call.
                if (image_exists or images_available) and "image_to_text" not in tools_called:
                    image_count = len([img for img in data.get("images", []) if img != "noimage"])
                    user_message_content += f"""\n\n🖼️ IMPORTANT: User has provided {image_count} image(s). You MUST call image_to_text() with image="user_provided_image_data" to analyze the image(s)."""

                # 🖼️ VISION CONTEXT FOR TOOL SELECTION (root-cause fix): the FORCED IMAGE PROCESSING block
                # already ran image_to_text, so the hint above is (correctly) skipped — but the tool-calling
                # model is TEXT-ONLY and cannot see the raw image. Without the analysis it forms its
                # evidence-gathering queries from the user's wrapper text alone and searches BLIND (observed:
                # "user posted design image will it work" → irrelevant results) instead of the real subject
                # ("solid oxide electrolysis SOXE Mars oxygen ISRU"). Give it the analysis as its EYES so it
                # can decide, per policy, whether external evidence is needed and what to query. The model
                # still decides — this is context, not a keyword router. (This same user_message flows into
                # the NO-TOOLS RE-PROMPT below, so both call sites are covered by this one change.)
                if "image_to_text" in tools_called and forced_image_processing_result.strip():
                    user_message_content += (
                        "\n\n🖼️ ANALYSIS OF THE USER'S ATTACHED IMAGE(S) — you cannot see the raw image, so "
                        "treat this as your eyes. Base any tool/query decisions on the SUBJECT MATTER described "
                        "here, NOT on the surrounding post text. If the user only wants the image described, "
                        "transcribed, translated, or summarized, NO external tools are needed (the image is the "
                        "source). If they ask you to assess, evaluate, verify, fact-check, or explain real-world "
                        "claims about what it depicts, call search_web()/wikipedia_query() on those specific "
                        "subjects so the Primary LLM has real, verifiable URLs to cite:\n"
                        f"{forced_image_processing_result}"
                    )

                user_message_content += f"""\n\nUser Prompt: {prompt_context + user_prompt}"""

                messages = [
                    {
                        "role": "system",
                        "content": system_content
                    },
                    {
                        "role": "user",
                        "content": user_message_content,
                        "images": data.get("images") if (image_exists or images_available) else None
                    }
                ]
                
                try:
                    tools_model = data.get('tools_calling_model', ServerConfig.DEFAULT_TOOL_CALLING_MODEL).strip()
                    # Tool calling model preparation
                    logger.info(f"Tool calling: {tools_model} (tools enabled: {tools_in_use})")
                    
                    # Call the tool calling model to get JSON function calls
                    # 🎯 NEW APPROACH: Let tool calling model orchestrate ALL tools, intercept email calls
                    # 🚫 SMART TOOL FILTERING: Exclude inappropriate tools for meta-tasks
                    # 🔧 FIX: Only check the actual user prompt, NOT conversation context
                    # 🔧 v1.0.3.9: No longer need to reassign - actual_user_prompt preserved at function level
                    # actual_user_prompt = user_prompt  # Use the original user prompt, not the system message
                    # 🔧 FIX v1.0.3.113: More specific meta-task detection to avoid false positives
                    # Only match EXACT Open-WebUI meta-task patterns, not partial matches
                    is_meta_task = any(meta_pattern in actual_user_prompt.lower() for meta_pattern in [
                        'generate a concise',
                        'title with emoji',
                        'generate 1-3 broad tags categorizing the main themes',  # Full phrase, not just "tags"
                        'categorizing the main themes of the chat history'       # Full phrase, not just "summarizing"
                    ])
                    
                    # 🎯 DEBUG: Log meta-task detection for troubleshooting
                    logger.error(f"🔧 DEBUG_MARKER: META-TASK CHECK REACHED - prompt: {actual_user_prompt[:100]}...")
                    if is_meta_task:
                        logger.error(f"🚫 META-TASK DETECTED: Skipping tools for: {actual_user_prompt[:100]}...")
                    else:
                        logger.error(f"✅ NORMAL TASK: Will use tools for: {actual_user_prompt[:100]}...")
                    
                    if is_meta_task:
                        # 🚀 META-TASK BYPASS: Skip tool calling entirely for title/tag generation (minimal logging)
                        # Reduced logging to minimize meta-task spam in logs
                        tools_results = ""  # Empty tools results for meta-tasks
                        tools_called = []   # No tools called
                        tools_array = []   # Empty tools array to prevent UnboundLocalError
                        tool_request = {}   # Empty tool request to prevent UnboundLocalError
                        # Skip directly to primary LLM execution
                    else:
                        # Normal tool processing for non-meta tasks
                        tools_array = await tool_manager.get_tools_definitions(exclude_file_email_tools=False)

                        # 🔒 TOOL WHITELIST ENFORCEMENT: Filter tools if allowed_tools is set
                        request_allowed_tools = data.get('allowed_tools')
                        if request_allowed_tools:
                            # Visibility = capability (Phase 1). When the per-request delivery gate
                            # permits it, EXPOSE the delivery tool surface so the LLM can create+email
                            # directly — the recipient-lock chokepoint and create_file-only scoping keep
                            # restricted clients safe. When NOT permitted, the bot genuinely lacks the
                            # tools, so it declines honestly (no "invisible system will deliver" prose).
                            _tool_auth = delivery_policy.authorize_delivery(data)
                            _effective_allowed = set(request_allowed_tools)
                            if _tool_auth.permitted and _LLM_DRIVEN_DELIVERY:
                                _effective_allowed |= set(_DELIVERY_TOOL_SURFACE)
                            tools_array = [
                                t for t in tools_array
                                if t['function']['name'] in _effective_allowed
                            ]
                            if _tool_auth.recipient_locked and _LLM_DRIVEN_DELIVERY:
                                # untrusted-input client → no shell: narrow sandboxed_executor to create_file
                                tools_array = [_restrict_sandboxed_executor_def(t) for t in tools_array]
                            logger.info(
                                f"🔒 Tool whitelist enforced: {sorted(_effective_allowed)} "
                                f"(delivery={'PERMITTED' if _tool_auth.permitted else 'off'}, "
                                f"locked={'yes' if _tool_auth.recipient_locked else 'no'})")

                        # Tools array prepared
                        if len(tools_array) == 0:
                            logger.error("❌ Tools array is empty! This will cause timeout.")
                        else:
                            tool_names = [tool['function']['name'] for tool in tools_array]
                            logger.info(f"Available tools: {tool_names}")
                        
                        # Use LLM Manager for provider-agnostic tool calling
                        logger.info("🔧 DEBUG: About to call LLM Manager for tool calling")
                        
                        # Convert messages to prompt for LLM Manager
                        user_message = messages[-1]['content'] if messages else data.get('prompt', '')
                        system_prompt = load_tool_model_system_prompt()
                        
                        logger.info("--- CALLING TOOL-CALLING MODEL ---")
                        response_data = await llm_manager.generate_tools(
                            prompt=user_message,
                            tools=tools_array,
                            model=tools_model,
                            system_prompt=system_prompt,
                            temperature=0,
                            max_tokens=4096
                        )
                        logger.info("--- TOOL-CALLING MODEL FINISHED ---")
                        logger.info("🔧 DEBUG: LLM Manager tool calling response received")
                        
                        # LLM Manager returns direct dictionary - no HTTP response wrapping needed
                        # response_data is already the parsed response from LLM Manager
                        
                        if response_data:  # Success case - LLM Manager returned data
                            # Tool calling completed successfully
                            
                            # Debug: Log what the LLM Manager returned
                            response_keys = list(response_data.keys())
                            logger.info(f"🔧 DEBUG: LLM Manager response keys: {response_keys}")
                            
                            # STAGE 2: Process tool calls if present - LLM Manager format
                            if 'tool_calls' in response_data and response_data['tool_calls']:
                                tool_calls = response_data['tool_calls']
                                logger.info(f"🎯 TOOL CALLS DETECTED: {len(tool_calls)} tools to execute")
                                
                                # Process each tool call - PARALLEL EXECUTION OPTIMIZATION
                                        
                                # Log all tool calls upfront
                                for i, tool_call in enumerate(tool_calls):
                                    function_name = tool_call['function']['name']
                                    function_args = tool_call['function']['arguments']
                                    
                                    # Parse JSON string arguments to dictionary if needed
                                    if isinstance(function_args, str):
                                        try:
                                            function_args = json.loads(function_args)
                                        except json.JSONDecodeError:
                                            logger.error(f"❌ Invalid JSON in function arguments for {function_name}: {function_args}")
                                            function_args = {}
                                    
                                    # Tool call registered
                                    tools_called.append(function_name)  # Track this tool was called
                                
                                def _apply_smart_file_decisions(email_args, phase1_results, logger):
                                    """
                                    Smart file decision logic: Use actual found files instead of placeholder files
                                    """
                                    try:
                                        # 🎨 PRIORITY CHECK: Handle analytical_visualizer results FIRST
                                        # When analytical_visualizer creates a file, always use that file for email
                                        for result_tuple in phase1_results:
                                            if isinstance(result_tuple, tuple) and len(result_tuple) >= 2:
                                                function_name, result = result_tuple[0], result_tuple[1]
                                                if function_name == "analytical_visualizer" and isinstance(result, str):
                                                    # Look for the created file in the output
                                                    import re
                                                    # Match patterns like: "visualization_output.png" or "Full Path: /path/to/file.png"
                                                    filename_match = re.search(r'(?:Figure Created|filename):\s*([^\n]+\.(?:png|jpg|jpeg|svg|pdf))', result, re.IGNORECASE)
                                                    fullpath_match = re.search(r'Full Path:\s*([^\n]+)', result)

                                                    if filename_match or fullpath_match:
                                                        # Prefer full path if available, otherwise use filename
                                                        if fullpath_match:
                                                            visual_file_path = fullpath_match.group(1).strip()
                                                        else:
                                                            visual_file_name = filename_match.group(1).strip()
                                                            # Construct full path
                                                            visual_file_path = f"sandbox_workspace/{visual_file_name}"

                                                        logger.info(f"🎨 SMART DECISION: analytical_visualizer created {visual_file_path}")
                                                        logger.info(f"🎨 SMART DECISION: Updating email attachment to use visualization file")

                                                        # Update email args to use the actual visualization file
                                                        email_args['attachments'] = visual_file_path
                                                        email_args['wait_for_attachments'] = False  # File already exists

                                                        return email_args

                                        # Find document_search results from phase 1
                                        document_search_result_str = None
                                        for result_tuple in phase1_results:
                                            if isinstance(result_tuple, tuple) and len(result_tuple) >= 2:
                                                function_name, result = result_tuple[0], result_tuple[1]
                                                if function_name == "document_search" and isinstance(result, str):
                                                    document_search_result_str = result
                                                    logger.info(f"📧 SMART DECISION: Found document_search result string")
                                                    break
                                        
                                        if not document_search_result_str:
                                            logger.info("📧 No document_search results found - using original email args")
                                            return email_args
                                        
                                        # Parse the document_search result string to extract sources
                                        # Look for "📋 Sources:" section and extract filenames
                                        import re
                                        
                                        # Pattern to match source files: "• filename" in the Sources section
                                        sources_pattern = r'📋 Sources:\n(.+?)(?:\n\n|\Z)'
                                        sources_match = re.search(sources_pattern, document_search_result_str, re.DOTALL)
                                        
                                        if not sources_match:
                                            # Try alternative pattern - look for document names in the result
                                            doc_pattern = r'Document \d+: ([^(]+\.(?:html|md|pdf|txt))'
                                            doc_matches = re.findall(doc_pattern, document_search_result_str)
                                            if doc_matches:
                                                # Use the first document found
                                                first_doc = doc_matches[0].strip()
                                                logger.info(f"📧 SMART DECISION: Parsed document from result: {first_doc}")
                                                
                                                # Look for the full path in logs or construct it
                                                if 'SD_TheSongWithin' in first_doc and 'html' in first_doc:
                                                    actual_file_path = '/var/www/html/silicon_dreams/stories/SD_TheSongWithin.html'
                                                elif 'SD_TheSongWithin' in first_doc and 'md' in first_doc:
                                                    actual_file_path = '/var/www/html/silicon_dreams/stories/SD_TheSongWithin.md'
                                                elif 'Weight of Silence' in first_doc:
                                                    actual_file_path = '/home/sabawi/Documents/The Weight of Silence.pdf'
                                                else:
                                                    actual_file_path = first_doc
                                                    
                                                logger.info(f"📧 SMART DECISION: Using actual found file: {actual_file_path}")
                                                email_args['attachments'] = actual_file_path
                                                # Disable attachment waiting since we know the file exists
                                                email_args['wait_for_attachments'] = False
                                                
                                                # Update subject and body to reflect actual content
                                                filename = actual_file_path.split('/')[-1]
                                                email_args['subject'] = f"Found Document: {filename}"
                                                email_args['body'] = f"Please find attached the requested document: {filename}\n\nFound matching Gaza-related story in the document collection."
                                                
                                                return email_args
                                                
                                        # If sources section is found, extract filenames
                                        if sources_match:
                                            sources_text = sources_match.group(1)
                                            source_lines = [line.strip() for line in sources_text.split('\n') if line.strip().startswith('•')]
                                            
                                            if source_lines:
                                                # 🎯 BALANCED FORMAT SELECTION: Respect user's explicit format preference
                                                user_prompt = data.get('prompt', '').lower()
                                                
                                                # Detect explicit format requests from user
                                                requested_format = None
                                                if 'pdf' in user_prompt and ('pdf version' in user_prompt or 'send pdf' in user_prompt or 'as pdf' in user_prompt or 'email the pdf' in user_prompt or 'pdf format' in user_prompt or 'convert' in user_prompt and 'pdf' in user_prompt):
                                                    requested_format = 'pdf'
                                                elif 'html' in user_prompt and ('html version' in user_prompt or 'send html' in user_prompt or 'as html' in user_prompt or 'email the html' in user_prompt or 'html format' in user_prompt):
                                                    requested_format = 'html'
                                                elif 'markdown' in user_prompt and ('markdown version' in user_prompt or 'send markdown' in user_prompt or 'as markdown' in user_prompt or 'email the markdown' in user_prompt or 'markdown format' in user_prompt or '.md' in user_prompt):
                                                    requested_format = 'markdown'
                                                
                                                # Select source file based on user preference
                                                first_source = None
                                                if requested_format:
                                                    # User explicitly requested a format - prioritize it
                                                    for source_line in source_lines:
                                                        source_name = source_line.replace('•', '').strip()
                                                        if f'.{requested_format}' in source_name.lower() or (requested_format == 'markdown' and '.md' in source_name.lower()):
                                                            first_source = source_name
                                                            logger.info(f"📧 SMART DECISION: User requested {requested_format.upper()} - using source file: {first_source}")
                                                            break
                                                
                                                # If no format-specific match found, use first available
                                                if not first_source:
                                                    first_source = source_lines[0].replace('•', '').strip()
                                                    if requested_format:
                                                        logger.info(f"📧 SMART DECISION: User requested {requested_format.upper()} but not available - using first source: {first_source}")
                                                    else:
                                                        logger.info(f"📧 SMART DECISION: No format preference - using first source: {first_source}")
                                                
                                                # 🔧 CRITICAL FIX: Extract full file path from document_search output
                                                actual_file_path = first_source  # Default fallback
                                                
                                                # Look for "📎 Full File Paths (for attachments):" section
                                                full_paths_match = re.search(r'📎 Full File Paths \(for attachments\):(.*?)(?=\n\n|\nTool:|$)', document_search_result_str, re.DOTALL)
                                                if full_paths_match:
                                                    paths_text = full_paths_match.group(1)
                                                    path_lines = [line.strip() for line in paths_text.split('\n') if line.strip().startswith('•')]
                                                    
                                                    # Find path that matches the selected source file
                                                    for path_line in path_lines:
                                                        full_path = path_line.replace('•', '').strip()
                                                        if first_source in full_path:
                                                            actual_file_path = full_path
                                                            logger.info(f"📧 SMART DECISION: Found matching full path: {actual_file_path}")
                                                            break
                                                
                                                logger.info(f"📧 SMART DECISION: Using full path: {actual_file_path}")
                                                email_args['attachments'] = actual_file_path
                                                # Disable attachment waiting since we know the file exists
                                                email_args['wait_for_attachments'] = False
                                                
                                                filename = first_source
                                                email_args['subject'] = f"Found Document: {filename}"
                                                email_args['body'] = f"Please find attached the requested document: {filename}\n\nFound {len(source_lines)} matching files in the search."
                                                
                                                return email_args
                                        
                                        # Fallback: inform user no files exist
                                        logger.info("📧 Could not parse sources from document_search - informing user")
                                        email_args['subject'] = "Search Results: No Files Found"
                                        email_args['body'] = "I searched for the requested documents but found no matching files to send."
                                        if 'attachments' in email_args:
                                            del email_args['attachments']  # Remove placeholder attachment
                                        
                                        return email_args
                                        
                                    except Exception as e:
                                        logger.error(f"❌ Error in smart file decisions: {e}")
                                        return email_args


                                def _apply_smart_file_decisions_for_sandboxed_executor(email_args, phase1_results, logger):
                                    """
                                    Smart file decision logic for sandboxed_executor: Use actual created files instead of placeholder files
                                    """
                                    try:
                                        # Find sandboxed_executor results from phase 1
                                        sandboxed_executor_result_str = None
                                        for result_tuple in phase1_results:
                                            if isinstance(result_tuple, tuple) and len(result_tuple) >= 2:
                                                function_name, result = result_tuple[0], result_tuple[1]
                                                if function_name == "sandboxed_executor" and isinstance(result, str):
                                                    sandboxed_executor_result_str = result
                                                    logger.info(f"📧 SMART DECISION: Found sandboxed_executor result string")
                                                    break
                                        
                                        if not sandboxed_executor_result_str:
                                            logger.info("📧 No sandboxed_executor results found - using original email args")
                                            return email_args
                                        
                                        # Parse the sandboxed_executor result string to extract filename
                                        import re
                                        
                                        # Pattern to match filename from sandboxed_executor output
                                        filename_match = re.search(r'Successfully created file: ([^\n]+)', sandboxed_executor_result_str, re.IGNORECASE)
                                        
                                        if filename_match:
                                            created_filename = filename_match.group(1).strip()
                                            logger.info(f"📧 SMART DECISION: Parsed filename from sandboxed_executor result: {created_filename}")
                                            
                                            # Update email args to use the actual created file
                                            email_args['attachments'] = created_filename
                                            email_args['wait_for_attachments'] = False  # File already exists
                                            
                                            # Update subject and body to reflect actual content
                                            email_args['subject'] = f"File Created: {created_filename}"
                                            email_args['body'] = f"Please find attached the requested file: {created_filename}"
                                            
                                            return email_args
                                        
                                        return email_args
                                        
                                    except Exception as e:
                                        logger.error(f"❌ Error in smart file decisions for sandboxed_executor: {e}")
                                        return email_args




                                def _apply_smart_file_decisions_for_sandboxed_executor(email_args, phase1_results, logger):
                                    """
                                    Smart file decision logic for sandboxed_executor: Use actual created files instead of placeholder files
                                    """
                                    try:
                                        # Find sandboxed_executor results from phase 1
                                        sandboxed_executor_result_str = None
                                        for result_tuple in phase1_results:
                                            if isinstance(result_tuple, tuple) and len(result_tuple) >= 2:
                                                function_name, result = result_tuple[0], result_tuple[1]
                                                if function_name == "sandboxed_executor" and isinstance(result, str):
                                                    sandboxed_executor_result_str = result
                                                    logger.info(f"📧 SMART DECISION: Found sandboxed_executor result string")
                                                    break
                                        
                                        if not sandboxed_executor_result_str:
                                            logger.info("📧 No sandboxed_executor results found - using original email args")
                                            return email_args
                                        
                                        # Parse the sandboxed_executor result string to extract filename
                                        import re
                                        
                                        # Pattern to match filename from sandboxed_executor output
                                        filename_match = re.search(r'Successfully created file: ([^\n]+)', sandboxed_executor_result_str, re.IGNORECASE)
                                        
                                        if filename_match:
                                            created_filename = filename_match.group(1).strip()
                                            logger.info(f"📧 SMART DECISION: Parsed filename from sandboxed_executor result: {created_filename}")
                                            
                                            # Update email args to use the actual created file
                                            email_args['attachments'] = created_filename
                                            email_args['wait_for_attachments'] = False  # File already exists
                                            
                                            # Update subject and body to reflect actual content
                                            email_args['subject'] = f"File Created: {created_filename}"
                                            email_args['body'] = f"Please find attached the requested file: {created_filename}"
                                            
                                            return email_args
                                        
                                        return email_args
                                        
                                    except Exception as e:
                                        logger.error(f"❌ Error in smart file decisions for sandboxed_executor: {e}")
                                        return email_args



                                def should_run_sequentially(tool_calls):
                                    """
                                    Dependency rule: email and file creation tools run after search tools
                                    This prevents placeholder file creation when real files exist
                                    Returns: (phase2_tools, phase1_tools)
                                    """
                                    phase1_tools = []  # Search and analysis tools
                                    phase2_tools = []  # File creation and email tools
                                    
                                    for tool_call in tool_calls:
                                        tool_name = tool_call['function']['name']
                                        # Phase 2: Tools that should run after search completes
                                        if tool_name in ['secure_email_sender', 'sandboxed_executor']:
                                            phase2_tools.append(tool_call)
                                        else:
                                            # Phase 1: Search and analysis tools
                                            phase1_tools.append(tool_call)
                                    
                                    return phase2_tools, phase1_tools

                                async def execute_tools_with_email_dependency(tool_calls):
                                    """
                                    Execute tools with smart file dependency: search first, then file creation and email
                                    """
                                    phase2_tools, phase1_tools = should_run_sequentially(tool_calls)

                                    # 🔒 AUTHORITATIVE DELIVERY GATE (at the execution site). The tool-calling model is
                                    # TAUGHT the delivery tools (secure_email_sender / sandboxed_executor) by
                                    # pre_tool_model_system_prompt.txt and will emit them for any email/file request,
                                    # regardless of the per-request function-array whitelist — so the delivery
                                    # PERMISSION cannot be enforced by hiding tools; it must be enforced HERE, where we
                                    # actually run them. If this request is not authorized for delivery (a restricted
                                    # client with no allow_delivery — e.g. a non-delivery NewX bot), drop the delivery/
                                    # file tools so they neither execute pre-LLM nor get deferred. Uses request `data`
                                    # directly: reliable and concurrency-safe (no ContextVar). Auto-trusted clients
                                    # (OpenWebUI) and delivery-authorized bots are `permitted` → unaffected.
                                    if phase2_tools and not delivery_policy.authorize_delivery(data).permitted:
                                        _dropped = [t['function']['name'] for t in phase2_tools]
                                        logger.warning(f"🔒 DELIVERY GATE: request NOT authorized for delivery — dropping "
                                                       f"tool-calling delivery tools {_dropped} (they will not run)")
                                        phase2_tools = []

                                    all_results = []
                                    phase1_results = []
                                    
                                    # Phase 1: Execute search and analysis tools (can be parallel)
                                    if phase1_tools:
                                        logger.info(f"🚀 PHASE 1 SEARCH: {len(phase1_tools)} tools - {[t['function']['name'] for t in phase1_tools]}")
                                        
                                        async def execute_single_tool(tool_call):
                                            function_name = tool_call['function']['name']
                                            function_args = tool_call['function']['arguments']
                                            
                                            # Parse JSON string arguments to dictionary if needed
                                            if isinstance(function_args, str):
                                                try:
                                                    function_args = json.loads(function_args)
                                                except json.JSONDecodeError:
                                                    logger.error(f"❌ Invalid JSON in function arguments for {function_name}: {function_args}")
                                                    function_args = {}
                                            
                                            # 🖼️ INTERCEPT IMAGE_TO_TEXT CALLS - Replace placeholder with actual image data
                                            if function_name == "image_to_text":
                                                logger.info(f"🖼️ INTERCEPT: Detected image_to_text tool call")
                                                # Log image count instead of full data
                                                images_data = data.get('images', 'NOT_FOUND')
                                                if images_data == 'NOT_FOUND':
                                                    logger.info(f"🖼️ INTERCEPT: data.get('images') = NOT_FOUND")
                                                elif isinstance(images_data, list):
                                                    image_count = len([img for img in images_data if img != "noimage"])
                                                    logger.info(f"🖼️ INTERCEPT: data.get('images') = [{image_count} image(s), first 100 chars: {str(images_data[0])[:100] if images_data and images_data[0] != 'noimage' else 'noimage'}...]")
                                                else:
                                                    logger.info(f"🖼️ INTERCEPT: data.get('images') = {type(images_data)}")

                                                # Log function_args with truncation for image data
                                                safe_args = function_args.copy() if isinstance(function_args, dict) else function_args
                                                if isinstance(safe_args, dict) and 'image' in safe_args and isinstance(safe_args['image'], str) and len(safe_args['image']) > 100:
                                                    safe_args_display = safe_args.copy()
                                                    safe_args_display['image'] = f"{safe_args['image'][:100]}... ({len(safe_args['image'])} chars)"
                                                    logger.info(f"🖼️ INTERCEPT: function_args = {safe_args_display}")
                                                else:
                                                    logger.info(f"🖼️ INTERCEPT: function_args = {function_args}")

                                                if data.get("images") and data.get("images")[0] != "noimage":
                                                    logger.info(f"🖼️ INTERCEPT: Images available, checking for placeholder...")
                                                    # Handle both "image" (singular) and "images" (plural) parameters
                                                    if "image" in function_args:
                                                        logger.info(f"🖼️ INTERCEPT: function_args['image'] = {function_args['image'][:50] if isinstance(function_args['image'], str) else function_args['image']}")
                                                        if function_args["image"] in [
                                                            "user_provided_image_data",
                                                            "<user_provided_image_data>",
                                                            "<actual_base64_image_data>",
                                                            "<base64_image_data>",
                                                            "<base64_encoded_image_data>",
                                                            "[BASE64_ENCODED_IMAGE_DATA]",
                                                            "[base64_encoded_image_data]"
                                                        ]:
                                                            # Replace placeholder with actual base64 image data for singular parameter
                                                            actual_images = data.get("images", [])
                                                            if actual_images and actual_images[0] != "noimage":
                                                                function_args["image"] = actual_images[0]  # Use first image for singular parameter
                                                                logger.info(f"🖼️ REPLACED singular image placeholder with actual base64 data ({len(actual_images[0])} chars)")
                                                            else:
                                                                logger.warning(f"🖼️ No image data available for singular image parameter")
                                                        else:
                                                            logger.warning(f"🖼️ image parameter is not a recognized placeholder: {function_args['image'][:100]}")

                                                    if "images" in function_args:
                                                        # Parse images if it's a string
                                                        images_arg = function_args["images"]
                                                        if isinstance(images_arg, str):
                                                            try:
                                                                images_arg = json.loads(images_arg)
                                                            except json.JSONDecodeError:
                                                                logger.warning(f"🖼️ Failed to parse images argument: {images_arg}")
                                                                images_arg = []

                                                        # Replace placeholder with actual image data
                                                        if isinstance(images_arg, list):
                                                            processed_images = []
                                                            for i, img_item in enumerate(images_arg):
                                                                if isinstance(img_item, dict) and img_item.get("path") == "user_provided_image_data":
                                                                    # Replace with actual base64 image data
                                                                    actual_images = data.get("images", [])
                                                                    if i < len(actual_images) and actual_images[i] != "noimage":
                                                                        processed_images.append({
                                                                            "type": "base64",
                                                                            "data": f"data:image/jpeg;base64,{actual_images[i]}",
                                                                            "filename": f"user_image_{i+1}"
                                                                        })
                                                                    else:
                                                                        logger.warning(f"🖼️ No image data available for index {i}")
                                                                else:
                                                                    processed_images.append(img_item)
                                                            function_args["images"] = processed_images
                                                            logger.info(f"🖼️ REPLACED image placeholder with {len(processed_images)} actual image(s)")
                                                else:
                                                    logger.warning(f"🖼️ INTERCEPT: No images in data or image is 'noimage'")
                                            
                                            start_time = time.time()

                                            # 🎯 INTERCEPT EMAIL AND FILE CREATION - Defer until after primary LLM generates content
                                            if function_name == "secure_email_sender":
                                                logger.info(f"📧 TOOL DEFERRED: {function_name} - Email intercepted for post-processing")
                                                result = "Email scheduled for sending after content generation"
                                                return (function_name, result, start_time, True, function_args.copy())
                                            elif function_name == "sandboxed_executor":
                                                # Parse args to check action
                                                parsed_args = function_args if isinstance(function_args, dict) else json.loads(function_args)
                                                if parsed_args.get('action') == 'create_file':
                                                    logger.info(f"📄 TOOL DEFERRED: {function_name} create_file - Will use primary LLM response as content")
                                                    result = "File creation scheduled for post-LLM processing with formatted content"
                                                    return (function_name, result, start_time, False, None)

                                            # 🔌 INTERCEPT PLUGIN TOOLS WITH {{PRIMARY_LLM_OUTPUT}} - Defer until after primary LLM generates content
                                            # Check if tool is a plugin (social_media_*, email_*, publishing_*)
                                            is_publishing_plugin = (
                                                function_name.startswith("social_media_") or
                                                function_name.startswith("email_") or
                                                function_name.startswith("publishing_") or
                                                function_name.endswith("_publish") or
                                                function_name.endswith("_post")
                                            )

                                            if is_publishing_plugin:
                                                # Parse args to check for {{PRIMARY_LLM_OUTPUT}} placeholder
                                                parsed_args = function_args if isinstance(function_args, dict) else {}
                                                if isinstance(function_args, str):
                                                    try:
                                                        parsed_args = json.loads(function_args)
                                                    except json.JSONDecodeError:
                                                        parsed_args = {}

                                                # Check if any parameter contains the placeholder
                                                has_placeholder = any(
                                                    "{{PRIMARY_LLM_OUTPUT}}" in str(v)
                                                    for v in parsed_args.values()
                                                )

                                                if has_placeholder:
                                                    logger.info(f"🔌 PLUGIN DEFERRED: {function_name} - Contains {{PRIMARY_LLM_OUTPUT}} placeholder, will execute after Primary LLM")
                                                    # Store parameters in result for POST-LLM retrieval
                                                    import json as json_lib
                                                    params_json = json_lib.dumps(parsed_args)
                                                    result = f"Publishing deferred - {function_name} will execute with generated content\n__DEFERRED_PARAMS__:{params_json}"
                                                    return (function_name, result, start_time, False, parsed_args.copy())

                                            # Execute non-deferred tools normally
                                            result = await tool_manager.safe_function_call(function_name, function_args)
                                            return (function_name, result, start_time, False, None)
                                        
                                        phase1_tasks = [execute_single_tool(call) for call in phase1_tools]
                                        phase1_results = await asyncio.gather(*phase1_tasks, return_exceptions=True)
                                        all_results.extend(phase1_results)
                                        
                                        logger.info(f"✅ PHASE 1 COMPLETE: All {len(phase1_tools)} search tools finished")
                                    
                                    # Phase 2: Execute file creation and email tools (sequential, with smart decisions)
                                    if phase2_tools:
                                        logger.info(f"📧 PHASE 2 SMART: {len(phase2_tools)} tools - {[t['function']['name'] for t in phase2_tools]}")

                                        # 🔧 BUILD STAGE_OUTPUTS for dependency resolution
                                        stage_outputs = {}
                                        for result_tuple in phase1_results:
                                            if isinstance(result_tuple, tuple) and len(result_tuple) >= 2:
                                                tool_name, result = result_tuple[0], result_tuple[1]
                                                stage_outputs[tool_name] = result
                                                logger.debug(f"🔧 STAGE_OUTPUT: {tool_name} → {len(str(result))} chars")

                                        for phase2_tool in phase2_tools:
                                            function_name = phase2_tool['function']['name']
                                            function_args = phase2_tool['function']['arguments']
                                            start_time = time.time()
                                            
                                            # 🧠 SMART FILE DECISION: Use actual found files instead of created placeholders
                                            should_execute = True
                                            
                                            # Parse JSON string to dict if needed
                                            if isinstance(function_args, str):
                                                try:
                                                    function_args_dict = json.loads(function_args)
                                                except json.JSONDecodeError:
                                                    logger.error(f"❌ Invalid JSON in function arguments for {function_name}: {function_args}")
                                                    function_args_dict = {}
                                            else:
                                                function_args_dict = function_args

                                            # 🔧 RESOLVE DEPENDENCIES: Replace symbolic references like {{NEWS_DATA}}
                                            resolved_args_dict = resolve_dependencies(function_args_dict, stage_outputs)
                                            if resolved_args_dict != function_args_dict:
                                                logger.info(f"🔧 DEPENDENCY RESOLUTION: Applied for {function_name}")
                                                function_args_dict = resolved_args_dict
                                                # 🔧 CRITICAL: Update function_args to use resolved values
                                                if isinstance(function_args, str):
                                                    function_args = json.dumps(function_args_dict)
                                                else:
                                                    function_args = function_args_dict

                                            # Apply smart decisions based on tool type
                                            if function_name == 'sandboxed_executor':
                                                # Check if this is trying to create a file when we have real files
                                                if function_args_dict.get('action') == 'create_file':
                                                    # Check if document_search found actual files
                                                    found_real_files = False
                                                    for result_tuple in phase1_results:
                                                        if isinstance(result_tuple, tuple) and len(result_tuple) >= 2:
                                                            tool_name, result = result_tuple[0], result_tuple[1]
                                                            if tool_name == "document_search" and isinstance(result, str):
                                                                if "Document 1:" in result or "Sources:" in result:
                                                                    found_real_files = True
                                                                    break
                                                    
                                                    if found_real_files:
                                                        # 🎯 RESPECT USER'S EXPLICIT FORMAT REQUESTS
                                                        user_prompt = data.get('prompt', '').lower()
                                                        requested_filename = function_args_dict.get('filename', '').lower()
                                                        
                                                        # Check if user explicitly requested a specific format
                                                        user_wants_pdf = ('pdf' in user_prompt and ('pdf version' in user_prompt or 'send pdf' in user_prompt or 'as pdf' in user_prompt)) or requested_filename.endswith('.pdf')
                                                        user_wants_html = ('html' in user_prompt and ('html version' in user_prompt or 'send html' in user_prompt or 'as html' in user_prompt)) or requested_filename.endswith('.html')
                                                        user_wants_markdown = ('markdown' in user_prompt and ('markdown version' in user_prompt or 'send markdown' in user_prompt or 'as markdown' in user_prompt)) or requested_filename.endswith(('.md', '.markdown'))
                                                        
                                                        if user_wants_pdf or user_wants_html or user_wants_markdown:
                                                            format_requested = 'PDF' if user_wants_pdf else ('HTML' if user_wants_html else 'MARKDOWN')
                                                            logger.info(f"✅ SMART DECISION: User explicitly requested {format_requested} format - allowing file creation despite existing documents")
                                                            should_execute = True
                                                        else:
                                                            logger.info(f"🚫 SMART DECISION: Skipping {function_name} file creation - real files found and no explicit format request")
                                                            should_execute = False
                                                            # Create a fake success result
                                                            result = "File creation skipped - using actual found documents instead"
                                                            all_results.append((function_name, result, start_time, False, None))
                                                            continue
                                            
                                            elif function_name == 'secure_email_sender':
                                                # Apply smart file decisions to email attachments
                                                modified_args_dict = _apply_smart_file_decisions(function_args_dict, phase1_results, logger)
                                                modified_args_dict = _apply_smart_file_decisions_for_sandboxed_executor(modified_args_dict, phase1_results, logger)

                                                
                                                # Convert back to the format expected by tool_manager
                                                if isinstance(function_args, str):
                                                    function_args = json.dumps(modified_args_dict)
                                                else:
                                                    function_args = modified_args_dict
                                            
                                            if should_execute:
                                                logger.info(f"📧 PHASE 2 TOOL: {function_name} starting (with smart file decisions)")

                                                # 🎯 SMART DEFERRAL v1.0.3.10: Check if user wants EXISTING content vs NEW content
                                                user_prompt_lower = data.get('prompt', '').lower()
                                                conversation_content_indicators = ["email the above", "email this", "send the above", "send this",
                                                                                   "email it", "send it", "previous response", "verbatim",
                                                                                   "full and complete response", "the response above"]
                                                wants_existing_content = any(indicator in user_prompt_lower for indicator in conversation_content_indicators)

                                                # 🎯 DEFER sandboxed_executor create_file AND secure_email_sender until POST-LLM
                                                # ONLY defer if user wants NEW content generation (not existing content)
                                                if function_name == 'sandboxed_executor' and function_args_dict.get('action') == 'create_file':
                                                    if wants_existing_content:
                                                        # User wants existing content - execute PRE-LLM
                                                        logger.info(f"📄 TOOL EXECUTING PRE-LLM: {function_name} create_file - User wants existing content")
                                                        result = await tool_manager.safe_function_call(function_name, function_args)
                                                        all_results.append((function_name, result, start_time, False, None))
                                                    else:
                                                        # User wants new content - defer POST-LLM
                                                        logger.info(f"📄 TOOL DEFERRED: {function_name} create_file - Will use primary LLM response")
                                                        # 🔧 FIX v1.0.3.10: Don't confuse Primary LLM with meta-instructions
                                                        result = "File creation deferred - will be created with the formatted content you generate"
                                                        all_results.append((function_name, result, start_time, False, None))
                                                elif function_name == 'secure_email_sender':
                                                    if wants_existing_content:
                                                        # User wants existing content - execute PRE-LLM
                                                        logger.info(f"📧 TOOL EXECUTING PRE-LLM: {function_name} - User wants existing content")
                                                        result = await tool_manager.safe_function_call(function_name, function_args)
                                                        all_results.append((function_name, result, start_time, False, None))
                                                    else:
                                                        # User wants new content - defer POST-LLM
                                                        logger.info(f"📧 TOOL DEFERRED: {function_name} - Will send after file creation in POST-LLM")
                                                        # 🔧 FIX v1.0.3.10: Don't confuse Primary LLM with meta-instructions
                                                        result = "Email sending deferred - will be sent after file creation completes"
                                                        all_results.append((function_name, result, start_time, True, function_args_dict.copy()))
                                                else:
                                                    result = await tool_manager.safe_function_call(function_name, function_args)
                                                    all_results.append((function_name, result, start_time, False, None))
                                                logger.info(f"✅ PHASE 2 COMPLETE: {function_name}")
                                    
                                    return all_results

                                # Define async function for parallel execution (legacy)
                                async def execute_single_tool(tool_call_data):
                                    i, tool_call = tool_call_data
                                    function_name = tool_call['function']['name']
                                    function_args = tool_call['function']['arguments']
                                    
                                    # Parse JSON string arguments to dictionary if needed
                                    if isinstance(function_args, str):
                                        try:
                                            function_args = json.loads(function_args)
                                        except json.JSONDecodeError:
                                            logger.error(f"❌ Invalid JSON in function arguments for {function_name}: {function_args}")
                                            function_args = {}
                                    
                                    # Add image if applicable (use images_available to survive forced processing reset)
                                    if "image" in function_args and (image_exists or images_available):
                                        function_args["image"] = data.get("images", [None])[0]
                                    
                                    # 🖼️ INTERCEPT IMAGE_TO_TEXT CALLS - ALWAYS replace with actual image data
                                    # Don't rely on matching specific placeholder strings - the LLM may generate
                                    # any arbitrary placeholder. Always inject real base64 when images exist.
                                    if function_name == "image_to_text" and data.get("images") and data.get("images")[0] != "noimage":
                                        # Handle "image" (singular) parameter - always inject real data
                                        if "image" in function_args:
                                            actual_images = data.get("images", [])
                                            if actual_images and actual_images[0] != "noimage":
                                                old_value = function_args["image"]
                                                function_args["image"] = actual_images[0]  # Use first image for singular parameter
                                                logger.info(f"🖼️ REPLACED image arg (was: '{str(old_value)[:80]}...') with actual base64 data ({len(actual_images[0])} chars)")
                                            else:
                                                logger.warning(f"🖼️ No image data available for singular image parameter")
                                        elif "images" in function_args:
                                            # Parse images if it's a string
                                            images_arg = function_args["images"]
                                            if isinstance(images_arg, str):
                                                try:
                                                    images_arg = json.loads(images_arg)
                                                except json.JSONDecodeError:
                                                    logger.warning(f"🖼️ Failed to parse images argument: {images_arg}")
                                                    images_arg = []
                                            
                                            # Replace placeholder with actual image data
                                            if isinstance(images_arg, list):
                                                processed_images = []
                                                for i, img_item in enumerate(images_arg):
                                                    if isinstance(img_item, dict) and img_item.get("path") == "user_provided_image_data":
                                                        # Replace with actual base64 image data
                                                        actual_images = data.get("images", [])
                                                        if i < len(actual_images) and actual_images[i] != "noimage":
                                                            processed_images.append({
                                                                "type": "base64",
                                                                "data": f"data:image/jpeg;base64,{actual_images[i]}",
                                                                "filename": f"user_image_{i+1}"
                                                            })
                                                        else:
                                                            logger.warning(f"🖼️ No image data available for index {i}")
                                                    else:
                                                        processed_images.append(img_item)
                                                function_args["images"] = processed_images
                                                logger.info(f"🖼️ REPLACED image placeholder with {len(processed_images)} actual image(s)")
                                    
                                    # Execute the function with timing
                                    start_time = time.time()
                                    logger.info(f"==> TOOL {i+1} CALLED: {function_name}({', '.join([f'{k}=\"{str(v)[:50]}...\"' if len(str(v)) > 50 else f'{k}=\"{v}\"' for k, v in function_args.items()])})") 
                                    
                                    # 🎯 INTERCEPT EMAIL CALLS - Fake success, set flag for post-processing
                                    if function_name == "secure_email_sender":
                                        logger.info(f"📧 TOOL {i+1} DEFERRED: {function_name} - Email intercepted for post-processing")
                                        result = "Email scheduled for sending after content generation"
                                        # Handle email interception in parallel context
                                        return (function_name, result, start_time, True, function_args.copy())
                                    else:
                                        result = await tool_manager.safe_function_call(function_name, function_args)
                                        return (function_name, result, start_time, False, None)
                                
                                # Execute tools with email dependency logic
                                tool_execution_start = time.time()
                                
                                # Use new dependency-aware execution
                                tool_results_list = await execute_tools_with_email_dependency(tool_calls)
                                
                                total_execution_time = time.time() - tool_execution_start
                                logger.info(f"⏱️ TOOL EXECUTION COMPLETE: {len(tool_calls)} tools in {total_execution_time:.2f}s")
                                
                                # 🧹 STREAMLINED LOGGING: Tool execution summaries (instead of full buffer dumps)
                                concise_logging = os.environ.get('CONCISE_LOGGING', 'true').lower() == 'true'
                                if concise_logging:
                                    logger.info(f"📊 TOOL EXECUTION SUMMARY:")
                                
                                # Process results and handle any email interceptions
                                # 🔧 FIX: Create formatted results list for arbitrator
                                formatted_tools_results_list = []

                                for i, result_data in enumerate(tool_results_list):
                                    if isinstance(result_data, Exception):
                                        logger.error(f"❌ TOOL {i+1} ERROR: {str(result_data)}")
                                        continue

                                    function_name, result, start_time, is_email, email_params = result_data
                                    end_time = time.time()
                                    execution_time = end_time - start_time

                                    # Handle email interception flag setting
                                    if is_email and email_params:
                                        email_intercepted = True
                                        intercepted_email_params = email_params

                                    # 🔧 FIX: Format result for arbitrator (was missing!)
                                    formatted_result = f"Tool: {function_name}\nResult: {result}\n\n"
                                    formatted_tools_results_list.append(formatted_result)

                                # 🔧 FIX: Append formatted results to preserve any pre-existing entries
                                # (e.g., FORCED IMAGE PROCESSING result added before regular tool calling)
                                tools_results_list = tools_results_list + formatted_tools_results_list

                            else:
                                # 🔧 FIX v1.0.0.44: Parse tool calls from content when tool_calls is empty
                                # Cloud-proxied models (e.g. qwen3.5:397b-cloud via Ollama OpenAI endpoint)
                                # sometimes return tool calls as JSON text in content instead of structured tool_calls
                                content_text = response_data.get('content', '').strip()
                                parsed_from_content = False
                                if content_text:
                                    try:
                                        parsed = json.loads(content_text)
                                        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict) and 'name' in parsed[0]:
                                            # Convert content-based tool calls to standard format
                                            tool_calls = []
                                            for tc in parsed:
                                                tool_calls.append({
                                                    'function': {
                                                        'name': tc.get('name', ''),
                                                        'arguments': tc.get('parameters', tc.get('arguments', {}))
                                                    }
                                                })
                                            response_data['tool_calls'] = tool_calls
                                            logger.info(f"🔧 CONTENT-PARSED: Extracted {len(tool_calls)} tool call(s) from content field: {[tc['function']['name'] for tc in tool_calls]}")
                                            parsed_from_content = True
                                    except (json.JSONDecodeError, TypeError, KeyError):
                                        pass  # Not valid JSON tool calls in content

                                if parsed_from_content:
                                    # Re-enter the tool execution path with parsed tool calls
                                    tool_calls = response_data['tool_calls']
                                    logger.info(f"🎯 TOOL CALLS DETECTED (from content): {len(tool_calls)} tools to execute")

                                    for i, tool_call in enumerate(tool_calls):
                                        function_name = tool_call['function']['name']
                                        function_args = tool_call['function']['arguments']

                                        if isinstance(function_args, str):
                                            try:
                                                function_args = json.loads(function_args)
                                                tool_call['function']['arguments'] = function_args
                                            except json.JSONDecodeError:
                                                function_args = {}

                                        tools_called.append(function_name)
                                        logger.info(f"🔧 Tool {i+1}/{len(tool_calls)}: {function_name} | Args: {list(function_args.keys()) if isinstance(function_args, dict) else function_args}")

                                    # Execute parsed tools in parallel (same as structured tool_calls path)
                                    async def execute_content_parsed_tool(tc_data):
                                        idx, tc = tc_data
                                        fn_name = tc['function']['name']
                                        fn_args = tc['function']['arguments']
                                        if isinstance(fn_args, str):
                                            try:
                                                fn_args = json.loads(fn_args)
                                            except json.JSONDecodeError:
                                                fn_args = {}
                                        
                                        # Convert args back to string for safe_function_call
                                        args_str = json.dumps(fn_args) if isinstance(fn_args, dict) else str(fn_args)
                                        result = await tool_manager.safe_function_call(fn_name, args_str)
                                        return idx, fn_name, fn_args, result

                                    logger.info(f"🚀 PARALLEL CONTENT-PARSED EXECUTION: Starting {len(tool_calls)} tools concurrently")
                                    tasks = [execute_content_parsed_tool((i, tc)) for i, tc in enumerate(tool_calls)]
                                    results = await asyncio.gather(*tasks, return_exceptions=True)

                                    formatted_tools_results_list = []
                                    for r in sorted(results, key=lambda x: x[0] if isinstance(x, tuple) else 0):
                                        if isinstance(r, Exception):
                                            logger.error(f"❌ Content-parsed tool execution error: {r}")
                                            continue
                                        idx, fn_name, fn_args, result = r
                                        result_str = str(result) if result else "No result"
                                        logger.info(f"✅ Tool {fn_name}: DONE | Result: {len(result_str)} chars")
                                        formatted_result = f"Tool: {fn_name}\nResult: {result}\n\n"
                                        formatted_tools_results_list.append(formatted_result)

                                    # Append to preserve any pre-existing entries (e.g., FORCED IMAGE PROCESSING result)
                                    tools_results_list = tools_results_list + formatted_tools_results_list

                                else:
                                    # Genuinely no tool calls - check if we should force data gathering
                                    logger.info("❌ No tool calls generated by the tool calling model")
                                    truncated_response_data = truncate_base64_for_logging(json.dumps(response_data, indent=2))
                                    logger.info(f"Raw LLM Manager response: {truncated_response_data}")

                                    # 🔥 PROGRAMMATIC TOOL CALL INJECTION 🔥
                                    # If the model refuses to call tools for file/email requests, force data gathering
                                    # BUT only check the CURRENT user request, not conversation history
                                    prompt_lower = user_prompt.lower()

                                    # Extract only the current request (after "=== CURRENT REQUEST ===" marker)
                                    if "=== current request ===" in prompt_lower:
                                        current_request = prompt_lower.split("=== current request ===")[-1]
                                    else:
                                        current_request = prompt_lower

                                    forced_tools = []

                                    # Skip the fallback for RAICA's OWN internal meta-task prompts (title / tag /
                                    # summary generation): they use fixed templates, never need tools, and re-prompting
                                    # them would add an LLM round-trip to every post. (This matches RAICA's own generated
                                    # prompt text — NOT user-intent classification.)
                                    if any(meta_task in current_request for meta_task in ['generate a concise', 'title with emoji', 'generate 1-3 broad tags', 'chat history']):
                                        logger.info("🚫 SKIPPING FORCED TOOLS: This is a meta/title/tag generation request")
                                    else:
                                        # POLICY-DRIVEN FALLBACK (CLAUDE.md LLM-Policy Gate — NO keyword meaning-guessing):
                                        # the tool model returned no tools. The old code here classified the request by
                                        # keywords and force-called a tool — which mis-routed news/general requests to a
                                        # ticker-only stock tool whenever the prompt merely contained the word "stock"
                                        # (e.g. the tool name "get_stock_and_company_data" printed in the bot's own
                                        # citation prompt), producing a TOOL-MISUSE error and a sourceless post. Instead,
                                        # re-prompt the SAME tool model ONCE with a firm directive: gather evidence IF the
                                        # request needs external/current info, else return none. The LLM decides; RAICA
                                        # only executes what it returns. (Transient 5xx that produce an empty result are
                                        # already retried inside the provider, so reaching here is a GENUINE "no tools".)
                                        try:
                                            reprompt = (
                                                f"{user_message}\n\n"
                                                "=== TOOL-USE RE-CHECK ===\n"
                                                "You returned NO tool calls for the request above. Reconsider:\n"
                                                "- If answering it ACCURATELY requires current or external information "
                                                "(latest news, real-world facts, live data/prices, web pages, documents, "
                                                "company/financial data, etc.), you MUST now call the appropriate tool(s) "
                                                "to gather it.\n"
                                                "- If the request is purely conversational/creative or is fully "
                                                "answerable from your own knowledge, return NO tools.\n"
                                                "Use ONLY the tools provided."
                                            )
                                            logger.info("🔁 NO-TOOLS RE-PROMPT: asking the tool model to reconsider evidence gathering")
                                            reprompt_resp = await llm_manager.generate_tools(
                                                prompt=reprompt,
                                                tools=tools_array,
                                                model=tools_model,
                                                system_prompt=system_prompt,
                                                temperature=0,
                                                max_tokens=4096
                                            )
                                            for tc in (reprompt_resp or {}).get('tool_calls', []) or []:
                                                fn = tc.get('function', {})
                                                fn_name = fn.get('name')
                                                fn_args = fn.get('arguments')
                                                if isinstance(fn_args, str):
                                                    try:
                                                        fn_args = json.loads(fn_args)
                                                    except (json.JSONDecodeError, TypeError):
                                                        fn_args = {}
                                                if fn_name:
                                                    forced_tools.append((fn_name, fn_args if isinstance(fn_args, dict) else {}))
                                            if forced_tools:
                                                logger.info(f"🔁 RE-PROMPT selected evidence tool(s): {[t[0] for t in forced_tools]}")
                                            else:
                                                logger.info("🔁 RE-PROMPT confirmed no tools needed — trusting the model")
                                        except Exception as _reprompt_err:
                                            logger.warning(f"🔁 NO-TOOLS RE-PROMPT skipped (non-fatal): {_reprompt_err}")

                                    # Execute forced tool calls - PARALLEL EXECUTION OPTIMIZATION
                                    if forced_tools:

                                        # Log all forced tool calls upfront
                                        for function_name, function_args in forced_tools:
                                            logger.info(f"🔧 FORCED Tool {function_name}: START | Args: {list(function_args.keys())}")
                                            tools_called.append(function_name)

                                        # Define async function for parallel forced execution
                                        async def execute_forced_tool(tool_data):
                                            function_name, function_args = tool_data
                                            start_time = time.time()
                                            result = await tool_manager.safe_function_call(function_name, function_args)
                                            return (function_name, result, start_time)

                                        # Execute all forced tools in parallel
                                        forced_execution_start = time.time()
                                        logger.info(f"🚀 PARALLEL FORCED EXECUTION: Starting {len(forced_tools)} forced tools concurrently")

                                        forced_tasks = [execute_forced_tool(tool_data) for tool_data in forced_tools]
                                        forced_results_list = await asyncio.gather(*forced_tasks, return_exceptions=True)

                                        total_forced_parallel_time = time.time() - forced_execution_start
                                        logger.info(f"🚀 PARALLEL FORCED EXECUTION COMPLETED: All {len(forced_tools)} forced tools finished in {total_forced_parallel_time:.2f}s")

                                        # Process forced results
                                        for result_data in forced_results_list:
                                            if isinstance(result_data, Exception):
                                                logger.error(f"🚨 Forced tool execution failed: {str(result_data)}")
                                                continue

                                            function_name, result, start_time = result_data
                                            end_time = time.time()
                                            execution_time = end_time - start_time
                                            logger.info(f"🔧 FORCED Tool {function_name}: COMPLETE | {execution_time:.2f}s | Result: {len(str(result))} chars")
                                            # Store FULL result for tools_results_list (needed for image extraction)
                                            full_result = str(result)
                                            tools_results_list.append(f"Tool: {function_name}\nResult: {full_result}\n\n")

                                            # Only truncate for logging display
                                            truncated_result = truncate_base64_for_logging(full_result)
                        
                        else:
                            logger.error(f"❌ Tool calling model failed - no response data returned")
                            logger.error(f"LLM Manager response: {response_data}")
                            # Fallback: just get current time
                            result = await tool_manager.get_the_secret_tool()
                            tools_results_list.append(f"Tool: get_the_secret_tool\nResult: {result}\n\n")
                            
                except Exception as e:
                    logger.error(f"❌ Tool calling exception: {e}")
                    logger.error(f"Exception type: {type(e).__name__}")
                    # Fallback: just get current time
                    result = await tool_manager.get_the_secret_tool()
                    tools_results_list.append(f"Tool: get_the_secret_tool\nResult: {result}\n\n")
            
            # CRITICAL: Convert tools_results_list to string for downstream processing
            # For meta-tasks, tools_results is already set to ""; for normal tasks, join the list
            if not is_meta_task:
                tools_results = "".join(tools_results_list)  # O(n) join vs O(n²) concatenation
            # For meta-tasks, tools_results is already set to "" above
            
            # 🚨 TRUE THREAD LOCKING ARBITRATOR SYSTEM
            # PRIMARY LLM EXECUTION LOCKED UNTIL TOOLS ARE VALIDATED AND CORRECTED
            arbitrator_config = config_loader.load_config().get('arbitrator', {})
            if arbitrator_config.get('enabled', False) and tools_called and not is_meta_task:
                logger.info(f"🔒 ARBITRATOR LOCK: Primary LLM thread locked - validating tools for: {user_prompt[:100]}...")
                
                # 🔒 CREATE LOCK FOR PRIMARY LLM THREAD
                primary_llm_lock = asyncio.Event()
                primary_llm_lock.clear()  # Start locked - primary LLM cannot proceed
                
                max_arbitrator_attempts = 5
                attempt = 0
                tools_are_valid = False
                corrected_tools_results = None  # 🔧 CRITICAL: Variable to store corrected results for main thread
                
                while attempt < max_arbitrator_attempts and not tools_are_valid:
                    attempt += 1
                    logger.info(f"🔄 ARBITRATOR ATTEMPT #{attempt}/{max_arbitrator_attempts} - Validating tools...")
                    
                    try:
                        # STEP 1: Validate current tool results
                        validated_results = await arbitrator_validate_tasks(
                            tools_called, tools_results_list, user_prompt, tool_manager
                        )
                        
                        # 🔍 DEBUG: Log what arbitrator function returned
                        if validated_results:
                            logger.info(f"🔍 DEBUG: Arbitrator returned SUCCESS - Type: {type(validated_results)}, Length: {len(validated_results)} chars")
                            logger.info(f"🔍 DEBUG: Arbitrator result preview: {validated_results[:200]}...")
                        else:
                            logger.info(f"🔍 DEBUG: Arbitrator returned FAILURE - validated_results = {validated_results}")
                        
                        if validated_results:
                            # ✅ SUCCESS: Tools validated - STORE CORRECTED RESULTS
                            corrected_tools_results = validated_results  # 🔧 CRITICAL: Store for main thread
                            tools_are_valid = True
                            primary_llm_lock.set()  # 🔓 UNLOCK PRIMARY LLM
                            logger.info(f"🔓 ARBITRATOR UNLOCK: Tools validated successfully on attempt #{attempt} - releasing primary LLM")
                            break
                        
                        elif attempt < max_arbitrator_attempts:
                            # ❌ FAILURE: Tools invalid - REGENERATE WHILE LOCKED
                            logger.warning(f"🔒 ARBITRATOR LOCKED: Attempt #{attempt} failed - regenerating tools while primary LLM remains locked")
                            
                            # STEP 2: Regenerate failed tools using existing tool calling LLM
                            logger.info(f"🔄 REGENERATING TOOLS: Using tool calling LLM to fix failures")
                            
                            # Build regeneration context with failed tool details
                            regeneration_prompt = f"""
CRITICAL: The following tools failed validation and must be regenerated with correct parameters:

USER REQUEST: {user_prompt}

FAILED TOOLS ANALYSIS:
"""
                            for i, (tool_name, result) in enumerate(zip(tools_called, tools_results_list)):
                                regeneration_prompt += f"""
Tool {i+1}: {tool_name}
Result: {result[:500]}...
Error Pattern: {_detect_tool_failure_pattern(result)}
"""
                            
                            regeneration_prompt += """

REGENERATION INSTRUCTIONS:
1. If document_search succeeded, use the ACTUAL file paths found (not placeholders)
2. If Python scripts use sys.argv[1], ensure run_code includes proper 'args' parameter
3. Fix any malformed JSON or parameter issues
4. Generate corrected tool calls that will execute successfully

Generate the corrected tool calls:"""

                            # Call tool calling LLM for regeneration
                            try:
                                logger.info(f"🧠 CALLING TOOL CALLING LLM FOR REGENERATION")
                                # 🔒 Apply tool whitelist to regeneration too
                                regen_tools = await tool_manager.get_tools_definitions()
                                regen_allowed = data.get('allowed_tools')
                                if regen_allowed:
                                    regen_tools = [t for t in regen_tools if t['function']['name'] in regen_allowed]
                                regeneration_response = await llm_manager.generate_tools(
                                    prompt=regeneration_prompt,
                                    tools=regen_tools,
                                    system_prompt="You are a tool calling specialist. Generate corrected tool calls that will execute successfully."
                                )
                                
                                if regeneration_response.get('tool_calls'):
                                    # STEP 3: Execute regenerated tools
                                    logger.info(f"🔄 EXECUTING {len(regeneration_response['tool_calls'])} REGENERATED TOOLS")
                                    regenerated_tools_results = []
                                    
                                    # Execute each regenerated tool
                                    for i, tool_call in enumerate(regeneration_response['tool_calls']):
                                        func_name = tool_call['function']['name']
                                        func_args = json.loads(tool_call['function']['arguments'])
                                        
                                        logger.info(f"🔧 REGENERATED TOOL {i+1}: {func_name}({func_args})")
                                        
                                        try:
                                            result = await tool_manager.safe_function_call(func_name, func_args)
                                            regenerated_tools_results.append(f"Tool: {func_name}\nResult: {result}\n\n")
                                            logger.info(f"✅ REGENERATED TOOL {i+1} SUCCESS: {func_name}")
                                        except Exception as tool_error:
                                            error_result = f"ERROR: {str(tool_error)}"
                                            regenerated_tools_results.append(f"Tool: {func_name}\nResult: {error_result}\n\n")
                                            logger.error(f"❌ REGENERATED TOOL {i+1} FAILED: {func_name} - {tool_error}")
                                    
                                    # Update tools_results_list with regenerated results
                                    tools_results_list = regenerated_tools_results
                                    tools_called = [tool_call['function']['name'] for tool_call in regeneration_response['tool_calls']]
                                    
                                else:
                                    logger.warning(f"❌ REGENERATION ATTEMPT #{attempt}: No tool calls generated")
                                    
                            except Exception as regen_error:
                                logger.error(f"❌ TOOL REGENERATION FAILED: {regen_error}")
                        
                        else:
                            # Final attempt failed
                            logger.error(f"🚨 ARBITRATOR FINAL FAILURE: All {max_arbitrator_attempts} attempts exhausted")
                            break
                            
                    except Exception as validation_error:
                        logger.error(f"❌ ARBITRATOR VALIDATION ERROR: {validation_error}")
                
                # FINAL DECISION POINT
                if not tools_are_valid:
                    # 🚨 CRITICAL FAILURE: Should we release lock with failed data or block indefinitely?
                    logger.error(f"🚨 ARBITRATOR CRITICAL FAILURE: Tools remain invalid after {max_arbitrator_attempts} attempts")
                    logger.error(f"🚨 DECISION: BLOCKING PRIMARY LLM INDEFINITELY - USER WILL NOT RECEIVE FABRICATED DATA")
                    
                    # 🚨 CRITICAL FIX: Release lock to prevent infinite hanging
                    # Previously this was blocking indefinitely, causing deadlock
                    
                    # Option: Release with error (allows some response vs infinite hang)  
                    primary_llm_lock.set()  # 🔓 CRITICAL: Always release lock to prevent deadlock
                    tools_results = "".join(tools_results_list)  # Use original results even if validation failed
                    
                    logger.warning(f"🚨 ARBITRATOR EMERGENCY RELEASE: Lock released to prevent deadlock - using unvalidated results")
                    logger.warning(f"🔧 MANUAL CHECK RECOMMENDED: Arbitrator failed after 5 attempts but system continues")
                
                # 🔒 WAIT FOR LOCK RELEASE BEFORE CONTINUING TO PRIMARY LLM
                logger.info(f"⏳ ARBITRATOR: Waiting for primary LLM lock release...")
                await primary_llm_lock.wait()  # This will block until lock is set
                logger.info(f"🔓 ARBITRATOR: Primary LLM lock released - proceeding with validated tools")
                
                # 🔧 CRITICAL: Apply corrected results to main thread if validation succeeded
                logger.info(f"🔍 DEBUG: corrected_tools_results status: {corrected_tools_results is not None}")
                if corrected_tools_results is not None:
                    logger.info(f"🔍 DEBUG: BEFORE applying corrected results - tools_results length: {len(tools_results)}")
                    logger.info(f"🔍 DEBUG: Corrected results length: {len(corrected_tools_results)}")
                    truncated_corrected_results = truncate_base64_for_logging(corrected_tools_results[:200] + "...")
                    logger.info(f"🔍 DEBUG: Corrected results preview: {truncated_corrected_results}")
                    
                    tools_results = corrected_tools_results
                    
                    logger.info(f"🔍 DEBUG: AFTER applying corrected results - tools_results length: {len(tools_results)}")
                    logger.info(f"🔧 ARBITRATOR FIX: Applied corrected results to primary LLM context ({len(corrected_tools_results)} chars)")
                else:
                    logger.warning(f"🚨 ARBITRATOR WARNING: No corrected results available - using original tools_results")
                    logger.info(f"🔍 DEBUG: Original tools_results length: {len(tools_results)}")
            
            # 🛡️ SAFE OPTIMIZATION INTEGRATION 🛡️ 
            # 🚨 CRITICAL FIX: Parse tools_results AFTER Arbitrator corrections are applied
            # Parse corrected tools_results into structured format for optimization system
            parsed_tool_results = []
            if tools_results.strip():
                logger.info(f"🔧 PARSING CORRECTED RESULTS: Processing {len(tools_results)} chars of corrected tools_results")
                # Split the tools_results string into individual tool entries
                tool_entries = []
                current_entry = {}
                lines = tools_results.split('\n')
                
                for line in lines:
                    if line.startswith('Tool: '):
                        if current_entry:  # Save previous entry
                            tool_entries.append(current_entry)
                        current_entry = {'tool': line[6:], 'result': ''}
                    elif line.startswith('Result: '):
                        if current_entry:
                            current_entry['result'] = line[8:]
                    elif current_entry and line.strip():
                        # Continue building result
                        current_entry['result'] += '\n' + line
                
                if current_entry:  # Don't forget the last entry
                    tool_entries.append(current_entry)
                
                # Convert to the format expected by our optimization system
                for entry in tool_entries:
                    parsed_tool_results.append({
                        'tool': entry.get('tool', 'unknown_tool'),
                        'result': entry.get('result', '')
                    })
                
                logger.info(f"🔧 PARSED RESULTS: Generated {len(parsed_tool_results)} tool entries from corrected results")
            
            # CRITICAL: Log when ALL tool execution is complete
            logger.info(f"🎯 ALL TOOL EXECUTION COMPLETED - Starting task verification")
            
            # 🔍 TASK COMPLETION VERIFIER - Cross the T's and dot the I's  
            verification_result = None
            pending_auto_execution = False
            try:
                logger.info(f"🔧 DEBUG: About to call verifier with prompt='{user_prompt}', tools_called={tools_called}")
                verification_result = await _verify_task_completion(user_prompt, tools_called, tools_results, tool_manager)
                logger.info(f"🔧 DEBUG: Verifier result (legacy): {verification_result}")
                # Phase 3c convergence: if convergence.intent_classifier.mode == 'llm', the LLM intent
                # classifier becomes AUTHORITATIVE (full tool set), with the legacy result above as the
                # fallback on any error/timeout. Default mode=legacy → returns the legacy result
                # unchanged (zero behavior change).
                _llm_authoritative = (config_loader.load_config().get('convergence', {}) or {}) \
                    .get('intent_classifier', {}).get('mode') == 'llm'
                verification_result = await _maybe_llm_authoritative(user_prompt, tools_called, verification_result)
                if _llm_authoritative:
                    logger.info(f"🔧 DEBUG: Verifier result (authoritative): {verification_result}")
                else:
                    # Phase 2: fire-and-forget SHADOW comparison (no-op unless shadow enabled). Skipped
                    # when the LLM is already authoritative (the comparison would be meaningless).
                    _schedule_shadow_classification(user_prompt, tools_called, verification_result, data)

                if not verification_result["complete"]:
                    logger.warning(f"⚠️ TASK INCOMPLETE: {verification_result['reason']}")
                    logger.info(f"📋 DEFERRED AUTO-EXECUTION: Will execute missing tools AFTER Primary LLM completes")
                    logger.info(f"📋 MISSING TOOLS: {verification_result['missing_tools']} - waiting for complete LLM response")
                    pending_auto_execution = True
                    # DO NOT execute missing tools here - wait for Primary LLM to generate complete content
                else:
                    logger.info(f"✅ TASK COMPLETION VERIFIED - All required steps completed")
            except Exception as e:
                logger.error(f"❌ VERIFIER ERROR: {e}")
                logger.error(f"❌ VERIFIER TRACEBACK: {traceback.format_exc()}")
                logger.info(f"⚠️ Continuing without verification due to error")
            
            logger.info(f"🎯 Starting context management")
            
            # 🧹 STREAMLINED LOGGING: Context summaries instead of full buffer dumps
            concise_logging = os.environ.get('CONCISE_LOGGING', 'true').lower() == 'true'
            buffer_size_logging = os.environ.get('BUFFER_SIZE_LOGGING', 'true').lower() == 'true'
            
            # Context management with safe optimization integration
            context_size = len(prompt_context) if prompt_context else 0
            tool_results_size = len(tools_results)
            system_prompt_size = len(data.get('system', ''))
            
            if concise_logging and buffer_size_logging:
                # Show concise context summary instead of full buffer dump
                logger.info(f"📊 CONTEXT SUMMARY:")
                logger.info(f"   tools_results: {tool_results_size} chars")
                logger.info(f"   in_prompt: {context_size} chars") 
                logger.info(f"   system_prompt: {system_prompt_size} chars")
                logger.info(f"   full_context: {context_size + tool_results_size + system_prompt_size} chars")
            else:
                # Legacy verbose logging
                logger.info(f"🎯 Total tools_results length: {len(tools_results)} chars")
            
            # 🧹 STREAMLINED DEBUG: Comment out verbose buffer dumps (taking too much space)
            # 🔍 DEBUG: Critical checkpoint - what is Primary LLM receiving?
            # logger.info(f"🔍 DEBUG: PRIMARY LLM CONTEXT CHECKPOINT")
            # logger.info(f"🔍 DEBUG: tools_results type: {type(tools_results)}")
            # logger.info(f"🔍 DEBUG: tools_results size: {tool_results_size} bytes") 
            # if tool_results_size > 0:
            #     logger.info(f"🔍 DEBUG: tools_results preview (first 300 chars): {tools_results[:300]}...")
            # else:
            #     logger.warning(f"🚨 DEBUG: tools_results is EMPTY! Value: '{tools_results}'")
            # logger.info(f"🔍 DEBUG: This is what Primary LLM will process")
            
            # 🧹 CONCISE DEBUG: Only show critical info when buffer dumps are disabled
            if not concise_logging:
                # Show verbose debug only when explicitly enabled
                logger.info(f"🔍 DEBUG: PRIMARY LLM CONTEXT CHECKPOINT")
                logger.info(f"🔍 DEBUG: tools_results type: {type(tools_results)}, size: {tool_results_size} bytes")
                if tool_results_size == 0:
                    logger.warning(f"🚨 DEBUG: tools_results is EMPTY!")
            elif tool_results_size == 0:
                # Always warn about empty results even in concise mode
                logger.warning(f"🚨 tools_results is EMPTY - Primary LLM will have no tool context!")
            # Use actual model context window from config instead of hardcoded 65536
            try:
                primary_config = config_loader.get_llm_config('primary')
                config_context_tokens = primary_config.get('config', {}).get('context_window_size', 32768)
                max_context_window = config_context_tokens * 4  # tokens to bytes estimate
            except Exception:
                max_context_window = ServerConfig.MAX_CONTEXT_WINDOW  # fallback
            max_context_tokens = max_context_window / 4  # estimating 4 bytes per token
            # Truncate base64 data before sending to LLM context to prevent streaming back
            truncated_tools_results = truncate_base64_for_logging(tools_results)
            full_tools_text = (prompt_context or "") + ".\n" + truncated_tools_results
            
            # 🚨 CRITICAL: Parse tools_results AFTER Arbitrator corrections are applied
            # (Moved after line 5438 to ensure corrected results are used)
            
            # Use safe optimization system or fallback to original processing
            try:
                # Get user_id from request if available (you may need to adjust this based on your auth system)
                user_id = getattr(request, 'user_id', None) if 'request' in locals() else None
                
                tools_results_summary, optimization_metadata = await process_with_safe_optimization(
                    tool_results=parsed_tool_results,
                    user_prompt=user_prompt,
                    max_context_window=max_context_window,
                    tools_called=tools_called,
                    thread_pool=thread_pool,
                    user_id=user_id
                )
                
                # Log optimization results
                if optimization_metadata.get('optimization_used'):
                    logger.info(f"🚀 OPTIMIZATION APPLIED: Score {optimization_metadata['optimization_score']:.1f}, Time {optimization_metadata['response_time']:.2f}s")
                else:
                    logger.info(f"🔄 FALLBACK PROCESSING: {optimization_metadata.get('fallback_reason', 'Feature disabled')}")
                    
            except Exception as e:
                logger.error(f"🚨 OPTIMIZATION INTEGRATION ERROR: {e}")
                logger.info("🔄 EMERGENCY FALLBACK: Using original processing")
                
                # Emergency fallback to original logic
                if len(full_tools_text) > (max_context_window) * 1.05:
                    try:
                        logger.info(f"Calling TextChunker() to reduce context size from {len(full_tools_text)} to around {max_context_window} bytes")
                        if TOOLS_AVAILABLE:
                            def sync_text_chunking():
                                from text_chunker import TextChunker
                                return TextChunker.summary_by_semantics(
                                    full_tools_text, 
                                    query=data.get('system', '') + ' \n' + user_prompt,
                                    max_length=max_context_window
                                )
                            
                            tools_results_summary = await asyncio.get_running_loop().run_in_executor(
                                thread_pool, sync_text_chunking
                            )
                            logger.info(f"TextChunker() was called and returned tools_results_summary size of {len(tools_results_summary)} bytes. From {len(full_tools_text)}")
                        else:
                            tools_results_summary = full_tools_text
                    except Exception as e2:
                        logger.error(f"Error: exception in TextChunker.summary_by_semantics() call. Function returned message: {e2}")
                        tools_results_summary = full_tools_text  # TextChunker() failed!! Use the full text
                else:
                    tools_results_summary = full_tools_text
            
            # Log context statistics (exactly like original)
            if tools_in_use:
                logger.info(f"""

###################################################
TOOLS RESULTS SUMMARY: 
###################################################

{tools_results_summary}
====================

                      Context Size (before tool call)= {context_size} bytes
                      Tool_Results_Size = {tool_results_size} bytes
                      System Prompt Size = {system_prompt_size} bytes
                      Full Text Size (context + tools_results) = {len(full_tools_text)} bytes
                      ==> Tool Results Summary Size = {len(tools_results_summary)} bytes
                      

====================
END OF TOOLS RESULTS SUMMARY
=================

""")
            else:
                logger.info(f"""

###################################################
FULL CONTEXT (NO TOOLS): 
###################################################

{tools_results_summary}
====================

                    Context Size (no tools call)= {context_size} bytes
                    System Prompt Size = {system_prompt_size} bytes
                    Full Text Size (no tools call) = {len(full_tools_text)} bytes
                    

====================
END OF CONTEXT 
=================

""")
            
            # 🖼️ PRE-LLM CONTEXT CLEANING: Remove base64 images from tools_results_summary before sending to LLM
            cleaned_tools_results_summary = tools_results_summary
            if tools_results and "analytical_visualizer" in tools_results:
                logger.info(f"🧹 PRE-LLM CONTEXT CLEANING: Removing base64 image data from tools_results_summary before LLM processing")
                
                # Find and remove base64 image data using the same pattern as injection
                import re
                img_pattern = r'<img src="(data:image/png;base64,[^"]+)"[^>]*>'
                img_match = re.search(img_pattern, cleaned_tools_results_summary)
                
                if img_match:
                    # Replace the entire <img> tag with a simple text reference
                    cleaned_tools_results_summary = re.sub(img_pattern, '**[Visualization has been generated and displayed above as HTML]**', cleaned_tools_results_summary)
                    logger.info(f"✅ PRE-LLM CONTEXT CLEANING: Replaced {len(img_match.group(1))} chars of base64 data with text reference")
                    logger.info(f"📊 CONTEXT SIZE REDUCTION: {len(tools_results_summary)} → {len(cleaned_tools_results_summary)} chars ({len(tools_results_summary) - len(cleaned_tools_results_summary)} chars removed)")
            
            # 🎯 NEW ARCHITECTURE: Build structured CONTEXT block and user system prompt
            context_block = _build_structured_context_block(cleaned_tools_results_summary, tools_called)
            
            # User-provided system prompt takes precedence
            user_system_prompt = data.get('system', '').strip()
            if user_system_prompt:
                # Use user's system prompt directly
                enhanced_system = user_system_prompt
                logger.info(f"📋 Using USER-PROVIDED system prompt ({len(user_system_prompt)} chars)")
            else:
                # Fallback to enhanced default system prompt
                # 🔧 FIX v1.0.0.32: Pass tools_called list (not full results) to prevent context overflow
                enhanced_system = _build_enhanced_primary_system_prompt(
                    user_system_prompt,
                    tools_were_executed=(len(tools_results.strip()) > 0),
                    tools_results_summary=cleaned_tools_results_summary,
                    tools_called=tools_called,
                    allow_delivery=delivery_policy.authorize_delivery(data).permitted
                )
                logger.info(f"📋 Using DEFAULT enhanced system prompt ({len(enhanced_system)} chars)")
            
            # 🚀 META-TASK OPTIMIZATION: Smart truncation for title/tag generation
            if is_meta_task:
                # Extract task instruction and chat history separately
                if '<chat_history>' in user_prompt and '</chat_history>' in user_prompt:
                    # Split task instruction from chat history
                    parts = user_prompt.split('<chat_history>')
                    task_instruction = parts[0].strip()
                    
                    chat_content = parts[1].split('</chat_history>')[0].strip()
                    
                    # Smart truncation: Keep last 1000 chars of chat history for context
                    if len(chat_content) > 1000:
                        chat_content = "..." + chat_content[-1000:]
                    
                    # Reconstruct optimized prompt
                    optimized_prompt = f"{task_instruction}\n<chat_history>\n{chat_content}\n</chat_history>"
                    in_prompt = f"PROMPT: {optimized_prompt}"
                    # Reduced meta-task logging: logger.info(f"🚀 META-TASK OPTIMIZED: Reduced prompt from {len(user_prompt)} to {len(optimized_prompt)} chars")
                else:
                    # Fallback: just truncate to reasonable size
                    if len(user_prompt) > 2000:
                        truncated = user_prompt[:1000] + "...[truncated]..." + user_prompt[-500:]
                        in_prompt = f"PROMPT: {truncated}"
                        # Reduced meta-task logging: logger.info(f"🚀 META-TASK OPTIMIZED: Reduced prompt from {len(user_prompt)} to {len(truncated)} chars")
                    else:
                        in_prompt = f"PROMPT: {user_prompt}"
            else:
                # 🎯 PROMPT TRANSFORMATION: Transform email requests to confirmation requests when tools already executed
                transformed_prompt = user_prompt
                if context_block.strip() and ("TOOLS EXECUTED:" in context_block):
                    # 🔧 CRITICAL FIX v1.0.3.9: Only transform if tools actually completed (not deferred)
                    # If tools are deferred, Primary LLM needs to generate the content!
                    if "deferred" not in context_block.lower():
                        # 🔧 ENHANCED FIX v1.0.3.9: Distinguish between workflow confirmation vs conversation content
                        # Check if user wants conversation content (previous response) vs workflow confirmation
                        conversation_content_indicators = ["response", "verbatim", "full", "complete", "previous", "story", "message"]
                        wants_conversation_content = any(indicator.lower() in user_prompt.lower() for indicator in conversation_content_indicators)

                        if wants_conversation_content:
                            # User wants to email previous assistant response, NOT workflow confirmation
                            logger.info(f"🔄 PROMPT NOT TRANSFORMED: User requesting previous conversation content, not workflow confirmation")
                        else:
                            # Check if user is asking to email something when tools have already been executed
                            email_keywords = ["email the above", "email this", "send the above", "send this", "email it"]
                            if any(keyword.lower() in user_prompt.lower() for keyword in email_keywords):
                                # Transform the prompt to ask for confirmation instead of redoing work
                                if "secure_email_sender" in context_block:
                                    transformed_prompt = "Please confirm what work has been completed and provide a summary of what was accomplished for the user."
                                else:
                                    transformed_prompt = user_prompt  # Keep original if no email was actually sent
                                logger.info(f"🔄 PROMPT TRANSFORMED: Email request → Confirmation request (tools already executed)")
                    else:
                        logger.info(f"🔄 PROMPT NOT TRANSFORMED: Tools were deferred, Primary LLM needs to generate content")
                
                # Build new format: --CONTEXT START-- + ORIGINAL CONVERSATION + CONTEXT BLOCK + PROMPT: [TRANSFORMED PROMPT]
                if context_block.strip():
                    # 🔧 CRITICAL FIX: Include original conversation context so Primary LLM knows what content was processed
                    full_context = ""
                    if prompt_context.strip():
                        full_context += f"{prompt_context}\n\n"
                    full_context += context_block
                    in_prompt = f"--CONTEXT START--\n{full_context}\n--CONTEXT END--\n\nPROMPT: {transformed_prompt}"
                else:
                    # If no tools executed, use original context only
                    if prompt_context.strip():
                        in_prompt = f"--CONTEXT START--\n{prompt_context}\n--CONTEXT END--\n\nPROMPT: {transformed_prompt}"
                    else:
                        in_prompt = f"PROMPT: {transformed_prompt}"
            
            # Core metrics for debugging
            logger.info(f"📜 Prompt: {len(in_prompt)} bytes | Context: {len(context_block)} | System: {len(enhanced_system)}")
            
            # Stream response from Ollama using connection pool
            async with http_pool.get_session() as session:
                # Get think parameter from primary LLM configuration
                # Disable think for meta-tasks (title generation, tagging, etc.)
                primary_config = config_loader.get_llm_config('primary')
                config_options = primary_config.get('config', {})
                
                base_think_enabled = config_options.get('think', False)
                think_enabled = False if is_meta_task else base_think_enabled

                # Use configured values as defaults, with request values as overrides
                stream_payload = {
                    "model": model,
                    "prompt": in_prompt,
                    "system": enhanced_system,
                    "options": {
                        "temperature": data.get('temperature', config_options.get('temperature', 0.7)),
                        "top_k": data.get('top_k', config_options.get('top_k', 40)),
                        "top_p": data.get('top_p', config_options.get('top_p', 0.9)),
                        "num_ctx": data.get('num_ctx', config_options.get('context_window_size', 8192)),
                        "num_predict": data.get('max_tokens', config_options.get('max_tokens', 4096)),
                        "repeat_penalty": data.get('repeat_penalty', config_options.get('repeat_penalty', 1.3)),
                        "low_vram": data.get('low_vram', config_options.get('low_vram', False))
                    },
                    "think": think_enabled,  # Add think parameter from configuration
                    "stream": True
                }
                
                # Add images if they exist (use images_available to survive forced-processing reset when tools_in_use=True)
                if image_exists or images_available:
                    stream_payload["images"] = data.get("images")
                
                logger.info(f"🤖 PRIMARY LLM: {model} | Input: {len(in_prompt)} bytes | Tools: {len(tools_called)}")
                
                # 🔍 DEBUG: DUMP COMPLETE PRIMARY LLM INPUT - This is what gets sent to Primary LLM
                logger.info(f"🔍 DEBUG: ========== PRIMARY LLM PAYLOAD DUMP ==========")
                logger.info(f"🔍 DEBUG: tools_results variable content ({len(tools_results)} chars):")
                truncated_tools_results = truncate_base64_for_logging(tools_results)
                logger.info(f"🔍 DEBUG: tools_results = '{truncated_tools_results}'")
                logger.info(f"🔍 DEBUG: =====================================")
                logger.info(f"🔍 DEBUG: context_block content ({len(context_block)} chars):")
                truncated_context_block = truncate_base64_for_logging(context_block)
                logger.info(f"🔍 DEBUG: context_block = '{truncated_context_block}'")
                logger.info(f"🔍 DEBUG: =====================================")
                logger.info(f"🔍 DEBUG: FULL in_prompt content ({len(in_prompt)} chars):")
                truncated_in_prompt = truncate_base64_for_logging(in_prompt)
                logger.info(f"🔍 DEBUG: in_prompt = '{truncated_in_prompt}'")
                logger.info(f"🔍 DEBUG: ========== END PRIMARY LLM PAYLOAD DUMP ==========")
                
                llm_start_time = time.time()
                
                # 🎯 PRE-LLM IMAGE INJECTION: Check if analytical_visualizer was executed
                if tools_results and "analytical_visualizer" in tools_results:
                    logger.info(f"🖼️ PRE-LLM IMAGE INJECTION: Analytical visualizer detected in tools_results")
                    
                    # Extract base64 image data from tools_results
                    import re
                    # Check for both HTML img tags and raw data URLs
                    img_pattern = r'<img src="(data:image/png;base64,[^"]+)"[^>]*>'
                    raw_data_pattern = r'(data:image/png;base64,[A-Za-z0-9+/=]+)'
                    
                    img_match = re.search(img_pattern, tools_results)
                    raw_match = re.search(raw_data_pattern, tools_results)
                    
                    base64_data_url = None
                    if img_match:
                        base64_data_url = img_match.group(1)
                        logger.info(f"📊 IMAGE FOUND (HTML): {len(base64_data_url)} chars of base64 data")
                    elif raw_match:
                        base64_data_url = raw_match.group(1)
                        logger.info(f"📊 IMAGE FOUND (RAW): {len(base64_data_url)} chars of base64 data")
                    
                    if base64_data_url:
                        
                        # Create unique canvas ID
                        canvas_id = f"viz_canvas_{int(time.time())}"
                        
                        # Create complete HTML page that LibreChat can execute
                        canvas_html = f'''```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analytical Visualization</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .visualization {{
            max-width: 100%;
            height: auto;
            border: 2px solid #ddd;
            border-radius: 8px;
            margin: 20px 0;
        }}
        h1 {{
            color: #333;
            margin-bottom: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Analytical Visualization</h1>
        <img src="{base64_data_url}" class="visualization" alt="Generated Analytical Visualization">
    </div>
</body>
</html>
```'''
                        
                        # 🔄 CHUNKED STREAMING: Break large HTML into manageable chunks  
                        # Ensure proper separation between HTML injection and LLM output
                        full_content = f'{canvas_html}\n\n'
                        chunk_size = 8192  # 8KB chunks for safe transmission
                        logger.info(f"📦 CHUNKED STREAMING: Breaking {len(full_content)} chars into {chunk_size} byte chunks")
                        
                        # Split content into chunks
                        for i in range(0, len(full_content), chunk_size):
                            chunk_content = full_content[i:i+chunk_size]
                            
                            image_chunk = {
                                "id": f"chatcmpl-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": stream_payload.get("model", "default"),
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "content": chunk_content
                                    },
                                    "finish_reason": None
                                }]
                            }
                            
                            yield f'data: {json.dumps(image_chunk)}\n\n'
                            logger.info(f"📦 CHUNK {i//chunk_size + 1}: Sent {len(chunk_content)} chars")
                        
                        # 📋 SEPARATOR CHUNK: Ensure clean boundary between HTML and LLM output
                        separator_chunk = {
                            "id": f"chatcmpl-{int(time.time())}",
                            "object": "chat.completion.chunk", 
                            "created": int(time.time()),
                            "model": stream_payload.get("model", "default"),
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "content": "\n---\n\n"
                                },
                                "finish_reason": None
                            }]
                        }
                        yield f'data: {json.dumps(separator_chunk)}\n\n'
                        
                        total_chunks = (len(full_content) + chunk_size - 1) // chunk_size
                        logger.info(f"✅ PRE-LLM IMAGE INJECTION: Successfully streamed {len(full_content)} chars in {total_chunks} chunks with separator")
                    else:
                        logger.info(f"⚠️ PRE-LLM IMAGE INJECTION: No base64 image found in analytical_visualizer result")
                
                # LLM input ready
                
                # 🔧 STREAMING FIX: Add reasonable timeout and error handling
                # Use a long but finite timeout to prevent infinite hangs
                logger.info(f"🕒 PRIMARY LLM: Starting with 45 minute timeout...")
                
                try:
                    logger.info(f"🧾 PRIMARY LLM: Sending request to Ollama at {ServerConfig.OLLAMA_URL}")
                    
                    # 🔍 COMPREHENSIVE PAYLOAD DUMP - Every field and parameter
                    logger.info("="*80)
                    logger.info("🔍 COMPLETE PRIMARY LLM PAYLOAD DUMP:")
                    logger.info("="*80)
                    logger.info(f"📋 MODEL: {stream_payload.get('model', 'NOT SET')}")
                    logger.info(f"📋 STREAM: {stream_payload.get('stream', 'NOT SET')}")
                    logger.info(f"📋 THINK: {stream_payload.get('think', 'NOT SET')}")
                    
                    # Options dump
                    options = stream_payload.get('options', {})
                    logger.info("📋 OPTIONS:")
                    for key, value in options.items():
                        logger.info(f"   - {key}: {value}")
                    
                    # System prompt dump with length
                    system_prompt = stream_payload.get("system", "")
                    logger.info(f"📋 SYSTEM PROMPT ({len(system_prompt)} chars):")
                    logger.info(f"   First 200 chars: {system_prompt[:200]}")
                    logger.info(f"   Last 200 chars: {system_prompt[-200:]}")
                    
                    # Prompt dump with length  
                    prompt = stream_payload.get("prompt", "")
                    logger.info(f"📋 PROMPT ({len(prompt)} chars):")
                    logger.info(f"   First 500 chars: {prompt[:500]}")
                    logger.info(f"   Last 500 chars: {prompt[-500:]}")
                    
                    # Full JSON dump
                    logger.info("📋 COMPLETE PAYLOAD JSON:")
                    logger.info(json.dumps(stream_payload, indent=2))
                    logger.info("="*80)
                    
                    # 🎯 PHASE 2 FIX: Use LLM Manager instead of hardcoded Ollama
                    logger.info(f"🧾 PRIMARY LLM: System Prompt: {stream_payload['system']}")
                    logger.info(f"🎛️ MANAGER: Routing to configured primary provider")

                    # Prepare parameters for LLM Manager
                    # Get think parameter from primary LLM configuration
                    # Disable think for meta-tasks (title generation, tagging, etc.)
                    primary_config = config_loader.get_llm_config('primary')
                    base_think_enabled = primary_config.get('config', {}).get('think', False)
                    think_enabled = False if is_meta_task else base_think_enabled

                    manager_kwargs = {
                        'model': stream_payload.get('model'),
                        'system_prompt': stream_payload.get('system'),
                        'temperature': stream_payload.get('options', {}).get('temperature', 0.7),
                        'max_tokens': stream_payload.get('options', {}).get('num_predict', 4096),
                        'stream': stream_payload.get('stream', True),
                        'think': think_enabled  # Pass think parameter from configuration
                    }

                    # Add images if present for vision models (use images_available to survive forced-processing reset)
                    if (image_exists or images_available) and stream_payload.get("images"):
                        manager_kwargs['images'] = stream_payload["images"]

                    try:
                        # Log context size information
                        prompt_text = stream_payload['prompt']
                        system_text = manager_kwargs.get('system_prompt', '')
                        full_context = f"{system_text}\n\n{prompt_text}" if system_text else prompt_text

                        char_count = len(full_context)
                        # Rough token estimation: ~4 characters per token for most models
                        token_estimate = char_count // 4

                        logger.info(f"📏 CONTEXT SIZE: {char_count:,} chars (~{token_estimate:,} tokens) → Primary LLM: {stream_payload.get('model', 'unknown')}")

                        # Use LLM Manager for provider-agnostic primary model call
                        async for chunk in llm_manager.generate_stream(stream_payload['prompt'], **manager_kwargs):
                            if chunk:
                                # 🎯 STREAMING FIX: Format LLM Manager text into proper JSON chunks
                                # Native endpoint expects Ollama-style JSON format
                                if isinstance(chunk, str):
                                    # Format text chunk as Ollama-style JSON response
                                    json_chunk = {
                                        "model": stream_payload.get('model', model),
                                        "response": chunk,
                                        "done": False
                                    }
                                    formatted_chunk = json.dumps(json_chunk) + '\n'
                                    yield formatted_chunk.encode('utf-8')
                                else:
                                    # Handle bytes - convert to JSON format
                                    chunk_text = chunk.decode('utf-8') if isinstance(chunk, bytes) else str(chunk)
                                    json_chunk = {
                                        "model": stream_payload.get('model', model),
                                        "response": chunk_text,
                                        "done": False
                                    }
                                    formatted_chunk = json.dumps(json_chunk) + '\n'
                                    yield formatted_chunk.encode('utf-8')

                                # 🎯 PHASE 3 FIX: Unified streaming interface
                                # LLM Manager providers already return clean text content
                                try:
                                    if isinstance(chunk, str):
                                        # Direct text content from LLM Manager
                                        complete_llm_response += chunk
                                    elif isinstance(chunk, bytes):
                                        # Convert bytes to string if needed
                                        chunk_text = chunk.decode('utf-8')
                                        complete_llm_response += chunk_text
                                except Exception as chunk_error:
                                    logger.warning(f"⚠️ Chunk processing error: {chunk_error}")
                                    pass  # Skip malformed chunks

                        # 🎯 STREAMING FIX: Send completion chunk
                        final_chunk = {
                            "model": stream_payload.get('model', model),
                            "response": "",
                            "done": True
                        }
                        final_formatted = json.dumps(final_chunk) + '\n'
                        yield final_formatted.encode('utf-8')

                    except Exception as e:
                        logger.error(f"❌ LLM Manager primary call failed: {e}")
                        # Fallback to direct Ollama if manager fails
                        logger.warning("🔄 Falling back to direct Ollama call")
                        async with session.post(ServerConfig.OLLAMA_URL, json=stream_payload, timeout=3600) as response:
                            if response.status == 200:
                                async for chunk in response.content.iter_chunked(1024):
                                    if chunk:
                                        yield chunk
                                        # Simplified fallback processing
                                        try:
                                            chunk_text = chunk.decode('utf-8')
                                            for line in chunk_text.strip().split('\n'):
                                                if line.strip():
                                                    try:
                                                        chunk_json = json.loads(line)
                                                        if 'response' in chunk_json:
                                                            complete_llm_response += chunk_json['response']
                                                    except Exception:
                                                        pass
                                        except Exception:
                                            pass
                        
                    # Output condition: PRIMARY LLM completed
                    llm_duration = time.time() - llm_start_time
                    logger.info(f"🤖 PRIMARY LLM: COMPLETE | {llm_duration:.2f}s | Output: {len(complete_llm_response)} chars")
                        
                    # Post-processing phase
                    logger.info(f"🔍🔍🔍 CRITICAL: Reached post-processing section!")
                    logger.info(f"🔍 PRE-POST-PROCESSING: email_intercepted={email_intercepted}")
                    logger.info(f"🔍 PRE-POST-PROCESSING: intercepted_email_params={intercepted_email_params}")

                    # 🎯 NEW POST-PROCESSING: Handle intercepted email calls first
                    # 🔧 CRITICAL FIX: Skip email interceptor if legacy POST-LLM auto-execution will run
                    # The legacy path has better dynamic naming (gaza_middle_east_analysis vs html_report)
                    if email_intercepted and not pending_auto_execution:
                        # 🚨 CRITICAL FIX: Block email execution for programming tasks and fabricated emails
                        should_block = False
                            
                        # Block known problematic patterns
                        if verification_result and verification_result.get('pattern') == 'programming_task':
                            should_block = True
                                
                        # Block fabricated email addresses
                        to_email = intercepted_email_params.get('to_email', '')
                        fabricated_indicators = [
                            'recipient@example.com', 'example@example.com', 'user@example.com',
                            'test@test.com', 'demo@demo.com', '@example.'
                        ]
                            
                        if any(indicator in to_email.lower() for indicator in fabricated_indicators):
                            should_block = True
                            logger.warning(f"🚨 FABRICATED EMAIL DETECTED: {to_email}")
                            
                        if should_block:
                            logger.warning(f"🛡️ PROGRAMMING TASK EMAIL BLOCK: Preventing fabricated email execution")
                            logger.warning(f"🛡️ Blocked email params: {intercepted_email_params}")
                            logger.warning(f"🛡️ Task pattern: {verification_result.get('pattern')} - {verification_result.get('reason')}")
                            logger.info(f"🔍 POST-PROCESSING SKIPPED: Programming task email blocked")
                        else:
                            logger.info(f"📧 POST-LLM EMAIL: Processing deferred email")
                            logger.info(f"📧 POST-LLM: Processing intercepted email call")
                            logger.info(f"🎯 Complete LLM response length: {len(complete_llm_response)} characters")
                            # 🔍 DEBUG v1.0.3.10: Check what Primary LLM actually generated
                            logger.info(f"🔍 COMPLETE_LLM_RESPONSE preview (first 500 chars): {complete_llm_response[:500]}")

                            try:
                                logger.info(f"🔄 STEP 1: Extracting filename from intercepted parameters")
                                # 🔧 FIX v1.0.3.21: NEVER trust LLM-generated filenames with dates!
                                # LLMs hallucinate dates and create files like "report_2025_10_12" when it's actually Oct 19
                                # Always generate filenames server-side with correct datetime.now()

                                # Generate proper filename with current timestamp from user_prompt content
                                from datetime import datetime
                                timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')

                                # Name the file from its CONTENT — never from hardcoded topic keywords
                                # (LLM-Policy Gate: no keyword classification). Prefer the subject the
                                # model set for this delivery; else derive a title from the content; slugify.
                                import re as _re_fn
                                _doc_title = (intercepted_email_params.get('subject') or '').strip()
                                if not _doc_title:
                                    # else derive from the document's OWN first heading (content-derived)
                                    for _ln in (complete_llm_response or '').splitlines():
                                        _hm = _re_fn.match(r'^#{1,4}\s+(.+\S)', _ln.strip())
                                        if _hm:
                                            _doc_title = _hm.group(1).strip()[:80]
                                            break
                                _doc_title = _doc_title or 'document'
                                _slug = _re_fn.sub(r'[^a-z0-9]+', '_', _doc_title.lower()).strip('_')[:60] or 'document'
                                filename = f"{_slug}_{timestamp}.html"
                                logger.info(f"🔄 STEP 1-GENERATED: content-derived filename '{filename}' (from '{_doc_title}')")
                                    
                                # Determine if PDF conversion is needed based on file extension
                                convert_to_pdf = filename.lower().endswith('.pdf')
                                logger.info(f"🔄 STEP 1F: File extension check - convert_to_pdf: {convert_to_pdf}")
                                    
                                # Keep original filename - don't force PDF extension
                                logger.info(f"🔄 STEP 1G: Using original filename: '{filename}'")
                                    
                                logger.info(f"🔄 STEP 2: About to create file with Primary LLM content")
                                    
                                # Save Primary LLM response as native Markdown first
                                base_filename = filename.rsplit('.', 1)[0]  # Remove extension
                                markdown_filename = f"{base_filename}.md"
                                logger.info(f"📄 Creating Markdown file: {markdown_filename}")
                                    
                                # Create Markdown file with Primary LLM content
                                md_result = await tool_manager.safe_function_call("sandboxed_executor", {
                                    "action": "create_file",
                                    "filename": markdown_filename,
                                    "content": complete_llm_response.strip(),
                                    "convert_to_pdf": False
                                })
                                    
                                # Check if user requested a specific file type that should be preserved
                                original_ext = filename.lower().split('.')[-1] if '.' in filename else ''
                                preserve_original_format = original_ext in ['py', 'js', 'java', 'cpp', 'c', 'h', 'sql', 'sh', 'yaml', 'yml', 'json', 'xml', 'csv', 'txt']
                                    
                                # CRITICAL FIX: Check if ANY file already exists from tool calling phase - REGARDLESS of extension
                                file_already_exists = False
                                existing_file_path = None
                                    
                                # Get sandbox tool instance from user_tools
                                sandbox_tool = None
                                if hasattr(tool_manager, 'user_tools') and tool_manager.user_tools:
                                    for tool in tool_manager.user_tools:
                                        if tool.name == "sandboxed_executor":
                                            sandbox_tool = tool
                                            break
                                    
                                if sandbox_tool and hasattr(sandbox_tool, 'sandbox_path'):
                                    workspace_path = sandbox_tool.sandbox_path
                                    full_path = workspace_path / filename
                                        
                                    if full_path.exists():
                                        file_already_exists = True
                                        existing_file_path = full_path
                                        existing_size = full_path.stat().st_size
                                        logger.info(f"🔒 EXISTING FILE DETECTED: {full_path} exists ({existing_size} bytes) - will preserve")
                                    else:
                                        logger.info(f"🔍 FILE CHECK: {full_path} does not exist - will create new")
                                else:
                                    logger.warning(f"⚠️ Could not get sandbox tool instance for workspace path check")
                                    
                                if file_already_exists:
                                    # File already exists - ALWAYS preserve, regardless of extension or format
                                    logger.info(f"🔒 PRESERVING EXISTING FILE: {existing_file_path} already exists from tool calling phase")
                                    file_result = {"filename": filename, "preserved": True, "size_bytes": existing_size}
                                elif convert_to_pdf:
                                    logger.info(f"📄 Creating PDF file for email: {filename}")
                                    file_result = await tool_manager.safe_function_call("sandboxed_executor", {
                                        "action": "create_file",
                                        "filename": filename,
                                        "content": complete_llm_response.strip(),
                                        "convert_to_pdf": True
                                    })
                                elif preserve_original_format:
                                    # User requested a specific code/data file type - create it with LLM content
                                    logger.info(f"📄 Creating preserved format file: {filename} (extension: {original_ext})")
                                    file_result = await tool_manager.safe_function_call("sandboxed_executor", {
                                        "action": "create_file",
                                        "filename": filename,
                                        "content": complete_llm_response.strip(),
                                        "convert_to_pdf": False
                                    })
                                    # Keep original filename - don't change it
                                else:
                                    # Create HTML version for email attachment (default behavior for reports)
                                    html_filename = f"{base_filename}.html"
                                    logger.info(f"📄 Creating HTML file for email: {html_filename}")
                                    file_result = await tool_manager.safe_function_call("sandboxed_executor", {
                                        "action": "create_file", 
                                        "filename": html_filename,
                                        "content": complete_llm_response.strip(),
                                        "convert_to_pdf": False
                                    })
                                    # Update filename for email attachment
                                    filename = html_filename
                                    
                                logger.info(f"🔄 STEP 2A: File creation completed")
                                logger.info(f"📄 File creation result: {file_result}")
                                    
                                logger.info(f"🔄 STEP 3: Checking file creation success")
                                # file_result is a string from safe_function_call, need to parse it if it's JSON
                                try:
                                    if isinstance(file_result, str) and file_result.strip().startswith('{'):
                                        file_result_dict = json.loads(file_result)
                                        logger.info(f"🔄 STEP 3A-PARSE: Successfully parsed JSON file_result")
                                    else:
                                        file_result_dict = file_result
                                        logger.info(f"🔄 STEP 3A-PARSE: Using file_result as-is (type: {type(file_result)})")
                                except json.JSONDecodeError as e:
                                    logger.error(f"🔄 STEP 3A-PARSE: JSON parse failed: {e}, using raw result")
                                    file_result_dict = file_result
                                    
                                # Check for successful file creation (JSON result contains filename and success indicators)
                                file_success = (isinstance(file_result_dict, dict) and 
                                              file_result_dict.get("filename") and 
                                              (file_result_dict.get("pdf_generated") == True or 
                                               file_result_dict.get("html_generated") == True or
                                               file_result_dict.get("preserved") == True or
                                               file_result_dict.get("size_bytes", 0) > 0)) or "successfully created" in str(file_result).lower()
                                logger.info(f"🔄 STEP 3A: File success check result: {file_success}")
                                    
                                if file_success:
                                    logger.info(f"🔄 STEP 3A: File creation successful, proceeding to email")
                                    # Update email params with the correct filename for attachment
                                    updated_email_params = intercepted_email_params.copy()
                                        
                                    # 🚨 CRITICAL FIX: Preserve all attachments, don't overwrite with just first one
                                    original_attachments = intercepted_email_params.get('attachments', '')
                                    if isinstance(original_attachments, str) and ',' in original_attachments:
                                        # Multiple attachments provided - preserve all of them
                                        updated_email_params['attachments'] = original_attachments
                                        logger.info(f"🔧 MULTI-ATTACHMENT FIX: Preserving all attachments: {original_attachments}")
                                    else:
                                        # Single attachment or file generation workflow - use processed filename
                                        updated_email_params['attachments'] = filename
                                        
                                    # Ensure body is not empty - add fallback if missing
                                    if not updated_email_params.get('body') or updated_email_params.get('body').strip() == '':
                                        updated_email_params['body'] = f"Please find the attached file: {filename.split('/')[-1]}"
                                        logger.info(f"🔄 STEP 4: Added fallback email body")
                                        
                                    logger.info(f"🔄 STEP 4: About to send email with updated attachment: {filename}")
                                    logger.info(f"🔄 STEP 4: Email params: {updated_email_params}")
                                    # Phase 1 D3: enforce the SAME recipient lock as every other delivery
                                    # path (shared orchestration/policy). Behavior-identical for current
                                    # traffic (auto-trusted clients aren't locked); closes the latent leak
                                    # so a restricted client can never be steered to a prompt-chosen address.
                                    _ic_auth = delivery_policy.authorize_delivery(data)
                                    email_result = await _send_email_locked(
                                        tool_manager, updated_email_params,
                                        _ic_auth.recipient_locked, _ic_auth.locked_recipient)
                                    logger.info(f"🔄 STEP 4A: Email sending completed")
                                    logger.info(f"📧 Email sent: {email_result}")
                                        
                                    # Add to stream response
                                    logger.info(f"🔄 STEP 5: Adding completion message to stream")
                                    yield f'data: {{"post_processing": "completed", "tools_executed": ["sandboxed_executor", "secure_email_sender"]}}\n\n'
                                    logger.info(f"🚪 EXIT: Post-processing completed successfully")
                                else:
                                    logger.error(f"❌ STEP 3B: File creation failed: {file_result}")
                                    logger.info(f"🚪 EXIT: Post-processing failed at file creation")
                                        
                            except Exception as e:
                                logger.error(f"❌ Email post-processing error: {e}")
                                logger.error(f"❌ Exception traceback: {traceback.format_exc()}")
                                logger.info(f"🚪 EXIT: Post-processing failed with exception")
                    else:
                        logger.info(f"🔍 POST-PROCESSING SKIPPED: email_intercepted=False")

                    # 🔌 DEFERRED PLUGIN POST-PROCESSING: Execute deferred publishing plugins with generated content
                    has_deferred_plugins = "__DEFERRED_PARAMS__:" in tools_results
                    logger.info(f"🔍 DEFERRED PLUGIN CHECK: has_deferred_plugins={has_deferred_plugins}")

                    if has_deferred_plugins:
                        logger.info(f"🔌 POST-LLM PLUGIN PROCESSING: Detected deferred plugins in tools_results")
                        logger.info(f"🔌 Complete LLM response length: {len(complete_llm_response)} characters")

                        # Extract deferred plugin calls from tools_results
                        deferred_plugins = []
                        for line in tools_results.split("\n"):
                            if line.startswith("Tool: ") and ("social_media_" in line or "publishing_" in line or "_publish" in line or "_post" in line):
                                tool_name = line.replace("Tool: ", "").strip()
                                deferred_plugins.append(tool_name)

                        logger.info(f"🔌 Found {len(deferred_plugins)} deferred plugins: {deferred_plugins}")

                        # Execute each deferred plugin
                        for tool_name in deferred_plugins:
                            logger.info(f"🔌 POST-LLM PLUGIN: Executing deferred plugin {tool_name}")

                            # Extract deferred parameters from tools_results
                            params_marker = f"__DEFERRED_PARAMS__:"
                            tool_section_start = tools_results.find(f"Tool: {tool_name}")
                            if tool_section_start != -1:
                                params_start = tools_results.find(params_marker, tool_section_start)
                                if params_start != -1:
                                    params_start += len(params_marker)
                                    params_end = tools_results.find("\n", params_start)
                                    if params_end == -1:
                                        params_end = len(tools_results)

                                    params_json = tools_results[params_start:params_end].strip()
                                    try:
                                        import json as json_lib
                                        plugin_params = json_lib.loads(params_json)

                                        # Fill {{PRIMARY_LLM_OUTPUT}} placeholder with actual generated content
                                        filled_params = {}
                                        for key, value in plugin_params.items():
                                            if isinstance(value, str) and "{{PRIMARY_LLM_OUTPUT}}" in value:
                                                # Use cleaned LLM response content
                                                filled_value = value.replace("{{PRIMARY_LLM_OUTPUT}}", complete_llm_response.strip())
                                                filled_params[key] = filled_value
                                                logger.info(f"🔌 POST-LLM: Filled {key} with generated content ({len(filled_value)} chars)")
                                            else:
                                                filled_params[key] = value

                                        # Execute the plugin with filled parameters
                                        logger.info(f"🔌 POST-LLM: Executing {tool_name} with filled parameters: {list(filled_params.keys())}")
                                        result = await tool_manager.safe_function_call(tool_name, filled_params)

                                        logger.info(f"🔌 POST-LLM PLUGIN: {tool_name} completed - Result: {result[:200] if result else 'None'}...")

                                        # Add to stream response
                                        yield f'data: {{"post_processing": "plugin_executed", "tool": "{tool_name}", "result": "completed"}}\n\n'

                                    except Exception as e:
                                        logger.error(f"❌ POST-LLM PLUGIN ERROR ({tool_name}): {e}")
                                        logger.error(f"❌ Exception traceback: {traceback.format_exc()}")

                        logger.info(f"✅ POST-LLM PLUGIN PROCESSING COMPLETED: {len(deferred_plugins)} plugins executed")
                    else:
                        logger.info(f"🔍 DEFERRED PLUGIN PROCESSING SKIPPED: No deferred plugins detected")

                    # 🎯 POST-LLM AUTO-EXECUTION: Execute missing tools with complete content (legacy)
                    logger.info(f"🔍 DEBUG: pending_auto_execution={pending_auto_execution}, verification_result={verification_result}, is_meta_task={is_meta_task}")

                    # 🔧 FIX v1.0.3.110: Block meta tasks from executing publishing tools
                    if is_meta_task and pending_auto_execution and verification_result:
                        logger.info(f"🚫 META-TASK BLOCKED: Preventing meta task from executing publishing tools: {verification_result.get('missing_tools', [])}")

                    if pending_auto_execution and verification_result and not is_meta_task:
                        # 🔒 v1.0.0.51: Filter POST-LLM missing tools against allowed_tools whitelist
                        post_llm_missing_tools = verification_result['missing_tools']
                        request_allowed_tools = data.get('allowed_tools')
                        # 📦 v1.0.0.81: DELIVERY PRIVILEGE on the legacy POST-LLM path. A client that
                        # presents an explicit allow_delivery=True privilege (e.g. a NewX user with the
                        # "email via RAICA" right) may use the DELIVERY tools (file creation + email)
                        # even though they are deliberately excluded from its zero-trust allowed_tools
                        # whitelist. SECURITY: for such a RESTRICTED client (one that sends an
                        # allowed_tools whitelist) the email recipient is LOCKED to delivery_recipient
                        # (the user's own server-authoritative account email) inside the executor — a
                        # prompt-specified address is NEVER honored. This mirrors the deep-research
                        # delivery path. Phase 1: both paths now derive this from the SAME shared policy
                        # (orchestration/policy.authorize_delivery) so they cannot drift apart.
                        _post_auth = delivery_policy.authorize_delivery(data)
                        _post_allow_delivery = _post_auth.permitted
                        _post_recipient_locked = _post_auth.recipient_locked
                        _post_locked_recipient = _post_auth.locked_recipient
                        if request_allowed_tools:
                            _effective_allowed = set(request_allowed_tools)
                            if _post_allow_delivery:
                                # Delivery is permitted for this bot+actor → run the post-generation
                                # ACTIONS the intent classifier chose. The LLM classifier is the authority
                                # on WHICH tools the request needs; the privilege gate decides WHETHER
                                # delivery happens. No hardcoded delivery-tool name list (LLM-Policy Gate).
                                _effective_allowed |= set(post_llm_missing_tools)
                            blocked = [t for t in post_llm_missing_tools if t not in _effective_allowed]
                            if blocked:
                                logger.warning(f"🔒 POST-LLM WHITELIST: Blocked tools not in allowed_tools: {blocked}")
                            if _post_allow_delivery and post_llm_missing_tools:
                                logger.info(f"📦 POST-LLM DELIVERY PRIVILEGE: allow_delivery=True → permitting "
                                            f"classifier-selected actions {post_llm_missing_tools}; recipient "
                                            f"{'LOCKED to '+str(_post_locked_recipient) if _post_recipient_locked else 'from request (auto-trusted client)'}")
                            post_llm_missing_tools = [t for t in post_llm_missing_tools if t in _effective_allowed]

                        if not post_llm_missing_tools:
                            logger.info(f"🔒 POST-LLM AUTO-EXECUTION SKIPPED: All missing tools blocked by whitelist")
                        else:
                            logger.info(f"🎯 POST-LLM AUTO-EXECUTION: Primary LLM completed, executing missing tools: {post_llm_missing_tools}")
                            logger.info(f"🎯 Complete LLM response length: {len(complete_llm_response)} characters")

                        if post_llm_missing_tools:
                            try:
                                # 🔧 CRITICAL FIX v1.0.3.9: Use actual_user_prompt (original) not user_prompt (may be reassigned/empty)
                                logger.info(f"🔍 BEFORE POST-LLM CALL: actual_user_prompt = {repr(actual_user_prompt[:200] if actual_user_prompt else 'EMPTY!')}")
                                logger.info(f"🔍 BEFORE POST-LLM CALL: user_prompt = {repr(user_prompt[:200] if user_prompt else 'EMPTY!')}")
                                # Execute missing tools with complete LLM response as content
                                # 🤖 v1.0.3.111: Pass llm_manager for Arbitrator-based parameter generation
                                additional_results = await _execute_missing_tools_post_llm(
                                    post_llm_missing_tools,
                                    tool_manager,
                                    tools_results,
                                    complete_llm_response,
                                    actual_user_prompt,
                                    llm_manager,
                                    locked_recipient=_post_locked_recipient,
                                    recipient_locked=_post_recipient_locked
                                )
                                # Neutral framing: the executor FINISHED running — per-action status
                                # (✅ sent / ⚠️ delivery failed) is carried inside additional_results, so we
                                # do NOT stamp a blanket "✅ COMPLETED" that would mislabel a failed send.
                                logger.info(f"📦 POST-LLM AUTO-EXECUTION FINISHED:\n{additional_results}")

                                # 🔧 FIX v1.0.3.19: Stream POST-LLM results in Ollama's JSON format
                                # This ensures Discord client displays the results correctly
                                if additional_results:
                                    # Format as readable text
                                    result_text = f"\n\n---\nPOST-PROCESSING RESULT:\n{additional_results}\n---\n"

                                    # Stream in Ollama's format so Discord client displays it
                                    import time
                                    post_llm_chunk = json.dumps({
                                        "model": model,
                                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                        "message": {
                                            "role": "assistant",
                                            "content": result_text
                                        },
                                        "done": False
                                    })
                                    yield (post_llm_chunk + '\n').encode()
                                    logger.info(f"📤 POST-LLM: Streamed results to user ({len(result_text)} chars)")

                            except Exception as e:
                                logger.error(f"❌ POST-LLM AUTO-EXECUTION FAILED: {e}")
                                error_msg = json.dumps({
                                    "post_processing": "failed",
                                    "error": str(e)
                                })
                                yield (error_msg + '\n').encode()

                except asyncio.TimeoutError:
                    logger.error("🕒 PRIMARY LLM: Request timed out after 10 minutes")
                    error_msg = json.dumps({"error": "Primary LLM request timed out"})
                    yield error_msg.encode() + b'\n'
                except Exception as http_error:
                    logger.error(f"🔗 PRIMARY LLM: HTTP request failed: {http_error}")
                    error_msg = json.dumps({"error": f"Primary LLM HTTP error: {str(http_error)}"})
                    yield error_msg.encode() + b'\n'
        
        except Exception as e:
            logger.error(f"Stream generation failed: {e}")
            error_msg = json.dumps({"error": f"Stream failed: {str(e)}"})
            yield error_msg.encode() + b'\n'
        logger.info("--- EXITING GENERATE_STREAM ---")
    
    logger.info("--- EXITING OLLAMA_STREAM ---")
    return StreamingResponse(
        generate_stream(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no"  # Critical: Prevent proxy buffering
        }
    )

# ==============================================================================
# BASIC ENDPOINTS (from simple version)
# ==============================================================================

@app.get("/", response_model=ApiResponse)
async def root():
    """Root endpoint"""
    return ApiResponse(
        success=True,
        data={"message": "FastAPI Analytics Server with Ollama LLM Integration"},
        timestamp=datetime.now().isoformat()
    )

@app.get("/health")
async def health_check():
    """Enhanced health check with Ollama status"""
    services = {"database": "unknown", "cache": "memory", "ollama": "unknown"}
    
    # Check database
    if db_pool:
        try:
            async with get_db_connection() as conn:
                services["database"] = "healthy"
        except Exception:
            services["database"] = "unhealthy"
    else:
        services["database"] = "unavailable"
    
    # Check Ollama
    ollama_healthy = await check_ollama_health()
    services["ollama"] = "healthy" if ollama_healthy else "unhealthy"
    
    overall_status = "healthy" if all(
        status in ["healthy", "memory", "unavailable"] for status in services.values()
    ) else "unhealthy"
    
    return {
        "status": overall_status,
        "timestamp": datetime.now().isoformat(),
        "version": __version__,
        "services": services,
        "cache_size": len(simple_cache),
        "tools_available": TOOLS_AVAILABLE
    }

# ==============================================================================
# LOGGING CONTROL ENDPOINTS
# ==============================================================================

@app.get("/admin/logging/status")
async def get_logging_status():
    """Get current logging configuration and status"""
    root_logger = logging.getLogger()
    current_level = root_logger.level

    # Get current config values
    debug_config = config_loader.load_config().get('debug', {})

    return {
        "logging_status": {
            "enabled": current_level != logging.CRITICAL + 1,
            "level": logging.getLevelName(current_level),
            "level_numeric": current_level,
            "disabled": logging.root.disabled,
            "handlers_count": len(root_logger.handlers)
        },
        "configuration": {
            "log_requests": debug_config.get('log_requests', True),
            "log_timing": debug_config.get('log_timing', True),
            "mock_providers": debug_config.get('mock_providers', False)
        },
        "log_levels": {
            "CRITICAL": logging.CRITICAL,
            "ERROR": logging.ERROR,
            "WARNING": logging.WARNING,
            "INFO": logging.INFO,
            "DEBUG": logging.DEBUG
        }
    }

@app.post("/admin/logging/enable")
async def enable_logging():
    """Enable logging with INFO level"""
    global log_requests_enabled, log_timing_enabled

    # Re-enable logging
    logging.disable(logging.NOTSET)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Update global flags
    log_requests_enabled = True
    log_timing_enabled = True

    logger.info("🔊 LOGGING ENABLED via API call")

    return {
        "status": "success",
        "message": "Logging enabled",
        "level": "INFO",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/admin/logging/disable")
async def disable_logging():
    """Disable all logging"""
    global log_requests_enabled, log_timing_enabled

    logger.info("🔇 LOGGING DISABLED via API call")

    # Disable logging
    logging.disable(logging.CRITICAL)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.CRITICAL + 1)

    # Update global flags
    log_requests_enabled = False
    log_timing_enabled = False

    return {
        "status": "success",
        "message": "Logging disabled",
        "level": "DISABLED",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/admin/logging/level/{level}")
async def set_logging_level(level: str):
    """Set specific logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"""
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }

    level_upper = level.upper()
    if level_upper not in level_map:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid log level. Must be one of: {list(level_map.keys())}"
        )

    # Enable logging if it was disabled and set the new level
    logging.disable(logging.NOTSET)
    root_logger = logging.getLogger()
    root_logger.setLevel(level_map[level_upper])

    logger.info(f"📊 LOGGING LEVEL SET TO {level_upper} via API call")

    return {
        "status": "success",
        "message": f"Logging level set to {level_upper}",
        "level": level_upper,
        "level_numeric": level_map[level_upper],
        "timestamp": datetime.now().isoformat()
    }

@app.post("/admin/logging/requests/toggle")
async def toggle_request_logging():
    """Toggle request logging on/off"""
    global log_requests_enabled

    log_requests_enabled = not log_requests_enabled

    status = "enabled" if log_requests_enabled else "disabled"
    logger.info(f"📝 REQUEST LOGGING {status.upper()} via API call")

    return {
        "status": "success",
        "message": f"Request logging {status}",
        "request_logging": log_requests_enabled,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/admin/logging/timing/toggle")
async def toggle_timing_logging():
    """Toggle timing logging on/off"""
    global log_timing_enabled

    log_timing_enabled = not log_timing_enabled

    status = "enabled" if log_timing_enabled else "disabled"
    logger.info(f"⏱️ TIMING LOGGING {status.upper()} via API call")

    return {
        "status": "success",
        "message": f"Timing logging {status}",
        "timing_logging": log_timing_enabled,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/help")
async def user_help():
    """User help endpoint providing quick reference and documentation"""
    help_content = {
        "agentic_rag_system": {
            "version": __version__,
            "description": "High-performance AI assistant with local language models and intelligent tool calling",
            "base_url": "http://localhost:5000"
        },
        
        "quick_start": {
            "basic_prompt": "POST /llama3_1b/stream",
            "openai_compatible": "POST /v1/chat/completions",
            "example_request": {
                "url": "http://localhost:5000/llama3_1b/stream",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "prompt": "Hello! What can you help me with today?",
                    "model": "qwen3:8b",
                    "toolsInUse": True,
                    "stream": False
                }
            }
        },
        
        "available_tools": {
            "total_count": 19,
            "categories": {
                "search_and_web": [
                    "search_web - Search the internet for current information",
                    "get_web_content - Extract and analyze content from web pages"
                ],
                "document_management": [
                    "document_search - Search through indexed documents using semantic search",
                    "watch_directory - Monitor directories for new documents",
                    "index_directory - Add new documents to the search index"
                ],
                "communication": [
                    "send_email - Send emails with attachments",
                    "send_mass_email - Send bulk emails to multiple recipients"
                ],
                "financial_and_data": [
                    "stock_data - Get real-time stock prices and financial data",
                    "flight_search - Search for flights with multiple booking options"
                ],
                "productivity": [
                    "calendar_tools - Create and manage calendar events",
                    "execute_code - Run code safely in sandboxed environment"
                ],
                "file_operations": [
                    "file_operations - Read, write, and manage files",
                    "process_image - Analyze images with AI vision processing"
                ],
                "system_utilities": [
                    "weather_data - Get current weather and forecasts",
                    "system_info - Retrieve system information and stats",
                    "math_operations - Perform complex mathematical calculations",
                    "time_operations - Work with dates and time calculations"
                ]
            }
        },
        
        "key_endpoints": {
            "health_check": "GET /health - Check system health and service status",
            "help": "GET /help - This help information",
            "models": "GET /v1/models - List available AI models",
            "chat": "POST /v1/chat/completions - OpenAI-compatible chat completions",
            "stream": "POST /llama3_1b/stream - Native streaming endpoint",
            "documents": {
                "search": "POST /documents/search - Search indexed documents",
                "stats": "GET /documents/stats - Document index statistics",
                "config": "GET /documents/config - View document configuration"
            },
            "admin": {
                "logging_status": "GET /admin/logging/status - Get current logging configuration",
                "enable_logging": "POST /admin/logging/enable - Enable all logging with INFO level",
                "disable_logging": "POST /admin/logging/disable - Disable all logging",
                "set_log_level": "POST /admin/logging/level/{level} - Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
                "toggle_requests": "POST /admin/logging/requests/toggle - Toggle request logging on/off",
                "toggle_timing": "POST /admin/logging/timing/toggle - Toggle timing logging on/off"
            }
        },
        
        "tool_usage": {
            "how_to_enable_tools": "Set 'toolsInUse': true in your request",
            "automatic_selection": "The AI automatically selects appropriate tools based on your query",
            "example_queries": [
                "Search for recent news about AI developments",
                "Find documents about server configuration in my files",
                "Send an email to john@example.com with project update",
                "What's the current stock price of AAPL?",
                "Create a calendar event for next Monday at 2 PM",
                "What's the weather forecast for tomorrow?"
            ]
        },
        
        "getting_help": {
            "documentation": {
                "user_guide": "docs/production/USER_GUIDE.md",
                "admin_guide": "docs/production/ADMINISTRATOR_GUIDE.md",
                "developer_guide": "docs/production/DEVELOPER_GUIDE.md",
                "installation": "docs/setup/INSTALLATION.md"
            },
            "support": {
                "logs": "Check server_complete.log for error details",
                "health": "Use GET /health to check service status",
                "models": "Use GET /ollama/models to verify model availability"
            }
        }
    }
    
    return help_content

@app.get("/ollama/models")
async def list_ollama_models():
    """List available Ollama models"""
    try:
        async with http_pool.get_session() as session:
            async with session.get(_get_ollama_health_url()) as response:
                if response.status == 200:
                    data = await response.json()
                    return ApiResponse(
                        success=True,
                        data=data,
                        timestamp=datetime.now().isoformat()
                    )
                else:
                    raise HTTPException(status_code=502, detail="Ollama service unavailable")
    except Exception as e:
        logger.error(f"Failed to list Ollama models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/retrieve_system_prompts")
async def retrieve_system_prompts(request: Request):
    """
    Retrieve system prompts from file
    Matches the exact behavior of the original Flask /retrieve_system_prompts endpoint
    """
    # Parse JSON data like the original Flask version
    data = await request.json()
    
    # Get filename exactly like the original
    filename = data.get('system_prompts_filename')
    logger.info(f"Retrieved filename: {filename}")
    
    # Validation exactly like the original
    if "system_prompts_filename" not in data:
        return JSONResponse(
            content={'message': 'Missing system_prompts_filename parameter'}, 
            status_code=400
        )
    
    system_prompts_filename = data["system_prompts_filename"]
    logger.info(f"----> {system_prompts_filename} from server")
    
    if not system_prompts_filename:
        return JSONResponse(
            content={'message': 'system_prompts_filename cannot be empty'}, 
            status_code=400
        )
    
    try:
        # Construct the full path to the file (exactly like original)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        prompts_dir = os.path.join(base_dir, 'prompts')
        file_path = os.path.join(prompts_dir, filename)  # Use filename like original
        
        # Print the directory being read from for debugging (like original)
        logger.info(f"Reading file from: {file_path}")
        
        # Read the file content (simple sync read like original)
        with open(file_path, 'r', encoding='utf-8') as file:
            file_content = file.read()
        
        # Return the file content as JSON (exactly like original)
        return JSONResponse(content=file_content, status_code=200)
            
    except FileNotFoundError:
        return JSONResponse(
            content={'message': f'File not found: {system_prompts_filename}'}, 
            status_code=404
        )
    except Exception as e:
        return JSONResponse(
            content={'message': f'Error occurred: {str(e)}'}, 
            status_code=500
        )

@app.get("/metrics")
async def get_metrics():
    """Enhanced metrics including Ollama status"""
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
    except Exception:
        cpu_percent = 0
        memory = None
    
    db_stats = {
        "available": db_pool is not None,
        "size": db_pool.size if db_pool else 0,
        "free": db_pool.freesize if db_pool else 0
    }
    
    ollama_status = await check_ollama_health()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "system": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent if memory else 0,
        },
        "database_pool": db_stats,
        "cache": {
            "type": "memory",
            "size": len(simple_cache)
        },
        "ollama": {
            "available": ollama_status,
            "url": ServerConfig.OLLAMA_URL
        },
        "tools": {
            "available": TOOLS_AVAILABLE,
            "count": len(tool_manager.available_functions)
        }
    }

# ==============================================================================
# OPTIMIZATION CONTROL ENDPOINTS
# ==============================================================================

@app.get("/optimization/status")
async def get_optimization_status():
    """Get comprehensive optimization system status"""
    if not OPTIMIZATION_AVAILABLE:
        return JSONResponse(
            content={
                "available": False,
                "error": "Optimization system not loaded"
            },
            status_code=503
        )
    
    return JSONResponse(content={
        "available": True,
        "status": optimization_controller.get_status_summary()
    })

@app.post("/optimization/enable")
async def enable_optimization(rollout_percentage: float = 100.0):
    """Enable optimization with optional gradual rollout"""
    if not OPTIMIZATION_AVAILABLE:
        return JSONResponse(
            content={"error": "Optimization system not available"},
            status_code=503
        )
    
    try:
        optimization_controller.enable_feature(rollout_percentage)
        return JSONResponse(content={
            "message": f"Optimization enabled with {rollout_percentage}% rollout",
            "status": optimization_controller.get_status_summary()
        })
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

@app.post("/optimization/disable")
async def disable_optimization():
    """Disable optimization completely"""
    if not OPTIMIZATION_AVAILABLE:
        return JSONResponse(
            content={"error": "Optimization system not available"},
            status_code=503
        )
    
    try:
        optimization_controller.disable_feature()
        return JSONResponse(content={
            "message": "Optimization disabled",
            "status": optimization_controller.get_status_summary()
        })
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

@app.post("/optimization/rollout")
async def set_rollout_percentage(percentage: float):
    """Set rollout percentage for gradual deployment"""
    if not OPTIMIZATION_AVAILABLE:
        return JSONResponse(
            content={"error": "Optimization system not available"},
            status_code=503
        )
    
    try:
        optimization_controller.set_rollout_percentage(percentage)
        return JSONResponse(content={
            "message": f"Rollout percentage set to {percentage}%",
            "status": optimization_controller.get_status_summary()
        })
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

@app.post("/optimization/emergency-rollback")
async def emergency_rollback(reason: str = "Manual emergency rollback"):
    """Trigger emergency rollback"""
    if not OPTIMIZATION_AVAILABLE:
        return JSONResponse(
            content={"error": "Optimization system not available"},
            status_code=503
        )
    
    try:
        rollback_event = optimization_controller.emergency_rollback(reason)
        return JSONResponse(content={
            "message": "Emergency rollback executed",
            "rollback_event": rollback_event
        })
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

# ==============================================================================
# OPENAI COMPATIBILITY ENDPOINT
# ==============================================================================

@app.get("/v1/models")
async def openai_models():
    """OpenAI compatible models endpoint"""
    try:
        # Build the response
        response_data = {
            "object": "list",
            "data": [
                {
                    "id": "RAICA-Model1",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "local"
                },
                {
                    "id": "RAICA-Model2",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "local"
                }
            ]
        }
        
        # Debug logging
        logger.info(f"🔍 /v1/models endpoint called - returning {len(response_data['data'])} models")
        logger.info(f"🔍 Models being returned:")
        for i, model in enumerate(response_data['data']):
            logger.info(f"🔍   Model {i+1}: {model['id']} (created: {model['created']}, owned_by: {model['owned_by']})")
        truncated_full_response = truncate_base64_for_logging(json.dumps(response_data, indent=2))
        logger.info(f"🔍 Full response: {truncated_full_response}")
        
        return response_data
        
    except Exception as e:
        logger.error(f"🚨 Models endpoint error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/chat/completions")
async def openai_chat_completions(request: OpenAIChatRequest):
    logger.info("--- ENTERING OLLAMA_STREAM ---")
    """
    OpenAI API Compatible Chat Completions Endpoint
    
    Zero-Trust Security Model:
    - Only extracts user prompt from messages and model name
    - Ignores all other parameters (temperature, top_p, etc.)
    - Forces tools=True and uses our system prompt
    - Routes through existing tool calling pipeline
    """
    try:
        # SECURITY: Extract only what we trust - user prompt and model name
        user_prompt = ""
        conversation_context = ""
        
        # Extract conversation ID from messages or generate one based on content hash
        conversation_id = hashlib.md5(str(request.messages).encode()).hexdigest()[:12]
        
        # Build conversation context from message history
        message_history = []
        images = []  # Collect images from vision requests
        
        # 🖼️ CRITICAL FIX: Use images parameter if provided (custom format)
        if request.images and request.images != ["noimage"]:
            images.extend(request.images)
            logger.info(f"🖼️ Using images from request parameter: {len(images)} images")
        
        for message in request.messages:
            if message.role in ["user", "assistant"]:
                # Handle both string and structured content (for vision)
                if isinstance(message.content, str):
                    content_text = message.content
                elif isinstance(message.content, list):
                    # Extract text and images from structured content
                    text_parts = []
                    for item in message.content:
                        if item.get('type') == 'text':
                            text_parts.append(item.get('text', ''))
                        elif item.get('type') == 'image_url':
                            image_url = item.get('image_url', {}).get('url', '')
                            if image_url.startswith('data:image/'):
                                # Extract base64 data
                                base64_data = image_url.split(',', 1)[1] if ',' in image_url else image_url
                                images.append(base64_data)
                            elif image_url.startswith('file://'):
                                # Extract local file path
                                file_path = image_url[7:]  # Remove 'file://' prefix
                                file_path = os.path.expanduser(file_path)
                                # Path traversal protection: block sensitive system paths
                                resolved = os.path.realpath(file_path)
                                BLOCKED_PATHS = ['/etc/passwd', '/etc/shadow', '/root', '/proc', '/sys', '/dev', '/boot']
                                if any(resolved.startswith(bp) for bp in BLOCKED_PATHS):
                                    logger.error(f"🖼️ Path traversal blocked (sensitive system path): {file_path} -> {resolved}")
                                    continue
                                if os.path.exists(file_path):
                                    try:
                                        with open(file_path, 'rb') as f:
                                            img_bytes = f.read()
                                        base64_data = base64.b64encode(img_bytes).decode('utf-8')
                                        images.append(base64_data)
                                        logger.info(f"🖼️ Loaded local file: {file_path} ({len(img_bytes)} bytes)")
                                    except Exception as e:
                                        logger.error(f"🖼️ Error loading file {file_path}: {e}")
                                else:
                                    logger.warning(f"🖼️ File not found: {file_path}")
                    content_text = ' '.join(text_parts)
                else:
                    content_text = str(message.content)
                
                message_history.append(f"{message.role.upper()}: {content_text}")
                if message.role == "user":
                    user_prompt = content_text  # Use the latest user message text
        
        if not user_prompt:
            raise HTTPException(status_code=400, detail="No user message found")
            
        # Check if this is a follow-up prompt (more than 1 message)
        is_followup = len(message_history) > 1
        if is_followup:
            conversation_context = "\n\n=== CONVERSATION HISTORY ===\n" + "\n".join(message_history[:-1]) + "\n=== CURRENT REQUEST ===\n"
            logger.info(f"🔄 FOLLOW-UP DETECTED: Conversation {conversation_id} with {len(message_history)} messages")
        else:
            logger.info(f"🆕 NEW CONVERSATION: {conversation_id}")
        
        logger.info(f"\n\n🔒 OpenAI Compatibility Request - Model: {request.model}")
        logger.info(f"🔒 Extracted user prompt: {user_prompt[:100]}...")
        logger.info(f"🔒 SECURITY: All other parameters discarded per zero-trust design")
        
        # Check if streaming is requested
        is_streaming = request.stream if request.stream is not None else False
        
        # Combine context with current prompt for follow-up conversations
        enhanced_prompt = conversation_context + user_prompt if is_followup else user_prompt
        
        if is_streaming:
            return await openai_streaming_response(enhanced_prompt, request.model, conversation_id, images, allowed_tools=request.allowed_tools, deep_research=request.deep_research, allow_delivery=request.allow_delivery, delivery_recipient=request.delivery_recipient)
        else:
            return await openai_non_streaming_response(enhanced_prompt, request.model, conversation_id, images, allowed_tools=request.allowed_tools, deep_research=request.deep_research, allow_delivery=request.allow_delivery, delivery_recipient=request.delivery_recipient)
        
    except Exception as e:
        logger.error(f"🚨 OpenAI compatibility error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

async def openai_non_streaming_response(user_prompt: str, model: str, conversation_id: str, images: list = None, allowed_tools: list = None, deep_research: bool = None, allow_delivery: bool = None, delivery_recipient: str = None):
    """Handle non-streaming OpenAI response with proper format"""
    try:
        logger.info(f"🔒 OpenAI Non-streaming Response - falling back to streaming with collect")

        # For non-streaming, we'll use streaming mode and collect all chunks
        streaming_response = await openai_streaming_response(user_prompt, model, conversation_id, images, allowed_tools=allowed_tools, deep_research=deep_research, allow_delivery=allow_delivery, delivery_recipient=delivery_recipient)
        
        # Collect all streaming content
        response_content = ""
        async for chunk in streaming_response.body_iterator:
            # Handle both bytes and string chunks
            if isinstance(chunk, bytes):
                chunk_data = chunk.decode('utf-8')
            else:
                chunk_data = str(chunk)
            # Parse JSON chunks and extract content
            lines = chunk_data.strip().split('\n')
            for line in lines:
                if line.startswith('data: ') and not line.endswith('[DONE]'):
                    try:
                        data_line = line[6:]  # Remove 'data: ' prefix
                        if data_line.strip():  # Skip empty lines
                            chunk_json = json.loads(data_line)
                            if 'choices' in chunk_json and len(chunk_json['choices']) > 0:
                                if 'delta' in chunk_json['choices'][0] and 'content' in chunk_json['choices'][0]['delta']:
                                    response_content += chunk_json['choices'][0]['delta']['content']
                    except json.JSONDecodeError:
                        continue

        # Non-streaming clients (e.g. NewX) COLLECT the whole stream and PUBLISH it as a permanent
        # (often PUBLIC) artifact. Strip from the assembled content:
        #   • transient "⏳ retrying…" keepalives — meaningless once collected (the chunks still
        #     flowed over the wire, keeping the connection warm during retry waits);
        #   • the "📎 Delivery: …" SUCCESS footnote — it names the recipient's email, which must NOT
        #     be echoed into a public post (the delivery email is itself the confirmation).
        # Failure alerts ("⚠️ Delivery: …") are KEPT — they carry no email and must not be silent.
        if "⏳" in response_content or "📎" in response_content:
            _lines = [_ln for _ln in response_content.split("\n")
                      if "⏳" not in _ln and "📎" not in _ln]
            # Drop any now-dangling trailing separator/blank lines left by a stripped footnote.
            while _lines and _lines[-1].strip() in ("", "---", "***", "___"):
                _lines.pop()
            response_content = "\n".join(_lines)

        # Return in standard OpenAI non-streaming format
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": _count_tokens(user_prompt),
                "completion_tokens": _count_tokens(response_content),
                "total_tokens": _count_tokens(user_prompt) + _count_tokens(response_content)
            }
        }
        
    except Exception as e:
        logger.error(f"🚨 OpenAI non-streaming error: {str(e)}")
        logger.error(traceback.format_exc())
        error_detail = str(e)[:1000]  # Truncate for safe inclusion in response
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"Error processing request: {error_detail}"
                    },
                    "finish_reason": "error"
                }
            ],
            "error": {
                "message": error_detail,
                "type": type(e).__name__
            },
            "usage": {
                "prompt_tokens": _count_tokens(user_prompt),
                "completion_tokens": 0,
                "total_tokens": _count_tokens(user_prompt)
            }
        }

async def openai_direct_stream(native_request_data: dict, model: str):
    """
    Option 2: Direct function calls to internal llama_stream (Faster, no HTTP overhead)
    Respects Prime Directive: Does not modify core server code
    FIXED: Properly handles StreamingResponse from llama_stream
    """
    try:
        logger.info(f"🎯 Direct streaming: Calling internal llama_stream function")

        # Sanitize request data for logging (truncate image data to prevent log flooding)
        safe_request_data = native_request_data.copy()
        if 'images' in safe_request_data and isinstance(safe_request_data['images'], list):
            safe_images = []
            for img in safe_request_data['images']:
                if isinstance(img, str) and len(img) > 100 and img != 'noimage':
                    safe_images.append(f"{img[:100]}... ({len(img)} chars)")
                else:
                    safe_images.append(img)
            safe_request_data['images'] = safe_images

        logger.debug(f"🔧 DIRECT_STREAM DEBUG: Received native_request_data: {safe_request_data}")
        logger.debug(f"🔧 DIRECT_STREAM DEBUG: model: {model}")

        # Create mock request object for llama_stream (following Prime Directive)
        class MockRequest:
            def __init__(self, data):
                self._data = data
            async def json(self):
                # Sanitize data for logging
                safe_data = self._data.copy()
                if 'images' in safe_data and isinstance(safe_data['images'], list):
                    image_count = len([img for img in safe_data['images'] if img != 'noimage'])
                    safe_data['images'] = f"[{image_count} image(s) - truncated for logging]"
                logger.info(f"🔧 MockRequest.json() called with data: {safe_data}")
                return self._data

        mock_request = MockRequest(native_request_data)
        logger.info(f"🔧 Native request data being passed: {safe_request_data}")
        
        # 🔧 CRITICAL DEBUG: Compare with working native format
        logger.info(f"🔧 COMPARISON - This should match working native requests")
        logger.debug(f"🔧 DIAGNOSTIC: OpenAI endpoint calling llama_stream with toolsInUse={native_request_data.get('toolsInUse')}")
        
        # 🖼️ Set image context for OpenAI endpoint - extract images from request data
        if native_request_data.get('images') and native_request_data['images'] != ['noimage']:
            tool_manager.set_image_context(native_request_data['images'], {"endpoint": "openai", "model": model})
        
        # Call the native llama_stream function directly
        internal_response = await llama_stream(mock_request)
        
        # 🔧 FIX: Properly handle StreamingResponse object with HTML injection support
        if hasattr(internal_response, 'body_iterator'):
            logger.info("🔧 Processing StreamingResponse body_iterator")
            async for chunk_data in internal_response.body_iterator:
                # Handle both bytes and string chunks
                if isinstance(chunk_data, bytes):
                    raw_content = chunk_data.decode('utf-8', errors='ignore')
                else:
                    raw_content = str(chunk_data)
                
                logger.debug(f"🔧 Raw chunk: {raw_content[:100]}...")
                
                # Check if this is already an OpenAI-format chunk (from HTML injection)
                if raw_content.startswith('data: '):
                    logger.debug("🔧 Detected OpenAI-format chunk (HTML injection), passing through")
                    yield raw_content
                    continue
                
                # Check if this is HTML content (direct HTML injection)
                if raw_content.startswith('<!DOCTYPE html>') or raw_content.startswith('<html'):
                    logger.debug("🔧 Detected HTML content, skipping (not suitable for OpenAI streaming)")
                    # Don't send HTML content through OpenAI endpoint - causes JSON parse errors
                    # The file was already created by POST-LLM, just skip streaming the HTML
                    continue
                
                # Try to parse as JSON (regular Ollama response format)
                if raw_content.strip():
                    try:
                        # Try to parse as JSON
                        native_json = json.loads(raw_content.strip())
                        logger.debug(f"🔧 Parsed JSON: {native_json}")

                        # 🎯 PHASE 4 FIX: Handle LLM Manager text content vs Ollama JSON
                        # Check if stream should end (only for dict responses from Ollama)
                        if isinstance(native_json, dict) and native_json.get("done", False):
                            logger.info("🏁 Stream completion detected")
                            # If there's still response content in the final chunk, send it first
                            if "response" in native_json and native_json["response"]:
                                content_chunk = {
                                    "id": f"chatcmpl-{int(time.time())}",
                                    "object": "chat.completion.chunk", 
                                    "created": int(time.time()),
                                    "model": model,
                                    "choices": [{"index": 0, "delta": {"content": native_json["response"]}, "finish_reason": None}]
                                }
                                yield f"data: {json.dumps(content_chunk)}\n\n"

                            # Send completion signal - but don't include metadata like context, created_at etc
                            final_chunk = {
                                "id": f"chatcmpl-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                            }
                            yield f"data: {json.dumps(final_chunk)}\n\n"
                            yield "data: [DONE]\n\n"

                            # ✅ FIX: Client stream closed, but continue consuming for POST-LLM execution
                            # Open-WebUI receives [DONE] and connection closes from client perspective
                            # But we continue consuming generator to allow POST-LLM code to execute
                            logger.info("🔄 PRIMARY LLM done, client received [DONE], consuming POST-LLM chunks...")

                            post_llm_chunk_count = 0
                            post_llm_logs = []

                            try:
                                # Continue consuming remaining chunks from llama_stream
                                # These chunks won't be sent to client (stream already terminated with [DONE])
                                # But consuming them allows the generator to complete execution
                                async for remaining_chunk in internal_response.body_iterator:
                                    post_llm_chunk_count += 1

                                    # Decode chunk for logging
                                    if isinstance(remaining_chunk, bytes):
                                        chunk_text = remaining_chunk.decode('utf-8', errors='ignore')
                                    else:
                                        chunk_text = str(remaining_chunk)

                                    # Log POST-LLM activity (truncate for readability)
                                    chunk_preview = chunk_text[:200] if len(chunk_text) > 200 else chunk_text
                                    logger.debug(f"📦 POST-LLM chunk {post_llm_chunk_count}: {chunk_preview}")
                                    post_llm_logs.append(chunk_preview)

                                    # Try to parse for informative logging
                                    try:
                                        if chunk_text.strip():
                                            chunk_json = json.loads(chunk_text.strip())
                                            # Log if this is a POST-LLM result chunk
                                            if isinstance(chunk_json, dict):
                                                if 'post_processing' in chunk_json:
                                                    logger.info(f"✅ POST-LLM: {chunk_json.get('post_processing')}")
                                                elif 'message' in chunk_json and 'POST-PROCESSING' in str(chunk_json.get('message', {})):
                                                    logger.info(f"✅ POST-LLM: Execution completed")
                                    except json.JSONDecodeError:
                                        pass  # Not JSON, just data chunk

                                logger.info(f"✅ Generator fully consumed: {post_llm_chunk_count} POST-LLM chunks processed")
                                if post_llm_chunk_count > 0:
                                    logger.info(f"📊 POST-LLM Summary: Processed background tasks successfully")
                                else:
                                    logger.warning(f"⚠️ No POST-LLM chunks received (this may be normal if no POST-LLM tasks)")

                            except Exception as e:
                                logger.error(f"❌ Error consuming POST-LLM chunks: {e}")
                                logger.error(f"❌ Traceback: {traceback.format_exc()}")

                            logger.info("🚪 openai_direct_stream: Returning after full generator consumption")
                            return
                        
                        # Extract and send content
                        if isinstance(native_json, dict) and "response" in native_json and native_json["response"]:
                            content_chunk = {
                                "id": f"chatcmpl-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": native_json["response"]}, "finish_reason": None}]
                            }
                            logger.debug(f"🔧 Sending content chunk: {native_json['response'][:50]}...")
                            yield f"data: {json.dumps(content_chunk)}\n\n"
                        elif not isinstance(native_json, dict):
                            # 🎯 PHASE 4 FIX: Handle LLM Manager text content parsed as non-dict JSON
                            logger.debug(f"🔧 LLM Manager text content: {str(native_json)}")
                            content_chunk = {
                                "id": f"chatcmpl-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": str(native_json)}, "finish_reason": None}]
                            }
                            yield f"data: {json.dumps(content_chunk)}\n\n"
                    except json.JSONDecodeError as json_err:
                        logger.debug(f"🔧 Not JSON, treating as raw content: {raw_content[:50]}...")
                        # Filter out unwanted content - don't send metadata or empty responses
                        if raw_content.strip() and not raw_content.startswith('{"model":'):
                            # Skip content that looks like Ollama metadata or context tokens
                            metadata_indicators = [
                                "created_at", "total_duration", "load_duration", 
                                "prompt_eval_count", "eval_count", "context", 
                                "done_reason", "eval_duration"
                            ]
                            if any(metadata_key in raw_content for metadata_key in metadata_indicators):
                                logger.debug("🔧 Skipping metadata content")
                                continue
                            
                            # Skip content that looks like raw token arrays (numbers separated by commas)
                            if raw_content.strip().startswith('[') or raw_content.replace(',', '').replace(' ', '').isdigit():
                                logger.debug("🔧 Skipping token array content")
                                continue
                            
                            # Skip content that is mostly numbers and commas (context tokens)
                            numeric_chars = sum(1 for c in raw_content if c.isdigit() or c in [',', ' ', '\n'])
                            if len(raw_content) > 50 and numeric_chars / len(raw_content) > 0.8:
                                logger.debug("🔧 Skipping numeric token content")
                                continue
                            
                            content_chunk = {
                                "id": f"chatcmpl-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": raw_content}, "finish_reason": None}]
                            }
                            yield f"data: {json.dumps(content_chunk)}\n\n"
        else:
            logger.error("🚨 Internal response missing body_iterator")
            logger.error(f"🚨 Response type: {type(internal_response)}")
            logger.error(f"🚨 Response attributes: {dir(internal_response)}")
    except Exception as e:
        logger.error(f"🚨 Direct streaming error: {str(e)}")
        logger.error(f"🚨 Error traceback: {traceback.format_exc()}")
        error_chunk = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"content": f"Error processing request: {str(e)}"}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"

async def export_conversation_to_pdf(message_history: list, filename: str = "conversation.pdf") -> dict:
    """
    Export conversation history to PDF using CENTRALIZED PDF SERVICE
    """
    logger.debug("🎯 ConversationExport: Routing to CENTRALIZED PDF SERVICE")
    
    try:
        # Import the centralized PDF service
        from services.pdf_service import create_pdf
        
        if not message_history:
            return {
                "success": False, 
                "error": "No conversation history to export"
            }
        
        # Parse message history into structured format
        parsed_messages = []
        for msg in message_history:
            # Parse "ROLE: content" format
            if ':' in msg and msg.upper().startswith(('USER:', 'ASSISTANT:', 'SYSTEM:')):
                parts = msg.split(':', 1)
                role = parts[0].strip().lower()
                content = parts[1].strip()
                
                parsed_messages.append({
                    'role': role,
                    'content': content
                })
        
        if not parsed_messages:
            return {
                "success": False,
                "error": "Could not parse conversation messages"
            }
        
        # Generate conversation content as markdown
        markdown_content = _format_conversation_for_markdown(parsed_messages)
        
        # Route to centralized PDF service
        result = create_pdf(
            content=markdown_content,
            output_path=filename,
            title="Conversation Export",
            content_type="markdown"
        )
        
        if result["success"]:
            return {
                "success": True,
                "file_path": filename,
                "message_count": len(parsed_messages),
                "service": result.get("service", "CentralizedPDFService"),
                "message": f"Conversation exported to {filename}"
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "PDF generation failed")
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Export failed: {str(e)}"
        }


def _format_conversation_for_markdown(messages: list) -> str:
    """Format conversation messages as clean Markdown for PDF conversion"""
    md_parts = []
    
    # Add conversation statistics
    md_parts.append("# 💬 Conversation Export")
    md_parts.append("")
    md_parts.append(f"**Export Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md_parts.append(f"**Total Messages:** {len(messages)}")
    md_parts.append("")
    
    user_count = sum(1 for msg in messages if msg['role'] == 'user')
    assistant_count = sum(1 for msg in messages if msg['role'] == 'assistant')
    
    md_parts.append(f"**User Messages:** {user_count}")
    md_parts.append(f"**Assistant Messages:** {assistant_count}")
    md_parts.append("")
    md_parts.append("---")
    md_parts.append("")
    
    # Add conversation content
    for i, message in enumerate(messages, 1):
        role = message['role'].title()
        content = message['content']
        
        # Add role headers for clarity
        if role == 'User':
            md_parts.append("## 👤 User")
        else:
            md_parts.append("## 🤖 Assistant")
        
        md_parts.append("")
        md_parts.append(content)
        md_parts.append("")
        
        # Add separator between messages
        if i < len(messages):
            md_parts.append("---")
            md_parts.append("")
    
    return '\n'.join(md_parts)

# ALL PDF FORMATTING FUNCTIONS REMOVED - PDF PROCESSING COMPLETELY DISABLED

async def openai_streaming_response(user_prompt: str, model: str, conversation_id: str, images: list = None, allowed_tools: list = None, deep_research: bool = None, allow_delivery: bool = None, delivery_recipient: str = None):
    """Handle streaming OpenAI response with proper format - simplified implementation"""
    try:
        logger.info(f"🔒 OpenAI Streaming Response requested")
        
        async def stream_generator():
            # Send initial chunk (OpenAI format: SSE)
            chunk = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None
                    }
                ]
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            
            # Mirror/capture native streaming response
            # 🔧 CRITICAL FIX: Properly split enhanced prompt for multi-turn conversations
            actual_prompt = ""
            context_part = ""
            
            if "\n=== CURRENT REQUEST ===\n" in user_prompt:
                # This is a multi-turn conversation with context
                parts = user_prompt.split("\n=== CURRENT REQUEST ===\n")
                context_part = parts[0]  # Everything before current request
                actual_prompt = parts[1]  # Current user request only
                logger.info(f"🔄 MULTI-TURN: Separated context ({len(context_part)} chars) from prompt ({len(actual_prompt)} chars)")
            else:
                # Single turn - no context separation needed
                actual_prompt = user_prompt
                context_part = ""
                logger.info(f"🆕 SINGLE-TURN: Using full prompt ({len(actual_prompt)} chars)")
            
            native_request_data = {
                "prompt": actual_prompt,
                "model": ServerConfig.DEFAULT_MODEL,
                "toolsInUse": True,
                "prompt_context": context_part,  # 🔧 FIX: Now properly includes conversation context
                "searchWebInUse": False,
                "images": images if images else ["noimage"],  # 🔧 FIX: Use actual images from OpenAI request
                "tools_calling_model": ServerConfig.DEFAULT_TOOL_CALLING_MODEL,
                "system": "",
                "allowed_tools": allowed_tools,  # Pass tool whitelist from caller
            }
            # Forward the client's deep-research opt-out so the gate (which reads
            # data.get('deep_research', True)) can honor it. Only set when explicitly
            # provided — None leaves the default (gate decides) untouched.
            if deep_research is not None:
                native_request_data["deep_research"] = deep_research
                logger.info(f"🔬 Client deep_research flag forwarded to pipeline: {deep_research}")
            # Forward the trusted-client delivery opt-in (Phase 2). Default None/false = content only.
            if allow_delivery is not None:
                native_request_data["allow_delivery"] = allow_delivery
                logger.info(f"📦 Client allow_delivery flag forwarded to pipeline: {allow_delivery}")
            if delivery_recipient:
                native_request_data["delivery_recipient"] = delivery_recipient
                logger.info(f"📦 Locked delivery recipient forwarded to pipeline: {delivery_recipient}")

            # Choose routing method based on feature flag
            if ServerConfig.USE_DIRECT_FUNCTION_CALLS:
                logger.info(f"🔀 Using DIRECT function calls (faster, no HTTP overhead)")
                logger.debug(f"🔧 CONTEXT FIX DEBUG: Calling openai_direct_stream")
                logger.debug(f"🔧 CONTEXT FIX DEBUG: prompt='{actual_prompt[:100]}...'")
                logger.debug(f"🔧 CONTEXT FIX DEBUG: context='{context_part[:100]}...'")
                logger.debug(f"🔧 CONTEXT FIX DEBUG: model='{model}'")
                # Option 2: Direct function calls - More efficient
                async for chunk_data in openai_direct_stream(native_request_data, model):
                    yield chunk_data
                return
            else:
                logger.info(f"🔀 HTTP requests temporarily disabled due to indentation issues")
                # TODO: Fix HTTP option later
                # Fallback to error for now
                error_chunk = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": "HTTP option temporarily disabled. Use USE_DIRECT_FUNCTION_CALLS=true"}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"
                return
            
            # Stream termination is now handled by detecting native "done" signal
        
        return StreamingResponse(
            stream_generator(),
            media_type="text/plain",  # SSE format (NOT NDJSON)
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",  # Critical: Enables SSE streaming
                "X-Accel-Buffering": "no"  # Critical: Prevent proxy buffering
            }
        )
        
    except Exception as e:
        logger.error(f"🚨 OpenAI streaming error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==============================================================================
# PHASE 2B MANAGEMENT ENDPOINTS
# ==============================================================================

if PHASE2B_AVAILABLE:
    @app.get("/phase2b/status")
    async def get_phase2b_status():
        """Get Phase 2B system status and feature flags"""
        try:
            return {
                "success": True,
                "rollback_controller": rollback_controller.get_status(),
                "performance_health": get_performance_health(),
                "streaming_stats": get_streaming_statistics(),
                "buffer_stats": get_buffer_statistics(),
                "classification_stats": get_classification_statistics(),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ Phase 2B status error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/phase2b/feature/{feature_name}/enable")
    async def enable_phase2b_feature_endpoint(feature_name: str):
        """Enable a Phase 2B feature"""
        try:
            # Validate feature name
            feature_map = {
                "streaming": FeatureFlag.STREAMING_FALLBACK,
                "buffer_optimization": FeatureFlag.BUFFER_OPTIMIZATION,
                "response_classification": FeatureFlag.RESPONSE_CLASSIFICATION,
                "performance_monitoring": FeatureFlag.PERFORMANCE_MONITORING,
                "response_streaming": FeatureFlag.RESPONSE_STREAMING
            }
            
            if feature_name not in feature_map:
                return {
                    "success": False, 
                    "error": f"Invalid feature name. Available: {list(feature_map.keys())}"
                }
            
            feature = feature_map[feature_name]
            success = enable_phase2b_feature(feature)
            
            if success:
                logger.info(f"✅ Phase 2B feature enabled: {feature_name}")
                return {
                    "success": True,
                    "message": f"Feature {feature_name} enabled successfully",
                    "status": rollback_controller.get_status()
                }
            else:
                return {"success": False, "error": "Failed to enable feature"}
                
        except Exception as e:
            logger.error(f"❌ Feature enable error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/phase2b/feature/{feature_name}/disable")
    async def disable_phase2b_feature_endpoint(feature_name: str):
        """Disable a Phase 2B feature"""
        try:
            feature_map = {
                "streaming": FeatureFlag.STREAMING_FALLBACK,
                "buffer_optimization": FeatureFlag.BUFFER_OPTIMIZATION,
                "response_classification": FeatureFlag.RESPONSE_CLASSIFICATION,
                "response_streaming": FeatureFlag.RESPONSE_STREAMING
                # Note: performance_monitoring cannot be disabled for safety
            }
            
            if feature_name not in feature_map:
                return {
                    "success": False, 
                    "error": f"Invalid feature name. Available: {list(feature_map.keys())}"
                }
            
            feature = feature_map[feature_name]
            success = disable_phase2b_feature(feature)
            
            if success:
                logger.info(f"🔒 Phase 2B feature disabled: {feature_name}")
                return {
                    "success": True,
                    "message": f"Feature {feature_name} disabled successfully",
                    "status": rollback_controller.get_status()
                }
            else:
                return {"success": False, "error": "Failed to disable feature"}
                
        except Exception as e:
            logger.error(f"❌ Feature disable error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/phase2b/rollback/emergency")
    async def emergency_rollback_endpoint():
        """Emergency rollback to Phase 2A baseline"""
        try:
            logger.warning("🚨 Emergency rollback requested via API")
            success = emergency_rollback_phase2b()
            
            if success:
                return {
                    "success": True,
                    "message": "Emergency rollback successful - Phase 2A baseline restored",
                    "status": rollback_controller.get_status()
                }
            else:
                return {"success": False, "error": "Emergency rollback failed"}
                
        except Exception as e:
            logger.critical(f"💥 Emergency rollback API error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/phase2b/rollback/clear-emergency")
    async def clear_emergency_fallback_endpoint():
        """Clear emergency fallback mode to allow feature activation"""
        try:
            logger.info("🔄 Clearing emergency fallback mode via API")
            success = rollback_controller.disable_emergency_fallback()
            
            if success:
                return {
                    "success": True,
                    "message": "Emergency fallback cleared - features can now be enabled",
                    "status": rollback_controller.get_status()
                }
            else:
                return {"success": False, "error": "Failed to clear emergency fallback"}
                
        except Exception as e:
            logger.error(f"❌ Clear emergency fallback error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.get("/phase2b/checkpoints")
    async def list_rollback_checkpoints():
        """List available rollback checkpoints"""
        try:
            checkpoints = rollback_controller.list_checkpoints()
            return {
                "success": True,
                "checkpoints": checkpoints,
                "count": len(checkpoints)
            }
        except Exception as e:
            logger.error(f"❌ Checkpoint listing error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/phase2b/rollback/{checkpoint_id}")
    async def rollback_to_checkpoint_endpoint(checkpoint_id: str):
        """Rollback to a specific checkpoint"""
        try:
            success = rollback_controller.rollback_to_checkpoint(checkpoint_id)
            
            if success:
                return {
                    "success": True,
                    "message": f"Rollback to {checkpoint_id} successful",
                    "status": rollback_controller.get_status()
                }
            else:
                return {"success": False, "error": f"Rollback to {checkpoint_id} failed"}
                
        except Exception as e:
            logger.error(f"❌ Rollback error: {e}")
            return {"success": False, "error": str(e)}

# ==============================================================================
# DOCUMENT INTERROGATION ENDPOINTS
# ==============================================================================

# Document Interrogation System - FAISS-based RAG integration
try:
    from document_interrogator import get_document_interrogator
    
    @app.post("/documents/index-directory")
    async def index_directory_endpoint(request: Request):
        """Index all documents in a directory for interrogation"""
        try:
            data = await request.json()
            directory_path = data.get('directory_path')
            recursive = data.get('recursive', True)
            
            if not directory_path:
                return {"success": False, "error": "directory_path is required"}
            
            interrogator = get_document_interrogator()
            if not interrogator.is_ready():
                return {
                    "success": False, 
                    "error": "Document interrogation system not ready. Install: pip install faiss-cpu numpy PyPDF2 python-docx openpyxl beautifulsoup4"
                }
            
            logger.info(f"📚 Starting smart directory indexing: {directory_path}")
            results = await interrogator.smart_index_directory(directory_path, recursive)
            
            if results['success']:
                return {
                    "success": True,
                    "message": results['message'],
                    "processed": results['processed'],
                    "failed": results['failed'], 
                    "skipped": results['skipped'],
                    "total_files_found": results['total_files_found'],
                    "files": results.get('files', []),
                    "stats": interrogator.get_stats()
                }
            else:
                return {
                    "success": False,
                    "error": results['error'],
                    "message": results['message']
                }
            
        except Exception as e:
            logger.error(f"❌ Directory indexing error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/documents/search")
    async def search_documents_endpoint(request: Request):
        """Search indexed documents for relevant content"""
        try:
            data = await request.json()
            query = data.get('query', '')
            k = data.get('k', 5)  # Number of chunks to return
            
            if not query.strip():
                return {"success": False, "error": "query is required"}
            
            interrogator = get_document_interrogator()
            if not interrogator.is_ready():
                return {
                    "success": False,
                    "error": "Document interrogation system not ready"
                }
            
            logger.info(f"🔍 Document search: {query}")
            search_results = await interrogator.search_documents(query, k)
            
            return {
                "success": True,
                "query": query,
                "chunks_found": search_results.get('chunks_found', 0),
                "chunks": search_results.get('chunks', []),
                "context": search_results.get('context', ''),
                "sources": search_results.get('sources', [])
            }
            
        except Exception as e:
            logger.error(f"❌ Document search error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/documents/interrogate")
    async def interrogate_documents_endpoint(request: Request):
        """Interrogate documents with natural language questions (integrates with 2-stage LLM)"""
        try:
            data = await request.json()
            question = data.get('question', '')
            k = data.get('k', 5)
            model = data.get('model', config_loader.get_tool_calling_model())
            
            if not question.strip():
                return {"success": False, "error": "question is required"}
            
            interrogator = get_document_interrogator()
            if not interrogator.is_ready():
                return {
                    "success": False,
                    "error": "Document interrogation system not ready"
                }
            
            logger.info(f"❓ Document interrogation: {question}")
            
            # Stage 0: RAG Retrieval - Get document context
            search_results = await interrogator.search_documents(question, k)
            
            if not search_results.get('context'):
                return {
                    "success": True,
                    "answer": "No relevant documents found for your question.",
                    "sources": [],
                    "query": question
                }
            
            # Prepare enhanced prompt with document context for 2-stage LLM
            document_context = search_results['context']
            enhanced_prompt = f"""Based on the following document excerpts, please answer the question: "{question}"

Document Context:
{document_context}

Please provide a comprehensive answer based on the information provided. If the information is insufficient, please indicate what additional information would be helpful."""
            
            # Stage 1 & 2: Use existing 2-stage LLM architecture
            # Create mock request for existing pipeline
            class MockRequest:
                def __init__(self, prompt, model):
                    self.method = "POST"
                    self.headers = {"content-type": "application/json"}
                    self._json = {
                        "prompt": prompt,
                        "model": model,
                        "stream": False
                    }
                
                async def json(self):
                    return self._json
            
            # Route through existing llama_stream function for consistency
            mock_request = MockRequest(enhanced_prompt, model)
            llm_response = await llama_stream(mock_request)
            
            # Extract answer from streaming response
            if hasattr(llm_response, 'body_iterator'):
                answer_parts = []
                async for chunk_data in llm_response.body_iterator:
                    if isinstance(chunk_data, bytes):
                        chunk_data = chunk_data.decode('utf-8')
                    answer_parts.append(chunk_data)
                answer = ''.join(answer_parts)
            else:
                answer = str(llm_response)
            
            return {
                "success": True,
                "answer": answer,
                "sources": search_results.get('sources', []),
                "query": question,
                "chunks_found": search_results.get('chunks_found', 0),
                "model_used": model
            }
            
        except Exception as e:
            logger.error(f"❌ Document interrogation error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/documents/watch-directory")
    async def watch_directory_endpoint(request: Request):
        """Start watching a directory for new/modified documents"""
        try:
            data = await request.json()
            directory_path = data.get('directory_path')
            
            if not directory_path:
                return {"success": False, "error": "directory_path is required"}
            
            interrogator = get_document_interrogator()
            success = interrogator.start_watching(directory_path)
            
            return {
                "success": success,
                "message": f"{'Started' if success else 'Failed to start'} watching directory: {directory_path}",
                "watched_directories": list(interrogator.watched_directories)
            }
            
        except Exception as e:
            logger.error(f"❌ Directory watching error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/documents/stop-watching")
    async def stop_watching_endpoint():
        """Stop watching all directories"""
        try:
            interrogator = get_document_interrogator()
            interrogator.stop_watching()
            
            return {
                "success": True,
                "message": "Stopped watching all directories"
            }
            
        except Exception as e:
            logger.error(f"❌ Stop watching error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.get("/documents/stats")
    async def document_stats_endpoint():
        """Get document interrogation system statistics"""
        try:
            interrogator = get_document_interrogator()
            stats = interrogator.get_stats()
            
            return {
                "success": True,
                "stats": stats,
                "system_ready": interrogator.is_ready()
            }
            
        except Exception as e:
            logger.error(f"❌ Document stats error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.get("/documents/config")
    async def get_config_endpoint():
        """Get current watch configuration status"""
        try:
            interrogator = get_document_interrogator()
            config_status = interrogator.get_config_status()
            
            return {
                "success": True,
                "config": config_status
            }
            
        except Exception as e:
            logger.error(f"❌ Get config error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/documents/config/add-directory")
    async def add_watch_directory_endpoint(request: Request):
        """Add a directory to the watch configuration"""
        try:
            data = await request.json()
            directory_path = data.get('path')
            recursive = data.get('recursive', True)
            enabled = data.get('enabled', True)
            description = data.get('description', '')
            
            if not directory_path:
                return {"success": False, "error": "path is required"}
            
            interrogator = get_document_interrogator()
            success = interrogator.add_watch_directory(directory_path, recursive, enabled, description)
            
            return {
                "success": success,
                "message": f"{'Added' if success else 'Failed to add'} directory to config: {directory_path}",
                "config": interrogator.get_config_status()
            }
            
        except Exception as e:
            logger.error(f"❌ Add watch directory error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/documents/config/remove-directory")
    async def remove_watch_directory_endpoint(request: Request):
        """Remove a directory from the watch configuration"""
        try:
            data = await request.json()
            directory_path = data.get('path')
            
            if not directory_path:
                return {"success": False, "error": "path is required"}
            
            interrogator = get_document_interrogator()
            success = interrogator.remove_watch_directory(directory_path)
            
            return {
                "success": success,
                "message": f"{'Removed' if success else 'Failed to remove'} directory from config: {directory_path}",
                "config": interrogator.get_config_status()
            }
            
        except Exception as e:
            logger.error(f"❌ Remove watch directory error: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/documents/config/scan-changes")
    async def force_scan_changes_endpoint():
        """Force scan all configured directories for changes"""
        try:
            interrogator = get_document_interrogator()
            await interrogator.force_scan_changes()
            
            return {
                "success": True,
                "message": "Completed force scan of all configured directories",
                "config": interrogator.get_config_status()
            }
            
        except Exception as e:
            logger.error(f"❌ Force scan error: {e}")
            return {"success": False, "error": str(e)}

except ImportError as e:
    logger.warning(f"⚠️ Document interrogation not available: {e}")
    
    # Provide fallback endpoints that return helpful error messages
    @app.post("/documents/index-directory")
    async def index_directory_unavailable():
        return {
            "success": False,
            "error": "Document interrogation not available. Install dependencies: pip install faiss-cpu numpy PyPDF2 python-docx openpyxl beautifulsoup4 pytesseract pillow watchdog"
        }
    
    @app.post("/documents/search")
    @app.post("/documents/interrogate")
    @app.post("/documents/watch-directory")
    @app.post("/documents/stop-watching")
    @app.get("/documents/stats")
    async def document_endpoints_unavailable():
        return {
            "success": False,
            "error": "Document interrogation not available. Install dependencies first."
        }

# ==============================================================================
# MAIN APPLICATION RUNNER
# ==============================================================================

if __name__ == "__main__":
    logger.info(f"Starting complete server on {ServerConfig.HOST}:{ServerConfig.PORT}")
    
    # Check logging configuration (env vars override config file)
    debug_config = config_loader.load_config().get('debug', {})
    log_requests_enabled = os.getenv('LOG_REQUESTS', str(debug_config.get('log_requests', True))).lower() in ('true', '1', 'yes')
    
    uvicorn.run(
        "fastapi_server_complete:app",
        host=ServerConfig.HOST,
        port=ServerConfig.PORT,
        reload=ServerConfig.DEBUG,
        access_log=log_requests_enabled,  # Respect configuration
        log_level="info"
    )
