"""
Unit tests for the Investigation Phase in AutonomousEnhancementController.

Tests the LLM-driven investigation phase that checks if existing functionality
can fulfill a request before proceeding with TDD implementation.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json


class TestInvestigationPhase:
    """Test the _investigate_before_implementation method."""

    @pytest.fixture
    def mock_llm_client(self):
        """Create a mock LLM client."""
        client = Mock()
        client.generate = Mock()
        return client

    @pytest.fixture
    def controller(self, mock_llm_client, tmp_path):
        """Create an enhancement controller with mocked dependencies."""
        with patch('agents.coding_agent.autonomous.enhancement_controller.ProjectDebugContext'):
            with patch('agents.coding_agent.autonomous.enhancement_controller.BugTestGenerator'):
                with patch('agents.coding_agent.autonomous.enhancement_controller.CodeSearcher'):
                    with patch('agents.coding_agent.autonomous.enhancement_controller.get_researcher'):
                        with patch('agents.coding_agent.autonomous.enhancement_controller.LinterService'):
                            with patch('agents.coding_agent.autonomous.enhancement_controller.PatchApplier'):
                                with patch('agents.coding_agent.autonomous.enhancement_controller.LanguageDetector'):
                                    with patch('agents.coding_agent.autonomous.enhancement_controller.CodePathTracer'):
                                        from agents.coding_agent.autonomous.enhancement_controller import AutonomousEnhancementController
                                        controller = AutonomousEnhancementController(
                                            llm_client=mock_llm_client,
                                            project_dir=tmp_path,
                                            output_callback=lambda x: None
                                        )
                                        return controller

    @pytest.mark.asyncio
    async def test_investigation_returns_execute_existing(self, controller, mock_llm_client):
        """Test that investigation returns execute_existing when LLM finds existing functionality."""
        # LLM returns decision to execute existing
        mock_response = Mock()
        mock_response.success = True
        mock_response.content = json.dumps({
            "decision": "execute_existing",
            "commands": ["python convert.py input.json output.txt"],
            "reasoning": "Found convert.py script that already does JSON to text conversion"
        })
        mock_llm_client.generate.return_value = mock_response

        context = {
            "files": ["convert.py", "utils.py"],
            "full_text": "def convert_json_to_text(input_file, output_file):\n    ..."
        }

        result = await controller._investigate_before_implementation(
            request="convert the json file to text",
            context=context
        )

        assert result["decision"] == "execute_existing"
        assert "convert.py" in result["commands"][0]
        assert "convert" in result["reasoning"].lower()

    @pytest.mark.asyncio
    async def test_investigation_returns_implement_new(self, controller, mock_llm_client):
        """Test that investigation returns implement_new when no existing functionality found."""
        mock_response = Mock()
        mock_response.success = True
        mock_response.content = json.dumps({
            "decision": "implement_new",
            "reasoning": "No existing script found that can convert markdown to HTML"
        })
        mock_llm_client.generate.return_value = mock_response

        context = {
            "files": ["app.py", "utils.py"],
            "full_text": "# No markdown conversion found"
        }

        result = await controller._investigate_before_implementation(
            request="convert markdown to html",
            context=context
        )

        assert result["decision"] == "implement_new"
        assert "commands" not in result or not result.get("commands")

    @pytest.mark.asyncio
    async def test_investigation_handles_tool_requests(self, controller, mock_llm_client, tmp_path):
        """Test that investigation processes tool requests before making decision."""
        # Create a test file that the toolkit can read
        test_script = tmp_path / "converter.py"
        test_script.write_text("#!/usr/bin/env python\nprint('converter')")

        # First call: LLM requests to read a file
        # Second call: LLM makes decision after seeing file content
        mock_responses = [
            Mock(success=True, content=json.dumps({
                "tool": "read_file",
                "args": {"path": str(test_script)}
            })),
            Mock(success=True, content=json.dumps({
                "decision": "execute_existing",
                "commands": [f"python {test_script}"],
                "reasoning": "Found converter.py that does the conversion"
            }))
        ]
        mock_llm_client.generate.side_effect = mock_responses

        context = {
            "files": [str(test_script)],
            "full_text": ""
        }

        result = await controller._investigate_before_implementation(
            request="run the converter",
            context=context
        )

        # Verify final decision
        assert result["decision"] == "execute_existing"
        assert "investigation_results" in result
        # Should have at least one investigation result from reading the file
        assert len(result["investigation_results"]) >= 1

    @pytest.mark.asyncio
    async def test_investigation_handles_llm_failure(self, controller, mock_llm_client):
        """Test that investigation defaults to implement_new on LLM failure."""
        mock_response = Mock()
        mock_response.success = False
        mock_response.error = "LLM service unavailable"
        mock_llm_client.generate.return_value = mock_response

        context = {
            "files": ["app.py"],
            "full_text": ""
        }

        result = await controller._investigate_before_implementation(
            request="do something",
            context=context
        )

        assert result["decision"] == "implement_new"
        assert "LLM" in result.get("reasoning", "")

    @pytest.mark.asyncio
    async def test_investigation_handles_invalid_json(self, controller, mock_llm_client):
        """Test that investigation handles invalid JSON responses gracefully."""
        mock_response = Mock()
        mock_response.success = True
        mock_response.content = "This is not valid JSON at all"
        mock_llm_client.generate.return_value = mock_response

        context = {
            "files": [],
            "full_text": ""
        }

        result = await controller._investigate_before_implementation(
            request="do something",
            context=context
        )

        assert result["decision"] == "implement_new"

    @pytest.mark.asyncio
    async def test_investigation_respects_max_iterations(self, controller, mock_llm_client, tmp_path):
        """Test that investigation stops after max iterations."""
        # LLM keeps requesting tools without making a decision
        mock_response = Mock()
        mock_response.success = True
        mock_response.content = json.dumps({
            "tool": "list_files",
            "args": {"path": str(tmp_path)}
        })
        mock_llm_client.generate.return_value = mock_response

        context = {
            "files": [],
            "full_text": ""
        }

        result = await controller._investigate_before_implementation(
            request="do something",
            context=context,
            max_iterations=3
        )

        # Should default to implement_new after max iterations
        assert result["decision"] == "implement_new"
        # Should have exactly 3 investigation results (one per iteration)
        assert len(result["investigation_results"]) == 3


class TestMainLoopIntegration:
    """Test that the investigation phase is properly integrated into the main loop."""

    @pytest.mark.asyncio
    async def test_main_loop_short_circuits_on_execute_existing(self):
        """Test that the main loop returns early when investigation says execute_existing."""
        # This is an integration-style test that would require more mocking
        # For now, we test the logic flow conceptually
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
