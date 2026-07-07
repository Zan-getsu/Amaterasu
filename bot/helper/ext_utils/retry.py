"""Phase 2.1 — Retry decorator with exponential backoff.

Provides @retryable decorator for wrapping async functions that may
transiently fail (network errors, 5xx responses, connection drops).

Backoff sequence: 1s, 2s, 4s, 8s, 16s (exponential, base 2).
Default max_retries=5 (so 6 total attempts: 1 initial + 5 retries).
Logs each retry at WARNING level.

Usage:
    from bot.helper.ext_utils.retry import retryable

    @retryable(max_retries=5, base_delay=1, exceptions=(NetworkError, TimeoutError))
    async def download_file(url):
        ...

Do NOT apply to:
    - User cancellation handlers (cancellation should propagate immediately)
    - Functions that mutate state in non-idempotent ways
    - Functions where retrying could cause duplicate side effects
"""

from asyncio import sleep
from functools import wraps
from logging import getLogger

LOGGER = getLogger(__name__)


def retryable(max_retries=5, base_delay=1, exceptions=(Exception,), backoff="exponential"):
    """Decorator that retries a coroutine on failure with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default 5).
        base_delay: Initial delay in seconds (default 1). Exponential
            backoff doubles this each retry: 1, 2, 4, 8, 16.
        exceptions: Tuple of exception types to catch and retry on.
            Other exceptions propagate immediately. Default (Exception,)
            catches everything — narrow this for production code.
        backoff: "exponential" (default) or "linear". Exponential doubles
            the delay each retry; linear adds base_delay each retry.

    Returns:
        Decorated function that retries on failure.

    The final exception (after all retries exhausted) is re-raised.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt >= max_retries:
                        LOGGER.error(
                            f"{func.__name__} failed after {max_retries + 1} "
                            f"attempts: {e}"
                        )
                        raise
                    # Calculate delay
                    if backoff == "exponential":
                        delay = base_delay * (2 ** attempt)
                    else:  # linear
                        delay = base_delay * (attempt + 1)
                    LOGGER.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                        f"after {type(e).__name__}: {e} — retrying in {delay}s"
                    )
                    await sleep(delay)
            # Should not reach here, but just in case
            if last_exception:
                raise last_exception
        return wrapper
    return decorator
