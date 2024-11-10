# thought_chain.py

from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
import random
from typing import Optional, Dict, List
import re
from src.prompt_templates import REPROMPT_TEMPLATES  # Import reprompt templates
import logging
import aiohttp
import time

logger = logging.getLogger(__name__)

@dataclass
class ThoughtChain:
    original_message: str
    last_response: str
    chain_count: int = 0
    last_update: datetime = datetime.now()

class ThoughtChainManager:
    def __init__(self):
        self._active_chains: Dict[str, ThoughtChain] = {}
        self._last_chain_time: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
            
    def should_continue_chain(self, message_content: str) -> bool:
        """
        Determines whether to start or continue a thought chain based on message content.
        """
        # Triggers that encourage starting a thought chain
        triggers = ['why', 'how', 'what if', 'imagine', 'wonder', 'consider', 'believe', 'ask', '!', 'cool', 'think', '?', '...']
        return any(trigger in message_content.lower() for trigger in triggers)
            
    async def maybe_start_chain(self, channel_id: str, message: str, response: str) -> bool:
        """
        Decides whether to start a thought chain and initializes it if so.
        """
        async with self._lock:
            current_time = datetime.now()
            if channel_id in self._last_chain_time:
                time_since_last = current_time - self._last_chain_time[channel_id]
                if time_since_last < timedelta(minutes=1):
                    return False  # Prevents starting chains too frequently
                
            if self.should_continue_chain(message):
                self._active_chains[channel_id] = ThoughtChain(
                    original_message=message,
                    last_response=response
                )
                self._last_chain_time[channel_id] = current_time
                return True
            return False

    async def get_follow_up_prompt(self, channel_id: str) -> Optional[str]:
        """
        Generates a follow-up prompt for Cleo to continue the thought chain.
        """
        try:
            chain = self._active_chains.get(channel_id)
            if not chain:
                logger.debug(f"No active chain found for channel {channel_id}")
                return None

            # Choose a random reprompt template
            reprompt_template = random.choice(REPROMPT_TEMPLATES)

            # Format the reprompt with Cleo's last response
            prompt = reprompt_template.format(last_response=chain.last_response.strip())

            # Include chain-of-thought instruction
            chain_of_thought_instruction = """
Think through your response step-by-step, and provide a thoughtful continuation of the conversation.
"""
            # Combine the prompt and instruction
            full_prompt = f"{prompt}\n\n{chain_of_thought_instruction}"
            return full_prompt.strip()
        except Exception as e:
            logger.error(f"Error generating follow-up prompt: {str(e)}")
            return None

    async def update_chain(self, channel_id: str, response: str) -> None:
        """Update the thought chain with a new response."""
        async with self._lock:
            if channel_id in self._active_chains:
                chain = self._active_chains[channel_id]
                chain.last_response = response
                chain.chain_count += 1

                # End chain if we've reached maximum thoughts
                if chain.chain_count >= 4:  # Increased from 1 to 2
                    del self._active_chains[channel_id]

    def find_interruption_points(self, text: str) -> List[int]:
        """Find valid interruption points avoiding existing ellipsis."""
        points = []
        for match in re.finditer(r'\b(and|but|so|because)\b', text):
            start = match.start()
            # Check if there's an ellipsis in the previous few characters
            prev_text = text[max(0, start-4):start]
            if '...' not in prev_text:
                points.append(start)
        return points

    async def handle_thought_interruption(self, current_thought: str) -> str:
        """Randomly inserts self-interruptions to simulate natural speech."""
        if "..." in current_thought:
            return current_thought
            
        interruption_points = self.find_interruption_points(current_thought)
        
        if interruption_points and random.random() < 0.3:
            point = random.choice(interruption_points)
            interruption = random.choice([
                "... wait, actually, ",
                "... oh! And ",
                "... hold on, ",
                "... you know what? ",
            ])
            
            interrupted_thought = current_thought[:point].rstrip() + " " + interruption + current_thought[point:].lstrip()
            return interrupted_thought
            
        return current_thought

    async def handle_sonar_search(self, response: str) -> Optional[tuple[str, str]]:
        """
        Extracts and processes sonar search commands from Cleo's response.
        Returns tuple of (original_query, search_results) if found, None otherwise.
        """
        sonar_pattern = r'sonar\("([^"]+)"\)'
        match = re.search(sonar_pattern, response)
        
        if not match:
            logger.debug("No sonar search pattern found in response")
            return None
            
        search_query = match.group(1)
        logger.info(f"=== Sonar Search Operation ===")
        logger.info(f"🔍 Search Query: {search_query[:50]}...")
        logger.info(f"📝 Original Response: {response[:100]}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                from src.perplexity import get_perplexity_completion
                
                logger.info("=== Search Request Details ===")
                logger.info("🌐 Initiating Perplexity API search request...")
                search_start_time = time.time()
                
                search_results = await get_perplexity_completion(
                    search_query,
                    system_prompt="You are a helpful search assistant. Provide concise, factual information about the query.",
                    max_tokens=300
                )
                
                search_duration = (time.time() - search_start_time) * 1000
                
                if search_results:
                    logger.info("=== Search Results ===")
                    logger.info(f"⏱️ Search completed in {search_duration:.2f}ms")
                    logger.info(f"📊 Results length: {len(search_results)} characters")
                    logger.debug(f"📑 First 100 chars: {search_results[:100]}...")
                    
                    # Remove the sonar command from the original response
                    cleaned_response = re.sub(sonar_pattern, '', response).strip()
                    logger.info("=== Response Processing ===")
                    logger.info(f"🧹 Cleaned response length: {len(cleaned_response)}")
                    logger.debug(f"📝 Cleaned response preview: {cleaned_response[:100]}...")
                    
                    return (cleaned_response, search_results)
                else:
                    logger.error("❌ Search returned empty results")
                    logger.error("=== Search Operation Failed ===")
                    
        except Exception as e:
            logger.error("=== Search Error Details ===")
            logger.error(f"❌ Error type: {type(e).__name__}")
            logger.error(f"❌ Error message: {str(e)}")
            logger.error(f"❌ Failed query: {search_query}")
            logger.error("=== End Error Details ===")
            
        return None
