"""One event loop for every test that generates embeddings.

WHY. The embedding HTTP client is created lazily and stays bound to the loop that first used it.
`asyncio.run()` creates and CLOSES a loop per call, so the second test to embed gets a client whose
loop is gone: `add_chunks` fails, nothing is indexed, and the assertions fail for a reason that has
nothing to do with the code under test.

It is worse than a nuisance. A test asserting "no new vectors were added" PASSES when embedding is
dead — silently, for the wrong reason. Sharing one loop keeps the client alive so those tests
discriminate. Import `run` instead of calling `asyncio.run` in any test that indexes documents.
"""
import asyncio

_LOOP = None


def run(coro):
    """Run `coro` on the shared session loop."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)
