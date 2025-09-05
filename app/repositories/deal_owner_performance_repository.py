from app.repositories.base_repository import BaseRepository

class DealOwnerPerformanceRepository(BaseRepository):
    def __init__(self):
        super().__init__("deal_owner_performance")
        self._create_indexes()
    
    def _create_indexes(self):
        """Create indexes for better query performance"""
        self.create_index({"owner": 1}, unique=True)

    def get_collection(self):
        return self.collection

    def delete_owner_performance(self, owner):
        self.collection.delete_one({"owner": owner})

    def insert_owner_performance(self, owner, performance):
        self.collection.insert_one({
            "owner": owner,
            "deals_performance": performance
        })
