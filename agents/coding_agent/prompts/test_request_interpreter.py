"""
Unit Tests for Request Interpreter Module
=========================================

Comprehensive test coverage for:
- Data classes (UserFeedback, TodoItem, InterpretationResult)
- UserFeedbackHandler
- RequestInterpreter

Run with: pytest test_request_interpreter.py -v
"""

import json
import pytest
from datetime import datetime
from typing import List, Optional

# Import the module under test
from request_interpreter import (
    UserFeedback,
    TodoItem,
    InterpretationResult,
    MaxIterationsExceeded,
    UserFeedbackHandler,
    RequestInterpreter,
    REQUEST_INTERPRETER_PROMPT,
    ITERATION_PROMPT_TEMPLATE
)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_user_feedback():
    """Create a sample UserFeedback instance."""
    return UserFeedback(
        is_accurate=True,
        confidence=5,
        missing_items=["missing feature A"],
        incorrect_items=["wrong assumption B"],
        additional_requirements=["extra requirement C"],
        priority_override="high",
        clarifications="Need more context on X",
        iteration=1
    )


@pytest.fixture
def sample_todo_item():
    """Create a sample TodoItem instance with descriptive task."""
    return TodoItem(
        step_number=1,
        task="Create main.py with application entry point and command line argument parsing",
        tool_suggestions=["read_file", "write_file"],
        depends_on=[],
        verification_criteria="File exists and runs without errors",
        estimated_effort="low",
        priority="high"
    )


@pytest.fixture
def sample_interpretation_result(sample_todo_item):
    """Create a sample InterpretationResult instance with 2+ todos."""
    todo2 = TodoItem(
        step_number=2,
        task="Create requirements.txt file with all necessary package dependencies listed",
        tool_suggestions=["write_file"],
        priority="medium"
    )
    return InterpretationResult(
        primary_intent="Create a Python web scraper",
        request_type="CODE_GENERATION",
        confidence=0.95,
        complexity="medium",
        todo_list=[sample_todo_item, todo2],
        context_needs=["requirements.txt", "project structure"],
        potential_issues=["API rate limits", "Network failures"],
        mitigation_strategies=["Add retry logic", "Cache responses"],
        user_confirmed=True,
        user_confidence=5,
        iteration_count=1
    )


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client for testing."""
    class MockLLMResponse:
        def __init__(self, content):
            self.content = content

    class MockLLMClient:
        def __init__(self, response_content):
            self.response_content = response_content

        def generate(self, prompt, **kwargs):
            return MockLLMResponse(self.response_content)

    def create_client(response_content):
        return MockLLMClient(response_content)

    return create_client


@pytest.fixture
def mock_ui_callback():
    """Create a mock UI callback that returns predetermined responses."""
    responses = []
    index = 0

    def callback(prompt: str) -> str:
        nonlocal index
        response = responses[index % len(responses)]
        index += 1
        return response

    callback.responses = responses
    callback.index = index
    return callback


# ═══════════════════════════════════════════════════════════════════════════
# USERFEEDBACK TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestUserFeedback:
    """Test UserFeedback dataclass."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        fb = UserFeedback()
        assert fb.is_accurate is False
        assert fb.confidence == 0
        assert fb.missing_items == []
        assert fb.incorrect_items == []
        assert fb.additional_requirements == []
        assert fb.priority_override is None
        assert fb.clarifications == ""
        assert fb.iteration == 0
        assert isinstance(fb.timestamp, datetime)

    def test_custom_values(self, sample_user_feedback):
        """Test that custom values are stored correctly."""
        assert sample_user_feedback.is_accurate is True
        assert sample_user_feedback.confidence == 5
        assert len(sample_user_feedback.missing_items) == 1
        assert len(sample_user_feedback.incorrect_items) == 1
        assert sample_user_feedback.priority_override == "high"

    def test_to_dict(self, sample_user_feedback):
        """Test serialization to dict."""
        data = sample_user_feedback.to_dict()
        assert data['is_accurate'] is True
        assert data['confidence'] == 5
        assert 'missing_items' in data
        assert 'timestamp' in data
        assert isinstance(data['timestamp'], str)


# ═══════════════════════════════════════════════════════════════════════════
# TODOITEM TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestTodoItem:
    """Test TodoItem dataclass."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        item = TodoItem(step_number=1, task="Test task")
        assert item.tool_suggestions == []
        assert item.depends_on == []
        assert item.verification_criteria == ""
        assert item.estimated_effort == "medium"
        assert item.priority == "medium"

    def test_custom_values(self, sample_todo_item):
        """Test that custom values are stored correctly."""
        assert sample_todo_item.step_number == 1
        assert "main.py" in sample_todo_item.task
        assert "entry point" in sample_todo_item.task
        assert len(sample_todo_item.tool_suggestions) == 2
        assert sample_todo_item.priority == "high"
        assert sample_todo_item.estimated_effort == "low"

    def test_to_dict(self, sample_todo_item):
        """Test serialization to dict."""
        data = sample_todo_item.to_dict()
        assert data['step_number'] == 1
        assert "main.py" in data['task']
        assert "entry point" in data['task']
        assert data['priority'] == "high"


# ═══════════════════════════════════════════════════════════════════════════
# INTERPRETATIONRESULT TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestInterpretationResult:
    """Test InterpretationResult dataclass."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        result = InterpretationResult()
        assert result.primary_intent == ""
        assert result.request_type == ""
        assert result.confidence == 0.0
        assert result.complexity == "medium"
        assert result.todo_list == []
        assert result.user_confirmed is False
        assert result.iteration_count == 0

    def test_custom_values(self, sample_interpretation_result):
        """Test that custom values are stored correctly."""
        assert sample_interpretation_result.primary_intent == "Create a Python web scraper"
        assert sample_interpretation_result.confidence == 0.95
        assert len(sample_interpretation_result.todo_list) == 2  # 2 todos for validation
        assert sample_interpretation_result.user_confirmed is True

    def test_to_dict(self, sample_interpretation_result):
        """Test serialization to dict."""
        data = sample_interpretation_result.to_dict()
        assert data['primary_intent'] == "Create a Python web scraper"
        assert data['confidence'] == 0.95
        assert 'todo_list' in data
        assert 'feedback_history' in data

    def test_get_summary(self, sample_interpretation_result):
        """Test summary generation."""
        summary = sample_interpretation_result.get_summary()
        assert "Intent:" in summary
        assert "Confidence:" in summary
        assert "Tasks:" in summary
        assert "User Confirmed:" in summary


# ═══════════════════════════════════════════════════════════════════════════
# USERFEEDBACKHANDLER TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestUserFeedbackHandler:
    """Test UserFeedbackHandler class."""

    def test_default_initialization(self):
        """Test that handler initializes with defaults."""
        handler = UserFeedbackHandler()
        assert handler.max_iterations == 10
        assert handler.ui_callback is not None

    def test_custom_callback(self):
        """Test that custom callback is stored."""
        def custom_callback(prompt: str) -> str:
            return "yes"

        handler = UserFeedbackHandler(ui_callback=custom_callback)
        assert handler.ui_callback == custom_callback

    def test_should_iterate_confirmed_high_confidence(self):
        """Test should_iterate returns False when user confirms with high confidence."""
        handler = UserFeedbackHandler()
        feedback = UserFeedback(is_accurate=True, confidence=5)

        result = handler.should_iterate(feedback, iteration=1)
        assert result is False

    def test_should_iterate_not_accurate(self):
        """Test should_iterate returns True when user says not accurate."""
        handler = UserFeedbackHandler()
        feedback = UserFeedback(is_accurate=False, confidence=1)

        result = handler.should_iterate(feedback, iteration=1)
        assert result is True

    def test_should_iterate_missing_items(self):
        """Test should_iterate returns True when there are missing items."""
        handler = UserFeedbackHandler()
        feedback = UserFeedback(
            is_accurate=True,
            confidence=4,
            missing_items=["missing item"]
        )

        result = handler.should_iterate(feedback, iteration=1)
        assert result is True

    def test_should_iterate_incorrect_items(self):
        """Test should_iterate returns True when there are incorrect items."""
        handler = UserFeedbackHandler()
        feedback = UserFeedback(
            is_accurate=True,
            confidence=4,
            incorrect_items=["wrong item"]
        )

        result = handler.should_iterate(feedback, iteration=1)
        assert result is True

    def test_should_iterate_max_iterations_reached(self):
        """Test should_iterate returns False when max iterations reached."""
        handler = UserFeedbackHandler()
        feedback = UserFeedback(is_accurate=False, confidence=1)

        result = handler.should_iterate(feedback, iteration=10)
        assert result is False

    def test_should_iterate_low_confidence(self):
        """Test should_iterate returns True when confidence is low."""
        handler = UserFeedbackHandler()
        feedback = UserFeedback(is_accurate=True, confidence=2)

        result = handler.should_iterate(feedback, iteration=1)
        assert result is True

    def test_present_interpretation_contains_key_sections(self, sample_interpretation_result):
        """Test that presentation includes key sections."""
        handler = UserFeedbackHandler()
        presentation = handler.present_interpretation(sample_interpretation_result)

        assert "INTENT:" in presentation
        assert "TO-DO LIST:" in presentation
        assert "Step 1" in presentation
        assert "Is this interpretation accurate?" in presentation

    def test_present_interpretation_with_issues(self, sample_interpretation_result):
        """Test that presentation includes issues section when present."""
        handler = UserFeedbackHandler()
        presentation = handler.present_interpretation(sample_interpretation_result)

        assert "POTENTIAL ISSUES" in presentation
        assert "API rate limits" in presentation
        assert "MITIGATION STRATEGIES" in presentation

    def test_build_iteration_prompt_structure(self, sample_interpretation_result, sample_user_feedback):
        """Test that iteration prompt has correct structure."""
        handler = UserFeedbackHandler()
        prompt = handler.build_iteration_prompt(
            "Original request",
            sample_interpretation_result,
            sample_user_feedback
        )

        assert "ORIGINAL REQUEST" in prompt
        assert "PREVIOUS INTERPRETATION" in prompt
        assert "USER FEEDBACK" in prompt
        assert "YOUR TASK" in prompt
        assert "Original request" in prompt

    def test_build_iteration_prompt_with_feedback_items(self, sample_interpretation_result):
        """Test that iteration prompt includes feedback items."""
        handler = UserFeedbackHandler()
        feedback = UserFeedback(
            is_accurate=False,
            confidence=2,
            missing_items=["item1", "item2"],
            incorrect_items=["wrong1"]
        )

        prompt = handler.build_iteration_prompt(
            "Original",
            sample_interpretation_result,
            feedback
        )

        assert "item1" in prompt or "item2" in prompt
        assert "wrong1" in prompt

    def test_capture_feedback_yes_response(self, sample_interpretation_result):
        """Test feedback capture with 'yes' response."""
        # Need responses for: accuracy, confidence, priority, clarifications
        responses = ["yes", "5", "high", ""]
        index = 0

        def mock_callback(prompt: str) -> str:
            nonlocal index
            response = responses[index % len(responses)]
            index += 1
            return response

        handler = UserFeedbackHandler(ui_callback=mock_callback)
        feedback = handler.capture_feedback(sample_interpretation_result)

        assert feedback.is_accurate is True
        assert feedback.confidence == 5

    def test_capture_feedback_no_response(self, sample_interpretation_result):
        """Test feedback capture with 'no' response."""
        responses = [
            "no",
            "missing authentication, error handling",
            "wrong language choice",
            "add logging",
            "high",
            "needs more detail"
        ]
        index = 0

        def mock_callback(prompt: str) -> str:
            nonlocal index
            response = responses[index]
            index += 1
            return response

        handler = UserFeedbackHandler(ui_callback=mock_callback)
        feedback = handler.capture_feedback(sample_interpretation_result)

        assert feedback.is_accurate is False
        assert feedback.confidence == 1
        assert len(feedback.missing_items) == 2
        assert len(feedback.incorrect_items) == 1
        assert len(feedback.additional_requirements) == 1
        assert feedback.priority_override == "high"
        assert "more detail" in feedback.clarifications

    def test_capture_feedback_partly_response(self, sample_interpretation_result):
        """Test feedback capture with 'partly' response."""
        responses = [
            "partly",
            "nothing",  # nothing missing
            "nothing",  # nothing incorrect
            "none",     # no additional
            "",         # no priority override
            ""          # no clarifications
        ]
        index = 0

        def mock_callback(prompt: str) -> str:
            nonlocal index
            response = responses[index]
            index += 1
            return response

        handler = UserFeedbackHandler(ui_callback=mock_callback)
        feedback = handler.capture_feedback(sample_interpretation_result)

        assert feedback.is_accurate is False
        assert feedback.confidence == 2


# ═══════════════════════════════════════════════════════════════════════════
# REQUESTINTERPRETER TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestRequestInterpreter:
    """Test RequestInterpreter class."""

    def test_default_initialization(self):
        """Test that interpreter initializes with defaults."""
        interpreter = RequestInterpreter(llm_client=None)
        assert interpreter.llm_client is None
        assert interpreter.feedback_handler is not None
        assert interpreter.DEFAULT_TOOLS is not None
        assert len(interpreter.DEFAULT_TOOLS) > 0

    def test_validate_interpretation_valid(self, sample_interpretation_result):
        """Test validation of a valid interpretation."""
        interpreter = RequestInterpreter(llm_client=None)

        is_valid, issues = interpreter.validate_interpretation(sample_interpretation_result)

        assert is_valid is True
        assert len(issues) == 0

    def test_validate_interpretation_empty_intent(self, sample_interpretation_result):
        """Test validation catches empty intent."""
        interpreter = RequestInterpreter(llm_client=None)
        sample_interpretation_result.primary_intent = ""

        is_valid, issues = interpreter.validate_interpretation(sample_interpretation_result)

        assert is_valid is False
        assert any("Missing primary_intent" in issue for issue in issues)

    def test_validate_interpretation_empty_todo(self, sample_interpretation_result):
        """Test validation catches empty todo list."""
        interpreter = RequestInterpreter(llm_client=None)
        sample_interpretation_result.todo_list = []

        is_valid, issues = interpreter.validate_interpretation(sample_interpretation_result)

        assert is_valid is False
        assert any("Empty todo_list" in issue for issue in issues)

    def test_validate_interpretation_low_confidence(self, sample_interpretation_result):
        """Test validation catches low confidence."""
        interpreter = RequestInterpreter(llm_client=None)
        sample_interpretation_result.confidence = 0.3

        is_valid, issues = interpreter.validate_interpretation(sample_interpretation_result)

        assert is_valid is False
        assert any("Low confidence" in issue for issue in issues)

    def test_validate_interpretation_few_steps(self, sample_interpretation_result):
        """Test validation catches too few steps."""
        interpreter = RequestInterpreter(llm_client=None)
        sample_interpretation_result.todo_list = [sample_interpretation_result.todo_list[0]]

        is_valid, issues = interpreter.validate_interpretation(sample_interpretation_result)

        assert is_valid is False
        assert any("Too few steps" in issue for issue in issues)

    def test_validate_interpretation_duplicate_steps(self, sample_interpretation_result):
        """Test validation catches duplicate step numbers."""
        interpreter = RequestInterpreter(llm_client=None)
        # Add another item with same step number
        duplicate = TodoItem(step_number=1, task="Duplicate step")
        sample_interpretation_result.todo_list.append(duplicate)

        is_valid, issues = interpreter.validate_interpretation(sample_interpretation_result)

        assert is_valid is False
        assert any("Duplicate step numbers" in issue for issue in issues)

    def test_validate_interpretation_short_task(self, sample_interpretation_result):
        """Test validation catches short task descriptions."""
        interpreter = RequestInterpreter(llm_client=None)
        sample_interpretation_result.todo_list[0].task = "short"

        is_valid, issues = interpreter.validate_interpretation(sample_interpretation_result)

        assert is_valid is False
        assert any("Task description too short" in issue for issue in issues)

    def test_parse_interpretation_valid_json(self, mock_llm_client):
        """Test parsing of valid LLM response."""
        valid_response = json.dumps({
            "interpretation": {
                "primary_intent": "Test intent",
                "request_type": "CODE_GENERATION",
                "confidence": 0.9,
                "complexity": "simple"
            },
            "todo_list": [
                {
                    "step_number": 1,
                    "task": "Create test file",
                    "tool_suggestions": ["write_file"],
                    "depends_on": [],
                    "verification_criteria": "File exists",
                    "estimated_effort": "low",
                    "priority": "high"
                }
            ],
            "context_needs": ["project structure"],
            "risk_assessment": {
                "potential_issues": ["issue1"],
                "mitigation_strategies": ["strategy1"]
            }
        })

        client = mock_llm_client(valid_response)
        interpreter = RequestInterpreter(llm_client=client)

        result = interpreter._parse_interpretation(valid_response)

        assert result is not None
        assert result.primary_intent == "Test intent"
        assert result.confidence == 0.9
        assert len(result.todo_list) == 1
        assert result.todo_list[0].step_number == 1

    def test_parse_interpretation_with_code_block(self, mock_llm_client):
        """Test parsing of LLM response with markdown code block."""
        response_with_block = """Here's the interpretation:

```json
{
    "interpretation": {
        "primary_intent": "Block test",
        "request_type": "SYSTEM_TASK",
        "confidence": 0.8,
        "complexity": "medium"
    },
    "todo_list": []
}
```

Hope this helps!"""

        client = mock_llm_client(response_with_block)
        interpreter = RequestInterpreter(llm_client=client)

        result = interpreter._parse_interpretation(response_with_block)

        assert result is not None
        assert result.primary_intent == "Block test"

    def test_parse_interpretation_invalid_json(self):
        """Test parsing of invalid JSON response."""
        interpreter = RequestInterpreter(llm_client=None)

        result = interpreter._parse_interpretation("not valid json")

        assert result is None

    def test_parse_interpretation_no_json(self):
        """Test parsing of response with no JSON."""
        interpreter = RequestInterpreter(llm_client=None)

        result = interpreter._parse_interpretation("just some text without braces")

        assert result is None

    def test_default_tools_list(self):
        """Test that default tools list is populated."""
        interpreter = RequestInterpreter(llm_client=None)

        assert "read_file" in interpreter.DEFAULT_TOOLS
        assert "write_file" in interpreter.DEFAULT_TOOLS
        assert "run_command" in interpreter.DEFAULT_TOOLS


# ═══════════════════════════════════════════════════════════════════════════
# PROMPT TEMPLATE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPromptTemplates:
    """Test system prompt templates."""

    def test_request_interpreter_prompt_not_empty(self):
        """Test that main prompt is not empty."""
        assert len(REQUEST_INTERPRETER_PROMPT) > 0
        assert "Request Interpreter" in REQUEST_INTERPRETER_PROMPT

    def test_request_interpreter_prompt_has_format(self):
        """Test that prompt includes output format instructions."""
        assert "OUTPUT FORMAT" in REQUEST_INTERPRETER_PROMPT
        assert "todo_list" in REQUEST_INTERPRETER_PROMPT
        assert "interpretation" in REQUEST_INTERPRETER_PROMPT

    def test_request_interpreter_prompt_has_placeholders(self):
        """Test that prompt has required placeholders."""
        assert "{user_request}" in REQUEST_INTERPRETER_PROMPT
        assert "{project_context}" in REQUEST_INTERPRETER_PROMPT
        assert "{available_tools}" in REQUEST_INTERPRETER_PROMPT

    def test_iteration_prompt_template_not_empty(self):
        """Test that iteration prompt is not empty."""
        assert len(ITERATION_PROMPT_TEMPLATE) > 0

    def test_iteration_prompt_has_placeholders(self):
        """Test that iteration prompt has required placeholders."""
        assert "{original_request}" in ITERATION_PROMPT_TEMPLATE
        assert "{previous_interpretation}" in ITERATION_PROMPT_TEMPLATE
        assert "{is_accurate}" in ITERATION_PROMPT_TEMPLATE
        assert "{missing_items}" in ITERATION_PROMPT_TEMPLATE


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Integration tests for the full flow."""

    @pytest.mark.asyncio
    async def test_interpret_request_success(self, mock_llm_client):
        """Test successful interpretation flow."""
        valid_response = json.dumps({
            "interpretation": {
                "primary_intent": "Create Python script",
                "request_type": "CODE_GENERATION",
                "confidence": 0.95,
                "complexity": "simple"
            },
            "todo_list": [
                {
                    "step_number": 1,
                    "task": "Create main.py file",
                    "tool_suggestions": ["write_file"],
                    "priority": "high"
                },
                {
                    "step_number": 2,
                    "task": "Add requirements.txt",
                    "tool_suggestions": ["write_file"],
                    "priority": "medium"
                }
            ],
            "context_needs": [],
            "risk_assessment": {
                "potential_issues": [],
                "mitigation_strategies": []
            }
        })

        # mock_llm_client is a factory function, call it to get actual client
        client = mock_llm_client(valid_response)
        interpreter = RequestInterpreter(llm_client=client)

        result = await interpreter.interpret_request(
            "Create a Python script",
            {"files": []}
        )

        assert result is not None
        assert result.primary_intent == "Create Python script"
        assert len(result.todo_list) == 2


# ═══════════════════════════════════════════════════════════════════════════
# EDGE CASE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge case tests."""

    def test_user_feedback_with_empty_lists(self):
        """Test UserFeedback with empty but initialized lists."""
        fb = UserFeedback(
            missing_items=[],
            incorrect_items=[],
            additional_requirements=[]
        )
        assert fb.missing_items == []
        assert fb.to_dict()['missing_items'] == []

    def test_todo_item_with_no_dependencies(self):
        """Test TodoItem with empty dependencies."""
        item = TodoItem(step_number=1, task="Test", depends_on=[])
        assert item.depends_on == []

    def test_interpretation_result_with_many_todos(self):
        """Test InterpretationResult with many todo items."""
        todos = [
            TodoItem(step_number=i, task=f"Implement feature number {i} with comprehensive error handling and logging")
            for i in range(1, 11)
        ]
        result = InterpretationResult(
            primary_intent="Create a complex application with many features",
            todo_list=todos,
            confidence=0.9
        )

        assert len(result.todo_list) == 10
        is_valid, issues = RequestInterpreter(llm_client=None).validate_interpretation(result)
        assert is_valid is True, f"Validation failed with issues: {issues}"

    def test_should_iterate_boundary_confidence(self):
        """Test should_iterate at boundary confidence levels."""
        handler = UserFeedbackHandler()

        # Confidence 4 - should NOT iterate (meets threshold)
        fb1 = UserFeedback(is_accurate=True, confidence=4)
        result1 = handler.should_iterate(fb1, 1)
        # User is accurate with confidence 4 - no need to iterate
        assert result1 is False

        # Confidence 3 - should ITERATE (below threshold)
        fb2 = UserFeedback(is_accurate=True, confidence=3)
        result2 = handler.should_iterate(fb2, 1)
        # Even though they said accurate, low confidence means iterate
        assert result2 is True

        # Confidence 2 - should ITERATE
        fb3 = UserFeedback(is_accurate=True, confidence=2)
        result3 = handler.should_iterate(fb3, 1)
        assert result3 is True


# ═══════════════════════════════════════════════════════════════════════════
# EXCEPTION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestExceptions:
    """Test exception handling."""

    def test_max_iterations_exceeded_exception(self):
        """Test MaxIterationsExceeded exception."""
        with pytest.raises(MaxIterationsExceeded) as exc_info:
            raise MaxIterationsExceeded("Test message")

        assert "Test message" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
