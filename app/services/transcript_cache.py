import redis
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
from app.core.config import settings

class TranscriptCache:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            decode_responses=True
        )
        self.ttl = getattr(settings, 'TRANSCRIPT_CACHE_TTL', 86400)  # 24 hours in seconds

    def _generate_key(self, customer_name: str, month: str, chunk_index: int) -> str:
        """Generate cache key in format: {customer_name}__{month}__chunk_{n}"""
        return f"{customer_name.lower()}__{month.lower()}__chunk_{chunk_index}"

    def store_chunks(self, customer_name: str, month: str, chunks: List[str]) -> None:
        """Store transcript chunks in cache with TTL"""
        for i, chunk in enumerate(chunks):
            key = self._generate_key(customer_name, month, i)
            self.redis_client.setex(key, self.ttl, json.dumps(chunk))

    def get_chunks(self, customer_name: str, month: str) -> Optional[List[str]]:
        """Retrieve all chunks for a customer in a specific month"""
        chunks = []
        i = 0
        while True:
            key = self._generate_key(customer_name, month, i)
            chunk = self.redis_client.get(key)
            if not chunk:
                break
            chunks.append(json.loads(chunk))
            i += 1
        return chunks if chunks else None

    def has_data(self, customer_name: str, month: str) -> bool:
        """Check if data exists for a customer in a specific month"""
        key = self._generate_key(customer_name, month, 0)
        return bool(self.redis_client.exists(key))

    def clear(self) -> None:
        """Clear all transcript data from cache"""
        self.redis_client.flushdb()

    def remove_customer_month(self, customer_name: str, month: str) -> None:
        """Remove all chunks for a specific customer and month"""
        i = 0
        while True:
            key = self._generate_key(customer_name, month, i)
            if not self.redis_client.exists(key):
                break
            self.redis_client.delete(key)
            i += 1 