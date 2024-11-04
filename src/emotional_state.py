from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
from typing import Dict, List, Optional
import numpy as np
import re
import random

@dataclass
class EmotionalParameters:
    engagement: float = 0.5      # How engaged the conversation is
    energy: float = 0.5         # Energy level of responses
    familiarity: float = 0.1    # How familiar we are with the user
    empathy: float = 0.5        # How empathetic responses should be
    playfulness: float = 0.5    # How playful responses should be
    enthusiasm: float = 0.5    # Excitement level about topic
    certainty: float = 0.5     # Confidence in opinions/knowledge
    curiosity: float = 0.5     # Likelihood to ask follow-ups
    formality: float = 0.3     # Conversation formality level
    focus: float = 0.5         # Stay on topic vs allow tangents
    
@dataclass
class PersonalityState:
    # Core traits (relatively stable)
    playfulness: float = 0.7
    curiosity: float = 0.8
    skepticism: float = 0.4
    
    # Dynamic states (more variable)
    enthusiasm: float = 0.5
    formality: float = 0.3
    mirroring: float = 0.0
    
    # Emotional momentum
    last_emotion: str = "neutral"
    emotion_intensity: float = 0.5
    
    def update_mirroring(self, user_style: str):
        # Gradually adjust mirroring based on interaction history
        target = min(0.8, self.mirroring + 0.2)
        self.mirroring = self.mirroring + (target - self.mirroring) * 0.3
        
    def resist_style(self) -> bool:
        # Occasionally resist matching user's style
        return random.random() < self.skepticism
    
class EmotionalStateManager:
    def __init__(self):
        self._states: Dict[str, EmotionalParameters] = {}
        self._last_interactions: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        
    async def analyze_message(self, message: str, user_id: str, context: List[Dict]) -> None:
        async with self._lock:
            # Initialize state if needed
            if user_id not in self._states:
                self._states[user_id] = EmotionalParameters()
            
            state = self._states[user_id]
            
            # Update familiarity based on interaction frequency
            current_time = datetime.now()
            if user_id in self._last_interactions:
                time_diff = current_time - self._last_interactions[user_id]
                # Increase familiarity if interactions are frequent
                if time_diff < timedelta(hours=24):
                    state.familiarity = min(1.0, state.familiarity + 0.05)
                else:
                    # Decay familiarity if long time between interactions
                    state.familiarity *= 0.95
            
            self._last_interactions[user_id] = current_time
            
            # Analyze message characteristics
            message_length = len(message)
            emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF]', message))
            contains_question = '?' in message
            exclamation_count = message.count('!')
            
            # Calculate message intensity
            intensity = (
                (emoji_count * 0.1) +
                (exclamation_count * 0.15) +
                (0.1 if contains_question else 0) +
                (0.05 if message_length > 50 else 0)
            )
            
            # Update engagement based on context and current message
            recent_context = context[-3:] if context else []
            context_activity = len(recent_context) / 3  # Normalize to 0-1
            
            state.engagement = min(1.0, state.engagement + (
                0.1 * context_activity +
                0.05 * intensity
            ))
            
            # Update energy based on message characteristics
            state.energy = min(1.0, max(0.2, (
                state.energy * 0.8 +  # Decay factor
                0.2 * intensity      # New intensity contribution
            )))
            
            # Update playfulness based on emoji usage and exclamations
            if emoji_count > 0 or exclamation_count > 1:
                state.playfulness = min(1.0, state.playfulness + 0.1)
            else:
                state.playfulness = max(0.2, state.playfulness - 0.05)
            
            # Natural decay of parameters
            state.engagement *= 0.95
            state.energy *= 0.95
            state.playfulness *= 0.95
            
            # Topic enthusiasm
            if any(keyword in message.lower() for keyword in ['ai', 'tech', 'science', 'coding']):
                state.enthusiasm = min(1.0, state.enthusiasm + 0.2)
                state.certainty = min(1.0, state.certainty + 0.15)
            
            # Adjust curiosity based on user engagement
            if '?' in message or any(word in message.lower() for word in ['how', 'why', 'what']):
                state.curiosity = min(1.0, state.curiosity + 0.15)
            
            # Dynamic formality adjustment
            state.formality = max(0.2, min(0.8, 
                state.formality + (0.1 if len(message.split()) > 15 else -0.1)
            ))
            
    def get_response_parameters(self, user_id: str) -> dict:
        """Convert emotional state to LLM parameters"""
        state = self._states.get(user_id, EmotionalParameters())
        
        return {
            "temperature": 0.2 + (state.playfulness * 0.3),  # 0.2-0.5 range
            "presence_penalty": 0.4 + (state.engagement * 0.4),  # 0.4-0.8 range
            "frequency_penalty": 0.6 + (state.familiarity * 0.4),  # 0.6-1.0 range
            "top_p": max(0.1, min(0.9, 0.5 + state.energy * 0.4))  # 0.5-0.9 range
        } 