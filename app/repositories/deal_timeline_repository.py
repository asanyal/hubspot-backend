from typing import Dict, List, Optional
from datetime import datetime
from app.repositories.base_repository import BaseRepository

class DealTimelineRepository(BaseRepository):
    def __init__(self):
        super().__init__("deal_timeline")
        self._create_indexes()

    def _create_indexes(self):
        self.create_index({"deal_id": 1}, unique=True)
        self.create_index({"deal_id": 1, "events.event_date": 1})
        # Add compound index for meeting queries with date range
        self.create_index({"events.event_type": 1, "events.event_date": 1})
        # Add index for sentiment filtering
        self.create_index({"events.sentiment": 1})

    def get_by_deal_id(self, deal_id: str) -> Optional[Dict]:
        return self.find_one({"deal_id": deal_id})
    
    def get_meetings_in_date_range(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Get all meetings within a date range using MongoDB aggregation for optimal performance
        """
        pipeline = [
            {
                "$match": {
                    "events": {
                        "$elemMatch": {
                            "event_type": "Meeting",
                            "event_date": {
                                "$gte": start_date,
                                "$lte": end_date
                            },
                            "sentiment": {"$ne": "Unknown"}  # Exclude unknown sentiment
                        }
                    }
                }
            },
            {
                "$project": {
                    "deal_id": 1,
                    "events": {
                        "$filter": {
                            "input": "$events",
                            "cond": {
                                "$and": [
                                    {"$eq": ["$$this.event_type", "Meeting"]},
                                    {"$gte": ["$$this.event_date", start_date]},
                                    {"$lte": ["$$this.event_date", end_date]},
                                    {"$ne": ["$$this.sentiment", "Unknown"]}
                                ]
                            }
                        }
                    }
                }
            },
            {
                "$match": {
                    "events": {"$ne": []}  # Only return documents with matching events
                }
            }
        ]
        
        return list(self.collection.aggregate(pipeline))

    def upsert_timeline(self, deal_id: str, timeline_data: Dict) -> bool:

        transformed_events = []
        for event in timeline_data.get('events', []):
            event_date = datetime.strptime(
                f"{event['date_str']} {event['time_str']}", 
                "%Y-%m-%d %H:%M"
            )
            
            transformed_event = {
                "event_id": event['id'],
                "event_type": event['type'],
                "event_date": event_date,
                "subject": event['subject'],
                "content": event['content'] or event['content_preview'],
                "sentiment": event['sentiment'],
                "buyer_intent": event['buyer_intent'],
                "buyer_intent_explanation": event['buyer_intent_explanation'] if isinstance(event['buyer_intent_explanation'], dict) else "N/A",
                "engagement_id": event['engagement_id']
            }
            transformed_events.append(transformed_event)

        # Sort events by date
        transformed_events.sort(key=lambda x: x["event_date"])

        # Create the document to upsert
        document = {
            "deal_id": deal_id,
            "events": transformed_events,
            "start_date": timeline_data.get('start_date'),
            "end_date": timeline_data.get('end_date'),
            "champions_summary": timeline_data.get('champions_summary', {}),
            "last_updated": datetime.utcnow()
        }

        result = self.collection.update_one(
            {"deal_id": deal_id},
            {"$set": document},
            upsert=True
        )
        return result.modified_count > 0 or result.upserted_id is not None

    def add_event(self, deal_id: str, event: Dict) -> bool:
        """
        Add a single event to the timeline
        Args:
            deal_id: The deal ID
            event: Event dictionary matching HubSpot event structure
        Returns:
            bool: True if successful, False otherwise
        """
        event_date = datetime.strptime(
            f"{event['date_str']} {event['time_str']}", 
            "%Y-%m-%d %H:%M"
        )
        transformed_event = {
            "event_id": event['id'],
            "event_type": event['type'],
            "event_date": event_date,
            "subject": event['subject'],
            "content": event['content'] or event['content_preview'],
            "sentiment": event['sentiment'],
            "buyer_intent": event['buyer_intent'],
            "buyer_intent_explanation": event['buyer_intent_explanation'] if isinstance(event['buyer_intent_explanation'], dict) else "N/A",
            "engagement_id": event['engagement_id']
        }

        return self.update_one(
            {"deal_id": deal_id},
            {
                "$push": {"events": transformed_event},
                "$set": {"last_updated": datetime.utcnow()}
            }
        )

    def remove_event(self, deal_id: str, event: Dict) -> bool:
        """
        Remove a single event from the timeline
        Args:
            deal_id: The deal ID
            event: Event dictionary to remove
        Returns:
            bool: True if successful, False otherwise
        """
        return self.update_one(
            {"deal_id": deal_id},
            {
                "$pull": {"events": event},
                "$set": {"last_updated": datetime.utcnow()}
            }
        )