
import pfzy
from pfzy.match import fuzzy_match

content = """
class MyClass:
    def __init__(self):
        self.x = 1

    def old_method(self):
        print("Old")
        return True

    def unrelated(self):
        pass
"""

# Case: LLM provides unindented SEARCH block
search = """def old_method(self):
    print("Old")
    return True"""

# We want to replace it with:
replace = """def new_method(self):
    print("New")
    return False"""

print(f"Original Content:\n{content}")
print("-" * 20)
print(f"Search:\n{search}")
print("-" * 20)

import asyncio

async def run_test():
    matches = await fuzzy_match(search, content)
    print(f"Matches found: {len(matches)}")

    for m in matches:
        print(f"Match Score: {m.score}")
        print(f"Start Index: {m.start_index}, End Index: {m.end_index}")
        print(f"Matched String:\n{content[m.start_index:m.end_index]}")

if __name__ == "__main__":
    asyncio.run(run_test())
