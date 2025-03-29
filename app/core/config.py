import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    HUBSPOT_API_KEY: str = os.getenv("HUBSPOT_API_KEY")
    GONG_ACCESS_KEY: str = os.getenv("GONG_ACCESS_KEY")
    GONG_CLIENT_SECRET: str = os.getenv("GONG_CLIENT_SECRET")
    CONTACTS_URL: str = "https://api.hubapi.com/crm/v3/objects/contacts"
    DEALS_URL: str = "https://api.hubapi.com/crm/v3/objects/deals"
    PIPELINE_DEALS_URL: str = "https://api.hubapi.com/crm/v3/pipelines/deals"
    OWNERS_URL: str = "https://api.hubapi.com/crm/v3/owners"

settings = Settings()