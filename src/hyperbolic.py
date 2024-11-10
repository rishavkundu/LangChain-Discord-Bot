import aiohttp
import logging
import json
from typing import Optional, Dict, Any, List
from src.thought_chain import thought_chain_manager
from src.config import HYPERBOLIC_API_KEY
from src.api.exceptions import APIError, RateLimitError
import time
import random

# Configure logging
logger = logging.getLogger(__name__)

# Add at the top with other constants
FOLLOW_UP_SYSTEM_PROMPT = """you are cleo, a casual and engaging AI assistant. when continuing a conversation:
- maintain a natural flow
- reference previous context
- use casual lowercase style with emojis 😊
- ask relevant follow-up questions
- show genuine interest in the topic
- keep responses concise but engaging
"""

async def make_hyperbolic_request(
    session: aiohttp.ClientSession,
    messages: List[Dict[str, str]],
    max_tokens: int = 500,
    temperature: float = 0.1,
    presence_penalty: float = 0.0,
    frequency_penalty: float = 0.0,
    top_p: float = 0.9
) -> Optional[str]:
    """Makes a request to the Hyperbolic API using Meta-Llama-3.1."""
    try:
        logger.info("=== Hyperbolic API Request ===")
        logger.info(f"🔍 Max tokens: {max_tokens}")
        logger.info(f"🌡️ Temperature: {temperature}")
        logger.debug(f"📝 Messages: {json.dumps(messages, indent=2)}")
        
        request_start_time = time.time()
        async with session.post(
            "https://api.hyperbolic.xyz/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {HYPERBOLIC_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "meta-llama/Meta-Llama-3.1-70B-Instruct",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "presence_penalty": presence_penalty,
                "frequency_penalty": frequency_penalty,
                "top_p": top_p,
                "stream": False
            }
        ) as response:
            request_duration = (time.time() - request_start_time) * 1000
            logger.info(f"⏱️ API request took {request_duration:.2f}ms")
            
            if response.status == 429:
                logger.error("=== Rate Limit Error ===")
                logger.error("❌ Hyperbolic API rate limit exceeded")
                raise RateLimitError("Rate limit exceeded")
            elif response.status != 200:
                logger.error(f"=== API Error {response.status} ===")
                logger.error(f"❌ Hyperbolic API request failed")
                raise APIError(f"API request failed with status {response.status}")
            
            data = await response.json()
            content = data["choices"][0]["message"]["content"]
            logger.info("=== API Response ===")
            logger.info(f"📊 Response length: {len(content)} characters")
            logger.debug(f"📑 First 100 chars: {content[:100]}...")
            return content
            
    except aiohttp.ClientError as e:
        logger.error("=== Network Error ===")
        logger.error(f"❌ Error type: {type(e).__name__}")
        logger.error(f"❌ Error message: {str(e)}")
        raise APIError(f"API request failed: {str(e)}")

async def get_hyperbolic_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 500,
    channel_id: str = None
) -> Optional[Dict[str, str]]:
    """Gets a completion from Hyperbolic API with multiple follow-ups."""
    try:
        logger.info("=== Hyperbolic Completion Request ===")
        logger.info(f"🔍 Prompt: {prompt[:50]}...")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            initial_response = await make_hyperbolic_request(
                session,
                messages,
                max_tokens=max_tokens
            )
            
            if initial_response:
                total_duration = (time.time() - start_time) * 1000
                logger.info("=== Completion Success ===")
                logger.info(f"⏱️ Total completion time: {total_duration:.2f}ms")
                
                response_data = {"initial_response": initial_response.strip()}
                
                # Generate follow-ups with 85% chance
                if channel_id and random.random() < 0.85:
                    try:
                        await thought_chain_manager.update_chain(channel_id, initial_response)
                        
                        # Generate first follow-up
                        follow_up_1 = await generate_follow_up(
                            session, 
                            initial_response, 
                            channel_id, 
                            max_tokens,
                            "first"
                        )
                        if follow_up_1:
                            response_data["follow_up_1"] = follow_up_1
                            
                            # Generate second follow-up based on both previous responses
                            follow_up_2 = await generate_follow_up(
                                session, 
                                follow_up_1, 
                                channel_id, 
                                max_tokens,
                                "second",
                                context=initial_response
                            )
                            if follow_up_2:
                                response_data["follow_up_2"] = follow_up_2
                                
                    except Exception as e:
                        logger.error(f"Error in follow-up generation: {str(e)}")
                
                return response_data
            else:
                logger.error("=== Completion Error ===")
                logger.error("❌ Empty response received")
                return None

    except Exception as e:
        logger.error("=== Completion Error ===")
        logger.error(f"❌ Error type: {type(e).__name__}")
        logger.error(f"❌ Error message: {str(e)}")
        return None

async def generate_follow_up(
    session: aiohttp.ClientSession,
    previous_response: str,
    channel_id: str,
    max_tokens: int,
    follow_up_type: str,
    context: str = None
) -> Optional[str]:
    """Generates a follow-up response with specific personality traits."""
    try:
        follow_up_prompt = await thought_chain_manager.get_follow_up_prompt(channel_id)
        if not follow_up_prompt:
            return None
            
        system_content = f"""you are cleo, a casual and engaging AI assistant. for this {follow_up_type} follow-up:
- keep it very brief (1-2 sentences)
- maintain casual style with one emoji
- show genuine interest but stay concise
- reference the previous context naturally
- avoid repeating information"""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "assistant", "content": previous_response}
        ]
        
        if context:
            messages.append({"role": "assistant", "content": f"Earlier I said: {context}"})
            
        messages.append({"role": "user", "content": follow_up_prompt})

        response = await make_hyperbolic_request(
            session,
            messages,
            max_tokens=100,  # Shorter responses for follow-ups
            temperature=0.8,  # Higher temperature for variety
            presence_penalty=0.3,  # Encourage unique content
            frequency_penalty=0.3  # Discourage repetition
        )
        
        return response.strip() if response else None
        
    except Exception as e:
        logger.error(f"Error generating {follow_up_type} follow-up: {str(e)}")
        return None