"""
Debug Context - Persistent context tracker for tool-calling debug architecture.

This module maintains the state/context across the debug session:
- Tracks all tool calls with parameters and results
- Maintains a running summary for LLM guidance
- Persists state for recovery and logging
- Provides formatted context for each LLM prompt
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ToolCallStatus(Enum):
    """Status of a tool call."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ToolCallRecord:
    """Record of a single tool call."""
    id: int
    tool_name: str
    args: Dict[str, Any]
    timestamp: str
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tool": self.tool_name,
            "args": self.args,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "result": str(self.result)[:500] if self.result else None,
            "error": self.error,
            "duration_ms": self.duration_ms
        }
    
    def to_summary(self) -> str:
        """Short summary for LLM context."""
        status = "✓" if self.status == ToolCallStatus.SUCCESS else "✗"
        args_str = ", ".join(f"{k}={repr(v)[:30]}" for k, v in list(self.args.items())[:3])
        return f"{status} {self.tool_name}({args_str})"


@dataclass
class PhaseRecord:
    """Record of a debug phase."""
    phase_name: str
    start_time: str
    end_time: Optional[str] = None
    tool_calls: List[int] = field(default_factory=list)  # IDs of tool calls in this phase
    findings: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


class DebugContext:
    """
    Persistent context tracker for debug sessions.
    
    Maintains:
    - Complete history of tool calls
    - Current phase and progress
    - Key findings from analysis
    - Files examined and modified
    - Running context summary for LLM
    
    Usage:
        context = DebugContext(project_dir, issue="Fix requirements.txt")
        
        # Track tool calls
        call_id = context.start_tool_call("read_file", {"path": "config.py"})
        context.complete_tool_call(call_id, result="file content...")
        
        # Get context for LLM
        llm_context = context.get_llm_context()
    """
    
    def __init__(
        self,
        project_dir: Path,
        issue: str,
        error_trace: str = "",
        session_id: str = None
    ):
        self.project_dir = Path(project_dir)
        self.issue = issue
        self.error_trace = error_trace
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = datetime.now().isoformat()

        # Tool call tracking
        self._tool_calls: List[ToolCallRecord] = []
        self._next_call_id = 1

        # Phase tracking
        self._phases: List[PhaseRecord] = []
        self._current_phase: Optional[PhaseRecord] = None

        # Key findings
        self.files_examined: List[str] = []
        self.files_modified: List[str] = []
        self.key_findings: Dict[str, Any] = {}
        self.hypothesis: Optional[str] = None
        self.fix_summary: Optional[str] = None

        # Project design context (LLD, HLD, objectives)
        self.project_lld: Optional[str] = None
        self.project_hld: Optional[str] = None
        self.original_request: Optional[str] = None
        self.project_objectives: Optional[str] = None
        self._load_project_design_context()

        # Track if surgical fixes have failed (enables full rewrite)
        self.surgical_fix_failures: int = 0
        self.allow_full_rewrite: bool = False

        # Persistence
        self._context_dir = self.project_dir / '.raica' / 'sessions' / self.session_id
        self._context_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._context_dir / 'tool_calls.jsonl'

        logger.info(f"DebugContext initialized: session={self.session_id}")

    def _load_project_design_context(self):
        """
        Load project design documents (LLD, HLD, objectives) from .raica directory.

        Looks for:
        - .raica/project_lld.md or LLD.md
        - .raica/project_hld.md or HLD.md
        - .raica/original_request.txt
        - .raica/objectives.md
        """
        raica_dir = self.project_dir / '.raica'

        # Load LLD
        for lld_name in ['project_lld.md', 'LLD.md', 'lld.md', 'design_lld.md']:
            lld_path = raica_dir / lld_name
            if lld_path.exists():
                try:
                    self.project_lld = lld_path.read_text(encoding='utf-8')
                    logger.info(f"Loaded project LLD from {lld_name}")
                    break
                except Exception as e:
                    logger.warning(f"Could not read LLD: {e}")

        # Load HLD
        for hld_name in ['project_hld.md', 'HLD.md', 'hld.md', 'design_hld.md']:
            hld_path = raica_dir / hld_name
            if hld_path.exists():
                try:
                    self.project_hld = hld_path.read_text(encoding='utf-8')
                    logger.info(f"Loaded project HLD from {hld_name}")
                    break
                except Exception as e:
                    logger.warning(f"Could not read HLD: {e}")

        # Load original request
        for req_name in ['original_request.txt', 'user_request.txt', 'request.txt']:
            req_path = raica_dir / req_name
            if req_path.exists():
                try:
                    self.original_request = req_path.read_text(encoding='utf-8')
                    logger.info(f"Loaded original request from {req_name}")
                    break
                except Exception as e:
                    logger.warning(f"Could not read original request: {e}")

        # Load objectives
        for obj_name in ['objectives.md', 'project_objectives.md', 'goals.md']:
            obj_path = raica_dir / obj_name
            if obj_path.exists():
                try:
                    self.project_objectives = obj_path.read_text(encoding='utf-8')
                    logger.info(f"Loaded project objectives from {obj_name}")
                    break
                except Exception as e:
                    logger.warning(f"Could not read objectives: {e}")

    def get_design_context_for_llm(self) -> str:
        """
        Get formatted project design context for inclusion in LLM prompts.

        Returns:
            Formatted string with project objectives, LLD, and constraints
        """
        parts = []

        parts.append("=" * 60)
        parts.append("PROJECT DESIGN DIRECTIVES - YOU MUST ADHERE TO THESE")
        parts.append("=" * 60)

        if self.original_request:
            parts.append("\n### ORIGINAL USER REQUEST ###")
            # Truncate if very long
            if len(self.original_request) > 2000:
                parts.append(self.original_request[:2000] + "\n... (truncated)")
            else:
                parts.append(self.original_request)

        if self.project_objectives:
            parts.append("\n### PROJECT OBJECTIVES ###")
            if len(self.project_objectives) > 1500:
                parts.append(self.project_objectives[:1500] + "\n... (truncated)")
            else:
                parts.append(self.project_objectives)

        if self.project_lld:
            parts.append("\n### LOW-LEVEL DESIGN (LLD) ###")
            # LLD can be long, truncate to key sections
            if len(self.project_lld) > 3000:
                parts.append(self.project_lld[:3000] + "\n... (truncated)")
            else:
                parts.append(self.project_lld)

        if self.project_hld:
            parts.append("\n### HIGH-LEVEL DESIGN (HLD) ###")
            if len(self.project_hld) > 2000:
                parts.append(self.project_hld[:2000] + "\n... (truncated)")
            else:
                parts.append(self.project_hld)

        parts.append("\n" + "=" * 60)
        parts.append("CRITICAL: Your fixes MUST align with the above design.")
        parts.append("Do NOT introduce changes that violate the project architecture.")
        parts.append("=" * 60)

        if parts[1:]:  # Has content beyond header
            return '\n'.join(parts)
        return ""  # No design context available

    def record_surgical_fix_failure(self):
        """Record that a surgical fix attempt failed."""
        self.surgical_fix_failures += 1
        if self.surgical_fix_failures >= 3:
            self.allow_full_rewrite = True
            logger.info("Enabling full rewrite mode after 3 surgical fix failures")
    
    # =========================================================================
    # PHASE MANAGEMENT
    # =========================================================================
    
    def start_phase(self, phase_name: str):
        """Start a new debug phase (e.g., 'diagnosis', 'fix', 'verification')."""
        if self._current_phase:
            self._current_phase.end_time = datetime.now().isoformat()
        
        self._current_phase = PhaseRecord(
            phase_name=phase_name,
            start_time=datetime.now().isoformat()
        )
        self._phases.append(self._current_phase)
        logger.info(f"Phase started: {phase_name}")
    
    def add_phase_note(self, note: str):
        """Add a note to the current phase."""
        if self._current_phase:
            self._current_phase.notes.append(note)
    
    def add_finding(self, key: str, value: Any):
        """Record a key finding."""
        self.key_findings[key] = value
        if self._current_phase:
            self._current_phase.findings[key] = value
    
    # =========================================================================
    # TOOL CALL TRACKING
    # =========================================================================
    
    def start_tool_call(self, tool_name: str, args: Dict[str, Any]) -> int:
        """
        Record the start of a tool call.
        
        Returns:
            Call ID for use with complete_tool_call
        """
        call_id = self._next_call_id
        self._next_call_id += 1
        
        record = ToolCallRecord(
            id=call_id,
            tool_name=tool_name,
            args=args,
            timestamp=datetime.now().isoformat()
        )
        self._tool_calls.append(record)
        
        if self._current_phase:
            self._current_phase.tool_calls.append(call_id)
        
        # Log to file
        self._log_tool_call(record)
        
        logger.info(f"Tool call #{call_id} started: {tool_name}({args})")
        return call_id
    
    def complete_tool_call(
        self,
        call_id: int,
        result: Any = None,
        error: Optional[str] = None,
        duration_ms: int = None
    ):
        """Record the completion of a tool call."""
        record = self._get_call(call_id)
        if not record:
            logger.warning(f"Unknown call_id: {call_id}")
            return
        
        record.status = ToolCallStatus.SUCCESS if error is None else ToolCallStatus.FAILED
        record.result = result
        record.error = error
        record.duration_ms = duration_ms
        
        # Track file modifications
        if record.status == ToolCallStatus.SUCCESS:
            if record.tool_name in ('write_file', 'edit_file', 'replace_line', 'insert_line', 'delete_file', 'move_file'):
                path = record.args.get('path') or record.args.get('source')
                if path and path not in self.files_modified:
                    self.files_modified.append(path)
            
            if record.tool_name == 'read_file':
                path = record.args.get('path')
                if path and path not in self.files_examined:
                    self.files_examined.append(path)
        
        # Update log
        self._log_tool_call(record)
        
        status = "SUCCESS" if record.status == ToolCallStatus.SUCCESS else "FAILED"
        logger.info(f"Tool call #{call_id} {status}")
    
    def _get_call(self, call_id: int) -> Optional[ToolCallRecord]:
        """Get a tool call record by ID."""
        for record in self._tool_calls:
            if record.id == call_id:
                return record
        return None
    
    def _log_tool_call(self, record: ToolCallRecord):
        """Append tool call to JSONL log file."""
        try:
            with open(self._log_file, 'a') as f:
                f.write(json.dumps(record.to_dict()) + '\n')
        except Exception as e:
            logger.warning(f"Failed to log tool call: {e}")
    
    # =========================================================================
    # CONTEXT FOR LLM
    # =========================================================================
    
    def get_llm_context(self, max_history: int = 20) -> str:
        """
        Get formatted context for LLM prompt.
        
        Includes:
        - Original issue and error
        - Current hypothesis
        - Recent tool call history with results
        - Key findings
        - Files modified
        """
        lines = []
        
        # Issue
        lines.append("═══ DEBUG SESSION CONTEXT ═══")
        lines.append(f"Issue: {self.issue}")
        if self.error_trace:
            lines.append(f"Error Trace: {self.error_trace[:500]}")
        lines.append("")
        
        # Hypothesis
        if self.hypothesis:
            lines.append(f"Hypothesis: {self.hypothesis}")
            lines.append("")
        
        # Key findings
        if self.key_findings:
            lines.append("Key Findings:")
            for key, value in list(self.key_findings.items())[:10]:
                val_str = str(value)[:200]
                lines.append(f"  • {key}: {val_str}")
            lines.append("")
        
        # Recent tool calls
        recent_calls = self._tool_calls[-max_history:]
        if recent_calls:
            lines.append(f"Recent Tool Calls ({len(recent_calls)} of {len(self._tool_calls)} total):")
            for record in recent_calls:
                lines.append(f"  {record.to_summary()}")
            lines.append("")
        
        # Files
        if self.files_examined:
            lines.append(f"Files Examined: {', '.join(self.files_examined[:10])}")
        if self.files_modified:
            lines.append(f"Files Modified: {', '.join(self.files_modified)}")
        
        lines.append("═══════════════════════════════")
        
        return "\n".join(lines)
    
    def get_tool_history_for_llm(self, last_n: int = 5) -> str:
        """Get recent tool call history formatted for LLM."""
        recent = self._tool_calls[-last_n:]
        if not recent:
            return "No tool calls yet."
        
        lines = ["Recent Tool Execution:"]
        for record in recent:
            status = "✓" if record.status == ToolCallStatus.SUCCESS else "✗"
            lines.append(f"\n{status} {record.tool_name}:")
            lines.append(f"   Args: {record.args}")
            if record.status == ToolCallStatus.SUCCESS and record.result:
                result_str = str(record.result)[:500]
                lines.append(f"   Result: {result_str}")
            elif record.error:
                lines.append(f"   Error: {record.error}")
        
        return "\n".join(lines)
    
    # =========================================================================
    # PERSISTENCE
    # =========================================================================
    
    def save_state(self):
        """Save context state to disk for recovery."""
        state = {
            "session_id": self.session_id,
            "issue": self.issue,
            "error_trace": self.error_trace,
            "start_time": self.start_time,
            "hypothesis": self.hypothesis,
            "fix_summary": self.fix_summary,
            "files_examined": self.files_examined,
            "files_modified": self.files_modified,
            "key_findings": self.key_findings,
            "tool_call_count": len(self._tool_calls),
            "phases": [
                {
                    "name": p.phase_name,
                    "start": p.start_time,
                    "end": p.end_time,
                    "findings": p.findings,
                    "notes": p.notes
                }
                for p in self._phases
            ]
        }
        
        state_file = self._context_dir / 'state.json'
        state_file.write_text(json.dumps(state, indent=2))
        logger.info(f"Context state saved: {state_file}")
    
    @classmethod
    def load_state(cls, project_dir: Path, session_id: str) -> Optional['DebugContext']:
        """Load context from a previous session."""
        context_dir = Path(project_dir) / '.raica' / 'sessions' / session_id
        state_file = context_dir / 'state.json'
        
        if not state_file.exists():
            logger.warning(f"No state file found: {state_file}")
            return None
        
        try:
            state = json.loads(state_file.read_text())
            context = cls(
                project_dir=project_dir,
                issue=state['issue'],
                error_trace=state.get('error_trace', ''),
                session_id=session_id
            )
            context.hypothesis = state.get('hypothesis')
            context.fix_summary = state.get('fix_summary')
            context.files_examined = state.get('files_examined', [])
            context.files_modified = state.get('files_modified', [])
            context.key_findings = state.get('key_findings', {})
            
            logger.info(f"Context loaded from session: {session_id}")
            return context
        except Exception as e:
            logger.error(f"Failed to load context: {e}")
            return None
    
    def get_summary(self) -> Dict:
        """Get a summary of the debug session."""
        successful = sum(1 for c in self._tool_calls if c.status == ToolCallStatus.SUCCESS)
        failed = sum(1 for c in self._tool_calls if c.status == ToolCallStatus.FAILED)
        
        return {
            "session_id": self.session_id,
            "issue": self.issue,
            "tool_calls": {
                "total": len(self._tool_calls),
                "successful": successful,
                "failed": failed
            },
            "phases": len(self._phases),
            "files_modified": self.files_modified,
            "hypothesis": self.hypothesis,
            "fix_summary": self.fix_summary
        }
