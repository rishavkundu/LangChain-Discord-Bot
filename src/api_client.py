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
from src.prompt_templates import METAPROMPT_TEMPLATES  # Import metaprompt templates
import random

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
        # Deque to store conversation context with a maximum size
        self.context = deque(maxlen=MAX_CONTEXT_SIZE)
        self.last_save = datetime.now()
        self._lock = asyncio.Lock()
        self._cache = {}
        self.user_profiles = {}  # New attribute for user profiles

    async def add_message(self, message: Dict[str, Any]) -> None:
        """Adds a message to the conversation context."""
        async with self._lock:
            self.context.append({
                "content": message["content"],
                "role": message.get("role", "user"),
                "timestamp": datetime.now(),
                "user_id": message.get("user_id")
            })
            self._cache.clear()
            self.last_save = datetime.now()

            # Update user profile if the message is from a user
            if message.get("role") == "user":
                user_id = message.get("user_id")
                if user_id:
                    self.update_user_profile(user_id, message["content"])

    def update_user_profile(self, user_id: str, message_content: str):
        """Updates the user's profile with extracted interests."""
        interests = self.extract_interests(message_content)
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {"interests": set()}
        self.user_profiles[user_id]["interests"].update(interests)

    def extract_interests(self, message_content: str) -> set:
        """Extracts interests from the message content based on keywords."""
        keywords = {'ai', 'music', 'science', 'art', 'technology', 'sports', 'movies', 'gaming'}
        words = set(re.findall(r'\b\w+\b', message_content.lower()))
        return {word for word in words if word in keywords}

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Retrieves the user profile."""
        return self.user_profiles.get(user_id, {})

    async def get_relevant_context(self, cache_key: str = None) -> List[Dict[str, Any]]:
        """Retrieves relevant context messages, considering decay over time."""
        if cache_key and cache_key in self._cache:
            return self._cache[cache_key]

        async with self._lock:
            current_time = datetime.now()
            cutoff_time = current_time - timedelta(hours=CONTEXT_DECAY_HOURS)
            
            relevant_messages = []
            for msg in self.context:
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
                                "role": msg.get("role", "user"),
                                "timestamp": datetime.fromisoformat(msg["timestamp"]),
                                "user_id": msg.get("user_id")
                            })
                except Exception as e:
                    logger.error(f"Error loading context file: {str(e)}")
        
        if new_message:
            await conversation_cache[channel_id].add_message(new_message)
    
    manager = conversation_cache[channel_id]
    return await manager.get_relevant_context()

async def save_context_periodically():
    """Periodically saves context to disk to maintain conversation history."""
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
                                "role": msg["role"],
                                "timestamp": msg["timestamp"].isoformat(),
                                "user_id": msg.get("user_id")
                            } for msg in manager.context], f, indent=2)
                    except Exception as e:
                        logger.error(f"Error saving context file: {str(e)}")
        except Exception as e:
            logger.error(f"Error in save_context_periodically: {str(e)}")
            await asyncio.sleep(60)  # Wait a minute before retrying

async def classify_query_length(prompt: str) -> Tuple[int, str]:
    """Classifies the query to determine appropriate response length."""
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

async def construct_metaprompt(
    user_message: str,
    cleo_last_response: str,
    context: List[Dict[str, Any]],
    user_id: str,
    enhanced_system_prompt: str
) -> List[Dict[str, str]]:
    """
    Constructs a metaprompt that includes Cleo's last response and guides her to produce a coherent follow-up with chain-of-thought reasoning.
    """
    # Choose a random metaprompt template
    metaprompt_template = random.choice(METAPROMPT_TEMPLATES)
    
    # Format the metaprompt with Cleo's last response
    metaprompt = metaprompt_template.format(cleo_last_response=cleo_last_response.strip())
    
    # Include a reminder to avoid redundancy
    metaprompt += "\n\nRemember to provide fresh insights without repeating yourself."
    
    # Build the messages list for the API call
    messages = [{"role": "system", "content": enhanced_system_prompt}]
    
    # Add recent context messages
    for msg in context[-5:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    
    # Add the user's message
    messages.append({"role": "user", "content": user_message})
    
    # Include the chain-of-thought instruction
    chain_of_thought_instruction = """
Think through your response step-by-step before sharing it with the user. Provide a well-reasoned and thoughtful reply.
"""
    # Add Cleo's last response and the metaprompt
    messages.append({"role": "assistant", "content": cleo_last_response})
    messages.append({"role": "system", "content": metaprompt})
    messages.append({"role": "system", "content": chain_of_thought_instruction})
    
    return messages


async def fetch_completion_with_hermes(
    prompt: str,
    channel_id: str,
    user_id: str,
    max_tokens: Optional[int] = None
) -> Optional[str]:
    """
    Fetches a completion from the AI model using metaprompting and emotional state parameters.
    """
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
        
        # Get user profile
        manager = conversation_cache[channel_id]
        user_profile = manager.get_user_profile(user_id)
        interests = ', '.join(user_profile.get('interests', []))
        
        # Include user interests in the system prompt
        enhanced_system_prompt = f"{system_prompt}\n\n{notes_context}"
        if interests:
            enhanced_system_prompt += f"\n\nUser's interests: {interests}"
        
        # Get Cleo's last response from the context
        cleo_last_response = ""
        for msg in reversed(context):
            if msg["role"] == "assistant":
                cleo_last_response = msg["content"]
                break
        
        # Construct the metaprompt messages
        messages = await construct_metaprompt(prompt, cleo_last_response, context, user_id, enhanced_system_prompt)
        
        # Initialize emotional state manager if not exists
        if not hasattr(fetch_completion_with_hermes, 'emotional_state_manager'):
            fetch_completion_with_hermes.emotional_state_manager = EmotionalStateManager()
        
        # Update emotional state
        await fetch_completion_with_hermes.emotional_state_manager.analyze_message(
            prompt, user_id, context
        )
        
        # Get emotionally-aware parameters
        emotional_params = fetch_completion_with_hermes.emotional_state_manager.get_response_parameters(user_id)
        
        # Extract parameters
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
            # Make the API call with the constructed messages and parameters
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
                        "top_p": top_p,
                        "frequency_penalty": frequency_penalty,
                        "repetition_penalty": 1.15,
                        "presence_penalty": presence_penalty,
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
    """Fixes spacing issues in the generated text."""
    # Fix missing spaces between words
    text = re.sub(r'(?<=[a-zA-Z])(?=[A-Z])', ' ', text)
    text = re.sub(r'([.,!?])([^\s])', r'\1 \2', text)
    text = re.sub(r'(\w)([.,!?])(\w)', r'\1\2 \3', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()

