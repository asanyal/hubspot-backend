from fastapi import APIRouter, HTTPException, Query, Request
from typing import List, Dict, Any, Optional
from datetime import datetime
from collections import Counter
from bson import ObjectId
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_activity_repository import DealActivityRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.deal_meeting_info_repository import DealMeetingInfoRepository
from colorama import Fore, Style, init

init()

router = APIRouter()
deal_info_repo = DealInfoRepository()
deal_activity_repo = DealActivityRepository()
deal_timeline_repo = DealTimelineRepository()
deal_meeting_info_repo = DealMeetingInfoRepository()

def convert_mongo_doc(doc: Dict) -> Dict:
    """Convert MongoDB document to JSON-serializable format"""
    if doc is None:
        return None
    
    # Convert ObjectId to string
    if '_id' in doc:
        doc['_id'] = str(doc['_id'])
    
    # Convert datetime objects to ISO format strings
    for key, value in doc.items():
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, ObjectId):
            doc[key] = str(value)
    
    return doc

@router.get("/health", status_code=200)
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "v2"}

@router.get("/stages", response_model=List[Dict[str, Any]])
async def get_pipeline_stages():
    """Get all pipeline stages from MongoDB"""
    print(Fore.BLUE + "#### Fetching pipeline stages from MongoDB" + Style.RESET_ALL)
    try:
        # Get all deals from MongoDB
        all_deals = deal_info_repo.get_all_deals()
        
        # Extract unique stages and their details
        stages = []
        seen_stages = set()
        
        for deal in all_deals:
            stage = deal.get('stage')
            if stage and stage not in seen_stages:
                seen_stages.add(stage)
                # Determine if it's a closed stage
                is_closed_won = any(closed_stage in stage.lower() for closed_stage in ['closed won', 'renew/closed won'])
                is_closed_lost = any(closed_stage in stage.lower() for closed_stage in ['closed lost', 'churned'])
                
                stages.append({
                    "stage_name": stage,
                    "display_order": len(stages),  # Use the order we find them in
                    "probability": None,
                    "closed_won": str(is_closed_won).lower(),
                    "closed_lost": is_closed_lost
                })
        
        # Sort stages by display_order
        stages.sort(key=lambda x: x["display_order"])
        
        return stages
    except Exception as e:
        print(Fore.RED + f"Error fetching pipeline stages: {str(e)}" + Style.RESET_ALL)
        raise HTTPException(status_code=500, detail=f"Error fetching pipeline stages: {str(e)}")

@router.get("/deals", response_model=List[Dict[str, Any]])
async def get_deals_by_stage(stage: str = Query(..., description="The name of the pipeline stage")):
    """Get all deals in a specific pipeline stage from MongoDB"""
    print(Fore.BLUE + f"#### Fetching deals for stage: '{stage}'" + Style.RESET_ALL)
    try:
        # Query MongoDB for deals in the specified stage
        deals = deal_info_repo.find_many({"stage": stage})
        
        if not deals:
            print(Fore.RED + f"No deals found for stage: '{stage}'" + Style.RESET_ALL)
            
            # Get available stages to help with debugging
            all_deals = deal_info_repo.get_all_deals()
            available_stages = set(deal.get('stage') for deal in all_deals if deal.get('stage'))
            
            similar_stages = [s for s in available_stages if s.lower() == stage.lower() or stage.lower() in s.lower()]
            if similar_stages:
                print(Fore.BLUE + f"Similar stages found: {similar_stages}" + Style.RESET_ALL)
        
        # Convert MongoDB documents to match v1 API format
        formatted_deals = []
        for deal in deals:
            # Convert dates to the required format
            created_at = deal.get('created_date')
            if created_at:
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                created_at = created_at.strftime('%b %d, %Y')
            
            last_updated = deal.get('last_updated')
            if last_updated:
                if isinstance(last_updated, str):
                    last_updated = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                days_ago = (datetime.now() - last_updated).days
                last_update = f"{days_ago} days ago"
            else:
                last_update = "Unknown"
            
            # Format the deal data
            formatted_deal = {
                "Deal_Name": deal.get('deal_id', 'N/A'),
                "Owner": deal.get('owner', 'N/A'),
                "Amount": deal.get('amount', 'N/A'),  # This will be added to the schema later
                "Created_At": created_at or "Not set",
                "Last_Update": last_update,
                "Expected_Close_Date": deal.get('expected_close_date', 'Not set'),  # This will be added to the schema later
                "Closed_Won": "Yes" if deal.get('is_closed_won') else "No",
                "Closed_Lost": "Yes" if deal.get('is_closed_lost') else "No"
            }
            formatted_deals.append(formatted_deal)
        
        return formatted_deals
    except Exception as e:
        print(Fore.RED + f"Error in get_deals_by_stage endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching deals: {str(e)}")

@router.get("/all-deals", response_model=List[Dict[str, Any]])
async def get_all_deals():
    """Get a list of all deals for dropdown selection"""
    print(Fore.BLUE + "#### Getting all deals from MongoDB" + Style.RESET_ALL)
    try:
        all_deals = deal_info_repo.get_all_deals()
        
        deal_list = [
            {
                "id": index,  # Using index as ID since HubSpot IDs might be complex
                "name": deal.get('deal_name', 'Unnamed Deal'),
                "createdate": deal.get('created_date'),
                "stage": deal.get('stage', 'Unknown Stage'),
                "owner": deal.get('owner', 'Unknown Owner')
            }
            for index, deal in enumerate(all_deals)
            if deal.get('deal_name')  # Skip deals without names
        ]
        
        # Sort by createdate descending
        deal_list = sorted(deal_list, key=lambda x: x['createdate'], reverse=True)
        
        return deal_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching deals: {str(e)}")

@router.get("/deal-timeline", response_model=Dict[str, Any])
async def get_deal_timeline(
    request: Request,
    dealName: str = Query(..., description="The name of the deal")
):
    """Get timeline data for a specific deal"""
    print(Fore.BLUE + f"#### Getting timeline for deal: {dealName}" + Style.RESET_ALL)
    try:
        # Get deal info first to get the deal_id
        deal_info = deal_info_repo.get_by_deal_id(dealName)
        if not deal_info:
            raise HTTPException(status_code=404, detail=f"Deal not found: {dealName}")
            
        # Get timeline data
        timeline_data = deal_timeline_repo.get_by_deal_id(dealName)
        if not timeline_data:
            return {
                "events": [],
                "start_date": None,
                "end_date": None,
                "deal_id": dealName,
                "champions_summary": {
                    "total_contacts": 0,
                    "champions_count": 0,
                    "meeting_count": 0,
                    "champions": []
                }
            }
            
        # Get meeting info for champion data
        meeting_info = deal_meeting_info_repo.get_by_deal_id(dealName)
        
        # Process champions data
        all_champions = []
        meeting_count = 0
        if meeting_info:
            for meeting in meeting_info:
                if meeting.get('champion_analysis'):
                    all_champions.extend(meeting['champion_analysis'])
                meeting_count += 1
        
        # Remove duplicates based on email
        unique_champions = {champ["email"]: champ for champ in all_champions}.values()
        champions_count = sum(1 for champ in unique_champions if champ.get("champion", False))
        total_contacts = len(unique_champions)
        
        # Format events to match old format
        formatted_events = []
        for event in timeline_data.get('events', []):
            # Parse the event date
            event_date = event.get('event_date')
            if isinstance(event_date, str):
                try:
                    event_date = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    event_date = datetime.now()
            
            # Format the event to match old format
            formatted_event = {
                "id": event.get('event_id', ''),
                "engagement_id": event.get('engagement_id', ''),
                "date_str": event_date.strftime('%Y-%m-%d') if event_date else '',
                "time_str": event_date.strftime('%H:%M') if event_date else '',
                "type": event.get('event_type', ''),
                "subject": event.get('subject', ''),
                "content": event.get('content', ''),
                "content_preview": event.get('content_preview', ''),
                "sentiment": event.get('sentiment', 'neutral'),
                "buyer_intent": event.get('buyer_intent', 'N/A'),
                "buyer_intent_explanation": event.get('buyer_intent_explanation', 'N/A')
            }
            formatted_events.append(formatted_event)
        
        # Format the response
        response = {
            "events": formatted_events,
            "start_date": timeline_data.get('start_date'),
            "end_date": timeline_data.get('end_date'),
            "deal_id": dealName,
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
        print(Fore.RED + f"Error in deal_timeline endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching deal timeline: {str(e)}")

@router.get("/deal-info", response_model=Dict[str, Any])
async def get_deal_info(dealName: str = Query(..., description="The name of the deal")):
    print(Fore.BLUE + f"#### Getting deal info for: {dealName}" + Style.RESET_ALL)
    try:
        # Get deal info
        deal_info = deal_info_repo.get_by_deal_id(dealName)
        if not deal_info:
            return {
                "dealId": "Not found",
                "dealOwner": "Not found",
                "activityCount": 0,
                "startDate": None,
                "endDate": None
            }
            
        # Get timeline data for activity count and dates
        timeline_data = deal_timeline_repo.get_by_deal_id(dealName)
        
        activity_count = len(timeline_data.get('events', [])) if timeline_data else 0
        start_date = timeline_data.get('start_date') if timeline_data else None
        end_date = timeline_data.get('end_date') if timeline_data else None
        
        return {
            "dealId": deal_info.get('deal_id', 'Not found'),
            "dealOwner": deal_info.get('owner', 'Not found'),
            "dealStage": deal_info.get('stage', 'Unknown'),
            "activityCount": activity_count,
            "startDate": start_date,
            "endDate": end_date
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching deal info: {str(e)}")

@router.get("/contacts-and-champion", response_model=Dict[str, Any])
async def get_contacts_and_champion(
    request: Request,
    dealName: str = Query(..., description="The name of the deal"),
    date: str = Query(..., description="The date to search around in YYYY-MM-DD format")
):
    print(Fore.BLUE + f"[{date}] Contacts and champion for deal: {dealName}" + Style.RESET_ALL)
    try:
        # Get meeting info for the deal
        meeting_info = deal_meeting_info_repo.get_by_deal_id(dealName)
        if not meeting_info:
            return {
                "contacts": [],
                "total_contacts": 0,
                "champions_count": 0
            }
            
        # Collect all champions from all meetings
        all_champions = []
        for meeting in meeting_info:
            if meeting.get('champion_analysis'):
                all_champions.extend(meeting['champion_analysis'])
        
        # Remove duplicates based on email
        unique_champions = {champ["email"]: champ for champ in all_champions}.values()
        champions_count = sum(1 for champ in unique_champions if champ.get("champion", False))
        
        return {
            "contacts": list(unique_champions),
            "total_contacts": len(unique_champions),
            "champions_count": champions_count
        }
    except Exception as e:
        print(Fore.RED + f"Error in contacts-and-champion endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error identifying contacts and champion: {str(e)}")

@router.get("/get-concerns", response_model=Dict[str, Any])
async def get_concerns(
    call_title: str = Query(..., description="The title of the call to analyze"),
    call_date: str = Query(..., description="The date of the call in YYYY-MM-DD format")
):
    """Get potential concerns analysis for a specific call"""
    print(Fore.BLUE + f"#### Getting concerns for call: {call_title} on {call_date}" + Style.RESET_ALL)
    try:
        # Get deal activity data
        deal_activity = deal_activity_repo.get_by_deal_id(call_title)
        if not deal_activity:
            return {
                "pricing_concerns": {"has_concerns": False, "explanation": "No data available"},
                "no_decision_maker": {"is_issue": False, "explanation": "No data available"},
                "already_has_vendor": {"has_vendor": False, "explanation": "No data available"}
            }
            
        # Get the most recent concerns from the concerns array
        concerns = deal_activity.get('concerns', [])
        if not concerns:
            return {
                "pricing_concerns": {"has_concerns": False, "explanation": "No concerns data available"},
                "no_decision_maker": {"is_issue": False, "explanation": "No concerns data available"},
                "already_has_vendor": {"has_vendor": False, "explanation": "No concerns data available"}
            }
            
        # Get the most recent concerns (last in the array)
        latest_concerns = concerns[-1]
        
        return {
            "pricing_concerns": latest_concerns.get('pricing_concerns', {"has_concerns": False, "explanation": "No pricing concerns data"}),
            "no_decision_maker": latest_concerns.get('no_decision_maker', {"is_issue": False, "explanation": "No decision maker data"}),
            "already_has_vendor": latest_concerns.get('already_has_vendor', {"has_vendor": False, "explanation": "No vendor data"})
        }
    except Exception as e:
        print(Fore.RED + f"Error in get-concerns endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error analyzing call concerns: {str(e)}")

@router.get("/deal-activities-count", response_model=Dict[str, int])
async def get_deal_activities_count(dealName: str = Query(..., description="The name of the deal")):
    """Get the count of activities for a specific deal"""
    print(Fore.BLUE + f"#### Getting deal activities count for: {dealName}" + Style.RESET_ALL)
    try:
        # Get timeline data
        timeline_data = deal_timeline_repo.get_by_deal_id(dealName)
        activity_count = len(timeline_data.get('events', [])) if timeline_data else 0
        
        return {"count": activity_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching deal activities count: {str(e)}")

@router.get("/pipeline-summary", response_model=List[Dict[str, Any]])
async def get_pipeline_summary():
    """Get a summary of the pipeline with counts and amounts by stage"""
    print(Fore.BLUE + "#### Get Pipeline Summary" + Style.RESET_ALL)
    try:
        # Get all deals
        all_deals = deal_info_repo.get_all_deals()
        
        # Extract stages
        stages = [deal.get('stage', 'Unknown') for deal in all_deals if deal.get('stage')]
        
        # Count number of deals in each stage
        stage_counts = Counter(stages)
        
        # Create summary data
        summary = [
            {
                "stage": stage,
                "count": count,
                "amount": 0  # Amount not available in MongoDB schema
            }
            for stage, count in stage_counts.items()
        ]
        
        # Sort by count descending
        summary = sorted(summary, key=lambda x: x["count"], reverse=True)
        
        return summary
    except Exception as e:
        print(Fore.RED + f"Pipeline summary error: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating pipeline summary: {str(e)}") 