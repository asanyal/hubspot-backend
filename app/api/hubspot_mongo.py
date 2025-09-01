from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from collections import Counter
from bson import ObjectId
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_insights_repository import DealInsightsRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.meeting_insights_repository import MeetingInsightsRepository
from app.repositories.company_overview_repository import CompanyOverviewRepository
from app.services.data_sync_service import DataSyncService
from app.services.dss2 import DataSyncService2
from app.repositories.deal_owner_performance_repository import DealOwnerPerformanceRepository
from colorama import Fore, Style, init
import threading
import queue
from pydantic import BaseModel
from app.services.llm_service import ask_openai

init()

router = APIRouter()

class SignalsResponse(BaseModel):
    very_likely_to_buy: int
    likely_to_buy: int
    less_likely_to_buy: int
deal_info_repo = DealInfoRepository()
deal_insights_repo = DealInsightsRepository()
deal_timeline_repo = DealTimelineRepository()
meeting_insights_repo = MeetingInsightsRepository()
company_overview_repo = CompanyOverviewRepository()
sync_service = DataSyncService()
sync_service_v2 = DataSyncService2()
deal_owner_performance_repo = DealOwnerPerformanceRepository()

# Store for tracking sync jobs
sync_jobs = {}
sync_job_queue = queue.Queue()
active_threads = {}

class DealNamesRequest(BaseModel):
    deal_names: List[str]

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

def sort_signal_dates_in_performance_data(performance_data: Dict) -> Dict:
    """Sort signal dates by recency (most recent first) in deal owner performance data"""
    
    def parse_date_for_sorting(date_str):
        try:
            return datetime.strptime(date_str, '%d %b %Y')
        except ValueError:
            # If parsing fails, return a very old date so it goes to the end
            return datetime(1900, 1, 1)
    
    # Check if this is a single owner's data or multiple owners
    if 'deals_performance' in performance_data:
        # Single owner data
        deals_performance = performance_data['deals_performance']
        for sentiment, sentiment_data in deals_performance.items():
            if 'deals' in sentiment_data:
                for deal in sentiment_data['deals']:
                    if isinstance(deal, dict) and 'signal_dates' in deal:
                        deal['signal_dates'] = sorted(deal['signal_dates'], key=parse_date_for_sorting, reverse=True)
    elif 'owners' in performance_data:
        # Multiple owners data
        for owner_data in performance_data['owners']:
            if 'deals_performance' in owner_data:
                deals_performance = owner_data['deals_performance']
                for sentiment, sentiment_data in deals_performance.items():
                    if 'deals' in sentiment_data:
                        for deal in sentiment_data['deals']:
                            if isinstance(deal, dict) and 'signal_dates' in deal:
                                deal['signal_dates'] = sorted(deal['signal_dates'], key=parse_date_for_sorting, reverse=True)
    
    return performance_data

@router.get("/health", status_code=200)
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "v2"}

@router.get("/test-signals")
async def test_signals():
    """Test endpoint for signals"""
    return {"message": "Signals endpoint is working"}

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
        
        # Get all deal names that have names
        deal_names = [deal.get('deal_name') for deal in all_deals if deal.get('deal_name')]
        
        # Get all timeline data in one call
        all_timeline_data = deal_timeline_repo.find_many({"deal_id": {"$in": deal_names}})
        
        # Create a lookup dictionary for quick access to activity counts
        activity_counts = {}
        for timeline in all_timeline_data:
            deal_id = timeline.get('deal_id')
            if deal_id:
                activity_counts[deal_id] = len(timeline.get('events', []))
        
        deal_list = []
        for index, deal in enumerate(all_deals):
            if deal.get('deal_name'):  # Skip deals without names
                deal_name = deal.get('deal_name')
                
                deal_info = {
                    "id": index,  # Using index as ID since HubSpot IDs might be complex
                    "name": deal_name,
                    "createdate": deal.get('created_date'),
                    "stage": deal.get('stage', 'Unknown Stage'),
                    "owner": "Unknown Owner" if not deal.get('owner') or deal.get('owner') == {} else deal.get('owner'),
                    "activities": activity_counts.get(deal_name, 0)
                }
                deal_list.append(deal_info)
        
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
                "events": "No events found",
                "start_date": None,
                "end_date": None,
                "deal_id": dealName,
                "champions_summary": {
                    "total_contacts": 0,
                    "champions_count": 0,
                    "meeting_count": 0,
                    "champions": "No champions found"
                }
            }
            
        
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
                "engagement_id": event.get('engagement_id', '') or '',  # Convert null to empty string
                "date_str": event_date.strftime('%Y-%m-%d') if event_date else '',
                "time_str": event_date.strftime('%H:%M') if event_date else '',
                "type": event.get('event_type', ''),
                "subject": event.get('subject', ''),
                "content": event.get('content', ''),
                "content_preview": event.get('content_preview', ''),
                "sentiment": event.get('sentiment', 'neutral'),
                "buyer_intent": event.get('buyer_intent', 'N/A'),
                "buyer_intent_explanation": event.get('buyer_intent_explanation', 'N/A') if isinstance(event.get('buyer_intent_explanation'), dict) else 'N/A'
            }
            formatted_events.append(formatted_event)

        # Format the response
        response = {
            "events": formatted_events,
            "start_date": timeline_data.get('start_date'),
            "end_date": timeline_data.get('end_date'),
            "deal_id": dealName,
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
                "dealOwner": "Unknown Owner",
                "activityCount": 0,
                "startDate": None,
                "endDate": None
            }
            
        # Get timeline data for activity count and dates
        timeline_data = deal_timeline_repo.get_by_deal_id(dealName)
        
        activity_count = len(timeline_data.get('events', [])) if timeline_data else 0
        start_date = timeline_data.get('start_date') if timeline_data else None
        end_date = timeline_data.get('end_date') if timeline_data else None
        
        # Prepare response
        response = {
            "dealId": deal_info.get('deal_id', 'Not found'),
            "dealOwner": deal_info.get('owner', 'Unknown Owner'),
            "dealStage": deal_info.get('stage', 'Unknown'),
            "activityCount": activity_count,
            "startDate": start_date,
            "endDate": end_date
        }
        
        # Ensure dealOwner is never an empty dictionary
        if response["dealOwner"] == {}:
            response["dealOwner"] = "Unknown Owner"
            
        return response
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
        meeting_info = meeting_insights_repo.get_by_deal_id(dealName)
        if not meeting_info:
            return {
                "contacts": "No contacts found",
                "total_contacts": 0,
                "champions_count": 0
            }
            
        all_attendees = []
        champions = []
        for meeting in meeting_info:
            if meeting.get('buyer_attendees'):
                all_attendees.extend(meeting['buyer_attendees'])
        
        return {
            "contacts": list(all_attendees),
            "total_attendees": len(all_attendees),
            "champions_count": len(champions)
        }
    except Exception as e:
        print(Fore.RED + f"Error in contacts-and-champion endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error identifying contacts and champion: {str(e)}")

@router.get("/get-concerns", response_model=List[Dict[str, Any]])
async def get_concerns(
    dealName: str = Query(..., description="The name of the deal"),
):
    print(Fore.BLUE + f"#### Getting concerns for deal: {dealName}." + Style.RESET_ALL)
    try:
        # Get deal insights
        deal_activity = deal_insights_repo.get_by_deal_id(dealName)
        if not deal_activity:
            print(Fore.YELLOW + f"No deal insights found for: {dealName}" + Style.RESET_ALL)
            # Return structured response with "N/A" values
            return [{
                "pricing_concerns": {
                    "has_concerns": "N/A",
                    "explanation": ""
                },
                "no_decision_maker": {
                    "is_issue": "N/A",
                    "explanation": ""
                },
                "already_has_vendor": {
                    "has_vendor": "N/A",
                    "explanation": ""
                }
            }]

        concerns = deal_activity.get("concerns", [])
        if not concerns:
            print(Fore.YELLOW + f"No concerns data found for: {dealName}" + Style.RESET_ALL)
            # Return structured response with "N/A" values
            return [{
                "pricing_concerns": {
                    "has_concerns": "N/A",
                    "explanation": ""
                },
                "no_decision_maker": {
                    "is_issue": "N/A",
                    "explanation": ""
                },
                "already_has_vendor": {
                    "has_vendor": "N/A",
                    "explanation": ""
                }
            }]

        # Handle both old format (dict) and new format (list)
        if isinstance(concerns, dict):
            # Convert old format to list format
            concerns_list = [concerns]
        elif isinstance(concerns, list):
            concerns_list = concerns
        else:
            print(Fore.YELLOW + f"Invalid concerns format for: {dealName}" + Style.RESET_ALL)
            # Return structured response with "N/A" values
            return [{
                "pricing_concerns": {
                    "has_concerns": "N/A",
                    "explanation": ""
                },
                "no_decision_maker": {
                    "is_issue": "N/A",
                    "explanation": ""
                },
                "already_has_vendor": {
                    "has_vendor": "N/A",
                    "explanation": ""
                }
            }]

        print(Fore.GREEN + f"Returning {len(concerns_list)} concerns for deal: {dealName}" + Style.RESET_ALL)
        return concerns_list

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
        
        # Create a dictionary to store stage summaries
        stage_summary = {}
        
        for deal in all_deals:
            stage = deal.get('stage', 'Unknown')
            amount_str = deal.get('amount')
            
            # Convert amount string to float, handling currency format and None values
            try:
                if amount_str is None:
                    amount = 0
                else:
                    # Remove $ and commas, then convert to float
                    amount = float(str(amount_str).replace('$', '').replace(',', ''))
            except (ValueError, TypeError):
                amount = 0
            
            if stage not in stage_summary:
                stage_summary[stage] = {
                    "stage": stage,
                    "count": 0,
                    "amount": 0
                }
            
            stage_summary[stage]["count"] += 1
            stage_summary[stage]["amount"] += amount
        
        # Convert dictionary to list and sort by count
        summary = list(stage_summary.values())
        summary = sorted(summary, key=lambda x: x["count"], reverse=True)
        
        return summary
    except Exception as e:
        print(Fore.RED + f"Pipeline summary error: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating pipeline summary: {str(e)}")

@router.get("/company-overview", response_model=Dict[str, str])
async def get_company_overview(dealName: str = Query(..., description="The name of the deal")):
    """Get company overview for a specific deal from MongoDB"""
    print(Fore.BLUE + f"#### Getting company overview for deal: {dealName}" + Style.RESET_ALL)
    
    try:
        # Get meeting insights from MongoDB
        meeting_insights = meeting_insights_repo.get_by_deal_id(dealName)
        
        if not meeting_insights:
            print(Fore.YELLOW + f"No meeting insights found for deal: {dealName}" + Style.RESET_ALL)
            return {"overview": "-"}
        
        # Sort meeting insights by date with latest first
        def get_meeting_date(meeting):
            meeting_date = meeting.get('meeting_date')
            if isinstance(meeting_date, str):
                try:
                    return datetime.strptime(meeting_date, "%Y-%m-%d")
                except ValueError:
                    return datetime.min
            elif isinstance(meeting_date, datetime):
                return meeting_date
            else:
                return datetime.min
        
        # Sort by meeting_date in descending order (latest first)
        meeting_insights.sort(key=get_meeting_date, reverse=True)
        
        print(Fore.BLUE + f"Found {len(meeting_insights)} meetings for deal: {dealName}" + Style.RESET_ALL)
        
        limited_meetings = meeting_insights[:6]
        print(Fore.BLUE + f"Processing first {len(limited_meetings)} most recent meetings for deal: {dealName}" + Style.RESET_ALL)
        
        all_transcripts = []
        for meeting in limited_meetings:
            transcript = meeting.get('transcript', '')
            if transcript and transcript.strip():
                all_transcripts.append(transcript.strip())
        
        if not all_transcripts:
            print(Fore.YELLOW + f"No transcripts found for deal: {dealName}" + Style.RESET_ALL)
            return {"overview": "-"}
        
        # Concatenate and cap at 10000 characters
        combined_transcript = " ".join(all_transcripts)
        if len(combined_transcript) > 10000:
            combined_transcript = combined_transcript[:10000]
        
        print(Fore.GREEN + f"Combined transcript length: {len(combined_transcript)} characters for deal: {dealName}" + Style.RESET_ALL)
        
        summary_prompt = f"""
        Please summarize the following transcript - conversation between the buyer and seller - in 2-3 lines. 
        The seller is always Galileo. The product being sold is Galileo.
        Focus on the key points in the transcript, any decisions made, any positive or negative signals (less likely to buy, likely to buy). Use gerund phrases. Only return the summary, no other text.

        Transcript:
        {combined_transcript}
        """
        
        summary = ask_openai(
            user_content=summary_prompt,
            system_content="You are a sales analyst that creates concise, informative summaries of meeting transcripts. Focus on key business insights and decisions."
        )
        
        return {"overview": summary}
        
    except Exception as e:
        print(Fore.RED + f"Error in company-overview endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        # Return a graceful response instead of raising an error
        return {"overview": "Error generating summary from meeting transcripts"}

@router.get("/get-signals")
async def get_signals(deal_name: Optional[str] = Query(None, description="The name of the deal")):
    """Get buyer intent signals from meeting events for a specific deal"""
    if not deal_name:
        raise HTTPException(status_code=400, detail="deal_name parameter is required")
    
    print(Fore.BLUE + f"#### Getting signals for deal: {deal_name}" + Style.RESET_ALL)
    
    try:
        # Get timeline data for the deal
        timeline_data = deal_timeline_repo.get_by_deal_id(deal_name)
        
        if not timeline_data:
            print(Fore.YELLOW + f"No timeline data found for deal: {deal_name}" + Style.RESET_ALL)
            return {
                "very_likely_to_buy": 0,
                "likely_to_buy": 0,
                "less_likely_to_buy": 0
            }
        
        # Initialize signal counters
        very_likely_to_buy = 0
        likely_to_buy = 0
        less_likely_to_buy = 0
        
        # Loop through events and count meeting signals
        events = timeline_data.get('events', [])
        print(f"Found {len(events)} events for deal {deal_name}")
        
        for event in events:
            event_type = event.get('event_type', '')
            buyer_intent = event.get('buyer_intent', '')
            print(f"Event type: {event_type}, Buyer intent: {buyer_intent}")
            
            if event_type == 'Meeting':
                # Map buyer_intent values to signal keys
                if buyer_intent == 'Very likely to buy':
                    very_likely_to_buy += 1
                elif buyer_intent == 'Likely to buy':
                    likely_to_buy += 1
                elif buyer_intent == 'Less likely to buy':
                    less_likely_to_buy += 1
        
        result = {
            "very_likely_to_buy": very_likely_to_buy,
            "likely_to_buy": likely_to_buy,
            "less_likely_to_buy": less_likely_to_buy
        }
        
        print(Fore.GREEN + f"Found signals for deal {deal_name}: {result}" + Style.RESET_ALL)
        return result
        
    except Exception as e:
        print(Fore.RED + f"Error in get-signals endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching signals: {str(e)}")

@router.post("/get-signals-group")
async def get_signals_group(deal_names: DealNamesRequest):
    """Get buyer intent signals from meeting events for multiple deals"""
    print(Fore.BLUE + f"#### Getting signals for {len(deal_names.deal_names)} deals" + Style.RESET_ALL)
    
    try:
        results = {}
        
        for deal_name in deal_names.deal_names:
            print(Fore.BLUE + f"Processing deal: {deal_name}" + Style.RESET_ALL)
            
            # Get timeline data for the deal
            timeline_data = deal_timeline_repo.get_by_deal_id(deal_name)
            
            if not timeline_data:
                print(Fore.YELLOW + f"No timeline data found for deal: {deal_name}" + Style.RESET_ALL)
                results[deal_name] = {
                    "very_likely_to_buy": 0,
                    "likely_to_buy": 0,
                    "less_likely_to_buy": 0
                }
                continue
            
            # Initialize signal counters
            very_likely_to_buy = 0
            likely_to_buy = 0
            less_likely_to_buy = 0
            
            # Loop through events and count meeting signals
            events = timeline_data.get('events', [])
            print(f"Found {len(events)} events for deal {deal_name}")
            
            for event in events:
                event_type = event.get('event_type', '')
                buyer_intent = event.get('buyer_intent', '')
                
                if event_type == 'Meeting':
                    # Map buyer_intent values to signal keys
                    if buyer_intent == 'Very likely to buy':
                        very_likely_to_buy += 1
                    elif buyer_intent == 'Likely to buy':
                        likely_to_buy += 1
                    elif buyer_intent == 'Less likely to buy':
                        less_likely_to_buy += 1
            
            result = {
                "very_likely_to_buy": very_likely_to_buy,
                "likely_to_buy": likely_to_buy,
                "less_likely_to_buy": less_likely_to_buy
            }
            
            results[deal_name] = result
            print(Fore.GREEN + f"Found signals for deal {deal_name}: {result}" + Style.RESET_ALL)
        
        print(Fore.GREEN + f"Completed processing {len(results)} deals" + Style.RESET_ALL)
        return results
        
    except Exception as e:
        print(Fore.RED + f"Error in get-signals-group endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching signals group: {str(e)}")

@router.get("/get-stakeholders")
async def get_stakeholders(deal_name: str = Query(..., description="The name of the deal")):
    """Get all stakeholders for a deal with decision maker analysis"""
    print(Fore.BLUE + f"#### Getting stakeholders for deal: {deal_name}" + Style.RESET_ALL)
    
    try:
        # Get all meeting insights for the deal
        meeting_insights = meeting_insights_repo.get_by_deal_id(deal_name)
        
        if not meeting_insights:
            print(Fore.YELLOW + f"No meeting insights found for deal: {deal_name}" + Style.RESET_ALL)
            return {"stakeholders": []}
        
        # Collect unique stakeholders using a set
        stakeholders_set = set()
        stakeholders_dict = {}
        
        for meeting in meeting_insights:
            buyer_attendees = meeting.get('buyer_attendees', [])
            for attendee in buyer_attendees:
                # Create a unique key based on email to avoid duplicates
                name = attendee.get('name', '')
                email = attendee.get('email', '')
                title = attendee.get('title', '')
                
                # Create unique identifier using email as primary key
                if email:
                    unique_key = email
                else:
                    # Fallback to name if no email available
                    unique_key = name
                
                if unique_key not in stakeholders_set:
                    stakeholders_set.add(unique_key)
                    stakeholders_dict[unique_key] = {
                        "name": name,
                        "email": email,
                        "title": title
                    }
        
        print(Fore.GREEN + f"Found {len(stakeholders_dict)} unique stakeholders for deal {deal_name}" + Style.RESET_ALL)
        
        # Analyze each stakeholder for decision maker potential
        
        
        stakeholders_with_analysis = []
        for unique_key, stakeholder in stakeholders_dict.items():
            title = stakeholder.get('title', '')
            
            potential_decision_maker = False
            if title:
                decision_maker_prompt = f"""
                Analyze if this person is likely to be a decision maker based on their job title.
                
                Job Title: {title}
                
                Decision makers are typically:
                - High-level individual contributors (Principal Engineer, Staff Engineer, Architect, etc.)
                - Management roles (Director, VP, Senior VP, C-suite, Founder, etc.)
                - People with significant influence over purchasing decisions
                
                Non-decision makers are typically:
                - Regular software engineers, developers, analysts
                - Junior or mid-level positions without purchasing authority
                
                Respond with only "Yes" or "No".
                """
                
                try:
                    response = ask_openai(
                        user_content=decision_maker_prompt,
                        system_content="You are a sales analyst that determines decision-making authority based on job titles. Respond only with 'Yes' or 'No'."
                    )
                    
                    response = response.strip().lower()
                    potential_decision_maker = response in ['yes', 'true', '1']
                    
                except Exception as e:
                    print(Fore.RED + f"Error analyzing decision maker for title '{title}': {str(e)}" + Style.RESET_ALL)
                    potential_decision_maker = False
            
            stakeholder_with_analysis = {
                "name": stakeholder["name"],
                "email": stakeholder["email"],
                "title": stakeholder["title"],
                "potential_decision_maker": potential_decision_maker
            }
            
            stakeholders_with_analysis.append(stakeholder_with_analysis)
        
        stakeholders_with_analysis.sort(key=lambda x: (-x['potential_decision_maker'], x['name'].lower()))
        
        print(Fore.GREEN + f"Completed stakeholder analysis for deal {deal_name}. Found {len(stakeholders_with_analysis)} stakeholders." + Style.RESET_ALL)
        return {"stakeholders": stakeholders_with_analysis}
        
    except Exception as e:
        print(Fore.RED + f"Error in get-stakeholders endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching stakeholders: {str(e)}")

@router.get("/get-latest-meetings", response_model=List[Dict[str, Any]])
async def get_latest_meetings(days: int = Query(2, description="Number of days to look back for meetings")):
    """Get all meetings from any deal that occurred from the start of N days ago to now"""
    print(Fore.BLUE + f"#### Getting latest meetings from the past {days} days" + Style.RESET_ALL)
    
    try:
        # Calculate the cutoff time (start of N days ago at 12am)
        now = datetime.now()
        cutoff_time = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        print(Fore.YELLOW + f"Current time: {now.isoformat()}" + Style.RESET_ALL)
        print(Fore.YELLOW + f"Cutoff time (start of day): {cutoff_time.isoformat()}" + Style.RESET_ALL)
        
        # Get all timeline documents
        all_timelines = deal_timeline_repo.find_many({})
        
        meetings = []
        total_meetings_checked = 0
        
        for timeline in all_timelines:
            deal_id = timeline.get('deal_id')
            events = timeline.get('events', [])
            
            for event in events:
                # Check if this is a meeting event
                if event.get('event_type') == 'Meeting':
                    total_meetings_checked += 1
                    event_date = event.get('event_date')
                    
                    # Handle different date formats
                    if isinstance(event_date, str):
                        try:
                            # Try to parse as ISO format first
                            event_date = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            try:
                                # Try to parse as datetime string
                                event_date = datetime.strptime(event_date, "%Y-%m-%d %H:%M")
                            except (ValueError, TypeError):
                                print(Fore.RED + f"Could not parse date string: {event_date}" + Style.RESET_ALL)
                                continue
                    elif not isinstance(event_date, datetime):
                        print(Fore.RED + f"Invalid event_date type: {type(event_date)}, value: {event_date}" + Style.RESET_ALL)
                        continue
                    
                    # Convert event_date to naive datetime if it has timezone info
                    if event_date.tzinfo is not None:
                        event_date = event_date.replace(tzinfo=None)
                    # Debug the comparison
                    is_after_cutoff = event_date >= cutoff_time
                    is_before_now = event_date <= now
                    within_range = is_after_cutoff and is_before_now
                    
                    # Check if event is within the time window (event_date should be <= now and >= cutoff_time)
                    if within_range:
                        # Filter out meetings with "Unknown" sentiment
                        sentiment = event.get('sentiment', '')
                        if sentiment.lower() == 'unknown':
                            print(Fore.YELLOW + f"✗ Skipped meeting (unknown sentiment): {event.get('subject', 'No subject')}" + Style.RESET_ALL)
                            continue
                        
                        meeting = {
                            "deal_id": deal_id,
                            "event_date": event_date.isoformat(),
                            "subject": event.get('subject', ''),
                            "sentiment": sentiment,
                            "buyer_intent": event.get('buyer_intent', ''),
                            "event_id": event.get('event_id', '')
                        }
                        meetings.append(meeting)
                        print(Fore.GREEN + f"✓ Added meeting: {meeting['subject']}" + Style.RESET_ALL) 
                               
        # Sort by event_date in descending order (most recent first)
        meetings.sort(key=lambda x: x['event_date'], reverse=True)
        
        print(Fore.GREEN + f"Found {len(meetings)} meetings in the past {days} days out of {total_meetings_checked} total meetings checked" + Style.RESET_ALL)
        return meetings
        
    except Exception as e:
        print(Fore.RED + f"Error in get-latest-meetings endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching latest meetings: {str(e)}")

@router.get("/deal-risk-score")
async def get_deal_risk_score(deal_name: str = Query(..., description="The name of the deal")):
    """Get risk score and analysis for a specific deal"""
    print(Fore.BLUE + f"#### Getting risk score for deal: {deal_name}" + Style.RESET_ALL)
    
    try:
        risk_factors = {}
        total_risk_score = 0
        data_sources = {}
        
        # 1. Get Deal Insights (concerns)
        deal_insights = deal_insights_repo.get_by_deal_id(deal_name)
        data_sources["deal_insights"] = deal_insights
        
        # 2. Get Deal Timeline
        timeline_data = deal_timeline_repo.get_by_deal_id(deal_name)
        data_sources["timeline_events"] = timeline_data
        
        # 3. Get Meeting Insights
        meeting_insights = meeting_insights_repo.get_by_deal_id(deal_name)
        data_sources["meeting_insights"] = meeting_insights
        
        # 4. Get Stakeholders
        stakeholders_response = await get_stakeholders(deal_name)
        stakeholders = stakeholders_response.get("stakeholders", [])
        data_sources["stakeholders"] = stakeholders
        
        # Calculate Risk Factors
        
        # Factor 1: No Decision Maker (0-25 points)
        no_decision_maker_score = 0
        no_decision_maker_details = []
        
        # Check deal insights first
        if deal_insights and deal_insights.get("concerns"):
            concerns = deal_insights.get("concerns")
            # Handle both old format (dict) and new format (list)
            if isinstance(concerns, dict):
                concerns_list = [concerns]
            elif isinstance(concerns, list):
                concerns_list = concerns
            else:
                concerns_list = []
            
            for concern in concerns_list:
                if isinstance(concern, dict) and concern.get("no_decision_maker", {}).get("is_issue", False):
                    no_decision_maker_score += 15
                    no_decision_maker_details.append("Deal insights indicate no decision maker identified")
                    break
        
        # Analyze stakeholders
        decision_makers = [s for s in stakeholders if s.get("potential_decision_maker", False)]
        if len(decision_makers) == 0:
            no_decision_maker_score += 10
            no_decision_maker_details.append("No decision makers found among stakeholders")
        else:
            no_decision_maker_details.append(f"Decision makers identified: {len(decision_makers)}")
        
        risk_factors["no_decision_maker"] = {
            "risk_score": no_decision_maker_score,
            "details": no_decision_maker_details,
            "max_score": 25
        }
        total_risk_score += no_decision_maker_score
        
        # Factor 2: Pricing Concerns (0-20 points)
        pricing_concerns_score = 0
        pricing_concerns_details = []
        
        if deal_insights and deal_insights.get("concerns"):
            concerns = deal_insights.get("concerns")
            if isinstance(concerns, dict):
                concerns_list = [concerns]
            elif isinstance(concerns, list):
                concerns_list = concerns
            else:
                concerns_list = []
            
            # Count pricing concerns
            pricing_concern_count = 0
            for concern in concerns_list:
                if isinstance(concern, dict) and concern.get("pricing_concerns", {}).get("has_concerns", False):
                    pricing_concern_count += 1
            
            if pricing_concern_count >= 2:
                pricing_concerns_score = 20
                pricing_concerns_details.append(f"High risk: {pricing_concern_count} pricing concerns identified")
            elif pricing_concern_count == 1:
                pricing_concerns_score = 10
                pricing_concerns_details.append("Medium risk: 1 pricing concern identified")
            else:
                pricing_concerns_details.append("No pricing concerns detected")
        
        risk_factors["pricing_concerns"] = {
            "risk_score": pricing_concerns_score,
            "details": pricing_concerns_details,
            "max_score": 20
        }
        total_risk_score += pricing_concerns_score
        
        # Factor 3: Competitor Presence (0-20 points)
        competitor_score = 0
        competitor_details = []
        
        if deal_insights and deal_insights.get("concerns"):
            concerns = deal_insights.get("concerns")
            if isinstance(concerns, dict):
                concerns_list = [concerns]
            elif isinstance(concerns, list):
                concerns_list = concerns
            else:
                concerns_list = []
            
            # Count competitor mentions
            competitor_mention_count = 0
            for concern in concerns_list:
                if isinstance(concern, dict) and concern.get("already_has_vendor", {}).get("has_vendor", False):
                    competitor_mention_count += 1
            
            if competitor_mention_count >= 1:
                competitor_score = 10
                competitor_details.append(f"Medium risk: {competitor_mention_count} competitor mentions")
            else:
                competitor_details.append("No competitor presence detected")
        
        risk_factors["competitor_presence"] = {
            "risk_score": competitor_score,
            "details": competitor_details,
            "max_score": 20
        }
        total_risk_score += competitor_score
        
        # Factor 4: Sentiment Trends (0-10 points)
        sentiment_score = 0
        sentiment_details = []
        
        if timeline_data and timeline_data.get("events"):
            events = timeline_data.get("events", [])
            recent_events = [e for e in events if e.get("sentiment") and e.get("sentiment") != "Unknown"]
            
            if recent_events:
                # Get last 5 events with sentiment
                recent_sentiments = [e.get("sentiment") for e in recent_events[-5:]]
                negative_count = sum(1 for s in recent_sentiments if s == "negative")
                
                if negative_count >= 3:
                    sentiment_score = 10
                    sentiment_details.append("Multiple negative sentiments in recent events")
                elif negative_count >= 1:
                    sentiment_score = 5
                    sentiment_details.append("Some negative sentiments detected")
                else:
                    sentiment_details.append("Generally positive sentiment trends")
        
        risk_factors["sentiment_trends"] = {
            "risk_score": sentiment_score,
            "details": sentiment_details,
            "max_score": 10
        }
        total_risk_score += sentiment_score
        
        # Ensure total score doesn't exceed 100
        total_risk_score = min(total_risk_score, 100)
        
        # Determine risk level based on individual factors
        # Count factors by risk level
        low_risk_factors = 0
        medium_risk_factors = 0
        high_risk_factors = 0
        max_risk_factors = 0
        
        for factor_name, factor_data in risk_factors.items():
            factor_score = factor_data.get("risk_score", 0)
            max_score = factor_data.get("max_score", 0)
            
            # Calculate percentage of max score
            if max_score > 0:
                percentage = (factor_score / max_score) * 100
                
                if percentage == 0:
                    low_risk_factors += 1
                elif percentage <= 50:
                    medium_risk_factors += 1
                elif percentage <= 80:
                    high_risk_factors += 1
                else:
                    max_risk_factors += 1
        
        # Determine overall risk level based on 4 factors
        if max_risk_factors >= 3:  # 3/4 factors are max scores
            risk_level = "Maximum"
        elif low_risk_factors >= 3 and max_risk_factors == 0:  # At least 3/4 factors are 0 scores, and no max scores
            risk_level = "Low"
        elif high_risk_factors >= 2:  # 2/4 factors are high risk
            risk_level = "High"
        elif high_risk_factors >= 1 and (high_risk_factors + medium_risk_factors) >= 4:  # 1 high + 3 medium
            risk_level = "High"
        else:
            risk_level = "Medium"
        
        response = {
            "risk_score": total_risk_score,
            "risk_level": risk_level,
            "risk_factors": risk_factors,
            "last_calculated": datetime.now().isoformat(),
            "deal_name": deal_name
        }
        
        print(Fore.GREEN + f"Risk score for {deal_name}: {total_risk_score}/100 ({risk_level})" + Style.RESET_ALL)
        return response
        
    except Exception as e:
        print(Fore.RED + f"Error in deal-risk-score endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error calculating risk score: {str(e)}")

def run_sync_job(job_id: str, deal: Optional[str], stage: Optional[str], epoch0: Optional[str]):
    """Background function to run sync operations"""
    try:
        if deal:
            print(Fore.YELLOW + f"Starting sync job {job_id}: Syncing deal {deal} from {epoch0} to {datetime.now().strftime('%Y-%m-%d')}" + Style.RESET_ALL)
            sync_service.sync_single_deal(
                deal_name=deal,
                epoch0=epoch0
            )
            sync_jobs[job_id]["status"] = "completed"
            sync_jobs[job_id]["message"] = f"Successfully synced deal: {deal}"
        else:
            stage_to_use = stage if stage else "all"
            print(Fore.YELLOW + f"Starting sync job {job_id}: Syncing deals from stage {stage_to_use} from {epoch0} to {datetime.now().strftime('%Y-%m-%d')}" + Style.RESET_ALL)
            sync_service.sync(
                stage=stage_to_use,
                epoch0=epoch0
            )
            sync_jobs[job_id]["status"] = "completed"
            sync_jobs[job_id]["message"] = f"Successfully synced deals for stage: {stage_to_use}"
    except Exception as e:
        print(Fore.RED + f"Error in sync job {job_id}: {str(e)}" + Style.RESET_ALL)
        sync_jobs[job_id]["status"] = "failed"
        sync_jobs[job_id]["message"] = f"Error syncing data: {str(e)}"
        sync_jobs[job_id]["error"] = str(e)
    finally:
        # Clean up thread reference
        if job_id in active_threads:
            del active_threads[job_id]

@router.post("/sync", status_code=202)
async def sync_data(
    background_tasks: BackgroundTasks,
    epoch_days: Optional[int] = Query(None, description="Number of days ago to start syncing from"),
    stage: Optional[str] = Query(None, description="Specific stage to sync deals from"),
    deal: Optional[str] = Query(None, description="Specific deal name to sync")
):
    """
    Start a background sync job. Returns immediately with a job ID that can be used to check status.
    Can be used in three ways:
    1. Sync all deals from today: /sync
    2. Sync all deals from N days ago: /sync?epoch_days=N
    3. Sync deals from a specific stage: /sync?stage="Stage Name"
    4. Sync a specific deal: /sync?deal="Deal Name"
    
    Parameters can be combined, e.g., /sync?stage="Stage Name"&epoch_days=2
    
    Use the /sync/status/{job_id} endpoint to check the status of the sync job.
    """
    try:
        # Calculate epoch0 if epoch_days is provided
        epoch0 = None
        if epoch_days is not None:
            today = datetime.now()
            epoch_date = today - timedelta(days=epoch_days)
            epoch0 = epoch_date.strftime("%Y-%m-%d")

        # Generate a unique job ID
        job_id = f"sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "deal": deal,
            "stage": stage,
            "epoch0": epoch0,
            "cancelled": False
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_sync_job,
            args=(job_id, deal, stage, epoch0)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        return {
            "status": "accepted",
            "message": "Sync job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting sync job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting sync job: {str(e)}")

@router.get("/sync/status/{job_id}", status_code=200)
async def get_sync_status(job_id: str):
    """
    Get the status of a sync job
    """
    if job_id not in sync_jobs:
        print(Fore.RED + f"Job not found: {job_id}" + Style.RESET_ALL)
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = sync_jobs[job_id]
    print(Fore.YELLOW + f"Job data: {job}" + Style.RESET_ALL)  # Debug log
    
    try:
        response = {
            "job_id": job_id,
            "status": job.get("status", "unknown"),
            "started_at": job.get("started_at"),
            "epoch0": job.get("epoch0"),
            "message": job.get("message"),
            "error": job.get("error"),
            "cancelled": job.get("cancelled", False),
            "type": job.get("type", "unknown")  # Add type to response for debugging
        }
        
        # Add job-specific fields based on job type
        if job.get("type") == "force_meeting_insights":
            response.update({
                "deal_names": job.get("deal_names", []),
                "epoch_days": job.get("epoch_days")
            })
        else:
            response.update({
                "deal": job.get("deal"),
                "stage": job.get("stage")
            })
        
        print(Fore.GREEN + f"Response: {response}" + Style.RESET_ALL)  # Debug log
        return response
        
    except Exception as e:
        print(Fore.RED + f"Error processing job status: {str(e)}" + Style.RESET_ALL)
        print(Fore.RED + f"Job data: {job}" + Style.RESET_ALL)
        raise HTTPException(status_code=500, detail=f"Error processing job status: {str(e)}")

@router.get("/sync/jobs", status_code=200)
async def list_sync_jobs(
    status: Optional[str] = Query(None, description="Filter jobs by status (running/completed/failed)")
):
    """
    List all sync jobs, optionally filtered by status
    """
    jobs = []
    for job_id, job in sync_jobs.items():
        if status and job["status"] != status:
            continue
            
        job_info = {
            "job_id": job_id,
            "status": job["status"],
            "started_at": job["started_at"],
            "epoch0": job["epoch0"],
            "message": job.get("message"),
            "error": job.get("error"),
            "cancelled": job.get("cancelled", False)
        }
        
        # Add job-specific fields based on job type
        if job.get("type") == "force_meeting_insights":
            job_info.update({
                "deal_names": job.get("deal_names", []),
                "epoch_days": job.get("epoch_days")
            })
        else:
            job_info.update({
                "deal": job.get("deal"),
                "stage": job.get("stage")
            })
            
        jobs.append(job_info)
    
    return {
        "total_jobs": len(jobs),
        "jobs": jobs
    }

@router.post("/sync/cancel/{job_id}", status_code=200)
async def cancel_sync_job(job_id: str):
    """
    Cancel a running sync job
    """
    if job_id not in sync_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = sync_jobs[job_id]
    if job["status"] != "running":
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in {job['status']} status")
    
    # Mark job as cancelled
    job["cancelled"] = True
    job["status"] = "cancelled"
    job["message"] = "Job was cancelled by user"
    
    # Note: We can't actually stop the thread, but we've marked it as cancelled
    # The sync service should check this flag periodically and stop if cancelled
    
    return {
        "status": "success",
        "message": f"Job {job_id} marked for cancellation"
    }

@router.post("/sync/force-meeting-insights", status_code=202)
async def force_sync_meeting_insights(
    background_tasks: BackgroundTasks,
    deal_names: List[str] = Query(..., description="List of deal names to force sync meeting insights for"),
    epoch_days: int = Query(..., description="Number of days ago to start syncing from")
):
    """
    Force update meeting insights for specific deals from N days ago to today.
    This will overwrite existing meeting insights data for the specified deals.
    
    Args:
        deal_names: List of deal names to sync
        epoch_days: Number of days ago to start syncing from
        
    Returns:
        dict: Job status information
    """
    try:
        # Calculate epoch0
        today = datetime.now()
        epoch_date = today - timedelta(days=epoch_days)
        epoch0 = epoch_date.strftime("%Y-%m-%d")

        # Generate a unique job ID
        job_id = f"force_meeting_insights_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "deal_names": deal_names,
            "epoch_days": epoch_days,
            "epoch0": epoch0,
            "cancelled": False,
            "type": "force_meeting_insights"
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_force_meeting_insights_job,
            args=(job_id, deal_names, epoch0)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        return {
            "status": "accepted",
            "message": "Force sync meeting insights job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting force sync meeting insights job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting force sync meeting insights job: {str(e)}")

def run_force_meeting_insights_job(job_id: str, deal_names: List[str], epoch0: str):
    """Background function to run force sync meeting insights operations"""
    try:
        print(Fore.YELLOW + f"Starting force sync meeting insights job {job_id}: Syncing {len(deal_names)} deals from {epoch0} to {datetime.now().strftime('%Y-%m-%d')}" + Style.RESET_ALL)

        # Convert epoch0 to datetime
        start_date = datetime.strptime(epoch0, "%Y-%m-%d")
        end_date = datetime.now()
        
        for deal_name in deal_names:
            if sync_jobs[job_id].get("cancelled", False):
                print(Fore.YELLOW + f"Job {job_id} was cancelled. Stopping force sync." + Style.RESET_ALL)
                sync_jobs[job_id]["status"] = "cancelled"
                sync_jobs[job_id]["message"] = "Job was cancelled by user"
                return
                
            print(Fore.YELLOW + f"\n### Force Syncing Meeting Insights for: {deal_name} ###" + Style.RESET_ALL)
            
            # First delete all existing meeting insights for this deal
            print(Fore.YELLOW + f"Deleting existing meeting insights for deal: {deal_name}" + Style.RESET_ALL)
            delete_result = meeting_insights_repo.delete_many({"deal_id": deal_name})
            print(Fore.GREEN + f"Deleted {delete_result} existing meeting insights documents for {deal_name}" + Style.RESET_ALL)
            
            current_date = start_date
            while current_date <= end_date:
                current_date_str = current_date.strftime("%Y-%m-%d")
                try:
                    # Use existing sync_meeting_insights method but with force update
                    sync_service._sync_meeting_insights(deal_name, current_date_str, force_update=True)
                    print(Fore.GREEN + f"Successfully force updated meeting insights for {deal_name} on {current_date_str}" + Style.RESET_ALL)
                except Exception as e:
                    print(Fore.RED + f"Error force updating meeting insights for {deal_name} on {current_date_str}: {str(e)}" + Style.RESET_ALL)
                current_date += timedelta(days=1)
        
        sync_jobs[job_id]["status"] = "completed"
        sync_jobs[job_id]["message"] = f"Successfully force synced meeting insights for {len(deal_names)} deals"
        
    except Exception as e:
        print(Fore.RED + f"Error in force sync meeting insights job {job_id}: {str(e)}" + Style.RESET_ALL)
        sync_jobs[job_id]["status"] = "failed"
        sync_jobs[job_id]["message"] = f"Error force syncing meeting insights: {str(e)}"
        sync_jobs[job_id]["error"] = str(e)
    finally:
        # Clean up thread reference
        if job_id in active_threads:
            del active_threads[job_id] 

@router.post("/deal-insights-aggregate", response_model=Dict[str, List[str]])
async def aggregate_deal_insights(deal_names: List[str]):
    print(Fore.BLUE + f"#### Aggregating deal insights for {len(deal_names)} deals" + Style.RESET_ALL)
    try:
        concern_deals = {
            "pricing_concerns": [],
            "pricing_concerns_no_data": [],
            "no_decision_maker": [],
            "no_decision_maker_no_data": [],
            "using_competitor": [],
            "using_competitor_no_data": []
        }

        all_deal_insights = deal_insights_repo.find_many({"deal_id": {"$in": deal_names}})

        for deal_insight in all_deal_insights:
            deal_name = deal_insight.get("deal_id")
            concerns = deal_insight.get("concerns")

            if not concerns:
                # No concerns at all → mark as no data across all types
                concern_deals["pricing_concerns_no_data"].append(deal_name)
                concern_deals["no_decision_maker_no_data"].append(deal_name)
                concern_deals["using_competitor_no_data"].append(deal_name)
                continue

            # Handle both old format (dict) and new format (list)
            if isinstance(concerns, dict):
                concerns_list = [concerns]
            elif isinstance(concerns, list):
                concerns_list = concerns
            else:
                # Invalid format → mark as no data
                concern_deals["pricing_concerns_no_data"].append(deal_name)
                concern_deals["no_decision_maker_no_data"].append(deal_name)
                concern_deals["using_competitor_no_data"].append(deal_name)
                continue

            # Track if any data was seen for each concern type
            flags = {
                "pricing_concerns": {"found": False, "triggered": False},
                "no_decision_maker": {"found": False, "triggered": False},
                "using_competitor": {"found": False, "triggered": False}
            }

            for concern in concerns_list:
                if not isinstance(concern, dict):
                    continue

                for concern_type, concern_data in concern.items():
                    if not isinstance(concern_data, dict):
                        continue

                    mapped_type = "using_competitor" if concern_type == "already_has_vendor" else concern_type
                    if mapped_type not in flags:
                        continue

                    flags[mapped_type]["found"] = True

                    value = None
                    if concern_type == "pricing_concerns":
                        value = concern_data.get("has_concerns", False)
                    elif concern_type == "no_decision_maker":
                        value = concern_data.get("is_issue", False)
                    elif concern_type == "already_has_vendor":
                        value = concern_data.get("has_vendor", False)

                    if value is True:
                        if not flags[mapped_type]["triggered"]:
                            concern_deals[mapped_type].append(deal_name)
                            flags[mapped_type]["triggered"] = True

            # Add to *_no_data if no info seen at all
            for key, info in flags.items():
                if not info["found"]:
                    concern_deals[f"{key}_no_data"].append(deal_name)

        return concern_deals

    except Exception as e:
        print(Fore.RED + f"Error in deal-insights-aggregate endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error aggregating deal insights: {str(e)}")

@router.delete("/delete-deal")
async def delete_deal(dealName: str = Query(..., description="The name of the deal to delete")):
    """Delete all deal-related data from MongoDB for a specific deal"""
    print(Fore.BLUE + f"#### Deleting all data for deal: {dealName}" + Style.RESET_ALL)
    try:
        # Delete from each repository
        deal_info_deleted = deal_info_repo.delete_one({"deal_id": dealName})
        deal_insights_deleted = deal_insights_repo.delete_one({"deal_id": dealName})
        deal_timeline_deleted = deal_timeline_repo.delete_one({"deal_id": dealName})
        meeting_insights_deleted = meeting_insights_repo.delete_many({"deal_id": dealName})

        # Count total documents deleted
        total_deleted = (
            (1 if deal_info_deleted else 0) +
            (1 if deal_insights_deleted else 0) +
            (1 if deal_timeline_deleted else 0) +
            meeting_insights_deleted
        )

        return {
            "status": "success",
            "message": f"Successfully deleted {total_deleted} documents for deal: {dealName}",
            "details": {
                "deal_info_deleted": bool(deal_info_deleted),
                "deal_insights_deleted": bool(deal_insights_deleted),
                "deal_timeline_deleted": bool(deal_timeline_deleted),
                "meeting_insights_deleted": meeting_insights_deleted
            }
        }
    except Exception as e:
        print(Fore.RED + f"Error deleting deal data: {str(e)}" + Style.RESET_ALL)
        raise HTTPException(status_code=500, detail=f"Error deleting deal data: {str(e)}")

def run_sync_job_v2(job_id: str, date_str: str, stage: str = "all", deal: Optional[str] = None):
    """Background function to run sync operations using DataSyncService2"""
    try:
        if deal:
            print(Fore.YELLOW + f"Starting sync job {job_id}: Syncing specific deal {deal} for date {date_str}" + Style.RESET_ALL)
        else:
            print(Fore.YELLOW + f"Starting sync job {job_id}: Syncing data for date {date_str}, stage: {stage}" + Style.RESET_ALL)
        
        sync_service_v2 = DataSyncService2()
        sync_service_v2.sync(date_str, stage, deal)
        
        if deal:
            sync_jobs[job_id]["status"] = "completed"
            sync_jobs[job_id]["message"] = f"Successfully synced deal {deal} for date: {date_str}"
        else:
            sync_jobs[job_id]["status"] = "completed"
            sync_jobs[job_id]["message"] = f"Successfully synced data for date: {date_str}, stage: {stage}"
    except Exception as e:
        print(Fore.RED + f"Error in sync job {job_id}: {str(e)}" + Style.RESET_ALL)
        sync_jobs[job_id]["status"] = "failed"
        sync_jobs[job_id]["message"] = f"Error syncing data: {str(e)}"
        sync_jobs[job_id]["error"] = str(e)
    finally:
        # Clean up thread reference
        if job_id in active_threads:
            del active_threads[job_id]

@router.post("/sync/v2", status_code=202)
async def sync_data_v2(
    background_tasks: BackgroundTasks,
    date_str: str = Query(..., description="Date string in format YYYY-MM-DD to sync data for"),
    stage: str = Query("all", description="Optional stage name to filter deals. Defaults to 'all' to sync all deals."),
    deal: Optional[str] = Query(None, description="Optional specific deal name to sync. If provided, only this deal will be synced.")
):

    try:
        # Generate a unique job ID
        job_id = f"sync_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "date_str": date_str,
            "stage": stage,
            "deal": deal,
            "cancelled": False,
            "type": "sync_v2"
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_sync_job_v2,
            args=(job_id, date_str, stage, deal)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        return {
            "status": "accepted",
            "message": "Sync job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting sync job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting sync job: {str(e)}")

@router.post("/sync/stage/date", status_code=202)
async def sync_stage_on_date(
    background_tasks: BackgroundTasks,
    stage: str = Query(..., description="Stage name to sync deals from"),
    date_str: str = Query(..., description="Date string in format YYYY-MM-DD to sync data for")
):
    """Sync all deals in a specific stage for a single date"""
    try:
        # Generate a unique job ID
        job_id = f"sync_stage_date_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "stage": stage,
            "date_str": date_str,
            "cancelled": False,
            "type": "sync_stage_date"
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_sync_stage_on_date,
            args=(job_id, stage, date_str)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        return {
            "status": "accepted",
            "message": "Sync job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting sync job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting sync job: {str(e)}")

@router.post("/sync/stage/date-range", status_code=202)
async def sync_stage_date_range(
    background_tasks: BackgroundTasks,
    stage: str = Query(..., description="Stage name to sync deals from"),
    start_date: str = Query(..., description="Start date in format YYYY-MM-DD"),
    end_date: str = Query(..., description="End date in format YYYY-MM-DD")
):
    """Sync all deals in a specific stage for a date range"""
    try:
        # Generate a unique job ID
        job_id = f"sync_stage_range_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "stage": stage,
            "start_date": start_date,
            "end_date": end_date,
            "cancelled": False,
            "type": "sync_stage_range"
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_sync_stage_date_range,
            args=(job_id, stage, start_date, end_date)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        return {
            "status": "accepted",
            "message": "Sync job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting sync job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting sync job: {str(e)}")

@router.post("/sync/deal/date", status_code=202)
async def sync_deal_on_date(
    background_tasks: BackgroundTasks,
    deal: str = Query(..., description="Deal name to sync"),
    date_str: str = Query(..., description="Date string in format YYYY-MM-DD to sync data for")
):
    """Sync a specific deal for a single date"""
    try:
        # Generate a unique job ID
        job_id = f"sync_deal_date_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "deal": deal,
            "date_str": date_str,
            "cancelled": False,
            "type": "sync_deal_date"
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_sync_deal_on_date,
            args=(job_id, deal, date_str)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        return {
            "status": "accepted",
            "message": "Sync job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting sync job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting sync job: {str(e)}")

@router.post("/sync/deal/date-range", status_code=202)
async def sync_deal_date_range(
    background_tasks: BackgroundTasks,
    deal: str = Query(..., description="Deal name to sync"),
    start_date: str = Query(..., description="Start date in format YYYY-MM-DD"),
    end_date: str = Query(..., description="End date in format YYYY-MM-DD")
):
    """Sync a specific deal for a date range"""
    try:
        # Generate a unique job ID
        job_id = f"sync_deal_range_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "deal": deal,
            "start_date": start_date,
            "end_date": end_date,
            "cancelled": False,
            "type": "sync_deal_range"
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_sync_deal_date_range,
            args=(job_id, deal, start_date, end_date)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        return {
            "status": "accepted",
            "message": "Sync job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting sync job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting sync job: {str(e)}")

# Background job runner functions
def run_sync_stage_on_date(job_id: str, stage: str, date_str: str):
    """Background function to run sync_stage_on_date"""
    try:
        sync_service_v2 = DataSyncService2()
        sync_service_v2.sync_stage_on_date(stage, date_str)
        
        sync_jobs[job_id]["status"] = "completed"
        sync_jobs[job_id]["message"] = f"Successfully synced stage {stage} for date: {date_str}"
    except Exception as e:
        print(Fore.RED + f"Error in sync job {job_id}: {str(e)}" + Style.RESET_ALL)
        sync_jobs[job_id]["status"] = "failed"
        sync_jobs[job_id]["message"] = f"Error syncing data: {str(e)}"
        sync_jobs[job_id]["error"] = str(e)
    finally:
        if job_id in active_threads:
            del active_threads[job_id]

def run_sync_stage_date_range(job_id: str, stage: str, start_date: str, end_date: str):
    """Background function to run sync_stage_date_range"""
    try:
        sync_service_v2 = DataSyncService2()
        sync_service_v2.sync_stage_date_range(stage, start_date, end_date)
        
        sync_jobs[job_id]["status"] = "completed"
        sync_jobs[job_id]["message"] = f"Successfully synced stage {stage} from {start_date} to {end_date}"
    except Exception as e:
        print(Fore.RED + f"Error in sync job {job_id}: {str(e)}" + Style.RESET_ALL)
        sync_jobs[job_id]["status"] = "failed"
        sync_jobs[job_id]["message"] = f"Error syncing data: {str(e)}"
        sync_jobs[job_id]["error"] = str(e)
    finally:
        if job_id in active_threads:
            del active_threads[job_id]

def run_sync_deal_on_date(job_id: str, deal: str, date_str: str):
    """Background function to run sync_deal_on_date"""
    try:
        sync_service_v2 = DataSyncService2()
        sync_service_v2.sync_deal_on_date(deal, date_str)
        
        sync_jobs[job_id]["status"] = "completed"
        sync_jobs[job_id]["message"] = f"Successfully synced deal {deal} for date: {date_str}"
    except Exception as e:
        print(Fore.RED + f"Error in sync job {job_id}: {str(e)}" + Style.RESET_ALL)
        sync_jobs[job_id]["status"] = "failed"
        sync_jobs[job_id]["message"] = f"Error syncing data: {str(e)}"
        sync_jobs[job_id]["error"] = str(e)
    finally:
        if job_id in active_threads:
            del active_threads[job_id]

def run_sync_deal_date_range(job_id: str, deal: str, start_date: str, end_date: str):
    """Background function to run sync_deal_date_range"""
    try:
        sync_service_v2 = DataSyncService2()
        sync_service_v2.sync_deal_date_range(deal, start_date, end_date)
        
        sync_jobs[job_id]["status"] = "completed"
        sync_jobs[job_id]["message"] = f"Successfully synced deal {deal} from {start_date} to {end_date}"
    except Exception as e:
        print(Fore.RED + f"Error in sync job {job_id}: {str(e)}" + Style.RESET_ALL)
        sync_jobs[job_id]["status"] = "failed"
        sync_jobs[job_id]["message"] = f"Error syncing data: {str(e)}"
        sync_jobs[job_id]["error"] = str(e)
    finally:
        if job_id in active_threads:
            del active_threads[job_id]

@router.post("/sync/all-stages/date", status_code=202)
async def sync_all_stages_on_date(
    background_tasks: BackgroundTasks,
    date_str: str = Query(..., description="Date string in format YYYY-MM-DD to sync data for")
):
    """Sync all deals across all stages for a single date"""
    try:
        # Generate a unique job ID
        job_id = f"sync_all_stages_date_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "date_str": date_str,
            "cancelled": False,
            "type": "sync_all_stages_date"
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_sync_all_stages_on_date,
            args=(job_id, date_str)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        return {
            "status": "accepted",
            "message": "Sync job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting sync job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting sync job: {str(e)}")

def run_sync_all_stages_on_date(job_id: str, date_str: str):
    """Background function to run sync_all_stages_on_date"""
    try:
        sync_service_v2 = DataSyncService2()
        sync_service_v2.sync_all_stages_on_date(date_str)
        
        sync_jobs[job_id]["status"] = "completed"
        sync_jobs[job_id]["message"] = f"Successfully synced all stages for date: {date_str}"
    except Exception as e:
        print(Fore.RED + f"Error in sync job {job_id}: {str(e)}" + Style.RESET_ALL)
        sync_jobs[job_id]["status"] = "failed"
        sync_jobs[job_id]["message"] = f"Error syncing data: {str(e)}"
        sync_jobs[job_id]["error"] = str(e)
    finally:
        if job_id in active_threads:
            del active_threads[job_id] 

@router.post("/sync/all-stages/yesterday", status_code=202)
async def sync_all_stages_yesterday(background_tasks: BackgroundTasks):
    """Sync all deals across all stages for yesterday's date"""
    try:
        # Calculate yesterday's date
        yesterday = datetime.now() - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

        # Generate a unique job ID
        job_id = f"sync_all_stages_yesterday_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{threading.get_ident()}"
        
        # Initialize job status
        sync_jobs[job_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "date_str": date_str,
            "cancelled": False,
            "type": "sync_all_stages_yesterday"
        }

        # Start the sync job in a background thread
        thread = threading.Thread(
            target=run_sync_all_stages_on_date,
            args=(job_id, date_str)
        )
        thread.daemon = True
        thread.start()
        
        # Store thread reference for potential cancellation
        active_threads[job_id] = thread

        print(Fore.MAGENTA + f"Syncing all stages for date: {date_str}" + Style.RESET_ALL)

        return {
            "status": "accepted",
            "message": "Sync job started",
            "job_id": job_id
        }

    except Exception as e:
        print(Fore.RED + f"Error starting sync job: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error starting sync job: {str(e)}") 

@router.get("/deal-owner-performance", response_model=Dict[str, Any])
async def get_deal_owner_performance(deal_owner: Optional[str] = Query(None, description="The name of the deal owner (optional)")):
    """Get deal owner performance data from MongoDB"""
    if deal_owner:
        print(Fore.BLUE + f"#### Getting performance data for deal owner: {deal_owner}" + Style.RESET_ALL)
        try:
            # Fetch the performance data for the specified deal owner
            performance_data = deal_owner_performance_repo.find_one({"owner": deal_owner})

            if not performance_data:
                raise HTTPException(status_code=404, detail=f"Performance data not found for deal owner: {deal_owner}")

            # Convert MongoDB document to JSON-serializable format
            performance_data = convert_mongo_doc(performance_data)
            
            # Sort signal dates by recency (most recent first)
            performance_data = sort_signal_dates_in_performance_data(performance_data)

            return performance_data
        except Exception as e:
            print(Fore.RED + f"Error fetching deal owner performance data: {str(e)}" + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Error fetching performance data: {str(e)}")
    else:
        print(Fore.BLUE + "#### Getting performance data for all deal owners" + Style.RESET_ALL)
        try:
            # Fetch all deal owner performance data
            all_performance_data = deal_owner_performance_repo.find_many({})

            if not all_performance_data:
                return {"owners": []}

            # Convert MongoDB documents to JSON-serializable format
            formatted_data = []
            for data in all_performance_data:
                formatted_data.append(convert_mongo_doc(data))

            # Sort signal dates by recency (most recent first)
            result = {"owners": formatted_data}
            result = sort_signal_dates_in_performance_data(result)

            return result
        except Exception as e:
            print(Fore.RED + f"Error fetching all deal owner performance data: {str(e)}" + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Error fetching performance data: {str(e)}")

@router.post("/sync-deal-owner-performance", status_code=202)
async def sync_deal_owner_performance_endpoint(background_tasks: BackgroundTasks):
    """Invoke the sync of deal owner performance data"""
    print(Fore.BLUE + "#### Invoking sync for deal owner performance data" + Style.RESET_ALL)
    try:
        # Run the sync operation in the background
        background_tasks.add_task(sync_service_v2.sync_deal_owner_performance)

        return {
            "status": "accepted",
            "message": "Sync job for deal owner performance started"
        }
    except Exception as e:
        print(Fore.RED + f"Error invoking sync for deal owner performance: {str(e)}" + Style.RESET_ALL)
        raise HTTPException(status_code=500, detail=f"Error invoking sync: {str(e)}")