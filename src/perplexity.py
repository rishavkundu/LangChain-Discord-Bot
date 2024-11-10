import aiohttp
import logging
import json
from typing import Optional, Dict, Any, List
from src.config import OPENAI_API_KEY
from src.api.exceptions import APIError, RateLimitError
import time

# Configure logging
logger = logging.getLogger(__name__)

async def make_perplexity_request(
    session: aiohttp.ClientSession,
    messages: List[Dict[str, str]],
    max_tokens: int = 500,
    temperature: float = 0.7,
    presence_penalty: float = 0.0,
    frequency_penalty: float = 0.0,
    top_p: float = 1.0
) -> Optional[str]:
    """Makes a request to the Perplexity API using Llama 3.1 Sonar."""
    try:
        logger.info("=== Perplexity API Request ===")
        logger.info(f"🎯 Max tokens: {max_tokens}")
        logger.info(f"🌡️ Temperature: {temperature}")
        logger.debug(f"📝 Messages: {json.dumps(messages, indent=2)}")
        
        request_start_time = time.time()
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "Cleo Discord Bot"
            },
            json={
                "model": "perplexity/llama-3.1-sonar-huge-128k-online",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "presence_penalty": presence_penalty,
                "frequency_penalty": frequency_penalty,
                "top_p": top_p,
                "stop": ["<|end|>", "\n\n\n"],
                "stream": False
            }
        ) as response:
            request_duration = (time.time() - request_start_time) * 1000
            logger.info(f"⏱️ API request took {request_duration:.2f}ms")
            
            if response.status == 429:
                logger.error("=== Rate Limit Error ===")
                logger.error("❌ Perplexity API rate limit exceeded")
                raise RateLimitError("Rate limit exceeded")
            elif response.status != 200:
                logger.error(f"=== API Error {response.status} ===")
                logger.error(f"❌ Perplexity API request failed")
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

async def get_perplexity_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 500
) -> Optional[str]:
    """Gets a completion from Perplexity API with error handling."""
    try:
        logger.info("=== Perplexity Completion Request ===")
        logger.info(f"🔍 Prompt: {prompt[:50]}...")
        if system_prompt:
            logger.info(f"⚙️ System prompt: {system_prompt[:50]}...")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            response = await make_perplexity_request(
                session,
                messages,
                max_tokens=max_tokens
            )
            
            if response:
                total_duration = (time.time() - start_time) * 1000
                logger.info("=== Completion Success ===")
                logger.info(f"⏱️ Total completion time: {total_duration:.2f}ms")
                return response.strip()
            else:
                logger.error("=== Completion Error ===")
                logger.error("❌ Empty response received")
                return None

    except Exception as e:
        logger.error("=== Completion Error ===")
        logger.error(f"❌ Error type: {type(e).__name__}")
        logger.error(f"❌ Error message: {str(e)}")
        return None 