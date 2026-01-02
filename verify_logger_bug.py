
import logging
import sys
from agents.common.agent_utils import get_patched_logger

# Create a logger
logger = logging.getLogger("test_logger")
logger.addHandler(logging.StreamHandler(sys.stdout))

# Call the function
result = get_patched_logger(logger)

# Check result
print(f"Result type: {type(result)}")
if result is None:
    print("BUG VERIFIED: get_patched_logger returned None")
    sys.exit(1)
else:
    print("BUG NOT REPRODUCED: get_patched_logger returned a value")
    sys.exit(0)
