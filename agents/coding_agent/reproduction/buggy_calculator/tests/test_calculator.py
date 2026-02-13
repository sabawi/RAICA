"""
Calculator Tests
================

Tests for the Calculator class.
The divide tests will FAIL due to the bug.
"""

import pytest
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from calculator import Calculator


class TestCalculatorBasic:
    """Test basic calculator operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.calc = Calculator(precision=2)

    def test_add_positive(self):
        """Test adding positive numbers."""
        assert self.calc.add(2, 3) == 5
        assert self.calc.add(10, 20) == 30

    def test_add_negative(self):
        """Test adding negative numbers."""
        assert self.calc.add(-2, -3) == -5
        assert self.calc.add(-10, 5) == -5

    def test_subtract(self):
        """Test subtraction."""
        assert self.calc.subtract(10, 3) == 7
        assert self.calc.subtract(5, 10) == -5

    def test_multiply(self):
        """Test multiplication."""
        assert self.calc.multiply(3, 4) == 12
        assert self.calc.multiply(-3, 4) == -12

    def test_divide_basic(self):
        """Test basic division - THIS WILL FAIL DUE TO BUG."""
        # 10 / 2 should equal 5, but buggy code returns 10 * 2 = 20
        result = self.calc.divide(10, 2)
        assert result == 5, f"Expected 5, got {result}"

    def test_divide_decimal(self):
        """Test division with decimals - THIS WILL FAIL DUE TO BUG."""
        # 7 / 2 should equal 3.5, but buggy code returns 7 * 2 = 14
        result = self.calc.divide(7, 2)
        assert result == 3.5, f"Expected 3.5, got {result}"

    def test_divide_by_zero(self):
        """Test division by zero raises error."""
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            self.calc.divide(10, 0)

    def test_history_tracking(self):
        """Test that operations are tracked in history."""
        self.calc.add(1, 2)
        self.calc.multiply(3, 4)
        history = self.calc.get_history()
        assert len(history) == 2
        assert history[0][0] == 'add'
        assert history[1][0] == 'multiply'

    def test_precision(self):
        """Test decimal precision."""
        calc = Calculator(precision=4)
        result = calc.add(1.23456, 2.34567)
        assert result == 3.5802  # Rounded to 4 decimal places
