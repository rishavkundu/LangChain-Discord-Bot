from datetime import datetime
import psutil
import asyncio
import threading

class BotMetrics:
    def __init__(self):
        self.start_time = datetime.now()
        self.messages_processed = 0
        self.commands_processed = 0
        self.searches_performed = 0
        self.error_count = 0
        self._cpu_percent = 0
        self._memory_percent = 0
        
    def increment_messages(self):
        self.messages_processed += 1
        
    def increment_commands(self):
        self.commands_processed += 1
        
    def increment_searches(self):
        self.searches_performed += 1
        
    def increment_errors(self):
        self.error_count += 1
        
    def get_system_metrics(self) -> dict:
        """Get current system metrics"""
        return {
            "uptime": datetime.now() - self.start_time,
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "threads": threading.active_count(),
            "messages_processed": self.messages_processed,
            "commands_processed": self.commands_processed,
            "searches_performed": self.searches_performed,
            "error_count": self.error_count
        }