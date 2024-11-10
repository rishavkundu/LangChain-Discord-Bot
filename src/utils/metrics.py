from datetime import datetime
import psutil
import asyncio

class BotMetrics:
    def __init__(self):
        self.start_time = datetime.now()
        self.messages_processed = 0
        self.commands_processed = 0
        self.error_count = 0
        self._lock = asyncio.Lock()  # Thread-safe updates
        
    async def increment_messages(self):
        async with self._lock:
            self.messages_processed += 1
            
    async def increment_errors(self):
        async with self._lock:
            self.error_count += 1
            
    def get_system_metrics(self):
        """Get current system and bot metrics."""
        return {
            'uptime': datetime.now() - self.start_time,
            'cpu_percent': psutil.cpu_percent(),
            'memory_percent': psutil.Process().memory_percent(),
            'threads': len(psutil.Process().threads()),
            'messages_processed': self.messages_processed,
            'commands_processed': self.commands_processed,
            'errors': self.error_count
        } 