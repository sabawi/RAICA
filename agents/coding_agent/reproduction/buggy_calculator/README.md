# Buggy Calculator Test Project

This is a test project for validating RAICA's autonomous debug capabilities.

## Structure

- `calculator.py` - Calculator class with basic arithmetic operations
- `data_processor.py` - DataProcessor that uses Calculator for data transformations
- `tests/` - Pytest test cases

## The Bug

The `Calculator.divide()` method has a bug - it multiplies instead of dividing.

This causes failures in:
- `test_calculator.py::test_divide_basic`
- `test_calculator.py::test_divide_decimal`
- `test_data_processor.py::test_normalize_basic`
- `test_data_processor.py::test_normalize_decimal`
- `test_data_processor.py::test_compute_average`

## Running Tests

```bash
cd buggy_calculator
python -m pytest tests/ -v
```

## Expected RAICA Behavior

RAICA should:
1. Identify the divide bug through test failures
2. Locate the bug in `calculator.py` line ~44
3. Generate a patch changing `*` to `/`
4. Verify all tests pass after the fix
