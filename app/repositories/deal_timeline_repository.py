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
        # Optimized compound index for get-latest-meetings queries
        self.create_index({
            "events.event_type": 1, 
            "events.event_date": 1, 
            "events.sentiment": 1
        })
        # Sparse index for better performance when filtering by date ranges
        self.create_index({"events.event_date": 1}, sparse=True)

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

    def get_meetings_with_deal_stages_in_date_range(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Get all meetings within a date range with deal stages using optimized MongoDB aggregation.
        This eliminates the N+1 query problem by joining with deal_info collection in a single query.
        """
        pipeline = [
            # Stage 1: Match documents that have meetings in the date range
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
            # Stage 2: Filter events to only include matching meetings
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
            # Stage 3: Only keep documents with matching events
            {
                "$match": {
                    "events": {"$ne": []}
                }
            },
            # Stage 4: Join with deal_info collection to get deal stage
            {
                "$lookup": {
                    "from": "deal_info",
                    "localField": "deal_id",
                    "foreignField": "deal_id",
                    "as": "deal_info",
                    "pipeline": [
                        {
                            "$project": {
                                "stage": 1,
                                "_id": 0
                            }
                        }
                    ]
                }
            },
            # Stage 5: Add deal_stage field from the joined data
            {
                "$addFields": {
                    "deal_stage": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$deal_info.stage", 0]},
                            "Unknown"
                        ]
                    }
                }
            },
            # Stage 6: Remove the temporary deal_info array
            {
                "$project": {
                    "deal_id": 1,
                    "deal_stage": 1,
                    "events": 1
                }
            }
        ]
        
        return list(self.collection.aggregate(pipeline))

    def get_meetings_with_deal_stages_in_date_range_paginated(self, start_date: datetime, end_date: datetime, limit: int = 1000) -> List[Dict]:
        """
        Get all meetings within a date range with deal stages using highly optimized MongoDB aggregation.
        This version minimizes data processing by doing joins before unwinding and sorting.
        """
        pipeline = [
            # Stage 1: Match documents that have meetings in the date range (uses index)
            {
                "$match": {
                    "events": {
                        "$elemMatch": {
                            "event_type": "Meeting",
                            "event_date": {
                                "$gte": start_date,
                                "$lte": end_date
                            },
                            "sentiment": {"$ne": "Unknown"}
                        }
                    }
                }
            },
            # Stage 2: Join with deal_info BEFORE unwinding (much more efficient)
            {
                "$lookup": {
                    "from": "deal_info",
                    "localField": "deal_id",
                    "foreignField": "deal_id",
                    "as": "deal_info",
                    "pipeline": [
                        {
                            "$project": {
                                "stage": 1,
                                "_id": 0
                            }
                        }
                    ]
                }
            },
            # Stage 3: Add deal_stage field early
            {
                "$addFields": {
                    "deal_stage": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$deal_info.stage", 0]},
                            "Unknown"
                        ]
                    }
                }
            },
            # Stage 4: Filter and transform events in a single stage
            {
                "$project": {
                    "deal_id": 1,
                    "deal_stage": 1,
                    "filtered_events": {
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
            # Stage 5: Only keep documents with matching events
            {
                "$match": {
                    "filtered_events": {"$ne": []}
                }
            },
            # Stage 6: Unwind the filtered events
            {
                "$unwind": "$filtered_events"
            },
            # Stage 7: Sort by event date (most recent first)
            {
                "$sort": {"filtered_events.event_date": -1}
            },
            # Stage 8: Limit results for performance
            {
                "$limit": limit
            },
            # Stage 9: Final projection
            {
                "$project": {
                    "deal_id": 1,
                    "deal_stage": 1,
                    "event": "$filtered_events"
                }
            }
        ]
        
        return list(self.collection.aggregate(pipeline))

    def get_meetings_with_deal_stages_in_date_range_ultra_fast(self, start_date: datetime, end_date: datetime, limit: int = 1000) -> List[Dict]:
        """
        Ultra-fast version that uses a different approach optimized for very large datasets.
        Uses aggregation with early limiting and minimal data processing.
        """
        pipeline = [
            # Stage 1: Match documents with meetings in date range
            {
                "$match": {
                    "events": {
                        "$elemMatch": {
                            "event_type": "Meeting",
                            "event_date": {
                                "$gte": start_date,
                                "$lte": end_date
                            },
                            "sentiment": {"$ne": "Unknown"}
                        }
                    }
                }
            },
            # Stage 2: Use $addFields to create a sorted and filtered events array
            {
                "$addFields": {
                    "matching_events": {
                        "$slice": [
                            {
                                "$sortArray": {
                                    "input": {
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
                                    },
                                    "sortBy": {"event_date": -1}
                                }
                            },
                            limit  # Take only the top N events per deal
                        ]
                    }
                }
            },
            # Stage 3: Only keep documents with matching events
            {
                "$match": {
                    "matching_events": {"$ne": []}
                }
            },
            # Stage 4: Join with deal_info (fewer documents now)
            {
                "$lookup": {
                    "from": "deal_info",
                    "localField": "deal_id",
                    "foreignField": "deal_id",
                    "as": "deal_info",
                    "pipeline": [
                        {
                            "$project": {
                                "stage": 1,
                                "_id": 0
                            }
                        }
                    ]
                }
            },
            # Stage 5: Unwind the matching events
            {
                "$unwind": "$matching_events"
            },
            # Stage 6: Sort globally and limit
            {
                "$sort": {"matching_events.event_date": -1}
            },
            {
                "$limit": limit
            },
            # Stage 7: Final projection
            {
                "$project": {
                    "deal_id": 1,
                    "deal_stage": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$deal_info.stage", 0]},
                            "Unknown"
                        ]
                    },
                    "event": "$matching_events"
                }
            }
        ]
        
        return list(self.collection.aggregate(pipeline))

    def get_meetings_with_deal_stages_in_date_range_simple(self, start_date: datetime, end_date: datetime, limit: int = 1000) -> List[Dict]:
        """
        Simplified ultra-fast version that avoids complex operations for maximum compatibility and speed.
        """
        pipeline = [
            # Stage 1: Match and project in one step to reduce data early
            {
                "$match": {
                    "events": {
                        "$elemMatch": {
                            "event_type": "Meeting",
                            "event_date": {"$gte": start_date, "$lte": end_date},
                            "sentiment": {"$ne": "Unknown"}
                        }
                    }
                }
            },
            # Stage 2: Join with deal_info early (before expensive operations)
            {
                "$lookup": {
                    "from": "deal_info",
                    "localField": "deal_id",
                    "foreignField": "deal_id",
                    "as": "deal_stage_info",
                    "pipeline": [{"$project": {"stage": 1, "_id": 0}}]
                }
            },
            # Stage 3: Filter events and add deal_stage in one step
            {
                "$project": {
                    "deal_id": 1,
                    "deal_stage": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$deal_stage_info.stage", 0]},
                            "Unknown"
                        ]
                    },
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
            # Stage 4: Only keep documents with events
            {"$match": {"events": {"$ne": []}}},
            # Stage 5: Unwind events
            {"$unwind": "$events"},
            # Stage 6: Sort and limit
            {"$sort": {"events.event_date": -1}},
            {"$limit": limit},
            # Stage 7: Final structure
            {
                "$project": {
                    "deal_id": 1,
                    "deal_stage": 1,
                    "event": "$events"
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
                "buyer_intent_explanation": event.get('buyer_intent_explanation', "N/A"),
                "engagement_id": event['engagement_id']
            }
            print(f"🔍 DEBUG REPO: Transformed event buyer_intent_explanation type: {type(transformed_event['buyer_intent_explanation'])}")
            if isinstance(transformed_event['buyer_intent_explanation'], dict):
                print(f"🔍 DEBUG REPO: Transformed event buyer_intent_explanation keys: {list(transformed_event['buyer_intent_explanation'].keys())}")
            else:
                print(f"⚠️ WARNING REPO: buyer_intent_explanation is not a dict, it's: {type(transformed_event['buyer_intent_explanation'])}")
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
            "buyer_intent_explanation": event.get('buyer_intent_explanation', "N/A"),
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