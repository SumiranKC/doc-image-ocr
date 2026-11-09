import unittest

from app.services.limits import RequestLimits, SlidingWindowRateLimiter


class RequestLimitTests(unittest.TestCase):
    def test_sliding_window_allows_requests_again_after_window(self) -> None:
        now = [100.0]
        limiter = SlidingWindowRateLimiter(2, 10, lambda: now[0])

        self.assertIsNone(limiter.check("session-a"))
        self.assertIsNone(limiter.check("session-a"))
        self.assertEqual(limiter.check("session-a"), 10)
        self.assertIsNone(limiter.check("session-b"))

        now[0] += 10
        self.assertIsNone(limiter.check("session-a"))

    def test_ocr_slots_never_exceed_configured_concurrency(self) -> None:
        limits = RequestLimits(10, 10, 10, 1)

        self.assertTrue(limits.acquire_ocr_slot())
        self.assertFalse(limits.acquire_ocr_slot())
        limits.release_ocr_slot()
        self.assertTrue(limits.acquire_ocr_slot())
        limits.release_ocr_slot()


if __name__ == "__main__":
    unittest.main()
