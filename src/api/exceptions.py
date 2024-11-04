class APIError(Exception):
    """Custom exception for API-related errors"""
    pass

class RateLimitError(APIError):
    """Raised when rate limits are exceeded"""
    pass

class ContextError(APIError):
    """Raised when there are issues with context management"""
    pass