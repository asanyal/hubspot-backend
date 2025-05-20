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
from colorama import Fore, Style, init
import threading
import queue
from pydantic import BaseModel

init()

router = APIRouter()
deal_info_repo = DealInfoRepository()
deal_insights_repo = DealInsightsRepository()
deal_timeline_repo = DealTimelineRepository()
meeting_insights_repo = MeetingInsightsRepository()
company_overview_repo = CompanyOverviewRepository()
sync_service = DataSyncService()

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
                "owner": "Unknown Owner" if not deal.get('owner') or deal.get('owner') == {} else deal.get('owner')
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
            
        # Get meeting info for champion data
        meeting_info = meeting_insights_repo.get_by_deal_id(dealName)
        
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
                "engagement_id": event.get('engagement_id', '') or '',  # Convert null to empty string
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
            
        # Collect all champions from all meetings
        all_champions = []
        for meeting in meeting_info:
            if meeting.get('champion_analysis'):
                all_champions.extend(meeting['champion_analysis'])
        
        # Remove duplicates based on email
        unique_champions = {champ["email"]: champ for champ in all_champions}.values()
        champions_count = sum(1 for champ in unique_champions if champ.get("champion", False))
        
        # If no champions found, return string instead of empty list
        if not unique_champions:
            return {
                "contacts": "No contacts found",
                "total_contacts": 0,
                "champions_count": 0
            }
        
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
    dealName: str = Query(..., description="The name of the deal"),
):
    """Get potential concerns analysis for a specific deal"""
    print(Fore.BLUE + f"#### Getting concerns for deal: {dealName}." + Style.RESET_ALL)
    try:
        # Get deal insights
        deal_activity = deal_insights_repo.get_by_deal_id(dealName)
        if not deal_activity:
            print(Fore.YELLOW + f"No deal insights found for: {dealName}" + Style.RESET_ALL)
            return {
                "pricing_concerns": "No pricing concerns data available",
                "no_decision_maker": "No decision maker data available",
                "already_has_vendor": "No vendor data available"
            }
            
        # Get the most recent concerns from the concerns array
        concerns = deal_activity.get('concerns', [])
        if not concerns:
            print(Fore.YELLOW + f"No concerns data found for: {dealName}" + Style.RESET_ALL)
            return {
                "pricing_concerns": "No concerns data available",
                "no_decision_maker": "No concerns data available",
                "already_has_vendor": "No concerns data available"
            }
        else:
            print(Fore.GREEN + f"Found concerns data: {concerns}" + Style.RESET_ALL)

        # Get the most recent concerns (last in the array)
        latest_concerns = concerns[-1]
        print(Fore.GREEN + f"Found concerns data: {latest_concerns}" + Style.RESET_ALL)
        
        # Convert any empty dictionaries to strings
        pricing_concerns = latest_concerns.get('pricing_concerns', "No pricing concerns data")
        no_decision_maker = latest_concerns.get('no_decision_maker', "No decision maker data")
        already_has_vendor = latest_concerns.get('already_has_vendor', "No vendor data")
        
        if pricing_concerns == {}:
            pricing_concerns = "No pricing concerns data"
        if no_decision_maker == {}:
            no_decision_maker = "No decision maker data"
        if already_has_vendor == {}:
            already_has_vendor = "No vendor data"
        
        response = {
            "pricing_concerns": pricing_concerns,
            "no_decision_maker": no_decision_maker,
            "already_has_vendor": already_has_vendor
        }
        print(Fore.GREEN + f"Returning response: {response}" + Style.RESET_ALL)
        return response
        
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
        # Get company overview from MongoDB
        overview_data = company_overview_repo.get_by_deal_id(dealName)
        
        if not overview_data:
            print(Fore.YELLOW + f"No company overview found for deal: {dealName}" + Style.RESET_ALL)
            return {"overview": "No company info available"}
            
        return {"overview": overview_data.get('overview', 'No company info available')}
        
    except Exception as e:
        print(Fore.RED + f"Error in company-overview endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        # Return a graceful response instead of raising an error
        return {"overview": "No company info available"}

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
    """
    Aggregate concerns data from deal insights for a list of deals.
    Returns lists of deal names for each concern type where the concern is true.
    
    Example request body:
    [
        "MetLife Inc - 001 - Eval/Obs/Protect",
        "Another Deal Name",
        "Third Deal Name"
    ]
    """
    print(Fore.BLUE + f"#### Aggregating deal insights for {len(deal_names)} deals" + Style.RESET_ALL)
    try:
        # Initialize lists for each concern type
        concern_deals = {}
        
        # Get all deal insights in a single query
        all_deal_insights = deal_insights_repo.find_many({"deal_id": {"$in": deal_names}})
        
        # Process each deal insight
        for deal_insight in all_deal_insights:
            deal_name = deal_insight.get('deal_id')
            if not deal_insight.get('concerns'):
                continue
                
            # Get the most recent concerns (last in the array)
            latest_concerns = deal_insight['concerns'][-1]
            
            # Process each concern type
            for concern_type, concern_data in latest_concerns.items():
                if not isinstance(concern_data, dict):
                    continue
                    
                # Map old key name to new key name
                if concern_type == "already_has_vendor":
                    concern_type = "using_competitor"
                    
                # Initialize list for this concern type if not exists
                if concern_type not in concern_deals:
                    concern_deals[concern_type] = []
                
                # Get the boolean value based on the key in the concern data
                # This handles different key names like 'has_concerns', 'is_issue', 'has_vendor'
                bool_value = None
                for key in ['has_concerns', 'is_issue', 'has_vendor']:
                    if key in concern_data:
                        bool_value = concern_data[key]
                        break
                
                # If the concern is true, add the deal name to the list
                if bool_value is True:
                    concern_deals[concern_type].append(deal_name)
        
        return concern_deals
        
    except Exception as e:
        print(Fore.RED + f"Error in deal-insights-aggregate endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error aggregating deal insights: {str(e)}") 