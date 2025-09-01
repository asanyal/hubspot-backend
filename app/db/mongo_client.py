import certifi
from pymongo import MongoClient
from app.core.config import settings
import os
from colorama import Fore, Style, init
init()

class MongoConnection:
    _client = None
    _db = None

    @classmethod
    def get_client(cls):
        if cls._client is None:
            # Use TLS with proper CA file (safe for Heroku + Atlas)
            tls_args = {
                "tls": True,
                "tlsCAFile": certifi.where()
            }

            print(Fore.YELLOW + f"Connecting to MongoDB: {settings.MONGO_URI}" + Style.RESET_ALL)
            cls._client = MongoClient(settings.MONGO_URI, **tls_args)

        return cls._client

    @classmethod
    def get_db(cls):
        if cls._db is None:
            cls._db = cls.get_client()[settings.MONGO_DB_NAME]
        return cls._db

    @classmethod
    def close_connection(cls):
        if cls._client:
            cls._client.close()
            cls._client = None
            cls._db = None