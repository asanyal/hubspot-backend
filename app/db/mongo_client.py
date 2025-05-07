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
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)  # Force TLS 1.2
            cls._client = MongoClient(
                settings.MONGO_URI,
                ssl=True,
                ssl_cert_reqs=ssl.CERT_REQUIRED,
                ssl_ca_certs=certifi.where(),
                ssl_context=ssl_context
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