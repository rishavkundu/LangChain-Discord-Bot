# api_client.py
import aiohttp
import logging
import json
import os
import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from config import OPENAI_API_KEY, system_prompt, MAX_CONTEXT_SIZE, CONTEXT_DECAY_HOURS
from user_notes import UserNotesManager  # Import UserNotesManager

logger = logging.getLogger(__name__)

# Global conversation cache
conversation_cache = {}
cache_lock = asyncio.Lock()

# Initialize UserNotesManager
notes_manager = UserNotesManager()

class ConversationManager:
    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self.context = deque(maxlen=MAX_CONTEXT_SIZE)
        self.last_save = datetime.now()

    def add_message(self, message: Dict[str, str]) -> None:
        self.context.append({
            "content": message["content"],
            "timestamp": datetime.now()
        })

    def get_relevant_context(self) -> List[Dict[str, Any]]:
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
                            conversation_cache[channel_id].add_message({
                                "content": msg["content"],
                                "timestamp": datetime.fromisoformat(msg["timestamp"])
                            })
                except Exception as e:
                    logger.error(f"Error loading context file: {str(e)}")
        
        if new_message:
            conversation_cache[channel_id].add_message(new_message)
    
    manager = conversation_cache[channel_id]
    return manager.get_relevant_context()

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

async def fetch_completion_with_hermes(
    prompt: str,
    channel_id: str,
    user_id: str,  # Add user_id parameter
    max_tokens: Optional[int] = None
) -> Optional[str]:
    """Fetches completion from the API with improved error handling"""
    try:
        logger.info(f"Fetching completion for prompt: {prompt} in channel: {channel_id}")
        
        # Get conversation context
        context = await manage_context(channel_id)
        
        # Get user notes
        user_notes = notes_manager.get_user_notes(user_id)
        logger.debug(f"Retrieved user notes for user {user_id}: {user_notes}")
        
        # Construct user notes context
        notes_context = ""
        if user_notes:
            notes_context = "Previous notes about this user:\n" + "\n".join(
                [f"- {note['content']}" for note in user_notes[-5:]]  # Last 5 notes
            ) + "\n"
            logger.debug(f"Constructed notes context for user {user_id}: {notes_context}")
        
        # Combine system prompt with user notes
        enhanced_system_prompt = f"{system_prompt}\n\n{notes_context}"
        
        messages = [{"role": "system", "content": enhanced_system_prompt}]
        for msg in context:
            messages.append({"role": "user", "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})

        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            }
            
            data = {
                "model": "nousresearch/hermes-3-llama-3.1-405b:free",
                "messages": messages,
                "max_tokens": max_tokens or 200,
                "temperature": 0.9,
                "top_p": 0.9,
                "frequency_penalty": 0.8,
                "presence_penalty": 0.6
            }

            max_retries = 3
            retry_delay = 1.0

            for attempt in range(max_retries):
                try:
                    async with session.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=data,
                        timeout=30
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            ai_response = result['choices'][0]['message']['content'].strip()
                            
                            # Add response to context
                            await manage_context(channel_id, {
                                "role": "assistant",
                                "content": ai_response
                            })
                            
                            return ai_response
                        else:
                            error_text = await response.text()
                            logger.error(f"API Error {response.status}: {error_text}")
                            
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay * (attempt + 1))
                            else:
                                return None
                                
                except Exception as e:
                    logger.error(f"Request attempt {attempt + 1} failed: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay * (attempt + 1))
                    else:
                        raise

    except Exception as e:
        logger.error(f"Error in fetch_completion_with_hermes: {str(e)}")
        return None