from collections import defaultdict, deque
from math import ceil
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Callable


class SlidingWindowRateLimiter:
    """Small, process-local sliding-window limiter for a single API worker."""

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("Rate limits and windows must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> int | None:
        """Record an allowed request, or return whole seconds until retry."""
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.limit:
                return max(1, ceil(requests[0] + self.window_seconds - now))
            requests.append(now)
            return None


class RequestLimits:
    def __init__(
        self,
        session_creations_per_minute: int,
        global_ocr_per_minute: int,
        session_ocr_per_minute: int,
        concurrent_ocr_jobs: int,
    ) -> None:
        if concurrent_ocr_jobs < 1:
            raise ValueError("At least one concurrent OCR job must be allowed.")
        self.session_creations = SlidingWindowRateLimiter(session_creations_per_minute)
        self.global_ocr = SlidingWindowRateLimiter(global_ocr_per_minute)
        self.session_ocr = SlidingWindowRateLimiter(session_ocr_per_minute)
        self._ocr_slots = BoundedSemaphore(concurrent_ocr_jobs)

    def check_session_creation(self) -> int | None:
        return self.session_creations.check("global")

    def check_ocr(self, session_id: str) -> int | None:
        session_retry = self.session_ocr.check(session_id)
        if session_retry is not None:
            return session_retry
        return self.global_ocr.check("global")

    def acquire_ocr_slot(self) -> bool:
        return self._ocr_slots.acquire(blocking=False)

    def release_ocr_slot(self) -> None:
        self._ocr_slots.release()
