import os
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Optional, ClassVar
from urllib.parse import quote_plus

load_dotenv()

class Settings(BaseModel):
    # API Keys
    HUBSPOT_API_KEY: str = os.getenv("HUBSPOT_API_KEY")
    GONG_ACCESS_KEY: str = os.getenv("GONG_ACCESS_KEY")
    GONG_CLIENT_SECRET: str = os.getenv("GONG_CLIENT_SECRET")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # HubSpot URLs
    CONTACTS_URL: str = "https://api.hubapi.com/crm/v3/objects/contacts"
    DEALS_URL: str = "https://api.hubapi.com/crm/v3/objects/deals"
    PIPELINE_DEALS_URL: str = "https://api.hubapi.com/crm/v3/pipelines/deals"
    OWNERS_URL: str = "https://api.hubapi.com/crm/v3/owners"
    
    # Redis Configuration
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))

    # Transcript Cache Configuration
    TRANSCRIPT_CACHE_TTL: int = int(os.getenv("TRANSCRIPT_CACHE_TTL", "86400"))  # 24 hours in seconds
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "600"))
    TOP_K_CHUNKS: int = int(os.getenv("TOP_K_CHUNKS", "10"))

    # MongoDB Configuration
    MONGO_URI: str = f"mongodb+srv://{quote_plus('atin')}:{quote_plus('Galileo@$123')}@cluster0.2dvzkmk.mongodb.net/spotlight_db?retryWrites=true&w=majority&appName=Cluster0"
    MONGO_DB_NAME: str = "spotlight_db"

settings = Settings()