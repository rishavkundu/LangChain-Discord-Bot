# api_client.py
import aiohttp
import logging
import json
import os
import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from src.config import OPENAI_API_KEY, system_prompt, MAX_CONTEXT_SIZE, CONTEXT_DECAY_HOURS
from src.user_notes import UserNotesManager
from src.api.exceptions import APIError, RateLimitError, ContextError
from src.api.utils import RateLimiter, MetricsCollector, retry_with_exponential_backoff
import re
from src.emotional_state import EmotionalStateManager

logger = logging.getLogger(__name__)

# Global conversation cache
conversation_cache = {}
cache_lock = asyncio.Lock()

# Initialize UserNotesManager
notes_manager = UserNotesManager()

rate_limiter = RateLimiter()
metrics = MetricsCollector()

class ConversationManager:
    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self.context = deque(maxlen=MAX_CONTEXT_SIZE)
        self.last_save = datetime.now()
        self._lock = asyncio.Lock()
        self._cache = {}

    async def add_message(self, message: Dict[str, str]) -> None:
        async with self._lock:
            self.context.append({
                "content": message["content"],
                "timestamp": datetime.now()
            })
            self._cache.clear()
            self.last_save = datetime.now()

    async def get_relevant_context(self, cache_key: str = None) -> List[Dict[str, Any]]:
        if cache_key and cache_key in self._cache:
            return self._cache[cache_key]

        async with self._lock:
            current_time = datetime.now()
            cutoff_time = current_time - timedelta(hours=CONTEXT_DECAY_HOURS)
            
            relevant_messages = []
            for msg in self.context:
                if msg["timestamp"] < cutoff_time:
                    continue
                    
                age = current_time - msg["timestamp"]
                relevance = 1.0 - (age.total_seconds() / (CONTEXT_DECAY_HOURS * 3600))
                relevant_messages.append({
                    "content": msg["content"],
                    "relevance": max(0.1, relevance)
                })
            
            if cache_key:
                self._cache[cache_key] = relevant_messages
            return relevant_messages

async def manage_context(channel_id: str, new_message: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Maintains compatibility with existing bot.py while using improved context management"""
    context_file = f"context_{channel_id}.json"
    
    async with cache_lock:
        if channel_id not in conversation_cache:
            conversation_cache[channel_id] = ConversationManager(channel_id)
            if os.path.exists(context_file):
                try:
                    with open(context_file, 'r') as f:
                        data = json.load(f)
                        for msg in data[-MAX_CONTEXT_SIZE:]:
                            await conversation_cache[channel_id].add_message({
                                "content": msg["content"],
                                "timestamp": datetime.fromisoformat(msg["timestamp"])
                            })
                except Exception as e:
                    logger.error(f"Error loading context file: {str(e)}")
        
        if new_message:
            await conversation_cache[channel_id].add_message(new_message)
    
    manager = conversation_cache[channel_id]
    return await manager.get_relevant_context()

async def save_context_periodically():
    """Periodically saves context to disk"""
    while True:
        try:
            await asyncio.sleep(300)  # Save every 5 minutes
            async with cache_lock:
                for channel_id, manager in conversation_cache.items():
                    context_file = f"context_{channel_id}.json"
                    try:
                        with open(context_file, 'w') as f:
                            json.dump([{
                                "content": msg["content"],
                                "timestamp": msg["timestamp"].isoformat()
                            } for msg in manager.context], f, indent=2)
                    except Exception as e:
                        logger.error(f"Error saving context file: {str(e)}")
        except Exception as e:
            logger.error(f"Error in save_context_periodically: {str(e)}")
            await asyncio.sleep(60)  # Wait a minute before retrying

async def classify_query_length(prompt: str) -> Tuple[int, str]:
    """Classifies the query to determine appropriate response length"""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            }
            
            classification_prompt = {
                "messages": [{
                    "role": "system",
                    "content": "Classify the following query into one of these response types:\n"
                              "1. BRIEF (max 30 tokens) - For simple acknowledgments, greetings\n"
                              "2. SHORT (max 60 tokens) - For quick answers, confirmations\n"
                              "3. MEDIUM (max 150 tokens) - For explanations, clarifications\n"
                              "4. DETAILED (max 300 tokens) - For technical explanations\n"
                              "5. COMPREHENSIVE (max 500 tokens) - For complex topics, tutorials\n"
                              "6. EXTENSIVE (max 800 tokens) - For in-depth analysis\n"
                              "Respond with just the category name in caps."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                "model": "gpt-4o-mini",
                "max_tokens": 10,
                "temperature": 0.3
            }

            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=classification_prompt
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    category = result['choices'][0]['message']['content'].strip()
                    
                    # Map categories to token lengths
                    token_map = {
                        "BRIEF": 25,
                        "SHORT": 50,
                        "MEDIUM": 120,
                        "DETAILED": 250,
                        "COMPREHENSIVE": 400,
                        "EXTENSIVE": 600
                    }
                    
                    return token_map.get(category, 300), category
                
        return 300, "DETAILED"  # Default fallback
    except Exception as e:
        logger.error(f"Error in query classification: {str(e)}")
        return 300, "DETAILED"  # Default fallback

async def fetch_completion_with_hermes(
    prompt: str,
    channel_id: str,
    user_id: str,
    max_tokens: Optional[int] = None
) -> Optional[str]:
    start_time = datetime.now()
    try:
        await rate_limiter.acquire()
        
        tokens, category = await retry_with_exponential_backoff(
            classify_query_length, prompt)
        
        final_max_tokens = max_tokens or tokens
        context = await manage_context(channel_id)
        user_notes = notes_manager.get_user_notes(user_id)
        
        notes_context = ""
        if user_notes:
            notes_context = "Previous notes about this user:\n" + "\n".join(
                [f"- {note['content']}" for note in user_notes[-5:]]
            ) + "\n"
        
        enhanced_system_prompt = f"{system_prompt}\n\n{notes_context}"
        messages = [{"role": "system", "content": enhanced_system_prompt}]
        
        for msg in context:
            messages.append({"role": "user", "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})

        # Initialize emotional state manager if not exists
        if not hasattr(fetch_completion_with_hermes, 'emotional_state_manager'):
            fetch_completion_with_hermes.emotional_state_manager = EmotionalStateManager()

        # Update emotional state
        await fetch_completion_with_hermes.emotional_state_manager.analyze_message(
            prompt, user_id, context
        )

        # Get emotionally-aware parameters
        emotional_params = fetch_completion_with_hermes.emotional_state_manager.get_response_parameters(user_id)

        # Merge with base parameters
        temperature = emotional_params["temperature"]
        presence_penalty = emotional_params["presence_penalty"]
        frequency_penalty = emotional_params["frequency_penalty"]
        top_p = emotional_params["top_p"]

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(
            total=60,      # Total timeout
            connect=10,    # Connection timeout
            sock_read=30,  # Socket read timeout
            sock_connect=10  # Socket connect timeout
        )) as session:
            response = await retry_with_exponential_backoff(
                lambda: session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {OPENAI_API_KEY}"
                    },
                    json={
                        "model": "nousresearch/hermes-3-llama-3.1-405b",
                        "messages": messages,
                        "max_tokens": final_max_tokens,
                        "temperature": temperature,
                        "top_p": 0.9,
                        "frequency_penalty": 0.8,
                        "repetition_penalty": 1.15,
                        "presence_penalty": 0.6,
                        "stop": ["<end>", "\n\n"],
                        "suffix": "<end>"
                    }
                )
            )
            
            if response.status == 200:
                result = await response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    ai_response = result['choices'][0]['message']['content'].strip()
                    
                    # Validate response has proper spacing
                    if len(ai_response) > 0:
                        # Apply comprehensive spacing fixes
                        ai_response = fix_spacing(ai_response)
                        
                        # Verify minimum spacing ratio (as a safety check)
                        space_ratio = ai_response.count(' ') / len(ai_response)
                        if space_ratio < 0.1:  # Typical English text has ~15-20% spaces
                            logger.warning(f"Response has unusually low space ratio: {space_ratio}")
                            ai_response = ' '.join(ai_response.split())  # Force normalize spacing
                    
                    await manage_context(channel_id, {
                        "role": "assistant",
                        "content": ai_response
                    })
                    
                    duration = (datetime.now() - start_time).total_seconds()
                    await metrics.record_response_time(duration)
                    
                    return ai_response
                
            error_text = await response.text()
            logger.error(f"API Error {response.status}: {error_text}")
            await metrics.record_error(f"APIError_{response.status}")
            return None
            
    except asyncio.TimeoutError as e:
        await metrics.record_error("TimeoutError")
        logger.error("Request timed out", exc_info=True)
        return None
    except Exception as e:
        await metrics.record_error(type(e).__name__)
        logger.error(f"Error in fetch_completion: {str(e)}", exc_info=True)
        logger.error(f"Error type: {type(e).__name__}")
        if isinstance(e, aiohttp.ClientError):
            logger.error("Network-related error occurred", exc_info=True)
        return None

def fix_spacing(text: str) -> str:
    # Fix spaces after punctuation only
    text = re.sub(r'([.,!?])([^\s])', r'\1 \2', text)
    
    # Fix spaces around apostrophes
    text = re.sub(r'(\w)\'(\w)', r"\1'\2", text)
    
    # Fix multiple spaces
    text = re.sub(r'\s{2,}', ' ', text)
    
    return text.strip()