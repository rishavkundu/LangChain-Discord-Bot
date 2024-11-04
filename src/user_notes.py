import os
import json
import re
import logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

class UserNotesManager:
    def __init__(self):
        self.notes_dir = "user_notes"
        os.makedirs(self.notes_dir, exist_ok=True)
        self._cache = {}

    def add_note(self, user_id: str, note: str) -> None:
        notes_file = os.path.join(self.notes_dir, f"{user_id}_notes.json")
        try:
            existing_notes = []
            if os.path.exists(notes_file):
                with open(notes_file, 'r') as f:
                    existing_notes = json.load(f)
            
            existing_notes.append({
                "content": note,
                "timestamp": datetime.now().isoformat()
            })
            
            with open(notes_file, 'w') as f:
                json.dump(existing_notes, f, indent=2)
            
            self._cache[user_id] = existing_notes
            
        except Exception as e:
            logger.error(f"Error adding note for user {user_id}: {str(e)}")

    def get_user_notes(self, user_id: str) -> List[Dict[str, str]]:
        if user_id in self._cache:
            logger.info(f"Retrieved {len(self._cache[user_id])} notes for user {user_id}")
            return self._cache[user_id]

        notes_file = os.path.join(self.notes_dir, f"{user_id}_notes.json")
        try:
            if os.path.exists(notes_file):
                with open(notes_file, 'r') as f:
                    notes = json.load(f)
                self._cache[user_id] = notes
                logger.info(f"Retrieved {len(notes)} notes for user {user_id}")
                return notes
        except Exception as e:
            logger.error(f"Error getting notes for user {user_id}: {str(e)}")
        
        return []

    @staticmethod
    def extract_user_notes(text: str) -> Tuple[str, List[str]]:
        notes = re.findall(r'<user_note>(.*?)</user_note>', text, re.DOTALL)
        cleaned_text = re.sub(r'<user_note>.*?</user_note>', '', text, flags=re.DOTALL)
        return cleaned_text.strip(), notes