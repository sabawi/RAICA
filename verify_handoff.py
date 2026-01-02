
from dataclasses import dataclass
from typing import List

@dataclass
class Result:
    generated_files: List[str]

# Test Case 1: Legacy flag
r1 = Result(generated_files=["some_file.txt", "__USE_CODE_GEN_PIPELINE__"])
if any(f.startswith("__CODE_GEN__") or f == "__USE_CODE_GEN_PIPELINE__" for f in r1.generated_files):
    print("Test 1 Passed: Detected legacy flag")
else:
    print("Test 1 FAILED")

# Test Case 2: New flag from Orchestrator
r2 = Result(generated_files=["__CODE_GEN__Create App", "log.txt"])
if any(f.startswith("__CODE_GEN__") or f == "__USE_CODE_GEN_PIPELINE__" for f in r2.generated_files):
    print("Test 2 Passed: Detected orchestrator flag")
else:
    print("Test 2 FAILED")

# Test Case 3: No flag
r3 = Result(generated_files=["just_a_file.txt"])
if not any(f.startswith("__CODE_GEN__") or f == "__USE_CODE_GEN_PIPELINE__" for f in r3.generated_files):
    print("Test 3 Passed: Correctly ignored normal files")
else:
    print("Test 3 FAILED")
