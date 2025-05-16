from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.repositories.base_repository import BaseRepository
from colorama import Fore, Style
from datetime import timezone

class MeetingInsightsRepository(BaseRepository):
    def __init__(self):
        super().__init__("meeting_insights")
        self._create_indexes()

    def _create_indexes(self):
        self.create_index({"deal_id": 1, "meeting_id": 1}, unique=True)
        self.create_index({"deal_id": 1, "meeting_date": 1})

    def get_by_deal_id(self, deal_id: str) -> List[Dict]:
        return self.find_many({"deal_id": deal_id})

    def get_by_meeting_id(self, deal_id: str, meeting_id: str) -> Optional[Dict]:
        return self.find_one({"deal_id": deal_id, "meeting_id": meeting_id})

    def find_by_deal_and_date(self, deal_id: str, date_str: str) -> List[Dict]:
        # Convert date string to datetime for comparison
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        next_date = target_date + timedelta(days=1)
        
        # Find meetings between target_date and next_date
        return self.find_many({
            "deal_id": deal_id,
            "meeting_date": {
                "$gte": target_date,
                "$lt": next_date
            }
        })

    def upsert_meeting(self, deal_id: str, meeting_id: str, meeting_data: Dict) -> bool:
        # Always upsert (insert or update) the meeting
        meeting_data["deal_id"] = deal_id
        meeting_data["meeting_id"] = meeting_id
        meeting_data["last_updated"] = datetime.now(timezone.utc)
        print(Fore.GREEN + f"Upserting meeting {meeting_id} for deal {deal_id}" + Style.RESET_ALL)
        result = self.collection.update_one(
            {"deal_id": deal_id, "meeting_id": meeting_id},
            {"$set": meeting_data},
            upsert=True
        )
        # Return True if a document was inserted or modified
        return result.upserted_id is not None or result.modified_count > 0 