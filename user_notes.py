import os
import json
import re
import logging
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

class UserNotesManager:
    def __init__(self, base_dir: str = "user_notes"):
        self.base_dir = base_dir
        self._ensure_notes_directory()
        logger.info(f"UserNotesManager initialized with directory: {base_dir}")

    def _ensure_notes_directory(self):
        """Create notes directory if it doesn't exist"""
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)
            logger.info(f"Created directory for user notes: {self.base_dir}")
        else:
            logger.info(f"Directory for user notes already exists: {self.base_dir}")

    def _get_user_file_path(self, user_id: str) -> str:
        """Get the path to a user's notes file"""
        return os.path.join(self.base_dir, f"{user_id}.json")

    def add_note(self, user_id: str, note: str) -> None:
        """Add a new note for a user"""
        file_path = self._get_user_file_path(user_id)
        logger.info(f"Adding note for user {user_id}: {note[:50]}...")
        
        try:
            # Load existing notes or create new structure
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    notes = json.load(f)
            else:
                notes = []

            # Add new note with timestamp
            notes.append({
                "content": note,
                "timestamp": datetime.now().isoformat()
            })

            # Save updated notes
            with open(file_path, 'w') as f:
                json.dump(notes, f, indent=2)
            logger.info(f"Successfully saved note for user {user_id}")
        except Exception as e:
            logger.error(f"Error saving note for user {user_id}: {str(e)}")

    def get_user_notes(self, user_id: str) -> List[Dict]:
        """Retrieve all notes for a user"""
        file_path = self._get_user_file_path(user_id)
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    notes = json.load(f)
                logger.info(f"Retrieved {len(notes)} notes for user {user_id}")
                return notes
            logger.info(f"No notes found for user {user_id}")
            return []
        except Exception as e:
            logger.error(f"Error retrieving notes for user {user_id}: {str(e)}")
            return []

    @staticmethod
    def extract_user_notes(response: str) -> tuple[str, List[str]]:
        """Extract user notes from response and return cleaned response and notes"""
        pattern = r'<user_note>(.*?)</user_note>'
        notes = re.findall(pattern, response, re.DOTALL)
        cleaned_response = re.sub(pattern, '', response)
        logger.info(f"Extracted {len(notes)} notes from response")
        return cleaned_response.strip(), notes