from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
import random
from typing import Optional, List, Dict
import re

from src.emotional_state import PersonalityState

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
        # Randomly decide to continue thought chain based on message complexity
        complexity_score = (
            len(message_content.split()) +
            message_content.count('?') * 5 +
            (10 if any(word in message_content.lower() for word in 
                ['why', 'how', 'what if', 'imagine', 'think']) else 0)
        )
        
        return random.random() < (complexity_score / 200)  # Higher complexity = higher chance
        
    async def maybe_start_chain(self, channel_id: str, message: str, response: str) -> bool:
        async with self._lock:
            # Check rate limiting
            current_time = datetime.now()
            if channel_id in self._last_chain_time:
                time_since_last = current_time - self._last_chain_time[channel_id]
                if time_since_last < timedelta(minutes=5):  # Minimum 5 minutes between chains
                    return False
            
            if self.should_continue_chain(message):
                self._active_chains[channel_id] = ThoughtChain(
                    original_message=message,
                    last_response=response
                )
                self._last_chain_time[channel_id] = current_time
                return True
            return False
            
    async def get_follow_up_prompt(self, channel_id: str) -> Optional[str]:
        chain = self._active_chains.get(channel_id)
        if not chain:
            return None
            
        follow_up_templates = [
            "wait... you know what's fascinating about {topic}? 🤔",
            "oh! that just reminded me of something SUPER cool about {topic}! ",
            "actually... *gets excited* i just had a thought about {topic}...",
            "you know what's kind of mind-blowing about {topic}? ",
            "ok but can we talk about how {topic} is literally AMAZING because...",
            "*gasps* omg wait - speaking of {topic}, i just remembered..."
        ]
        
        # Extract topic more intelligently
        key_phrases = re.findall(r'(?:about|regarding|discussing) ([^,.!?]+)', chain.last_response)
        if key_phrases:
            topic = key_phrases[0].strip()
        else:
            # Fallback to first few meaningful words
            words = chain.last_response.split()
            topic = " ".join(words[1:4]).rstrip(',.!?')
        
        return random.choice(follow_up_templates).format(topic=topic)
    
    async def update_chain(self, channel_id: str, response: str) -> None:
        """Update the thought chain with a new response"""
        async with self._lock:
            if channel_id in self._active_chains:
                chain = self._active_chains[channel_id]
                chain.last_response = response
                chain.chain_count += 1
                
                # End chain if we've reached maximum thoughts
                if chain.chain_count >= 2:
                    del self._active_chains[channel_id]
    
    async def get_style_resistant_response(self, message: str, emotional_state: PersonalityState) -> str:
        resistance_templates = [
            "woah there, getting pretty deep! let me break this down in my own way... 🤔",
            "haha, i love your poetic vibes, but let me keep it real for a sec... 😄",
            "okay but can we talk about this in normal-speak for a minute? 😅",
            "*adjusts virtual glasses* in simpler terms... ✨"
        ]
        
        if emotional_state.resist_style():
            return random.choice(resistance_templates)
        return None