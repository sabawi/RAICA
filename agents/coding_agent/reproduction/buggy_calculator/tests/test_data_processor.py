"""
Data Processor Tests
====================

Tests for the DataProcessor class.
Tests that use division will FAIL due to the bug in Calculator.
"""

import pytest
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_processor import DataProcessor


class TestDataProcessor:
    """Test data processing operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.processor = DataProcessor()

    def test_scale(self):
        """Test scaling values - should pass."""
        values = [1, 2, 3, 4, 5]
        result = self.processor.scale(values, 2)
        assert result == [2, 4, 6, 8, 10]

    def test_normalize_basic(self):
        """Test normalizing values - THIS WILL FAIL DUE TO BUG."""
        # [10, 20, 30] / 10 should be [1, 2, 3]
        # But buggy code multiplies: [10, 20, 30] * 10 = [100, 200, 300]
        values = [10, 20, 30]
        result = self.processor.normalize(values, 10)
        assert result == [1.0, 2.0, 3.0], f"Expected [1.0, 2.0, 3.0], got {result}"

    def test_normalize_decimal(self):
        """Test normalizing with decimal factor - THIS WILL FAIL."""
        values = [5, 10, 15]
        result = self.processor.normalize(values, 5)
        assert result == [1.0, 2.0, 3.0], f"Expected [1.0, 2.0, 3.0], got {result}"

    def test_normalize_zero_factor(self):
        """Test normalizing with zero factor raises error."""
        with pytest.raises(ValueError, match="Normalization factor cannot be zero"):
            self.processor.normalize([1, 2, 3], 0)

    def test_compute_average(self):
        """Test computing average - THIS WILL FAIL DUE TO BUG."""
        # Average of [10, 20, 30] = 60 / 3 = 20
        # But buggy code does: 60 * 3 = 180
        values = [10, 20, 30]
        result = self.processor.compute_average(values)
        assert result == 20.0, f"Expected 20.0, got {result}"

    def test_compute_average_empty(self):
        """Test computing average of empty list."""
        result = self.processor.compute_average([])
        assert result == 0.0

    def test_processed_count(self):
        """Test that processed count is tracked."""
        self.processor.scale([1, 2, 3], 2)
        self.processor.normalize([4, 5, 6], 2)
        stats = self.processor.get_stats()
        assert stats['processed_count'] == 6
