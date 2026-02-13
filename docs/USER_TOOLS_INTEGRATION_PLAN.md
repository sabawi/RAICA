# User Tools Integration Plan

**Date:** 2026-02-06
**Purpose:** Integrate RAICA server's user_tools into context-first architecture

## 📊 Current State

**User Tools Directory:** `/home/sabawi/Development/RAICA/user_tools`

**Available Tools (~20):**
- Communication: secure_email_sender, email_retriever
- Documents: pdf_generator_tool, document_search
- OCR: image_to_text
- Finance: comprehensive_stock_analyzer, sec_edgar_tool
- Productivity: google_calendar_scheduler
- Travel: flight_search
- Research: published_papers_search_tool, research_paper_search
- Data: analytical_visualizer
- Development: sandboxed_executor, process_executor
- Utility: example_calculator

**Discovery System:**
- `tool_discovery.py` - Automatic discovery via `discover_user_tools()`
- `base_user_tool.py` - Standard interface (name, description, parameters, execute)
- All tools return: `{"success": bool, "result": Any, "error": str|None}`

## 🎯 Integration Strategy

### Problem: Token Budget Constraint

**Token Cost Analysis:**
- Full tool definition: ~100-150 tokens each (name + description + full JSON schema)
- 20 tools × 125 tokens = **~2500 tokens** (exceeds our entire budget!)

**Current Budget:**
- System Profile: ~200 tokens
- User Profile: ~50 tokens
- Project Profile: ~1500 tokens
- User Tools (if full): ~2500 tokens ❌ OVER BUDGET!
- **Total: ~4250 tokens** ❌ TOO HEAVY

### Solution: Two-Layer Discovery

#### Layer 1: Tool Catalog (First Contact)
**Include:** Tool name + one-line description only
**Exclude:** Full parameter schemas
**Token Cost:** ~30 tokens per tool × 20 = **~600 tokens** ✅

```
Available User Tools:
  • secure_email_sender: Send emails securely via SMTP
  • pdf_generator_tool: Generate PDF documents
  • image_to_text: Extract text from images (OCR)
  • comprehensive_stock_analyzer: Analyze stock market data
  • google_calendar_scheduler: Manage Google Calendar events
  • flight_search: Search for flight information
  ... (15 more)

To use a tool, request its details first with INVESTIGATE decision.
```

#### Layer 2: On-Demand Details (Investigation)
**When:** LLM decides to use a tool
**How:** LLM uses INVESTIGATE decision to request tool details
**Returns:** Full tool schema (name, description, parameters)

**Example Flow:**
```
1. User: "Send an email to john@example.com"

2. LLM First Contact:
   - Sees: "secure_email_sender: Send emails securely via SMTP"
   - Decides: Need details to use this tool

3. LLM INVESTIGATE:
   {
     "decision_type": "INVESTIGATE",
     "action": {"commands": ["get_tool_details secure_email_sender"]}
   }

4. RAICA Returns:
   {
     "name": "secure_email_sender",
     "description": "Send emails securely with SMTP...",
     "parameters": {
       "type": "object",
       "properties": {
         "to": {"type": "string", "description": "Recipient email"},
         "subject": {"type": "string", "description": "Email subject"},
         "body": {"type": "string", "description": "Email body"},
         ...
       },
       "required": ["to", "subject", "body"]
     }
   }

5. LLM Now Has Full Details:
   - Can construct proper tool call with all parameters
```

## 🏗️ Implementation

### Step 1: Add UserToolsProfile to context_builder.py

```python
@dataclass
class UserToolsProfile:
    """User-defined tools available on RAICA server."""
    tools: Dict[str, str] = field(default_factory=dict)  # name → description
    estimated_tokens: int = 0

    def to_compact_dict(self) -> Dict[str, Any]:
        """Compact representation (catalog only, no schemas)."""
        return {
            'available': len(self.tools),
            'catalog': self.tools  # Just name → description
        }

    def estimate_tokens(self) -> int:
        """Estimate token usage for tool catalog."""
        # Each tool: ~30 tokens (name + short description)
        self.estimated_tokens = len(self.tools) * 30
        return self.estimated_tokens
```

### Step 2: Discover Tools in ContextBuilder

```python
def _build_user_tools_profile(self) -> UserToolsProfile:
    """
    Build user tools profile - catalog only, not full schemas.

    Strategy: Give LLM AWARENESS of available tools, not full details.
    LLM can request details via INVESTIGATE if it wants to use a tool.
    """
    if self._user_tools_cache:
        return self._user_tools_cache

    profile = UserToolsProfile()

    try:
        # Discover all user tools
        import sys
        sys.path.insert(0, '/home/sabawi/Development/RAICA')
        from user_tools.tool_discovery import discover_user_tools

        import asyncio
        tools = asyncio.run(discover_user_tools())

        # Extract name + description only (NOT full schemas)
        for tool in tools:
            # Get short description (first line/sentence)
            desc = tool.description
            if '\n' in desc:
                desc = desc.split('\n')[0]
            if len(desc) > 100:
                desc = desc[:97] + "..."

            profile.tools[tool.name] = desc

        logger.info(f"Discovered {len(profile.tools)} user tools")

    except Exception as e:
        logger.warning(f"Failed to discover user tools: {e}")

    profile.estimate_tokens()
    self._user_tools_cache = profile

    return profile
```

### Step 3: Update Context Structure

```python
@dataclass
class Context:
    """Complete context for first LLM contact."""
    system: Optional[SystemProfile] = None
    user: Optional[UserProfile] = None
    user_tools: Optional[UserToolsProfile] = None  # NEW!
    project: Optional[ProjectProfile] = None
    request: str = ""
```

### Step 4: Update First Contact Template

```python
def build_first_contact_prompt(context: 'Context') -> str:
    """Build first contact prompt with user tools catalog."""

    # ... (existing sections)

    # User Tools Section (NEW!)
    if context.user_tools and context.user_tools.tools:
        sections.append(f"""## RAICA USER TOOLS

Available user-defined tools ({len(context.user_tools.tools)} total):

{_format_user_tools_catalog(context.user_tools.tools)}

**To use a tool:** First use INVESTIGATE decision to request full details:
  Example: {{"decision_type": "INVESTIGATE", "action": {{"commands": ["get_tool_details tool_name"]}}}}
""")
```

### Step 5: Add Tool Details Retrieval

Create new module: `agents/coding_agent/services/tool_details_provider.py`

```python
async def get_tool_details(tool_name: str) -> Dict[str, Any]:
    """
    Get full details for a specific user tool.

    Returns:
        Full tool definition with parameters schema
    """
    from user_tools.tool_discovery import discover_user_tools, get_user_tool_by_name

    tools = await discover_user_tools()
    tool = get_user_tool_by_name(tools, tool_name)

    if not tool:
        return {
            "error": f"Tool not found: {tool_name}",
            "available_tools": [t.name for t in tools]
        }

    return tool.get_function_definition()
```

### Step 6: Handle INVESTIGATE for Tool Details

Update `universal_handler.py` ACT phase:

```python
async def _act(self, decision: Decision) -> dict:
    """Execute the decision."""

    if decision.decision_type == DecisionType.INVESTIGATE:
        commands = decision.action.get('commands', [])

        for cmd in commands:
            # Check if requesting tool details
            if cmd.startswith('get_tool_details '):
                tool_name = cmd.split(' ', 1)[1]
                from .services.tool_details_provider import get_tool_details
                details = await get_tool_details(tool_name)
                return {'success': True, 'output': json.dumps(details, indent=2)}

        # ... (existing INVESTIGATE handling)
```

## 📊 Token Budget After Integration

**Updated Budget:**
- System Profile: ~200 tokens
- User Profile: ~50 tokens
- **User Tools Catalog: ~600 tokens** (NEW!)
- Project Profile: ~1500 tokens
- **Total First Contact: ~2350 tokens** ✅ Within budget!

**On-Demand Tool Details:**
- Requested via INVESTIGATE: ~150 tokens per tool
- Only when LLM wants to use a tool
- Doesn't bloat first contact

## 🧪 Testing Plan

### Test 1: Tool Discovery
```python
from context_builder import ContextBuilder

builder = ContextBuilder()
context = await builder.build_context("Send an email")

print(f"User tools found: {len(context.user_tools.tools)}")
print(f"Token cost: {context.user_tools.estimated_tokens}")
```

### Test 2: First Contact with Tools
```python
from first_contact_template import build_first_contact_prompt

prompt = build_first_contact_prompt(context)
print(f"Prompt length: {len(prompt)} chars (~{len(prompt)//4} tokens)")
```

### Test 3: Tool Details Retrieval
```python
from tool_details_provider import get_tool_details

details = await get_tool_details('secure_email_sender')
print(json.dumps(details, indent=2))
```

### Test 4: End-to-End with LLM
- Request: "Send an email to test@example.com"
- Expected flow:
  1. First contact: LLM sees secure_email_sender in catalog
  2. LLM INVESTIGATE: Requests tool details
  3. LLM receives full schema
  4. LLM EXECUTE: Calls tool with proper parameters

## 🔑 Key Benefits

1. **Token Efficient**: Catalog is ~600 tokens vs ~2500 for full schemas
2. **LLM Aware**: Knows what tools exist from the start
3. **On-Demand Details**: Gets full info only when needed
4. **Extensible**: New tools auto-discovered, no code changes
5. **Clean Separation**: RAICA discovers, LLM decides which to use

## ⚠️ Potential Issues

1. **Extra Round Trip**: LLM needs INVESTIGATE before using tool
   - **Mitigation**: Cache tool details after first request per session

2. **Tool Path Hardcoded**: `/home/sabawi/Development/RAICA/user_tools`
   - **Mitigation**: Make configurable in llm_config.yaml

3. **Discovery Failure**: If tool_discovery.py fails
   - **Mitigation**: Graceful fallback, log warning, continue without tools

4. **Stale Cache**: New tools added while RAICA running
   - **Mitigation**: Add cache invalidation on demand or periodic refresh

## 📋 Implementation Checklist

- [ ] Add UserToolsProfile to context_builder.py
- [ ] Implement _build_user_tools_profile() with discovery
- [ ] Update Context dataclass to include user_tools
- [ ] Update first_contact_template.py with user tools catalog section
- [ ] Create tool_details_provider.py for on-demand details
- [ ] Update universal_handler.py ACT phase to handle get_tool_details
- [ ] Test tool discovery and token usage
- [ ] Test end-to-end with LLM
- [ ] Make user_tools path configurable
- [ ] Add error handling and graceful fallbacks

## 🎯 Success Criteria

- [x] User tools discovered automatically
- [ ] Tool catalog included in first contact (< 700 tokens)
- [ ] LLM can request tool details via INVESTIGATE
- [ ] Tool details returned in <1 second
- [ ] End-to-end: LLM successfully uses a user tool
- [ ] Token budget stays under 2500 for first contact

---

**Next Step:** Implement UserToolsProfile integration in context_builder.py
