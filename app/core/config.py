from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from urllib.parse import quote_plus

# Load .env file
load_dotenv()

class Settings(BaseSettings):
    # API Keys
    HUBSPOT_API_KEY: str
    GONG_ACCESS_KEY: str
    GONG_CLIENT_SECRET: str
    OPENAI_API_KEY: str = ""

    # HubSpot URLs
    CONTACTS_URL: str = "https://api.hubapi.com/crm/v3/objects/contacts"
    DEALS_URL: str = "https://api.hubapi.com/crm/v3/objects/deals"
    PIPELINE_DEALS_URL: str = "https://api.hubapi.com/crm/v3/pipelines/deals"
    OWNERS_URL: str = "https://api.hubapi.com/crm/v3/owners"

    # Redis Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # Transcript Cache Configuration
    TRANSCRIPT_CACHE_TTL: int = 86400
    CHUNK_SIZE: int = 600
    TOP_K_CHUNKS: int = 10

    # MongoDB Configuration via env vars
    MONGO_USER: str
    MONGO_PASS: str
    MONGO_CLUSTER: str
    MONGO_DB_NAME: str = "spotlight_db"

    @property
    def MONGO_URI(self) -> str:
        user = quote_plus(self.MONGO_USER)
        password = quote_plus(self.MONGO_PASS)
        return (
            f"mongodb+srv://{user}:{password}@{self.MONGO_CLUSTER}/"
            f"{self.MONGO_DB_NAME}?retryWrites=true&w=majority&tls=true"
        )

    class Config:
        env_file = ".env"

settings = Settings()