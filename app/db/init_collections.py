from app.db.mongo_client import MongoConnection
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_insights_repository import DealInsightsRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.meeting_insights_repository import MeetingInsightsRepository

def init_collections():
    """Initialize MongoDB collections with their indexes"""
    try:
        # Initialize repositories which will create collections and indexes
        DealInfoRepository()
        DealInsightsRepository()
        DealTimelineRepository()
        MeetingInsightsRepository()
        
        print("Successfully initialized all collections and indexes")
    except Exception as e:
        print(f"Error initializing collections: {str(e)}")
        raise

if __name__ == "__main__":
    init_collections() 