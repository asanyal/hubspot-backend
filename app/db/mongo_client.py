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
            # Optimized connection configuration for better performance
            connection_args = {
                "tls": True,
                "tlsCAFile": certifi.where(),
                # Connection pool settings
                "maxPoolSize": 50,  # Maximum connections in pool
                "minPoolSize": 5,   # Minimum connections in pool
                "maxIdleTimeMS": 30000,  # Close connections after 30s idle
                # Timeout settings
                "socketTimeoutMS": 30000,  # 30s socket timeout
                "serverSelectionTimeoutMS": 5000,  # 5s server selection timeout
                "connectTimeoutMS": 10000,  # 10s connection timeout
                # Read/Write settings
                "retryWrites": True,
                "retryReads": True,
                "readPreference": "secondaryPreferred",  # Use secondary for reads when possible
                # Connection management
                "heartbeatFrequencyMS": 10000,  # 10s heartbeat
            }

            print(Fore.YELLOW + f"Connecting to MongoDB with optimized settings" + Style.RESET_ALL)
            cls._client = MongoClient(settings.MONGO_URI, **connection_args)
            
            # Test connection
            try:
                cls._client.admin.command('ping')
                print(Fore.GREEN + "MongoDB connection established successfully" + Style.RESET_ALL)
            except Exception as e:
                print(Fore.RED + f"MongoDB connection failed: {str(e)}" + Style.RESET_ALL)
                raise

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