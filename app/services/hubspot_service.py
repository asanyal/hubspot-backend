import requests
from datetime import datetime, timezone
import sys
import os

# Add the project root directory to Python path when running directly
if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.config import settings
from typing import List, Dict, Any, Optional
from app.utils.general_utils import extract_company_name
import concurrent.futures
from app.services.llm_service import ask_openai

class HubspotService:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(HubspotService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.api_key = settings.HUBSPOT_API_KEY
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            # Cache for mappings
            self._stage_mapping = None
            self._owner_mapping = None
            self._deal_id_cache = {}
            
            # Initialize session for connection reuse
            self._session = requests.Session()
            self._session.headers.update(self.headers)

            from app.services.gong_service import GongService
            self.gong_service = GongService()
            
            # Initialize deals cache
            self._deals_cache = None
            self._deals_cache_timestamp = None
            self._deals_cache_ttl = 3600  # 1 hour in seconds
            
            self._initialized = True
        else:
            pass

    def _initialize_stage_mapping(self):
        """Initialize the mapping of stage IDs to stage names"""
        if self._stage_mapping is not None:
            return
        
        self._stage_mapping = {}
        
        try:
            # Get all pipelines
            pipelines_url = "https://api.hubapi.com/crm/v3/pipelines/deals"
            response = self._session.get(pipelines_url) if hasattr(self, '_session') else requests.get(pipelines_url, headers=self.headers)
            
            if response.status_code != 200:
                return
                
            pipelines = response.json().get("results", [])
            
            for pipeline in pipelines:
                pipeline_id = pipeline.get("id")
                stages = pipeline.get("stages", [])
                
                for stage in stages:
                    stage_id = stage.get("id")
                    if stage_id:
                        self._stage_mapping[stage_id] = {
                            "label": stage.get("label", "Unknown"),
                            "pipeline_id": pipeline_id,
                            "display_order": stage.get("displayOrder", 0),
                            "closed_won": stage.get("metadata", {}).get("isClosed", False) and stage.get("metadata", {}).get("probability", 0) == 1,
                            "closed_lost": stage.get("metadata", {}).get("isClosed", False) and stage.get("metadata", {}).get("probability", 0) == 0,
                        }
        except Exception as e:
            import traceback
            traceback.print_exc()

    def get_stage_id_name_mapping(self):
        """Get mapping of stage IDs to stage names"""
        if self._stage_mapping is not None:
            return self._stage_mapping
            
        response = requests.get(settings.PIPELINE_DEALS_URL, headers=self.headers)
        stage_map = {}

        if response.status_code == 200:
            pipelines = response.json()
            for pipeline in pipelines.get("results", []):
                for stage in pipeline.get("stages", []):
                    stage_map[stage["id"]] = stage["label"]
        
        self._stage_mapping = stage_map
        return stage_map

    def get_owner_id_name_mapping(self):
        """Get mapping of owner IDs to owner names"""
        if self._owner_mapping is not None:
            return self._owner_mapping
            
        response = requests.get(settings.OWNERS_URL, headers=self.headers)
        owner_map = {}
        
        if response.status_code == 200:
            owners_data = response.json()
            owner_map = {
                owner["id"]: f"{owner.get('firstName', '')} {owner.get('lastName', '')}" 
                for owner in owners_data.get("results", [])
            }
        
        self._owner_mapping = owner_map
        return owner_map

    def get_pipeline_stages(self) -> List[Dict[str, Any]]:
        """Get all pipeline stages with detailed information"""
        response = requests.get(settings.PIPELINE_DEALS_URL, headers=self.headers)
        
        if response.status_code != 200:
            return []
        
        pipelines = response.json()
        all_stages = []
        
        for pipeline in pipelines.get("results", []):
            pipeline_id = pipeline.get("id")
            pipeline_name = pipeline.get("label")
            
            for stage in pipeline.get("stages", []):
                stage_info = {
                    "pipeline_id": pipeline_id,
                    "pipeline_name": pipeline_name,
                    "stage_id": stage.get("id"),
                    "stage_name": stage.get("label"),
                    "display_order": stage.get("displayOrder"),
                    "probability": stage.get("probability"),
                    "closed_won": stage.get("metadata", {}).get("isClosed", False),
                    "closed_lost": stage.get("metadata", {}).get("probability", 0) == 0 and 
                                stage.get("metadata", {}).get("isClosed", False)
                }
                
                all_stages.append(stage_info)
        
        # Sort by pipeline name and display order
        return sorted(all_stages, key=lambda x: (x["pipeline_name"], x["display_order"]))

    def get_deals_by_stage(self, stage_name: str) -> List[Dict[str, Any]]:
        """Get all deals in a specific pipeline stage"""
        all_deals = []
        after = None
        
        if not hasattr(self, "_stage_mapping") or not self._stage_mapping:
            self._initialize_stage_mapping()
            
        while True:
            params = {
                "limit": "100"
            }
            
            if after:
                params["after"] = after
            
            response = requests.get(settings.DEALS_URL, headers=self.headers, params=params)
            
            if response.status_code == 200:
                deals = response.json()
                
                for deal in deals.get("results", []):
                    props = deal.get('properties', {})
                    
                    deal_stage_id = props.get('dealstage', 'N/A')
                    mapped_stage = 'N/A'
                    
                    if hasattr(self, "_stage_mapping") and self._stage_mapping:
                        stage_info = self._stage_mapping.get(deal_stage_id, {})
                        if isinstance(stage_info, dict):
                            mapped_stage = stage_info.get("label", "N/A")
                        else:
                            mapped_stage = stage_info

                    all_deals.append({
                        'dealname': props.get('dealname', 'N/A'),
                        'stage': mapped_stage,
                        'stage_id': deal_stage_id,
                        'amount': props.get('amount', 'N/A'),
                        'created_at': props.get('createdate', 'N/A'),
                        'close_date': props.get('closedate', 'N/A'),
                        'updated_at': props.get('hs_lastmodifieddate', 'N/A'),
                        'owner': self.get_owner_id_name_mapping().get(props.get('hubspot_owner_id', 'N/A'), 'N/A'),
                        'is_closed_won': props.get('hs_is_closed_won', 'N/A'),
                        'is_closed_lost': props.get('hs_is_closed_lost', 'N/A')
                    })
                
                # Check for pagination
                paging_info = deals.get("paging", {}).get("next", {})
                after = paging_info.get("after")
                
                if not after:
                    break  # No more pages, exit loop
            else:
                break  # Stop if an error occurs
        
        # Step 2: Now filter by stage with robust matching
        # Try exact match first
        stage_deals = [deal for deal in all_deals if deal['stage'] == stage_name]
        
        # If no deals found, try case-insensitive match
        if not stage_deals:
            stage_deals = [deal for deal in all_deals if deal['stage'].lower() == stage_name.lower()]
        
        # If still no deals, try matching with trimmed whitespace
        if not stage_deals:
            stage_deals = [deal for deal in all_deals if deal['stage'].strip() == stage_name.strip()]
        
        # If still no deals, try looser matching (contains)
        if not stage_deals:
            stage_deals = [deal for deal in all_deals if stage_name.lower() in deal['stage'].lower()]
            
            # Get the stage IDs from the mapping that might match
            potential_stage_ids = []
            if hasattr(self, "_stage_mapping") and self._stage_mapping:
                for stage_id, stage_info in self._stage_mapping.items():
                    stage_label = stage_info.get("label") if isinstance(stage_info, dict) else stage_info
                    if stage_label and (
                        stage_label == stage_name or 
                        stage_label.lower() == stage_name.lower() or
                        stage_label.strip() == stage_name.strip() or
                        stage_name.lower() in stage_label.lower()
                    ):
                        potential_stage_ids.append((stage_id, stage_label))
        
        if not stage_deals:
            return []
        
        # Process each deal
        processed_deals = []
        for deal in stage_deals:
            try:
                # Format amount
                amount = "Not specified"
                if deal['amount'] and deal['amount'] != 'N/A':
                    try:
                        amount = f"${float(deal['amount']):,.2f}"
                    except (ValueError, TypeError):
                        pass
                
                # Parse dates
                created_at = self._parse_date(deal['created_at'])
                updated_at = self._parse_date(deal['updated_at']) 
                close_date = self._parse_date(deal['close_date'])
                
                # Format as relative time for updated_at
                last_update = "Unknown"
                if updated_at:
                    days_ago = (datetime.now() - updated_at).days
                    last_update = f"{days_ago} days ago"
                
                processed_deals.append({
                    "Deal_Name": deal['dealname'],
                    "Owner": deal['owner'],
                    "Amount": amount,
                    "Created_At": created_at.strftime('%b %d, %Y') if created_at else "Not set",
                    "Last_Update": last_update,
                    "Expected_Close_Date": close_date.strftime('%b %d, %Y') if close_date else "Not set",
                    "Closed_Won": "Yes" if deal['is_closed_won'] == "true" else "No",
                    "Closed_Lost": "Yes" if deal['is_closed_lost'] == "true" else "No"
                })
            except Exception as e:
                continue
        
        return processed_deals

    def _process_deal(self, props, stage_map, owner_map):
        """Process a deal's properties into a standardized format"""
        
        # Format amount
        amount = "Not specified"
        if props.get('amount'):
            try:
                amount = f"${float(props.get('amount')):,.2f}"
            except (ValueError, TypeError):
                pass

        # Parse dates
        created_at = self._parse_date(props.get('createdate'))
        updated_at = self._parse_date(props.get('hs_lastmodifieddate'))
        close_date = self._parse_date(props.get('closedate'))
        
        # Format as relative time for updated_at
        last_update = "Unknown"
        if updated_at:
            days_ago = (datetime.now() - updated_at).days
            last_update = f"{days_ago} days ago"
            
        # Get owner name
        owner_id = props.get('hubspot_owner_id', '')
        owner_name = owner_map.get(owner_id, 'Unknown')
        
        return {
            "Deal_Name": props.get('dealname', 'Unnamed Deal'),
            "Stage": stage_map.get(props.get('dealstage', ''), 'Unknown Stage'),
            "Amount": amount,
            "Created_At": created_at.strftime('%b %d, %Y') if created_at else "Not set",
            "Last_Update": last_update,
            "Expected_Close_Date": close_date.strftime('%b %d, %Y') if close_date else "Not set",
            "Owner": owner_name,
            "Owner_ID": owner_id,
            "Closed_Won": props.get('hs_is_closed_won') == "true",
            "Closed_Lost": props.get('hs_is_closed_lost') == "true"
        }
    
    def _parse_date(self, date_string):
        """Parse a date string from HubSpot"""
        if not date_string:
            return None

        formats = [
            '%Y-%m-%dT%H:%M:%S.%fZ',  # With microseconds
            '%Y-%m-%dT%H:%M:%SZ'       # Without microseconds
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_string, fmt)
            except (ValueError, TypeError):
                continue

        try:
            return datetime.fromtimestamp(int(date_string) / 1000)
        except (ValueError, TypeError):
            return None

    def get_all_deals(self) -> List[Dict[str, Any]]:
        """Get all deals from HubSpot with their basic properties, using parallel processing"""
        # Check if we have valid cached data
        current_time = datetime.now().timestamp()
        if self._deals_cache is not None:
            if self._deals_cache_timestamp is not None:
                if current_time - self._deals_cache_timestamp < self._deals_cache_ttl:
                    return self._deals_cache
            
        deals_url = "https://api.hubapi.com/crm/v3/objects/deals"
        params = {
            "properties": "dealname,dealstage,amount,hs_object_id,hs_lastmodifieddate,createdate,pipeline,closedate,hubspot_owner_id",
        }
        
        # First, initialize stage mapping if needed
        if not hasattr(self, "_stage_mapping") or not self._stage_mapping:
            self._initialize_stage_mapping()
        
        # Step 1: Get all pages of deals in parallel
        def fetch_deals_page(page_params):
            try:
                response = self._session.get(deals_url, params=page_params)
                if response.status_code != 200:
                    return []
                    
                result = response.json()
                return result.get("results", [])
            except Exception as e:
                print(f"Error fetching deals page: {str(e)}")
                return []
        
        # First, get initial page to determine total pages
        response = self._session.get(deals_url, params=params)
        if response.status_code != 200:
            print(f"Error fetching initial deals page: {response.status_code}")
            return []
        
        result = response.json()

        all_pages_params = [params]  # Start with the first page params
        
        # Set up pagination params for remaining pages
        pagination = result.get("paging", {})
        while "next" in pagination and "after" in pagination["next"]:
            next_params = params.copy()
            next_params["after"] = pagination["next"]["after"]
            all_pages_params.append(next_params)
            
            # Fetch next pagination info
            next_response = self._session.get(deals_url, params=next_params)
            if next_response.status_code != 200:
                break
                
            next_result = next_response.json()
            pagination = next_result.get("paging", {})
        
        # Now fetch all pages in parallel
        all_deals_raw = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_page = {executor.submit(fetch_deals_page, page_params): i 
                            for i, page_params in enumerate(all_pages_params)}
            
            for future in concurrent.futures.as_completed(future_to_page):
                page_result = future.result()
                all_deals_raw.extend(page_result)
        
        # Step 2: Process all deals in parallel
        def process_deal(deal):
            try:
                deal_props = deal.get("properties", {})
                # Get pipeline stage information
                stage_id = deal_props.get("dealstage", "")
                stage_name = "Unknown"
                
                # Use stage mapping if we have it
                if self._stage_mapping and stage_id in self._stage_mapping:
                    stage_info = self._stage_mapping.get(stage_id, {})
                    stage_name = stage_info.get("label", "Unknown Stage")
                # Format the deal data
                deal_data = {
                    "dealId": deal.get("id", ""),
                    "dealname": deal_props.get("dealname", "Unnamed Deal"),
                    "stage": stage_name,
                    "stage_id": stage_id,
                    "amount": deal_props.get("amount", "0"),
                    "createdate": deal_props.get("createdate", ""),
                    "closedate": deal_props.get("closedate", ""),
                    "lastmodifieddate": deal_props.get("hs_lastmodifieddate", ""),
                }

                # Add owner info if available
                owner_id = deal_props.get("hubspot_owner_id")
                if owner_id and self.get_owner_id_name_mapping():
                    owner_info = self.get_owner_id_name_mapping().get(owner_id, {})
                    deal_data["owner"] = owner_info
                else:
                    deal_data["owner"] = "Unknown Owner"
                
                return deal_data
            except Exception as e:
                return None
        
        # Process all deals in parallel
        all_deals = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            future_to_deal = {executor.submit(process_deal, deal): deal.get("id", "") 
                            for deal in all_deals_raw}
            
            for future in concurrent.futures.as_completed(future_to_deal):
                deal_result = future.result()
                if deal_result:
                    all_deals.append(deal_result)
        
        validated_deals = []

        for deal in all_deals:
            if not deal:
                continue
                
            if not isinstance(deal, dict):
                continue
                
            # Additionally verify the deal has required fields
            if not deal.get("dealId") or not deal.get("stage"):
                continue
                
            validated_deals.append(deal)
        
        # Cache the validated deals
        self._deals_cache = validated_deals
        self._deals_cache_timestamp = current_time
        
        return validated_deals

    def get_deal_timeline(self, deal_name: str) -> Dict[str, Any]:
        """Get timeline data for a specific deal. Returns email content if include_content is True"""
        from datetime import datetime

        try:
            # Find the deal ID
            deal_id = self._find_deal_id(deal_name)
            if not deal_id:
                return {"events": [], "start_date": None, "end_date": None}
            
            # Now fetch activities for this deal
            print("Getting all engagements from HubSpot for deal: ", deal_name)
            engagement_url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}/associations/engagements"
            engagement_response = self._session.get(engagement_url)
            
            if engagement_response.status_code != 200:
                return {"events": [], "start_date": None, "end_date": None}
            
            engagement_results = engagement_response.json().get("results", [])
            engagement_ids = [result.get("id") for result in engagement_results]
            
            if not engagement_ids:
                return {"events": [], "start_date": None, "end_date": None}

            timeline_events = []
            start_engagement_date = None
            latest_engagement_date = None
            seen_subjects = set()  # Track seen subjects for deduplication
            prefixes = ["[Gong] Google Meet:", "[Gong] Zoom:", "[Gong] WebEx:", "[Gong]"]

            # Process each engagement sequentially
            for eng_id in engagement_ids:
                try:
                    detail_url = f"https://api.hubapi.com/crm/v3/objects/engagements/{eng_id}"
                    detail_params = {
                        "properties": "hs_engagement_type,hs_timestamp,hs_email_subject,hs_email_text,hs_note_body,hs_call_body,hs_meeting_title,hs_meeting_body,hs_task_body"
                    }

                    detail_response = self._session.get(detail_url, params=detail_params)
                    if detail_response.status_code != 200:
                        continue
                        
                    details = detail_response.json()
                    props = details.get("properties", {})
                    
                    # Get engagement type
                    activity_type = props.get("hs_engagement_type", "Unknown")
                    if activity_type is None:
                        activity_type = "Unknown"
                        
                    timestamp = props.get("hs_timestamp")
                    date_time = None
                    
                    # Format timestamp
                    if timestamp:
                        try:
                            # Try to handle as integer timestamp (milliseconds)
                            date_time = datetime.fromtimestamp(int(timestamp) / 1000)
                        except (ValueError, TypeError):
                            # Handle ISO format date string
                            try:
                                date_string = timestamp.replace('Z', '+00:00')
                                date_time = datetime.fromisoformat(date_string)
                            except (ValueError, TypeError, AttributeError):
                                # If all parsing fails, try another format
                                try:
                                    date_time = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
                                except (ValueError, TypeError):
                                    date_time = datetime.now()  # Fallback
                    else:
                        continue  # Skip events without a timestamp
                    
                    # Get content and subject based on activity type
                    subject = ""
                    content = ""
                    
                    if activity_type == "EMAIL" or activity_type == "INCOMING_EMAIL":
                        subject = props.get('hs_email_subject', 'No subject')
                        content = props.get('hs_email_text', '')
                        display_type = "Incoming Email" if activity_type == "INCOMING_EMAIL" else "Outgoing Email"
                    elif activity_type == "CALL":
                        content = props.get("hs_call_body", '')
                        display_type = "Call"
                    elif activity_type == "MEETING":
                        subject = props.get('hs_meeting_title', 'Untitled meeting')
                        print("Meeting. Subject: ", subject)
                        content = props.get('hs_meeting_body', '')
                        display_type = "Meeting"
                    elif activity_type == "TASK":
                        content = props.get("hs_task_body", '')
                        display_type = "Task"
                    elif activity_type == "NOTE":
                        content = props.get("hs_note_body", '')
                        display_type = "Note"
                    else:
                        display_type = activity_type.replace("_", " ").title()

                    # Ensure content is not None
                    if content is None:
                        content = ""
                    if subject is None:
                        subject = ""

                    # Create a unique event ID
                    event_id = f"{eng_id}_{date_time.strftime('%Y%m%d%H%M')}"

                    buyer_intent = {"intent": "N/A", "explanation": "N/A"}
                    if display_type == "Meeting":
                        print("Getting the intent analysis data for meeting: ", subject)
                        result = self.gong_service.get_buyer_intent(
                            call_title=subject.strip(), 
                            call_date=date_time.strftime('%Y-%m-%d'),
                            seller_name="Galileo"
                        )
                        if result is not None:
                            # Only use the result if both intent and explanation are valid
                            if (result.get("intent") and result.get("intent") != "N/A" and 
                                result.get("explanation") and result.get("explanation") != "N/A" and
                                result.get("explanation").strip()):
                                buyer_intent = result
                            else:
                                print(f"Invalid buyer intent data for meeting {subject}: intent={result.get('intent')}, explanation={result.get('explanation')}")
                                buyer_intent = {"intent": "N/A", "explanation": "N/A"}

                    # Get sentiment for content
                    sentiment = "Unknown"
                    if content is not None and content != "":
                        # Truncate content to a reasonable length before analysis
                        max_content_length = 15000
                        if len(content) > max_content_length:
                            content = content[max_content_length:] + "..."
                            
                        sentiment = ask_openai(
                            system_content="You are a smart Sales Operations Analyst that analyzes Sales emails.",
                            user_content=f"""
                            Classify the buyer sentiment in this email as positive (likely to purchase), negative (unlikely to purchase), or neutral (undecided):
                            {content}
                            Return only one word: positive, negative, or neutral
                            """
                        )

                        # Truncate content for summary
                        content = ask_openai(
                            system_content="You are a smart Sales Operations Analyst that summarizes Sales emails.",
                            user_content=f"""
                                Shorten the content to 2 lines: {content}
                            """
                        )

                    # Prepare content preview
                    content_preview = content[:150] + "..." if len(content) > 150 else content

                    event = {
                        "id": event_id,
                        "engagement_id": eng_id,
                        "date_str": date_time.strftime('%Y-%m-%d'),
                        "time_str": date_time.strftime('%H:%M'),
                        "type": display_type,
                        "subject": subject,
                        "content": content,
                        "content_preview": content_preview,
                        "sentiment": sentiment,
                        "buyer_intent": buyer_intent["intent"],
                        "buyer_intent_explanation": buyer_intent["explanation"]
                    }
                    
                    if event.get("type") == "Meeting":
                        for prefix in prefixes:
                            event['subject'] = event['subject'].replace(prefix, "").strip()
                        print("Meeting. Removed prefix from subject: ", event['subject'])
                        
                        subject_key = f"{event['subject'].lower().strip()}_{event['date_str']}"

                        if subject_key in seen_subjects:
                            # Find the existing event with this subject
                            existing_event = next((e for e in timeline_events if f"{e['subject'].lower().strip()}_{e['date_str']}" == subject_key), None)
                            
                            if existing_event:
                                # If existing event has no buyer intent but current event does, update just that field
                                if (not existing_event.get('buyer_intent_explanation') or 
                                    existing_event.get('buyer_intent_explanation') == 'N/A' or
                                    existing_event.get('buyer_intent_explanation') == '') and \
                                   event.get('buyer_intent_explanation') and \
                                   event.get('buyer_intent_explanation') != 'N/A':
                                    print(f"# Updating buyer intent data for meeting: {event['subject']}")
                                    existing_event['buyer_intent_explanation'] = event['buyer_intent_explanation']
                                    existing_event['buyer_intent'] = event['buyer_intent']
                                    print("Old buyer intent: ", existing_event['buyer_intent'])
                                    print("New buyer intent: ", event['buyer_intent'])
                                else:
                                    print(f"Skipping duplicate meeting: {event['subject']}.")
                                    continue
                        else:
                            seen_subjects.add(subject_key)
                            timeline_events.append(event)
                    else:
                        timeline_events.append(event)
                    
                    # Track first and last engagement dates
                    if start_engagement_date is None or date_time < start_engagement_date:
                        start_engagement_date = date_time
                    if latest_engagement_date is None or date_time > latest_engagement_date:
                        latest_engagement_date = date_time
                        
                except Exception as e:
                    continue

            # Get additional meetings from Gong
            company_name = extract_company_name(deal_name)
            print("Getting additional meetings from Gong for company: ", company_name)
            gong_meetings_events = self.gong_service.get_additional_meetings(company_name, timeline_events)
            if gong_meetings_events:
                # Add Gong meetings, checking for duplicates
                for event in gong_meetings_events:
                    if event.get("type") == "Meeting":
                        subject_key = f"{event['subject'].lower().strip()}_{event['date_str']}"
                        if subject_key not in seen_subjects:
                            timeline_events.append(event)
                            seen_subjects.add(subject_key)
                    else:
                        timeline_events.append(event)
                
                # Recalculate end_date to include Gong meetings
                for event in gong_meetings_events:
                    try:
                        event_date = datetime.strptime(f"{event['date_str']} {event['time_str']}", "%Y-%m-%d %H:%M")
                        event_date = event_date.replace(tzinfo=timezone.utc)
                        
                        if latest_engagement_date and latest_engagement_date.tzinfo is None:
                            latest_engagement_date = latest_engagement_date.replace(tzinfo=timezone.utc)
                            
                        if latest_engagement_date is None or event_date > latest_engagement_date:
                            latest_engagement_date = event_date
                    except (ValueError, TypeError) as e:
                        continue

            # Sort events by date
            timeline_events.sort(key=lambda x: (x["date_str"], x["time_str"]))
            
            # Count meetings and champions
            meeting_count = sum(1 for event in timeline_events if event["type"] == "Meeting")
            all_champions = []
            for event in timeline_events:
                if event.get("champion_data"):
                    all_champions.extend(event["champion_data"])
            
            # Remove duplicates based on email
            unique_champions = {champ["email"]: champ for champ in all_champions}.values()
            champions_count = sum(1 for champ in unique_champions if champ.get("champion", False))
            total_contacts = len(unique_champions)
            
            # Prepare response
            response = {
                "events": timeline_events,
                "start_date": start_engagement_date.strftime('%Y-%m-%d') if start_engagement_date else None,
                "end_date": latest_engagement_date.strftime('%Y-%m-%d') if latest_engagement_date else None,
                "deal_id": str(deal_id),
                "champions_summary": {
                    "total_contacts": total_contacts,
                    "champions_count": champions_count,
                    "meeting_count": meeting_count,
                    "champions": [
                        {
                            "champion": champ.get("champion", False),
                            "explanation": champ.get("explanation", ""),
                            "email": champ.get("email", "")
                        }
                        for champ in unique_champions
                    ]
                }
            }
            
            return response
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"events": [], "start_date": None, "end_date": None, "error": str(e)}

    def _find_deal_id(self, deal_name: str) -> str:
        """Find a deal ID by name, with caching"""
        # Check cache first
        if not hasattr(self, '_deal_id_cache'):
            self._deal_id_cache = {}
            
        if deal_name in self._deal_id_cache:
            return self._deal_id_cache[deal_name]
            
        # Try direct search first (much faster)
        deal_search_url = "https://api.hubapi.com/crm/v3/objects/deals/search"
        search_payload = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "dealname",
                    "operator": "EQ",
                    "value": deal_name
                }]
            }],
            "properties": ["dealname", "hs_object_id"],
            "limit": 1
        }

        search_response = self._session.post(deal_search_url, json=search_payload)
        
        if search_response.status_code == 200:
            results = search_response.json().get("results", [])
            if results:
                deal_id = results[0].get("id")
                if deal_id:
                    self._deal_id_cache[deal_name] = deal_id
                    return deal_id
        
        # Fall back to listing all deals if search fails
        deals_url = "https://api.hubapi.com/crm/v3/objects/deals"
        params = {"properties": "dealname,id", "limit": "100"}
        
        all_deals = []
        after = None
        
        while True:
            if after:
                params["after"] = after
                
            response = self._session.get(deals_url, params=params)
            
            if response.status_code == 200:
                result = response.json()
                deals_page = result.get("results", [])
                all_deals.extend(deals_page)
                
                pagination = result.get("paging", {})
                if "next" in pagination and "after" in pagination["next"]:
                    after = pagination["next"]["after"]
                else:
                    break
            else:
                return None
        
        # Find the deal ID by matching deal name
        for deal in all_deals:
            if deal.get('properties', {}).get('dealname') == deal_name:
                deal_id = deal.get('id')
                if deal_id:
                    self._deal_id_cache[deal_name] = deal_id
                    return deal_id

        return None

    def get_deal_activities_count(self, deal_name: str) -> int:
        """Get the count of activities for a specific deal"""
        # First try to get deal ID from cache
        if hasattr(self, '_deal_id_cache') and deal_name in self._deal_id_cache:
            deal_id = self._deal_id_cache[deal_name]
        else:
            # If not in cache, try to find it in the deals cache
            if self._deals_cache is not None:
                for deal in self._deals_cache:
                    if deal.get('dealname') == deal_name:
                        deal_id = deal.get('dealId')
                        if deal_id:
                            self._deal_id_cache[deal_name] = deal_id
                            break
                else:
                    # If not found in cache, fetch fresh data
                    deals = self.get_all_deals()
                    for deal in deals:
                        if deal.get('dealname') == deal_name:
                            deal_id = deal.get('dealId')
                            if deal_id:
                                self._deal_id_cache[deal_name] = deal_id
                                break
                    else:
                        return 0
            else:
                deals = self.get_all_deals()
                for deal in deals:
                    if deal.get('dealname') == deal_name:
                        deal_id = deal.get('dealId')
                        if deal_id:
                            self._deal_id_cache[deal_name] = deal_id
                            break
                else:
                    print(f"Deal with name '{deal_name}' not found in fresh data.")
                    return 0

        if not deal_id:
            print(f"Could not find deal ID for deal: {deal_name}")
            return 0

        # Now fetch activities for this deal
        engagement_url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}/associations/engagements"
        
        try:
            engagement_response = self._session.get(engagement_url)
            
            if engagement_response.status_code == 404:
                return 0
                
            if engagement_response.status_code != 200:
                return 0
            
            engagement_results = engagement_response.json().get("results", [])
            engagement_count = len(engagement_results)
            
            print(f"Found {engagement_count} activities for deal: {deal_name}")
            return engagement_count
            
        except Exception as e:
            return 0

def main():
    service = HubspotService()
    
    timeline = service.get_deal_timeline("Coveo-New Deal")
    print(timeline)

if __name__ == "__main__":
    main()