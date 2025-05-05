from typing import Dict, List, Optional, Any
from app.db.mongo_client import MongoConnection

class BaseRepository:
    def __init__(self, collection_name: str):
        self.db = MongoConnection.get_db()
        self.collection = self.db[collection_name]

    def create_index(self, keys, **kwargs):
        """Create an index on the collection"""
        return self.collection.create_index(keys, **kwargs)

    def find_one(self, filter_dict: Dict) -> Optional[Dict]:
        """Find a single document"""
        return self.collection.find_one(filter_dict)

    def find_many(self, filter_dict: Dict) -> List[Dict]:
        """Find multiple documents"""
        return list(self.collection.find(filter_dict))

    def insert_one(self, document: Dict) -> bool:
        """Insert a single document"""
        result = self.collection.insert_one(document)
        return result.inserted_id is not None

    def update_one(self, filter_dict: Dict, update_dict: Dict) -> bool:
        """Update a single document"""
        result = self.collection.update_one(filter_dict, update_dict)
        return result.modified_count > 0

    def delete_one(self, filter_dict: Dict) -> bool:
        """Delete a single document"""
        result = self.collection.delete_one(filter_dict)
        return result.deleted_count > 0 