import os
import sys

# Add the project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from pymongo import MongoClient
from app.core.config import settings
import certifi
import ssl

class MongoConnection:
    _client = None
    _db = None

    @classmethod
    def get_client(cls) -> MongoClient:
        if cls._client is None:
            tls_args = {}

            # Use certifi only if running on Heroku (or production)
            if os.getenv("DYNO"):  # Heroku sets DYNO in env
                import certifi
                tls_args = {
                    "tls": True,
                    "tlsCAFile": certifi.where()
                }

            cls._client = MongoClient(
                settings.MONGO_URI,
                **tls_args
            )
        return cls._client

    @classmethod
    def get_db(cls):
        if cls._db is None:
            cls._db = cls.get_client()[settings.MONGO_DB_NAME]
        return cls._db

    @classmethod
    def close_connection(cls):
        if cls._client is not None:
            cls._client.close()
            cls._client = None
            cls._db = None 