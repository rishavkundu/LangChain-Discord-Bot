import time
import functools
import logging
from typing import Callable, Any

logger = logging.getLogger('timing')

def log_timing(name: str = None):
    def decorator(func: Callable) -> Callable:
        # Track if we're already timing this function
        func._is_being_timed = False
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Prevent recursive timing
            if getattr(wrapper, '_is_being_timed', False):
                return await func(*args, **kwargs)
                
            wrapper._is_being_timed = True
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                operation = name or func.__name__
                logger.info(f"⏱️ {operation} completed in {elapsed_ms:.2f}ms")
                return result
            except Exception as e:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                operation = name or func.__name__
                logger.error(f"❌ {operation} failed after {elapsed_ms:.2f}ms: {str(e)}")
                raise
            finally:
                wrapper._is_being_timed = False
        return wrapper
    return decorator 