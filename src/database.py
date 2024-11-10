from asyncio.log import logger
import sqlite3
import json
from datetime import datetime
import aiosqlite
from typing import Dict, Any, List, Optional

class DatabaseManager:
    def __init__(self, db_path: str = "bot_context.db"):
        self.db_path = db_path
        
    async def init_db(self):
        """Initialize the database tables."""
        async with aiosqlite.connect(self.db_path) as db:
            # Create conversations table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    channel_id TEXT PRIMARY KEY,
                    last_updated TIMESTAMP
                )
            """)
            
            # Create messages table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT,
                    content TEXT,
                    role TEXT,
                    timestamp TIMESTAMP,
                    user_id TEXT,
                    FOREIGN KEY (channel_id) REFERENCES conversations (channel_id)
                )
            """)
            
            # Create user_profiles table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    interests TEXT,
                    last_updated TIMESTAMP
                )
            """)
            
            await db.commit()

    async def add_message(self, channel_id: str, message: Dict[str, Any]) -> None:
        """Add a message to the database."""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute('BEGIN')
                # Ensure conversation exists
                await db.execute(
                    "INSERT OR REPLACE INTO conversations (channel_id, last_updated) VALUES (?, ?)",
                    (channel_id, datetime.now().isoformat())
                )
                
                # Add message
                await db.execute("""
                    INSERT INTO messages (channel_id, content, role, timestamp, user_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    channel_id,
                    message["content"],
                    message.get("role", "user"),
                    message.get("timestamp", datetime.now()).isoformat(),
                    message.get("user_id")
                ))
                
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"Database error: {str(e)}")
                raise

    async def get_context(self, channel_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve conversation context for a channel."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT content, role, timestamp, user_id
                FROM messages
                WHERE channel_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (channel_id, limit)) as cursor:
                messages = await cursor.fetchall()
                
                return [{
                    "content": msg[0],
                    "role": msg[1],
                    "timestamp": datetime.fromisoformat(msg[2]),
                    "user_id": msg[3]
                } for msg in reversed(messages)]

    async def update_user_profile(self, user_id: str, interests: set) -> None:
        """Update user profile in the database."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_profiles (user_id, interests, last_updated)
                VALUES (?, ?, ?)
            """, (
                user_id,
                json.dumps(list(interests)),
                datetime.now().isoformat()
            ))
            await db.commit()