# thought_chain.py

from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
import random
from typing import Optional, Dict
import re
from src.prompt_templates import REPROMPT_TEMPLATES  # Import reprompt templates

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
        triggers = ['why', 'how', 'what if', 'imagine', 'think', '?', '...']
        return any(trigger in message_content.lower() for trigger in triggers)
            
    async def maybe_start_chain(self, channel_id: str, message: str, response: str) -> bool:
        """
        Decides whether to start a thought chain and initializes it if so.
        """
        async with self._lock:
            current_time = datetime.now()
            if channel_id in self._last_chain_time:
                time_since_last = current_time - self._last_chain_time[channel_id]
                if time_since_last < timedelta(minutes=5):
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
        chain = self._active_chains.get(channel_id)
        if not chain:
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

    async def update_chain(self, channel_id: str, response: str) -> None:
        """Update the thought chain with a new response."""
        async with self._lock:
            if channel_id in self._active_chains:
                chain = self._active_chains[channel_id]
                chain.last_response = response
                chain.chain_count += 1

                # End chain if we've reached maximum thoughts
                if chain.chain_count >= 1:  # Reduced from 2 to 1
                    del self._active_chains[channel_id]


    async def handle_thought_interruption(self, current_thought: str) -> str:
        """
        Randomly inserts self-interruptions to simulate natural speech.
        """
        # Possible interruption points
        interruption_points = [m.start() for m in re.finditer(r'\b(and|but|so|because)\b', current_thought)]
        if interruption_points and random.random() < 0.3:
            point = random.choice(interruption_points)
            interruption = random.choice([
                "... wait, actually, ",
                "... oh! And ",
                "... hold on, ",
                "... you know what? ",
            ])
            # Insert the interruption into the thought
            interrupted_thought = current_thought[:point] + interruption + current_thought[point:]
            return interrupted_thought
        return current_thought
