import asyncio
from datetime import datetime
import logging
from typing import Callable, Any
import aiohttp

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, requests_per_minute=60):
        self.requests_per_minute = requests_per_minute
        self.requests = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = datetime.now()
            self.requests = [req for req in self.requests 
                           if (now - req).total_seconds() < 60]
            
            if len(self.requests) >= self.requests_per_minute:
                sleep_time = 60 - (now - self.requests[0]).total_seconds()
                await asyncio.sleep(sleep_time)
            
            self.requests.append(now)

class MetricsCollector:
    def __init__(self):
        self.response_times = []
        self.error_counts = {}
        self._lock = asyncio.Lock()

    async def record_response_time(self, duration: float):
        async with self._lock:
            self.response_times.append(duration)
            if len(self.response_times) > 1000:
                self.response_times = self.response_times[-1000:]

    async def record_error(self, error_type: str):
        async with self._lock:
            self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1

async def retry_with_exponential_backoff(func: Callable, *args, max_retries=3, base_delay=1.0) -> Any:
    for attempt in range(max_retries):
        try:
            return await func(*args)
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed with {type(e).__name__}: {str(e)}. Retrying in {delay}s")
            await asyncio.sleep(delay)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {delay}s")
            await asyncio.sleep(delay)