from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
import random
from typing import Optional, Dict
import re

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
        # Analyze message complexity to determine if we should continue chain
        complexity_score = (
            len(message_content.split()) +
            message_content.count('?') * 5 +
            (10 if any(word in message_content.lower() for word in 
                ['why', 'how', 'what if', 'imagine', 'think']) else 0)
        )
        
        # Higher complexity = higher chance of continuing
        return random.random() < (complexity_score / 200)
        
    async def maybe_start_chain(self, channel_id: str, message: str, response: str) -> bool:
        async with self._lock:
            # Rate limiting check
            current_time = datetime.now()
            if channel_id in self._last_chain_time:
                time_since_last = current_time - self._last_chain_time[channel_id]
                if time_since_last < timedelta(minutes=5):
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
            
        # Add more natural thought transition templates
        follow_up_templates = [
            "wait...",
            "oh! that reminds me...",
            "*thinking*",
            "actually... you know what's interesting?",
            "hmm... 🤔",
            "oh! and another thing about {topic}...",
            "speaking of {topic}... *gets excited*",
            "wait wait wait- i just realized something about {topic}!",
        ]
        
        # Sometimes just trail off mid-thought
        if random.random() < 0.15:
            return random.choice([
                "although...",
                "but then again...",
                "unless...",
                "although maybe...",
            ])
        
        return random.choice(follow_up_templates)
    
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
    
    async def handle_thought_interruption(self, current_thought: str) -> tuple[str, str]:
        """Split thoughts naturally when interrupting self"""
        interruption_patterns = [
            "... wait",
            "... oh!",
            "... actually",
            "... hang on",
        ]
        
        split_point = random.randint(len(current_thought)//2, len(current_thought)-10)
        first_part = current_thought[:split_point]
        second_part = random.choice(interruption_patterns) + current_thought[split_point:]
        
        return first_part, second_part