from app.repositories.base_repository import BaseRepository
from pymongo import UpdateOne

class CompanyOverviewRepository(BaseRepository):
    def __init__(self):
        super().__init__("company_overviews")
        
    def get_by_deal_id(self, deal_id: str) -> dict:
        """Get company overview by deal ID"""
        return self.find_one({"deal_id": deal_id})
        
    def upsert_by_deal_id(self, deal_id: str, overview: str) -> bool:
        """Upsert company overview by deal ID"""
        filter_dict = {"deal_id": deal_id}
        update_dict = {"$set": {"deal_id": deal_id, "overview": overview}}
        result = self.collection.update_one(filter_dict, update_dict, upsert=True)
        return result.modified_count > 0 or result.upserted_id is not None