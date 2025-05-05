import requests
from datetime import datetime
from app.core.config import settings
from typing import List, Dict, Any, Optional
import concurrent.futures
from app.services.llm_service import ask_openai
from colorama import Fore, Style, init

init()

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
            
            # Initialize engagement cache
            self._engagement_cache = {}
            
            # Initialize deals cache
            self._deals_cache = None
            self._deals_cache_timestamp = None
            self._deals_cache_ttl = 3600  # 1 hour in seconds
            
            self._initialized = True
            print(Fore.CYAN + "[SINGLETON] Initialized new HubspotService instance" + Style.RESET_ALL)
        else:
            print(Fore.CYAN + "[SINGLETON] Reusing existing HubspotService instance" + Style.RESET_ALL)

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
                print(f"Error fetching pipelines: {response.status_code}")
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
            print(f"Error initializing stage mapping: {str(e)}")
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
        print(Fore.CYAN + f"Getting deals for stage: '{stage_name}'" + Style.RESET_ALL)
        
        all_deals = []
        after = None
        
        if not hasattr(self, "_stage_mapping") or not self._stage_mapping:
            self._initialize_stage_mapping()
            
        while True:
            params = {
                # "properties": "dealname,dealstage,amount,createdate,closedate,hs_lastmodifieddate,hubspot_owner_id,hs_is_closed_won,hs_is_closed_lost,galileo_exec_sponsor",
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
                print(f"Error: {response.status_code}, {response.text}")
                break  # Stop if an error occurs
        
        # Step 2: Now filter by stage with robust matching
        # Try exact match first
        stage_deals = [deal for deal in all_deals if deal['stage'] == stage_name]
        
        # If no deals found, try case-insensitive match
        if not stage_deals:
            print(Fore.CYAN + f"No exact matches for '{stage_name}', trying case-insensitive match..." + Style.RESET_ALL)
            stage_deals = [deal for deal in all_deals if deal['stage'].lower() == stage_name.lower()]
        
        # If still no deals, try matching with trimmed whitespace
        if not stage_deals:
            print(Fore.CYAN + f"No case-insensitive matches, trying with trimmed whitespace..." + Style.RESET_ALL)
            stage_deals = [deal for deal in all_deals if deal['stage'].strip() == stage_name.strip()]
        
        # If still no deals, try looser matching (contains)
        if not stage_deals:
            print(Fore.CYAN + f"No whitespace-trimmed matches, checking if any stage contains '{stage_name}'..." + Style.RESET_ALL)
            stage_deals = [deal for deal in all_deals if stage_name.lower() in deal['stage'].lower()]
            
            # Print more detailed debug info if we found matches with looser criteria
            if stage_deals:
                similar_stages = set(deal['stage'] for deal in stage_deals)
                print(Fore.CYAN + f"Found similar stages: {similar_stages}" + Style.RESET_ALL)
        
        print(Fore.CYAN + f"Found {len(stage_deals)} deals in stage: '{stage_name}'" + Style.RESET_ALL)
        
        # Add stage ID debugging info
        if not stage_deals:
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
            
            if potential_stage_ids:
                print(Fore.CYAN + f"Potential matching stage IDs: {potential_stage_ids}" + Style.RESET_ALL)
            else:
                print(Fore.CYAN + f"No potential matching stage IDs found in mapping" + Style.RESET_ALL)
        
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
                print(Fore.RED + f"Error processing deal: {str(e)}" + Style.RESET_ALL)
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
        print(Fore.CYAN + f"[CACHE CHECK] Current time: {current_time}, Cache timestamp: {self._deals_cache_timestamp}, TTL: {self._deals_cache_ttl}" + Style.RESET_ALL)
        
        if self._deals_cache is not None:
            print(Fore.CYAN + f"[CACHE CHECK] Cache exists with {len(self._deals_cache)} deals" + Style.RESET_ALL)
        else:
            print(Fore.CYAN + "[CACHE CHECK] No cache exists" + Style.RESET_ALL)
            
        if self._deals_cache_timestamp is not None:
            print(Fore.CYAN + f"[CACHE CHECK] Cache timestamp exists: {self._deals_cache_timestamp}" + Style.RESET_ALL)
        else:
            print(Fore.CYAN + "[CACHE CHECK] No cache timestamp" + Style.RESET_ALL)
            
        if (self._deals_cache is not None and 
            self._deals_cache_timestamp is not None and 
            current_time - self._deals_cache_timestamp < self._deals_cache_ttl):
            print(Fore.GREEN + f"[CACHE HIT] Returning cached deals data (age: {int(current_time - self._deals_cache_timestamp)}s)" + Style.RESET_ALL)
            return self._deals_cache
        else:
            if self._deals_cache is None:
                print(Fore.CYAN + "[CACHE MISS] No cache exists" + Style.RESET_ALL)
            elif self._deals_cache_timestamp is None:
                print(Fore.CYAN + "[CACHE MISS] No cache timestamp" + Style.RESET_ALL)
            else:
                age = int(current_time - self._deals_cache_timestamp)
                print(Fore.CYAN + f"[CACHE MISS] Cache expired (age: {age}s, TTL: {self._deals_cache_ttl}s)" + Style.RESET_ALL)

        print(Fore.CYAN + "[CACHE MISS] Fetching fresh deals data" + Style.RESET_ALL)
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
                    print(f"Error fetching deals page: {response.status_code}")
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
                print(f"Error processing deal: {str(e)}")
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
                print(f"Warning: Found non-dictionary deal: {type(deal)}, {deal}")
                continue
                
            # Additionally verify the deal has required fields
            if not deal.get("dealId") or not deal.get("stage"):
                print(f"Warning: Deal missing required fields: {deal}")
                continue
                
            validated_deals.append(deal)
        
        print(Fore.CYAN + f"Original deal count: {len(all_deals)}, Validated deal count: {len(validated_deals)}" + Style.RESET_ALL)
        
        # Cache the validated deals
        self._deals_cache = validated_deals
        self._deals_cache_timestamp = current_time
        print(Fore.CYAN + f"[CACHE UPDATE] Updated cache with {len(validated_deals)} deals" + Style.RESET_ALL)
        
        return validated_deals

    def get_deal_timeline(self, deal_name: str, include_content: bool = False) -> Dict[str, Any]:
        """Get timeline data for a specific deal. Returns email content if include_content is True"""
        import concurrent.futures
        from datetime import datetime
        print(Fore.CYAN + f"Getting timeline for deal: {deal_name}" + Style.RESET_ALL)
        
        try:
            if hasattr(self, '_find_deal_id'):
                deal_id = self._find_deal_id(deal_name)
            else:
                deals_url = "https://api.hubapi.com/crm/v3/objects/deals"
                params = {"properties": "dealname,id", "limit": "100"}
                
                all_deals = []
                after = None
                
                while True:
                    if after:
                        params["after"] = after
                        
                    response = self._session.get(deals_url, params=params) if hasattr(self, '_session') else requests.get(deals_url, headers=self.headers, params=params)
                    
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
                        print(Fore.CYAN + f"[ERROR][get_deal_timeline] Error fetching deals: {response.status_code}" + Style.RESET_ALL)
                        return {"events": [], "start_date": None, "end_date": None}
                
                # Find the deal ID by matching deal name
                deal_id = None
                for deal in all_deals:
                    if deal.get('properties', {}).get('dealname') == deal_name:
                        deal_id = deal.get('id')
                        break
            
            if not deal_id:
                print(f"Deal with name '{deal_name}' not found.")
                return {"events": [], "start_date": None, "end_date": None}
            
            # Now fetch activities for this deal
            engagement_url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}/associations/engagements"
            
            # Use _session if available, otherwise fallback
            engagement_response = self._session.get(engagement_url) if hasattr(self, '_session') else requests.get(engagement_url, headers=self.headers)
            
            if engagement_response.status_code != 200:
                print(Fore.CYAN + f"[ERROR][get_deal_timeline] Error fetching engagements: {engagement_response.status_code}" + Style.RESET_ALL)
                return {"events": [], "start_date": None, "end_date": None}
            
            engagement_results = engagement_response.json().get("results", [])
            engagement_ids = [result.get("id") for result in engagement_results]
            
            if not engagement_ids:
                print(Fore.CYAN + f"No activities found for deal: {deal_name}" + Style.RESET_ALL)
                return {"events": [], "start_date": None, "end_date": None}
            
            print(Fore.CYAN + f"Found {len(engagement_ids)} activities for this deal" + Style.RESET_ALL)
            
            # Initialize or clear the cache for this deal
            if not hasattr(self, '_engagement_cache'):
                self._engagement_cache = {}
            
            deal_cache_key = f"deal_{deal_id}"
            print(Fore.CYAN + f"Adding this deal to cache: {deal_cache_key}" + Style.RESET_ALL)
            self._engagement_cache[deal_cache_key] = {}
            
            timeline_events = []
            start_engagement_date = None
            latest_engagement_date = None
            
            # Thread to process engagements in parallel
            def fetch_and_process_engagement(eng_id):
                try:
                    detail_url = f"https://api.hubapi.com/crm/v3/objects/engagements/{eng_id}"
                    detail_params = {
                        "properties": "hs_engagement_type,hs_timestamp,hs_email_subject,hs_email_text,hs_note_body,hs_call_body,hs_meeting_title,hs_meeting_body,hs_task_body"
                    }
                    
                    # Use _session if available, otherwise fallback
                    detail_response = self._session.get(detail_url, params=detail_params) if hasattr(self, '_session') else requests.get(detail_url, headers=self.headers, params=detail_params)
                    
                    if detail_response.status_code != 200:
                        return None
                        
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
                        return None  # Skip events without a timestamp
                    
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
                        result = self.gong_service.get_buyer_intent(
                            call_title=subject.strip(), 
                            call_date=date_time.strftime('%Y-%m-%d'),
                            seller_name="Atin Sanyal"
                        )
                        # Add null check here
                        if result is not None:
                            buyer_intent = result
                        else:
                            print(Fore.YELLOW + f"No transcript found for meeting: {subject.strip()} on {date_time.strftime('%Y-%m-%d')}" + Style.RESET_ALL)
                        
                    ## content
                    sentiment = "neutral"
                    if content is not None and content != "":
                        # Truncate content to a reasonable length before analysis
                        max_content_length = 10000  # Roughly 2500 tokens
                        if len(content) > max_content_length:
                            content = content[:max_content_length] + "..."
                            
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
                                Shorten the content of the email to 2 lines: {content}
                            """
                        )
                        
                    # Prepare content preview
                    content_preview = content[:150] + "..." if len(content) > 150 else content
                    
                    # Store in thread-safe way
                    cache_data = {
                        "type": display_type,
                        "subject": subject,
                        "date_str": date_time.strftime('%Y-%m-%d'),
                        "time_str": date_time.strftime('%H:%M'),
                        "content": content,
                        "sentiment": sentiment,
                        "content_preview": content_preview,
                        "buyer_intent": buyer_intent["intent"],
                        "buyer_intent_explanation": buyer_intent["explanation"]
                    }
                    
                    # Create event object
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
                    
                    return {
                        "event": event, 
                        "date_time": date_time,
                        "cache_data": cache_data,
                        "event_id": event_id
                    }
                except Exception as e:
                    print(Fore.RED + f"[ERROR][get_deal_timeline] Error processing engagement {eng_id}: {str(e)}" + Style.RESET_ALL)
                    import traceback
                    traceback.print_exc()
                    return None
            
            # Use thread pool to process engagements in parallel
            cache_updates = {}
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_engagement = {
                    executor.submit(fetch_and_process_engagement, eng_id): eng_id 
                    for eng_id in engagement_ids
                }
                
                for future in concurrent.futures.as_completed(future_to_engagement):
                    try:
                        result = future.result()
                        if result is None:
                            continue
                            
                        timeline_events.append(result["event"])
                        date_time = result["date_time"]
                        
                        # Track first and last engagement dates
                        if start_engagement_date is None or date_time < start_engagement_date:
                            start_engagement_date = date_time
                        if latest_engagement_date is None or date_time > latest_engagement_date:
                            latest_engagement_date = date_time
                            
                        # Store cache updates for applying after processing
                        cache_updates[result["event_id"]] = result["cache_data"]
                    except Exception as e:
                        print(Fore.RED + f"[ERROR][get_deal_timeline] Error processing future result: {str(e)}" + Style.RESET_ALL)
                        continue
            
            # Apply cache updates
            self._engagement_cache[deal_cache_key].update(cache_updates)
            
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
            
            # Ensure all required fields are present and properly formatted
            response = {
                "events": timeline_events,
                "start_date": start_engagement_date.strftime('%Y-%m-%d') if start_engagement_date else None,
                "end_date": latest_engagement_date.strftime('%Y-%m-%d') if latest_engagement_date else None,
                "deal_id": str(deal_id),  # Ensure deal_id is a string
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
            
            # Validate the response structure
            if not isinstance(response["events"], list):
                response["events"] = []
            if not isinstance(response["champions_summary"]["champions"], list):
                response["champions_summary"]["champions"] = []
            
            return response
        except Exception as e:
            print(Fore.RED + f"[ERROR][get_deal_timeline] Error in get_deal_timeline: {str(e)}" + Style.RESET_ALL)
            import traceback
            traceback.print_exc()
            return {"events": [], "start_date": None, "end_date": None, "error": str(e)}

    def _find_deal_id(self, deal_name: str) -> str:
        """Find a deal ID by name, with caching"""
        # Check cache first
        if not hasattr(self, '_deal_id_cache'):
            self._deal_id_cache = {}
            
        if deal_name in self._deal_id_cache:
            print(Fore.CYAN + f"[CACHE LOOKUP] Deal ID found in cache: {deal_name}" + Style.RESET_ALL)
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
                print(Fore.RED + f"[ERROR][get_deal_timeline] Error fetching deals: {response.status_code}" + Style.RESET_ALL)
                return None
        
        # Find the deal ID by matching deal name
        for deal in all_deals:
            if deal.get('properties', {}).get('dealname') == deal_name:
                deal_id = deal.get('id')
                if deal_id:
                    self._deal_id_cache[deal_name] = deal_id
                    return deal_id

        return None

    def get_event_content(self, deal_id: str, eng_id: str) -> Dict[str, Any]:
        """Get content for a specific event using just the engagement ID"""
        deal_cache_key = f"deal_{deal_id}"
        
        if not hasattr(self, '_engagement_cache') or not self._engagement_cache:
            return {"error": "No cached events found. Key: " + deal_cache_key}
        
        deal_cache = self._engagement_cache.get(deal_cache_key, {})
        if not deal_cache:
            return {"error": f"No cached events found for key {deal_cache_key}"}
        
        # Find event with this engagement ID prefix
        for cached_event_id, cached_event_data in deal_cache.items():
            # event_id format: "{eng_id}_{timestamp}"
            cached_eng_id = cached_event_id.split('_')[0]
            
            if cached_eng_id == eng_id:
                return cached_event_data
        
        return {"error": f"Event with engagement ID {eng_id} not found"}

    def get_deal_activities_count(self, deal_name: str) -> int:
        """Get the count of activities for a specific deal"""
        print(Fore.CYAN + f"Getting activities count for deal: {deal_name}" + Style.RESET_ALL)

        # First try to get deal ID from cache
        if hasattr(self, '_deal_id_cache') and deal_name in self._deal_id_cache:
            deal_id = self._deal_id_cache[deal_name]
            print(Fore.CYAN + f"Found deal ID in cache: {deal_id}" + Style.RESET_ALL)
        else:
            # If not in cache, try to find it in the deals cache
            if self._deals_cache is not None:
                for deal in self._deals_cache:
                    if deal.get('dealname') == deal_name:
                        deal_id = deal.get('dealId')
                        if deal_id:
                            self._deal_id_cache[deal_name] = deal_id
                            print(Fore.CYAN + f"Found deal ID in deals cache: {deal_id}" + Style.RESET_ALL)
                            break
                else:
                    print(Fore.YELLOW + f"Deal '{deal_name}' not found in deals cache, fetching fresh data..." + Style.RESET_ALL)
                    # If not found in cache, fetch fresh data
                    deals = self.get_all_deals()
                    for deal in deals:
                        if deal.get('dealname') == deal_name:
                            deal_id = deal.get('dealId')
                            if deal_id:
                                self._deal_id_cache[deal_name] = deal_id
                                print(Fore.CYAN + f"Found deal ID in fresh data: {deal_id}" + Style.RESET_ALL)
                                break
                    else:
                        print(Fore.RED + f"Deal with name '{deal_name}' not found in any cache or fresh data." + Style.RESET_ALL)
                        return 0
            else:
                print(Fore.RED + "No deals cache available, fetching fresh data..." + Style.RESET_ALL)
                deals = self.get_all_deals()
                for deal in deals:
                    if deal.get('dealname') == deal_name:
                        deal_id = deal.get('dealId')
                        if deal_id:
                            self._deal_id_cache[deal_name] = deal_id
                            print(Fore.CYAN + f"Found deal ID in fresh data: {deal_id}" + Style.RESET_ALL)
                            break
                else:
                    print(Fore.RED + f"Deal with name '{deal_name}' not found in fresh data." + Style.RESET_ALL)
                    return 0

        if not deal_id:
            print(Fore.RED + f"Could not find deal ID for deal: {deal_name}" + Style.RESET_ALL)
            return 0

        # Now fetch activities for this deal
        engagement_url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}/associations/engagements"
        
        try:
            engagement_response = self._session.get(engagement_url)
            
            if engagement_response.status_code == 404:
                print(Fore.YELLOW + f"No engagements found for deal: {deal_name}" + Style.RESET_ALL)
                return 0
                
            if engagement_response.status_code != 200:
                print(Fore.RED + f"Error fetching engagements: {engagement_response.status_code}" + Style.RESET_ALL)
                return 0
            
            engagement_results = engagement_response.json().get("results", [])
            engagement_count = len(engagement_results)
            
            print(Fore.GREEN + f"Found {engagement_count} activities for deal: {deal_name}" + Style.RESET_ALL)
            return engagement_count
            
        except Exception as e:
            print(Fore.RED + f"Exception while fetching engagements: {str(e)}" + Style.RESET_ALL)
            return 0