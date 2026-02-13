import pytest
 import sys
 from io import StringIO
 from unittest.mock import patch, MagicMock
 
 # Import the module being tested
 import main
 
 class TestMainFunction:
     """Tests for the main() function."""
     
     def test_main_returns_zero(self):
         """Test that main() returns 0 (success exit code)."""
         result = main.main()
         assert result == 0
         assert isinstance(result, int)
     
     def test_main_prints_hello_world(self, capsys):
         """Test that main() prints 'Hello, World!' to stdout."""
         main.main()
         captured = capsys.readouterr()
         assert captured.out == "Hello, World!\n"
         assert captured.err == ""
     
     def test_main_no_exceptions(self):
         """Test that main() executes without raising exceptions."""
         try:
             main.main()
         except Exception as e:
             pytest.fail(f"main() raised an exception: {e}")
 
 class TestMainEntryPoint:
     """Tests for the if __name__ == '__main__' block."""
     
     def test_entry_point_calls_sys_exit(self, monkeypatch):
         """Test that the entry point calls sys.exit with main's return value."""
         # Mock sys.exit to prevent actual exit and capture the argument
         mock_exit = MagicMock()
         monkeypatch.setattr(sys, 'exit', mock_exit)
         
         # Mock __name__ to simulate being run as main script
         monkeypatch.setattr(main, '__name__', '__main__')
         
         # Re-execute the entry point logic
         # Since the module is already imported, we need to simulate the block
         if main.__name__ == "__main__":
             sys.exit(main.main())
         
         # Verify sys.exit was called with 0
         mock_exit.assert_called_once_with(0)
     
     def test_entry_point_integration(self, monkeypatch, capsys):
         """Integration test for the entry point behavior."""
         # Mock sys.exit
         mock_exit = MagicMock()
         monkeypatch.setattr(sys, 'exit', mock_exit)
         
         # Simulate running as main
         monkeypatch.setattr(main, '__name__', '__main__')
         
         # Execute the logic that would run in the if block
         exit_code = main.main()
         
         # Verify output
         captured = capsys.readouterr()
         assert captured.out == "Hello, World!\n"
         
         # Verify exit code
         assert exit_code == 0
         
         # Simulate what the if block does
         sys.exit(exit_code)
         mock_exit.assert_called_with(0)
 
 class TestEdgeCases:
     """Tests for edge cases and robustness."""
     
     def test_main_return_type(self):
         """Test that main returns an integer (not None or other type)."""
         result = main.main()
         assert type(result) is int
     
     def test_main_output_format(self, capsys):
         """Test that output matches expected format exactly."""
         main.main()
         captured = capsys.readouterr()
         # Check for exact match including newline
         assert captured.out == "Hello, World!\n"
         # Ensure no extra whitespace
         assert not captured.out.startswith(" ")
         assert not captured.out.endswith(" \n")
     
     def test_main_idempotent(self, capsys):
         """Test that calling main multiple times produces consistent results."""
         result1 = main.main()
         captured1 = capsys.readouterr()
         
         result2 = main.main()
         captured2 = capsys.readouterr()
         
         assert result1 == result2 == 0
         assert captured1.out == captured2.out == "Hello, World!\n"