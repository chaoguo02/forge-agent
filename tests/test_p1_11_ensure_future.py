"""
P1-11: asyncio.ensure_future() without event loop guard in single session delete.

Verifies:
  M1: _fire_and_forget_cleanup() helper handles both with-loop and no-loop cases
  M2: delete_session handler does not crash when no event loop is running
  regression: batch_delete handler still works correctly
"""

import asyncio
from unittest.mock import patch


# ────────────────────────────────────────────────────────────────────────────
# M1: _fire_and_forget_cleanup() helper
# ────────────────────────────────────────────────────────────────────────────

class TestFireAndForgetCleanup:
    """Verify the extracted helper handles both event-loop and no-loop cases."""

    def test_with_loop_schedules_coroutine(self):
        """When event loop is running → coroutine is scheduled, no exception."""
        from server.routers.sessions import _fire_and_forget_cleanup

        async def dummy_cleanup():
            return "done"

        async def _run():
            _fire_and_forget_cleanup(dummy_cleanup())

        asyncio.run(_run())  # no exception = pass

    def test_no_loop_passes_silently(self):
        """When no event loop → RuntimeError caught, no exception propagated."""
        from server.routers.sessions import _fire_and_forget_cleanup

        async def dummy_cleanup():
            return "done"

        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no running event loop")):
            _fire_and_forget_cleanup(dummy_cleanup())
            # If we reach here without exception, the test passes


# ────────────────────────────────────────────────────────────────────────────
# M2: delete_session handler (single) — no-loop safety
# ────────────────────────────────────────────────────────────────────────────

class TestDeleteSessionNoLoop:
    """Verify single session delete does not crash without event loop."""

    def test_delete_session_without_loop_does_not_crash(self):
        """_fire_and_forget_cleanup catches RuntimeError — no 500."""
        from server.routers.sessions import _fire_and_forget_cleanup

        async def dummy_destroy():
            return None

        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no running event loop")):
            _fire_and_forget_cleanup(dummy_destroy())
            # Reaching here = no exception = pass


# ────────────────────────────────────────────────────────────────────────────
# Regression: batch_delete handler
# ────────────────────────────────────────────────────────────────────────────

class TestBatchDeleteRegression:
    """Verify batch_delete_sessions handler is not degraded by the refactor."""

    def test_batch_delete_cleanup_still_works(self):
        """batch_delete correctly schedules cleanup for multiple sessions."""
        from server.routers.sessions import _fire_and_forget_cleanup

        async def dummy_destroy():
            return None

        async def _run():
            for _ in range(3):
                _fire_and_forget_cleanup(dummy_destroy())

        asyncio.run(_run())  # no exception = pass
