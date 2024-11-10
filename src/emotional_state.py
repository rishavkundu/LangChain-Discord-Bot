# emotional_state.py

from typing import List, Dict
import random
from datetime import datetime
from src.types import EmotionalState, ConversationContextProvider

class EmotionalStateManager:
    def __init__(self):
        self.states = {}
    
    def get_state(self, user_id: str) -> EmotionalState:
        if user_id not in self.states:
            self.states[user_id] = EmotionalState()
        return self.states[user_id]
    
    def get_response_parameters(self, user_id: str) -> Dict[str, float]:
        state = self.get_state(user_id)
        return {
            "temperature": 0.7 + (state.mood - 0.5) * 0.2,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
            "top_p": 0.9
        }
    
    async def analyze_message(self, message: str, user_id: str, context_provider: ConversationContextProvider) -> None:
        state = self.get_state(user_id)
        sentiment = self.calculate_sentiment(message)
        state.mood = min(1.0, max(0.0, state.mood + sentiment * 0.1))
        context = await context_provider.get_relevant_context()
        
        decay_rate = 0.95
        for attr in vars(state):
            if attr != 'mood':
                setattr(state, attr, max(0.0, min(1.0, getattr(state, attr) * decay_rate)))
    
    def calculate_sentiment(self, message: str) -> float:
        positive_words = set(['good', 'great', 'fantastic', 'amazing', 'love', 'happy', 'wonderful', 'best', 'awesome'])
        negative_words = set(['bad', 'terrible', 'sad', 'angry', 'hate', 'worst', 'awful', 'horrible', 'disappoint'])
        words = message.lower().split()
        positive_count = sum(1 for word in words if word in positive_words)
        negative_count = sum(1 for word in words if word in negative_words)
        total_words = len(words)
        sentiment_score = (positive_count - negative_count) / total_words if total_words > 0 else 0
        return sentiment_score

# Create a singleton instance
emotional_state_manager = EmotionalStateManager()