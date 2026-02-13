"""
Data Processor Module
=====================

Uses Calculator for data transformations.
Demonstrates cross-module dependencies.
"""

from calculator import Calculator


class DataProcessor:
    """Process numerical data using calculator operations."""

    def __init__(self):
        self.calc = Calculator(precision=4)
        self.processed_count = 0

    def normalize(self, values: list, factor: float) -> list:
        """Normalize values by dividing each by a factor.

        This uses Calculator.divide() internally.
        """
        if factor == 0:
            raise ValueError("Normalization factor cannot be zero")

        normalized = []
        for val in values:
            # Uses the buggy divide method
            result = self.calc.divide(val, factor)
            normalized.append(result)

        self.processed_count += len(values)
        return normalized

    def scale(self, values: list, factor: float) -> list:
        """Scale values by multiplying each by a factor."""
        scaled = []
        for val in values:
            result = self.calc.multiply(val, factor)
            scaled.append(result)

        self.processed_count += len(values)
        return scaled

    def compute_average(self, values: list) -> float:
        """Compute the average of a list of values."""
        if not values:
            return 0.0

        total = 0.0
        for val in values:
            total = self.calc.add(total, val)

        # Uses the buggy divide method
        return self.calc.divide(total, len(values))

    def get_stats(self) -> dict:
        """Return processing statistics."""
        return {
            'processed_count': self.processed_count,
            'operation_history': self.calc.get_history()
        }
