from typing import Dict, Optional
from datetime import datetime
from app.repositories.base_repository import BaseRepository

class DealActivityRepository(BaseRepository):
    def __init__(self):
        super().__init__("deal_activity")
        self._create_indexes()

    def _create_indexes(self):
        self.create_index({"deal_id": 1}, unique=True)

    def get_by_deal_id(self, deal_id: str) -> Optional[Dict]:
        return self.find_one({"deal_id": deal_id})

    def upsert_activity(self, deal_id: str, activity_data: Dict) -> bool:
        activity_data["deal_id"] = deal_id
        activity_data["last_updated"] = datetime.utcnow()
        
        result = self.collection.update_one(
            {"deal_id": deal_id},
            {"$set": activity_data},
            upsert=True
        )
        return result.modified_count > 0 or result.upserted_id is not None

    def update_metrics(self, deal_id: str, metrics: Dict) -> bool:
        return self.update_one(
            {"deal_id": deal_id},
            {"$set": {**metrics, "last_updated": datetime.utcnow()}}
        ) 