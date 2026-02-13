import unittest
from agents.coding_agent.services.context_manager import ContextManager, ContextPriority

class TestContextManager(unittest.TestCase):
    def setUp(self):
        # Initialize with enough tokens for basic tests
        self.cm = ContextManager(max_tokens=100)

    def test_priority_sorting(self):
        """Test that items are sorted by priority (lower number first)."""
        self.cm.add_context_item(
            type="low_prio",
            content="Low Priority",
            priority=ContextPriority.LOW_PRIORITY
        )
        self.cm.add_context_item(
            type="high_prio",
            content="Critical Error",
            priority=ContextPriority.CRITICAL_ERROR
        )
        
        # In compilation, Critical Error should come first
        compiled = self.cm.compile_context()
        self.assertTrue(compiled.startswith("Critical Error"))
        self.assertTrue("Low Priority" in compiled)

    def test_token_budget_truncation(self):
        """Test that lower priority items are dropped when budget is exceeded."""
        # Use a small budget
        small_cm = ContextManager(max_tokens=10)
        
        # High priority item (fits) "High" ~ 1 token
        small_cm.add_context_item(
            type="high",
            content="High",
            priority=ContextPriority.CRITICAL_ERROR
        )
        
        # Low priority item (would exceed if both added)
        # "This is a very long string that will definitely exceed the small token budget we set"
        long_content = "A" * 50 # ~12 tokens
        small_cm.add_context_item(
            type="low",
            content=long_content,
            priority=ContextPriority.LOW_PRIORITY
        )
        
        compiled = small_cm.compile_context()
        
        # Should contain High but NOT the long content
        self.assertIn("High", compiled)
        self.assertNotIn(long_content, compiled)

    def test_clear(self):
        """Test clearing the context."""
        self.cm.add_context_item("test", "content", ContextPriority.LOW_PRIORITY)
        self.cm.clear()
        self.assertEqual(len(self.cm.items), 0)
        self.assertEqual(self.cm.budget.current_tokens, 0)

    def test_structured_context(self):
        """Test getting structured context (list of dicts)."""
        self.cm.add_context_item(
            type="user",
            content="Do this",
            priority=ContextPriority.USER_REQUEST
        )
        self.cm.add_context_item(
            type="system",
            content="System instruction",
            priority=ContextPriority.SYSTEM_INSTRUCTION
        )
        
        structured = self.cm.get_structured_context()
        
        self.assertEqual(len(structured), 2)
        # Check order (USER=1, SYSTEM=2)
        self.assertEqual(structured[0]['role'], 'user')
        self.assertEqual(structured[0]['content'], 'Do this')
        self.assertEqual(structured[1]['role'], 'system')

if __name__ == '__main__':
    unittest.main()
