# emotional_state.py

from typing import List, Dict
import random

class EmotionalState:
    def __init__(self):
        self.engagement = 0.5
        self.energy = 0.5
        self.playfulness = 0.5
        self.enthusiasm = 0.5
        self.certainty = 0.5
        self.curiosity = 0.5
        self.mood = 0.5  # New attribute for overall mood

class EmotionalStateManager:
    def __init__(self):
        self.states = {}
    
    def get_state(self, user_id: str) -> EmotionalState:
        if user_id not in self.states:
            self.states[user_id] = EmotionalState()
        return self.states[user_id]
    
    def get_response_parameters(self, user_id: str):
        state = self.get_state(user_id)
    
        # Map emotional state values to API parameters
        temperature = 0.5 + state.energy * 0.5 + (state.mood - 0.5) * 0.2
        presence_penalty = state.curiosity * 0.5
        frequency_penalty = (1 - state.certainty) * 0.5
        top_p = 0.7 + state.engagement * 0.3
    
        # Ensure parameters are within valid ranges
        temperature = max(0.1, min(temperature, 1.0))
        presence_penalty = max(0.0, min(presence_penalty, 1.0))
        frequency_penalty = max(0.0, min(frequency_penalty, 1.0))
        top_p = max(0.1, min(top_p, 1.0))
    
        return {
            "engagement": state.engagement,
            "energy": state.energy,
            "playfulness": state.playfulness,
            "enthusiasm": state.enthusiasm,
            "certainty": state.certainty,
            "curiosity": state.curiosity,
            "mood": state.mood,
            "temperature": temperature,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
            "top_p": top_p
        }
    
    async def analyze_message(self, message: str, user_id: str, context: List[Dict]) -> None:
        state = self.get_state(user_id)
    
        # Perform sentiment analysis to adjust mood
        sentiment = self.calculate_sentiment(message)
        state.mood = min(1.0, max(0.0, state.mood + sentiment * 0.1))
    
        # Existing analysis logic for other emotional states
        # ... (Your existing code for engagement, energy, playfulness, etc.)
    
        # Natural decay of parameters
        decay_rate = 0.95
        for attr in vars(state):
            if attr != 'mood':  # Mood decays differently
                setattr(state, attr, max(0.0, min(1.0, getattr(state, attr) * decay_rate)))
    
    def calculate_sentiment(self, message: str) -> float:
        # Simple sentiment analysis: returns a value between -1.0 (negative) and 1.0 (positive)
        positive_words = set(['good', 'great', 'fantastic', 'amazing', 'love', 'happy', 'wonderful', 'best', 'awesome'])
        negative_words = set(['bad', 'terrible', 'sad', 'angry', 'hate', 'worst', 'awful', 'horrible', 'disappoint'])
        words = message.lower().split()
        positive_count = sum(1 for word in words if word in positive_words)
        negative_count = sum(1 for word in words if word in negative_words)
        total_words = len(words)
        sentiment_score = (positive_count - negative_count) / total_words if total_words > 0 else 0
        return sentiment_score
