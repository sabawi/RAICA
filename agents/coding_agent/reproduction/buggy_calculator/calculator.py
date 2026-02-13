"""
Calculator Module
=================

Provides basic arithmetic operations.
Used by DataProcessor for data transformations.
"""


class Calculator:
    """A simple calculator with basic operations."""

    def __init__(self, precision: int = 2):
        """Initialize calculator with decimal precision."""
        self.precision = precision
        self._history = []

    def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        result = round(a + b, self.precision)
        self._history.append(('add', a, b, result))
        return result

    def subtract(self, a: float, b: float) -> float:
        """Subtract b from a."""
        result = round(a - b, self.precision)
        self._history.append(('subtract', a, b, result))
        return result

    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers."""
        result = round(a * b, self.precision)
        self._history.append(('multiply', a, b, result))
        return result

    def divide(self, a: float, b: float) -> float:
        """Divide a by b.

        BUG: This actually multiplies instead of dividing!
        """
        if b == 0:
            raise ValueError("Cannot divide by zero")
        # BUG: Wrong operator - should be / not *
        result = round(a / b, self.precision)
        self._history.append(('divide', a, b, result))
        return result

    def get_history(self) -> list:
        """Return operation history."""
        return self._history.copy()

    def clear_history(self) -> None:
        """Clear operation history."""
        self._history = []
