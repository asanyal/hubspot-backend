from typing import Dict, Optional, List
from datetime import datetime
from app.repositories.base_repository import BaseRepository

class DealInsightsRepository(BaseRepository):
    def __init__(self):
        super().__init__("deal_insights")
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

    def upsert_activity_with_concerns_list(self, deal_id: str, activity_data: Dict, new_concerns: Dict) -> bool:
        """
        Upsert activity data and handle concerns as a list.
        If concerns already exist as a dictionary, convert to list of size 1.
        If concerns already exist as a list, append new concerns.
        """
        # Get existing document to check current concerns structure
        existing_doc = self.find_one({"deal_id": deal_id})
        
        # Prepare concerns list
        if existing_doc and "concerns" in existing_doc:
            existing_concerns = existing_doc["concerns"]
            if isinstance(existing_concerns, dict):
                # Convert existing dictionary to list with one item
                concerns_list = [existing_concerns]
            elif isinstance(existing_concerns, list):
                # Use existing list
                concerns_list = existing_concerns
            else:
                # Invalid format, start fresh
                concerns_list = []
        else:
            # No existing concerns, start fresh
            concerns_list = []
        
        # Add new concerns to the list
        concerns_list.append(new_concerns)
        
        # Update activity_data with the concerns list
        activity_data["concerns"] = concerns_list
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