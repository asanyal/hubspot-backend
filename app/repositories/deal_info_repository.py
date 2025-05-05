from typing import Dict, List, Optional
from datetime import datetime
from app.repositories.base_repository import BaseRepository

class DealInfoRepository(BaseRepository):
    def __init__(self):
        super().__init__("deal_info")
        self._create_indexes()

    def _create_indexes(self):
        self.create_index({"deal_id": 1}, unique=True)
        self.create_index({"company_name": 1})
        self.create_index({"amount": 1})

    def get_by_deal_id(self, deal_id: str) -> Optional[Dict]:
        return self.find_one({"deal_id": deal_id})

    def get_by_company_name(self, company_name: str) -> List[Dict]:
        return self.find_many({"company_name": company_name})

    def upsert_deal(self, deal_id: str, deal_data: Dict) -> bool:
        amount = deal_data.get("amount")
        if amount and amount != "N/A":
            try:
                if not amount.startswith("$"):
                    amount = f"${float(amount):,.2f}"
                deal_data["amount"] = amount
            except (ValueError, TypeError):
                deal_data["amount"] = "N/A"

        deal_data["deal_id"] = deal_id
        deal_data["last_updated"] = datetime.utcnow()
        
        result = self.collection.update_one(
            {"deal_id": deal_id},
            {"$set": deal_data},
            upsert=True
        )
        return result.modified_count > 0 or result.upserted_id is not None

    def get_all_deals(self) -> List[Dict]:
        return self.find_many({}) 