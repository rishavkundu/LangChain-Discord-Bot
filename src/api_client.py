import aiohttp
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from src.config import OPENAI_API_KEY, system_prompt, MAX_CONTEXT_SIZE, CONTEXT_DECAY_HOURS
from src.api.exceptions import APIError, RateLimitError, ContextError
from src.api.utils import RateLimiter, MetricsCollector, retry_with_exponential_backoff
from src.database import DatabaseManager
from src.types import ConversationContextProvider
from src.emotional_state import emotional_state_manager

# Configure logging
logger = logging.getLogger(__name__)

# Global conversation cache and lock
conversation_cache: Dict[str, 'ConversationManager'] = {}
cache_lock = asyncio.Lock()

class ConversationManager(ConversationContextProvider):
    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self._lock = asyncio.Lock()
        self._cache = {}
        self.db = DatabaseManager()
        
    async def initialize(self):
        """Initialize the database."""
        await self.db.init_db()
        
    @classmethod
    async def create(cls, channel_id: str):
        """Factory method to create and initialize a ConversationManager"""
        manager = cls(channel_id)
        await manager.initialize()
        return manager

    async def add_message(self, message: Dict[str, Any]) -> None:
        """Adds a message to the conversation context."""
        async with self._lock:
            await self.db.add_message(self.channel_id, {
                "content": message["content"],
                "role": message.get("role", "user"),
                "timestamp": datetime.now(),
                "user_id": message.get("user_id")
            })
            self._cache.clear()

    async def get_relevant_context(self, cache_key: str = None) -> List[Dict[str, Any]]:
        """Retrieves relevant context messages, considering decay over time."""
        if cache_key and cache_key in self._cache:
            return self._cache[cache_key]

        async with self._lock:
            current_time = datetime.now()
            cutoff_time = current_time - timedelta(hours=CONTEXT_DECAY_HOURS)
            
            # Fetch messages from database
            messages = await self.db.get_context(self.channel_id)
            
            relevant_messages = []
            for msg in messages:
                if msg["timestamp"] < cutoff_time:
                    continue  # Skip messages outside the decay window
                    
                age = current_time - msg["timestamp"]
                relevance = 1.0 - (age.total_seconds() / (CONTEXT_DECAY_HOURS * 3600))
                relevant_messages.append({
                    "content": msg["content"],
                    "role": msg["role"],
                    "relevance": max(0.1, relevance)
                })
            
            if cache_key:
                self._cache[cache_key] = relevant_messages
            return relevant_messages

async def manage_context(channel_id: str, new_message: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Manages the conversation context for each channel."""
    async with cache_lock:
        if channel_id not in conversation_cache:
            conversation_cache[channel_id] = await ConversationManager.create(channel_id)
        
        if new_message:
            await conversation_cache[channel_id].add_message(new_message)
    
    manager = conversation_cache[channel_id]
    return await manager.get_relevant_context()

async def make_api_request(
    session: aiohttp.ClientSession,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.7,
    presence_penalty: float = 0.0,
    frequency_penalty: float = 0.0,
    top_p: float = 1.0
) -> Optional[str]:
    """Makes a request to the OpenAI API."""
    try:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "nousresearch/hermes-3-llama-3.1-405b",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "presence_penalty": presence_penalty,
                "frequency_penalty": frequency_penalty,
                "top_p": top_p,
                "stop": ["<|end|>", "\n\n\n"],  # Add stop sequences
                "stream": False
            }
        ) as response:
            if response.status == 429:
                raise RateLimitError("Rate limit exceeded")
            elif response.status != 200:
                raise APIError(f"API request failed with status {response.status}")
            
            data = await response.json()
            return data["choices"][0]["message"]["content"]
            
    except aiohttp.ClientError as e:
        raise APIError(f"API request failed: {str(e)}")

# Initialize rate limiter and metrics collector
rate_limiter = RateLimiter(requests_per_minute=20)
metrics_collector = MetricsCollector()

async def acquire_rate_limit():
    """Acquire rate limit token."""
    await rate_limiter.acquire()

# Update fetch_completion_with_hermes to use rate limiting
async def fetch_completion_with_hermes(
    prompt: str,
    channel_id: str,
    user_id: str,
    max_tokens: int = 150
) -> Optional[str]:
    """Fetches a completion from the API with rate limiting and error handling."""
    try:
        # Acquire rate limit before making the request
        await acquire_rate_limit()
        
        # Get or create conversation manager
        async with cache_lock:
            if channel_id not in conversation_cache:
                conversation_cache[channel_id] = await ConversationManager.create(channel_id)
            manager = conversation_cache[channel_id]

        context = await manager.get_relevant_context()
        
        # Build the messages array for the API
        messages = [
            {"role": "system", "content": system_prompt},
            *[{"role": msg["role"], "content": msg["content"]} for msg in context],
            {"role": "user", "content": prompt}
        ]

        # Get response parameters from emotional state
        emotional_params = emotional_state_manager.get_response_parameters(user_id)

        async with aiohttp.ClientSession() as session:
            logger.info(f"Making API request with prompt: {prompt[:50]}...")
            response = await make_api_request(
                session, 
                messages, 
                max_tokens,
                temperature=emotional_params["temperature"],
                presence_penalty=emotional_params["presence_penalty"],
                frequency_penalty=emotional_params["frequency_penalty"],
                top_p=emotional_params["top_p"]
            )
            
            if response:
                logger.info("API request successful")
                return response.strip()
            else:
                logger.error("API request returned empty response")
                return None

    except RateLimitError as e:
        logger.error(f"Rate limit exceeded: {str(e)}")
        return None
    except APIError as e:
        logger.error(f"API error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error in fetch_completion: {str(e)}", exc_info=True)
        return None

def format_context_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    formatted_messages = []
    current_topic = []
    
    for msg in messages:
        # Start new topic if significant time gap (> 5 minutes)
        if msg.get('time_gap') and msg['time_gap'] > 300:
            if current_topic:
                formatted_messages.append({
                    "role": "system",
                    "content": "New conversation topic started."
                })
        
        # Format message with proper spacing and punctuation
        content = msg['content'].strip()
        if not content.endswith(('.', '!', '?')):
            content += '.'
            
        formatted_messages.append({
            "role": msg['role'],
            "content": content
        })
    
    return formatted_messages