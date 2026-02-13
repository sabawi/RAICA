"""
Debugging Discipline
====================

Enforces systematic debugging rules:
1. Document and verify assumptions before acting
2. Systematic file/code lookup (never guess)
3. Follow evidence trail to TRUE root cause
4. Verify fix works end-to-end before declaring done
5. Flag issues found during work for autonomous fix (with approval)

Storage: .raica/assumptions.json, .raica/issues_found.json
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AssumptionStatus(Enum):
    """Status of an assumption."""
    UNVERIFIED = "unverified"
    VERIFIED_TRUE = "verified_true"
    VERIFIED_FALSE = "verified_false"
    PARTIALLY_TRUE = "partially_true"


class IssueSeverity(Enum):
    """Severity of a found issue."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueStatus(Enum):
    """Status of a found issue."""
    FOUND = "found"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    WONT_FIX = "wont_fix"
    DEFERRED = "deferred"


@dataclass
class Assumption:
    """An assumption that needs verification."""
    id: int
    description: str
    status: AssumptionStatus = AssumptionStatus.UNVERIFIED
    verification_method: Optional[str] = None
    verification_result: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    verified_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'description': self.description,
            'status': self.status.value,
            'verification_method': self.verification_method,
            'verification_result': self.verification_result,
            'created_at': self.created_at,
            'verified_at': self.verified_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Assumption':
        return cls(
            id=data.get('id', 0),
            description=data.get('description', ''),
            status=AssumptionStatus(data.get('status', 'unverified')),
            verification_method=data.get('verification_method'),
            verification_result=data.get('verification_result'),
            created_at=data.get('created_at', datetime.now().isoformat()),
            verified_at=data.get('verified_at'),
        )


@dataclass
class Evidence:
    """Evidence collected during investigation."""
    description: str
    source: str  # file path, command output, etc.
    content: str  # actual evidence content (truncated if long)
    collected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'description': self.description,
            'source': self.source,
            'content': self.content[:500] if len(self.content) > 500 else self.content,
            'collected_at': self.collected_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Evidence':
        return cls(
            description=data.get('description', ''),
            source=data.get('source', ''),
            content=data.get('content', ''),
            collected_at=data.get('collected_at', datetime.now().isoformat()),
        )


@dataclass
class IssueFound:
    """An issue found during work that should be flagged for fix."""
    id: int
    description: str
    severity: IssueSeverity
    status: IssueStatus = IssueStatus.FOUND
    found_in: str = ""  # file or context where found
    suggested_fix: str = ""
    related_to_current_task: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    approved_at: Optional[str] = None
    fixed_at: Optional[str] = None
    user_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'description': self.description,
            'severity': self.severity.value,
            'status': self.status.value,
            'found_in': self.found_in,
            'suggested_fix': self.suggested_fix,
            'related_to_current_task': self.related_to_current_task,
            'created_at': self.created_at,
            'approved_at': self.approved_at,
            'fixed_at': self.fixed_at,
            'user_notes': self.user_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IssueFound':
        return cls(
            id=data.get('id', 0),
            description=data.get('description', ''),
            severity=IssueSeverity(data.get('severity', 'medium')),
            status=IssueStatus(data.get('status', 'found')),
            found_in=data.get('found_in', ''),
            suggested_fix=data.get('suggested_fix', ''),
            related_to_current_task=data.get('related_to_current_task', True),
            created_at=data.get('created_at', datetime.now().isoformat()),
            approved_at=data.get('approved_at'),
            fixed_at=data.get('fixed_at'),
            user_notes=data.get('user_notes', ''),
        )


class DebuggingDiscipline:
    """
    Enforces debugging discipline rules.

    Rules:
    1. Document and verify assumptions before acting
    2. Systematic file/code lookup (never guess)
    3. Follow evidence trail to TRUE root cause
    4. Verify fix works end-to-end before declaring done
    5. Flag issues found during work for autonomous fix (with approval)
    """

    RULES = [
        "Document and verify assumptions before acting",
        "Systematic file/code lookup (never guess)",
        "Follow evidence trail to TRUE root cause",
        "Verify fix works end-to-end before declaring done",
        "Flag issues found during work for autonomous fix (with approval)"
    ]

    ASSUMPTIONS_FILE = "assumptions.json"
    ISSUES_FILE = "issues_found.json"

    def __init__(self, project_dir: Optional[Path] = None):
        """
        Initialize DebuggingDiscipline.

        Args:
            project_dir: Project directory for storage
        """
        self.project_dir = project_dir or Path.cwd()
        self.storage_dir = self.project_dir / ".raica"
        self.assumptions_file = self.storage_dir / self.ASSUMPTIONS_FILE
        self.issues_file = self.storage_dir / self.ISSUES_FILE

        # Current session data
        self.assumptions: List[Assumption] = []
        self.evidence_trail: List[Evidence] = []
        self.issues_found: List[IssueFound] = []

        # Tracking
        self.next_assumption_id = 1
        self.next_issue_id = 1
        self.fix_verified = False
        self.root_cause_identified = False
        self.root_cause_description: str = ""

    def document_assumption(self, description: str) -> Assumption:
        """
        Document an assumption that needs verification.

        Args:
            description: The assumption being made

        Returns:
            Created Assumption
        """
        assumption = Assumption(
            id=self.next_assumption_id,
            description=description
        )
        self.assumptions.append(assumption)
        self.next_assumption_id += 1

        logger.info(f"Assumption #{assumption.id}: {description}")
        return assumption

    def verify_assumption(
        self,
        assumption_id: int,
        method: str,
        result: str,
        is_true: bool
    ) -> bool:
        """
        Record verification of an assumption.

        Args:
            assumption_id: ID of assumption to verify
            method: How it was verified (file read, test, etc.)
            result: What was found
            is_true: Whether the assumption was correct

        Returns:
            True if assumption was found and updated
        """
        for assumption in self.assumptions:
            if assumption.id == assumption_id:
                assumption.verification_method = method
                assumption.verification_result = result
                assumption.verified_at = datetime.now().isoformat()
                assumption.status = (
                    AssumptionStatus.VERIFIED_TRUE if is_true
                    else AssumptionStatus.VERIFIED_FALSE
                )

                logger.info(
                    f"Assumption #{assumption_id} verified: "
                    f"{'TRUE' if is_true else 'FALSE'}"
                )
                return True

        return False

    def add_evidence(
        self,
        description: str,
        source: str,
        content: str
    ) -> Evidence:
        """
        Add evidence to the investigation trail.

        Args:
            description: What this evidence shows
            source: Where it came from (file, command, etc.)
            content: The actual evidence

        Returns:
            Created Evidence
        """
        evidence = Evidence(
            description=description,
            source=source,
            content=content
        )
        self.evidence_trail.append(evidence)

        logger.debug(f"Evidence added: {description} (from {source})")
        return evidence

    def identify_root_cause(self, description: str) -> None:
        """
        Record the identified root cause.

        Args:
            description: Description of the root cause
        """
        self.root_cause_identified = True
        self.root_cause_description = description
        logger.info(f"Root cause identified: {description}")

    def flag_issue(
        self,
        description: str,
        severity: IssueSeverity,
        found_in: str = "",
        suggested_fix: str = "",
        related: bool = True
    ) -> IssueFound:
        """
        Flag an issue found during work.

        Args:
            description: Issue description
            severity: How severe the issue is
            found_in: Where the issue was found
            suggested_fix: Suggested fix approach
            related: Whether related to current task

        Returns:
            Created IssueFound
        """
        issue = IssueFound(
            id=self.next_issue_id,
            description=description,
            severity=severity,
            found_in=found_in,
            suggested_fix=suggested_fix,
            related_to_current_task=related
        )
        self.issues_found.append(issue)
        self.next_issue_id += 1

        logger.info(f"Issue flagged: {description} (severity: {severity.value})")
        return issue

    def approve_issue(self, issue_id: int, notes: str = "") -> bool:
        """
        Approve an issue for fixing.

        Args:
            issue_id: ID of issue to approve
            notes: Optional user notes

        Returns:
            True if issue was found and approved
        """
        for issue in self.issues_found:
            if issue.id == issue_id:
                issue.status = IssueStatus.APPROVED
                issue.approved_at = datetime.now().isoformat()
                issue.user_notes = notes
                return True
        return False

    def mark_issue_fixed(self, issue_id: int) -> bool:
        """
        Mark an issue as fixed.

        Args:
            issue_id: ID of issue that was fixed

        Returns:
            True if issue was found and marked
        """
        for issue in self.issues_found:
            if issue.id == issue_id:
                issue.status = IssueStatus.FIXED
                issue.fixed_at = datetime.now().isoformat()
                return True
        return False

    def defer_issue(self, issue_id: int, notes: str = "") -> bool:
        """
        Defer an issue for later.

        Args:
            issue_id: ID of issue to defer
            notes: Reason for deferring

        Returns:
            True if issue was found and deferred
        """
        for issue in self.issues_found:
            if issue.id == issue_id:
                issue.status = IssueStatus.DEFERRED
                issue.user_notes = notes
                return True
        return False

    def record_fix_verified(self) -> None:
        """Record that the fix was verified end-to-end."""
        self.fix_verified = True
        logger.info("Fix verified end-to-end")

    def get_unapproved_issues(self) -> List[IssueFound]:
        """Get issues that need approval."""
        return [i for i in self.issues_found if i.status == IssueStatus.FOUND]

    def get_approved_issues(self) -> List[IssueFound]:
        """Get issues approved for fixing."""
        return [i for i in self.issues_found if i.status == IssueStatus.APPROVED]

    def get_unverified_assumptions(self) -> List[Assumption]:
        """Get assumptions that haven't been verified."""
        return [
            a for a in self.assumptions
            if a.status == AssumptionStatus.UNVERIFIED
        ]

    def enforce_discipline(self, action: str) -> List[str]:
        """
        Check if discipline rules are being followed.

        Args:
            action: Action about to be taken

        Returns:
            List of violations/warnings
        """
        violations = []

        # Check for unverified assumptions before taking action
        unverified = self.get_unverified_assumptions()
        if unverified and action in ['fix', 'implement', 'modify']:
            violations.append(
                f"Unverified assumptions ({len(unverified)}): "
                f"{unverified[0].description}"
            )

        # Check root cause before fixing
        if action == 'fix' and not self.root_cause_identified:
            violations.append(
                "Root cause not yet identified. "
                "Continue investigation before fixing."
            )

        # Check for pending issues that need attention
        pending = self.get_unapproved_issues()
        if pending and action == 'complete':
            violations.append(
                f"Issues found but not addressed ({len(pending)}): "
                f"{pending[0].description}"
            )

        return violations

    def get_discipline_status(self) -> str:
        """Get a summary of discipline status."""
        lines = []

        # Assumptions status
        total_assumptions = len(self.assumptions)
        unverified = len(self.get_unverified_assumptions())
        if total_assumptions > 0:
            lines.append(
                f"Assumptions: {total_assumptions - unverified}/{total_assumptions} verified"
            )

        # Root cause status
        if self.root_cause_identified:
            lines.append(f"Root cause: {self.root_cause_description[:50]}...")
        else:
            lines.append("Root cause: Not yet identified")

        # Evidence collected
        if self.evidence_trail:
            lines.append(f"Evidence pieces: {len(self.evidence_trail)}")

        # Issues status
        unapproved = len(self.get_unapproved_issues())
        approved = len(self.get_approved_issues())
        if unapproved > 0 or approved > 0:
            lines.append(f"Issues: {unapproved} pending approval, {approved} approved")

        # Fix verified
        if self.fix_verified:
            lines.append("Fix: Verified end-to-end")

        return '\n'.join(lines) if lines else "No debugging activity yet"

    def save(self) -> bool:
        """Save debugging state to disk."""
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

            # Save assumptions
            assumptions_data = {
                'assumptions': [a.to_dict() for a in self.assumptions],
                'evidence_trail': [e.to_dict() for e in self.evidence_trail],
                'root_cause_identified': self.root_cause_identified,
                'root_cause_description': self.root_cause_description,
                'fix_verified': self.fix_verified,
            }
            with open(self.assumptions_file, 'w') as f:
                json.dump(assumptions_data, f, indent=2)

            # Save issues
            issues_data = {
                'issues': [i.to_dict() for i in self.issues_found]
            }
            with open(self.issues_file, 'w') as f:
                json.dump(issues_data, f, indent=2)

            return True

        except Exception as e:
            logger.warning(f"Failed to save debugging state: {e}")
            return False

    def load(self) -> bool:
        """Load debugging state from disk."""
        loaded = False

        # Load assumptions
        if self.assumptions_file.exists():
            try:
                with open(self.assumptions_file, 'r') as f:
                    data = json.load(f)

                self.assumptions = [
                    Assumption.from_dict(a) for a in data.get('assumptions', [])
                ]
                self.evidence_trail = [
                    Evidence.from_dict(e) for e in data.get('evidence_trail', [])
                ]
                self.root_cause_identified = data.get('root_cause_identified', False)
                self.root_cause_description = data.get('root_cause_description', '')
                self.fix_verified = data.get('fix_verified', False)

                if self.assumptions:
                    self.next_assumption_id = max(a.id for a in self.assumptions) + 1

                loaded = True

            except Exception as e:
                logger.warning(f"Failed to load assumptions: {e}")

        # Load issues
        if self.issues_file.exists():
            try:
                with open(self.issues_file, 'r') as f:
                    data = json.load(f)

                self.issues_found = [
                    IssueFound.from_dict(i) for i in data.get('issues', [])
                ]

                if self.issues_found:
                    self.next_issue_id = max(i.id for i in self.issues_found) + 1

                loaded = True

            except Exception as e:
                logger.warning(f"Failed to load issues: {e}")

        return loaded

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            'assumptions': [a.to_dict() for a in self.assumptions],
            'evidence_trail': [e.to_dict() for e in self.evidence_trail],
            'issues_found': [i.to_dict() for i in self.issues_found],
            'root_cause_identified': self.root_cause_identified,
            'root_cause_description': self.root_cause_description,
            'fix_verified': self.fix_verified,
        }
