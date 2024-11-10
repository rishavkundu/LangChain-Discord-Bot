from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional

@dataclass
class EmotionalState:
    def __init__(self):
        self.engagement = 0.5
        self.energy = 0.5
        self.playfulness = 0.5
        self.mood = 0.5

class ConversationContextProvider:
    """Abstract base class for conversation context"""
    async def get_relevant_context(self, cache_key: str = None) -> List[Dict[str, Any]]:
        raise NotImplementedError