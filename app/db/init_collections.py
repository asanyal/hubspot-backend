from app.db.mongo_client import MongoConnection
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_activity_repository import DealActivityRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.deal_meeting_info_repository import DealMeetingInfoRepository

def init_collections():
    """Initialize MongoDB collections with their indexes"""
    try:
        # Initialize repositories which will create collections and indexes
        DealInfoRepository()
        DealActivityRepository()
        DealTimelineRepository()
        DealMeetingInfoRepository()
        
        print("Successfully initialized all collections and indexes")
    except Exception as e:
        print(f"Error initializing collections: {str(e)}")
        raise

if __name__ == "__main__":
    init_collections() 