# Request Interpreter - User Feedback Loop Design

**Version:** 1.0.0
**Date:** 2026-01-29
**Status:** Design Document
**Related:** Task 2.1 in RAICA_CODING_AGENT_IMPROVEMENT_PLAN.md

---

## Overview

The User Feedback Loop ensures the LLM's interpretation of user requests is validated before execution. This prevents miscommunication and ensures the system understands user intent correctly.

---

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     USER FEEDBACK LOOP                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────┐    ┌────────┐ │
│  │   USER   │───▶│     LLM      │───▶│  PRESENT    │───▶│  USER  │ │
│  │ REQUEST  │    │ INTERPRETER  │    │ INTERPRET.  │    │ REVIEW │ │
│  └──────────┘    └──────────────┘    └─────────────┘    └────────┘ │
│                                                              │      │
│                                                              ▼      │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────┐    ┌────────┐ │
│  │  PROCEED │◀───│  UPDATE INT. │◀───│ USER PROVIDES│◀──│  USER  │ │
│  │  TO EXEC │    │  BASED ON    │    │  FEEDBACK   │    │ CONFIRM│ │
│  │          │    │  FEEDBACK    │    │             │    │  YES?  │ │
│  └──────────┘    └──────────────┘    └─────────────┘    └───┬────┘ │
│                                                             │       │
│                                                        NO ──┘       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. UserFeedback Dataclass

```python
@dataclass
class UserFeedback:
    """Captures user's validation of interpretation."""

    # Overall confirmation
    is_accurate: bool                      # Does interpretation match intent?
    confidence: int                        # 1-5 scale (5 = exactly right)

    # Specific corrections
    missing_items: List[str]               # What was missed?
    incorrect_items: List[str]             # What was wrong?
    additional_requirements: List[str]     # What else is needed?

    # Priority adjustment
    priority_override: Optional[str]       # high/medium/low

    # User notes
    clarifications: str                    # Free-form clarification

    # Metadata
    iteration: int                         # Which iteration this is
    timestamp: datetime
```

### 2. UserFeedbackHandler Class

```python
class UserFeedbackHandler:
    """Handles presentation and capture of user feedback."""

    def __init__(self, ui_callback: Callable[[str], str]):
        """
        Args:
            ui_callback: Function to send message to user and get response
                        Signature: (prompt: str) -> str (user response)
        """
        self.ui_callback = ui_callback
        self.max_iterations = 3  # Prevent infinite loops

    def present_interpretation(self, interpretation: dict) -> str:
        """
        Format interpretation for user review.

        Returns formatted string like:

        ═══════════════════════════════════════════════════════
        📋 INTERPRETATION OF YOUR REQUEST
        ═══════════════════════════════════════════════════════

        🎯 INTENT: Create a Python script to calculate stock prices
                   with real-time data feed.

        Confidence: 92%

        📋 TO-DO LIST:
        1. [HIGH] Create main.py with price calculation logic
        2. [HIGH] Add API integration for real-time data
        3. [MEDIUM] Implement error handling for API failures
        4. [MEDIUM] Add data validation for price inputs
        5. [LOW] Create configuration file for API keys

        🔧 RECOMMENDED TOOLS:
        - yfinance (stock data)
        - requests (API calls)
        - python-dotenv (config management)

        ⚠️ RISKS IDENTIFIED:
        - API rate limits may affect performance
        - Real-time data requires network connectivity

        🔄 DEPENDENCIES:
        - Step 2 depends on Step 1
        - Step 3 depends on Step 2

        ═══════════════════════════════════════════════════════
        Is this what you meant? (yes/no/partly)
        ═══════════════════════════════════════════════════════
        """

    def capture_feedback(self, interpretation: dict) -> UserFeedback:
        """
        Interactive questionnaire to capture user feedback.

        Questions flow:
        1. "Is this what you meant? (yes/no/partly)"
           - If yes: confidence level (1-5)
           - If no/partly: proceed to corrections

        2. "What's missing or incorrect?"
           - Free-form text, parsed for bullet points

        3. "Any additional requirements?"
           - Free-form text

        4. "Priority level? (high/medium/low)"
           - Default: interpreted priority

        Returns: UserFeedback object
        """

    def should_iterate(self, feedback: UserFeedback, iteration: int) -> bool:
        """
        Determine if we need another iteration.

        Returns True if:
        - feedback.is_accurate is False
        - feedback.confidence < 4
        - feedback.missing_items is not empty
        - feedback.incorrect_items is not empty
        - iteration < max_iterations

        Returns False if:
        - user confirmed accuracy with confidence >= 4
        - max iterations reached
        """

    def build_iteration_prompt(self, original_request: str,
                               current_interpretation: dict,
                               feedback: UserFeedback) -> str:
        """
        Build prompt for LLM to revise interpretation.

        Includes:
        - Original user request
        - Current interpretation (what LLM thought)
        - User feedback (what was wrong/missing)
        - Instructions to refine

        Example prompt structure:
        """
        USER REQUEST: {original_request}

        YOUR PREVIOUS INTERPRETATION:
        {current_interpretation}

        USER FEEDBACK:
        - Accurate: {feedback.is_accurate}
        - Confidence: {feedback.confidence}/5
        - Missing: {feedback.missing_items}
        - Incorrect: {feedback.incorrect_items}
        - Additional: {feedback.additional_requirements}
        - Clarifications: {feedback.clarifications}

        TASK:
        Revise your interpretation based on the feedback.
        Keep what was correct, fix what was wrong, add what was missing.
        Provide an updated TO-DO list that accurately reflects user intent.
        """
```

### 3. Interpretation Iteration Loop

```python
async def interpretation_iteration_loop(
    self,
    user_request: str,
    project_context: dict
) -> dict:
    """
    Main loop that iterates until user confirms interpretation.

    Args:
        user_request: Original user request text
        project_context: Project structure and available files

    Returns:
        Final validated interpretation dict

    Raises:
        MaxIterationsExceeded: If user doesn't confirm after max tries
    """
    iteration = 0
    interpretation = None
    feedback_history = []

    while iteration < self.max_iterations:
        iteration += 1

        # Step 1: Get interpretation from LLM
        if iteration == 1:
            interpretation = await self.interpret_request(
                user_request, project_context
            )
        else:
            # Revise based on feedback
            iteration_prompt = self.feedback_handler.build_iteration_prompt(
                user_request, interpretation, last_feedback
            )
            interpretation = await self.interpret_request(
                iteration_prompt, project_context, is_revision=True
            )

        # Step 2: Present to user
        presentation = self.feedback_handler.present_interpretation(
            interpretation
        )

        # Step 3: Capture feedback
        feedback = self.feedback_handler.capture_feedback(interpretation)
        feedback.iteration = iteration
        feedback_history.append(feedback)

        # Step 4: Check if done
        if not self.feedback_handler.should_iterate(feedback, iteration):
            # User confirmed - proceed
            interpretation['user_confirmed'] = True
            interpretation['confidence'] = feedback.confidence
            interpretation['feedback_history'] = feedback_history
            return interpretation

        last_feedback = feedback

        # Continue to next iteration
        self.output(f"🔄 Refining interpretation (iteration {iteration + 1})...")

    # Max iterations reached
    raise MaxIterationsExceeded(
        f"User did not confirm interpretation after {self.max_iterations} attempts"
    )
```

---

## UI Integration

### TUI Mode (Textual)

```python
class InterpretationReviewScreen(ModalScreen):
    """Modal screen for reviewing interpretation in TUI."""

    def compose(self) -> ComposeResult:
        yield Label("📋 Interpretation Review", id="title")
        yield RichLog(id="interpretation_display")
        yield Label("Is this accurate?")
        yield Horizontal(
            Button("✓ Yes", id="yes", variant="success"),
            Button("~ Partly", id="partly", variant="warning"),
            Button("✗ No", id="no", variant="error"),
        )
        yield Input(id="feedback_input", placeholder="What's missing or wrong?")
        yield Button("Submit Feedback", id="submit")
```

### CLI Mode (Non-interactive)

```python
def cli_feedback_capture(interpretation: dict) -> UserFeedback:
    """Fallback for non-interactive environments."""

    print("\n" + "=" * 60)
    print("INTERPRETATION REVIEW")
    print("=" * 60)
    print(present_interpretation(interpretation))
    print("=" * 60)

    # Interactive prompts
    accurate = input("Is this accurate? (yes/no/partly): ").lower()

    if accurate in ('no', 'partly'):
        missing = input("What's missing? (comma-separated): ")
        wrong = input("What's incorrect? (comma-separated): ")
        clarifications = input("Additional clarifications: ")

        return UserFeedback(
            is_accurate=False,
            missing_items=[x.strip() for x in missing.split(',') if x.strip()],
            incorrect_items=[x.strip() for x in wrong.split(',') if x.strip()],
            clarifications=clarifications
        )

    return UserFeedback(is_accurate=True, confidence=5)
```

---

## Example Flow

### Iteration 1 - Initial Interpretation

**User:** "Create a web scraper for stock prices"

**LLM Interpretation:**
```json
{
  "intent": "Create Python script to scrape stock prices from web",
  "todo_list": [
    {"step": 1, "task": "Create scraper.py with requests/BeautifulSoup"},
    {"step": 2, "task": "Add HTML parsing for stock data"},
    {"step": 3, "task": "Save data to CSV file"}
  ],
  "tools": ["requests", "beautifulsoup4", "pandas"]
}
```

**User Feedback:** "Partly correct. I need real-time data from an API, not scraping. Also need a GUI to display prices."

### Iteration 2 - Revised Interpretation

**LLM Revised Interpretation:**
```json
{
  "intent": "Create Python app with GUI to display real-time stock prices from API",
  "todo_list": [
    {"step": 1, "task": "Create main.py with tkinter GUI"},
    {"step": 2, "task": "Integrate yfinance API for real-time data"},
    {"step": 3, "task": "Add price display with auto-refresh"},
    {"step": 4, "task": "Add error handling for API failures"}
  ],
  "tools": ["yfinance", "tkinter"]
}
```

**User Feedback:** "Yes, exactly what I need! Confidence: 5/5"

**✓ Proceed to execution**

---

## Edge Cases

### Case 1: Max Iterations Reached
If user doesn't confirm after 3 iterations:
- Log warning
- Use best interpretation so far
- Proceed with explicit note to user: "Using best interpretation after 3 refinement attempts"

### Case 2: Empty/Vague Feedback
If user says "It's wrong" but provides no details:
- Ask specific questions: "What specifically is missing?"
- If still vague, proceed with warning

### Case 3: Contradictory Feedback
If user says "yes it's accurate" but also lists missing items:
- Prioritize explicit list over boolean
- Ask for clarification: "You said yes, but listed missing items - should I add those?"

### Case 4: Non-interactive Mode
If running in script/batch mode:
- Skip feedback loop
- Log interpretation for review
- Add command-line flag `--confirm-interpretation` to enable

---

## Integration with Orchestrator

```python
class Orchestrator:
    async def handle_request(self, request: str):
        # Step 1: Interpret with feedback loop
        interpreter = RequestInterpreter(
            llm_client=self.llm_client,
            feedback_handler=UserFeedbackHandler(self.ui_callback)
        )

        interpretation = await interpreter.interpretation_iteration_loop(
            user_request=request,
            project_context=self.get_project_context()
        )

        # Step 2: Now classify based on confirmed interpretation
        classification = self.classifier.classify(
            request=interpretation['refined_request'],
            context=interpretation
        )

        # Step 3: Decompose into steps
        plan = self.decomposer.decompose(
            interpretation=interpretation,
            classification=classification
        )

        # Step 4: Execute
        return await self.execute_plan(plan)
```

---

## Success Metrics

1. **User Confirmation Rate**: % of requests confirmed on first iteration (target: 70%)
2. **Average Iterations**: Average number of iterations needed (target: 1.3)
3. **Abandonment Rate**: % of requests abandoned due to interpretation issues (target: <5%)

---

## Implementation Checklist

- [ ] UserFeedback dataclass
- [ ] UserFeedbackHandler class
- [ ] present_interpretation() formatting
- [ ] capture_feedback() questionnaire
- [ ] should_iterate() logic
- [ ] build_iteration_prompt() method
- [ ] interpretation_iteration_loop() main loop
- [ ] TUI Integration (InterpretationReviewScreen)
- [ ] CLI Integration (fallback mode)
- [ ] Max iterations handling
- [ ] Edge case handling (empty feedback, contradictions)
- [ ] Unit tests (10+ scenarios)
- [ ] Integration with Orchestrator
- [ ] Logging and metrics

---

**END OF DESIGN DOCUMENT**
