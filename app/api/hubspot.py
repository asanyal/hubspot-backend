from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request
from typing import List, Dict, Any, Optional
from app.services.hubspot_service import HubspotService
from app.services.gong_service import GongService
from app.services.session_service import SessionService
from collections import Counter
from datetime import datetime
import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime
import time
from colorama import Fore, Style, init
from pydantic import BaseModel
import asyncio
from concurrent.futures import ThreadPoolExecutor, CancelledError
import threading

init()

router = APIRouter()
hubspot_service = HubspotService()
session_service = SessionService()
gong_service = GongService()  # Create a global instance

# Store ongoing requests by browser ID
ongoing_requests = {}

# Thread pool for background tasks
# Increased from 4 to 8 workers for better throughput
# Formula: (2 * number_of_cores) is a common practice for optimal thread pool size
thread_pool = ThreadPoolExecutor(max_workers=10)  # Increased concurrent background tasks

@router.get("/health", status_code=200)
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "api_key_configured": bool(hubspot_service.api_key)}

@router.get("/stages", response_model=List[Dict[str, Any]])
async def get_pipeline_stages():
    """Get all pipeline stages from HubSpot"""

    print(Fore.BLUE + "#### Fetching pipeline stages" + Style.RESET_ALL)
    try:
        stages = hubspot_service.get_pipeline_stages()
        return stages
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching pipeline stages: {str(e)}")

@router.get("/deals", response_model=List[Dict[str, Any]])
async def get_deals_by_stage(stage: str = Query(..., description="The name of the pipeline stage")):
    """Get all deals in a specific pipeline stage"""
    try:
        print(Fore.BLUE + f"#### Fetching deals for stage: '{stage}'" + Style.RESET_ALL)
        deals = hubspot_service.get_deals_by_stage(stage)
        
        if not deals:
            print(Fore.RED + f"No deals found for stage: '{stage}'" + Style.RESET_ALL)
            
            try:
                stages = hubspot_service.get_pipeline_stages()
                available_stages = [s["stage_name"] for s in stages]
                
                similar_stages = [s for s in available_stages if s.lower() == stage.lower() or stage.lower() in s.lower()]
                if similar_stages:
                    print(Fore.BLUE + f"Stage found: {similar_stages}" + Style.RESET_ALL)
            except Exception as e:
                print(Fore.RED + f"Error fetching available stages: {e}" + Style.RESET_ALL)
        if deals is not None and len(deals) > 0:
            print(deals[0])
        return deals
    except Exception as e:
        print(f"Error in get_deals_by_stage endpoint: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching deals: {str(e)}")

@router.get("/pipeline-summary", response_model=List[Dict[str, Any]])
async def get_pipeline_summary():
    """Get a summary of the pipeline with counts and amounts by stage"""
    print(Fore.BLUE + "#### Get Pipeline Summary" + Style.RESET_ALL)
    try:
        # Use the global service instance instead of creating a new one
        all_deals = hubspot_service.get_all_deals()
        
        # Validate deals are dictionaries
        valid_deals = []
        for deal in all_deals:
            if not isinstance(deal, dict):
                print(Fore.YELLOW + f"Warning: Expected deal to be a dictionary, got {type(deal)}: {deal}" + Style.RESET_ALL)
                continue
            valid_deals.append(deal)
        
        # Extract stages - add error handling for None values
        stages = [deal.get('stage', 'Unknown') for deal in valid_deals if deal.get('stage') and deal.get('stage') != 'N/A']
        
        # Count number of deals in each stage
        stage_counts = Counter(stages)
        
        # Calculate sum of amounts for each stage
        stage_amounts = {}
        for stage in stage_counts.keys():
            total = 0
            for deal in valid_deals:
                if deal.get('stage') == stage:
                    try:
                        amount = deal.get('amount', 0)
                        if amount and amount != 'N/A':
                            # Handle both string and numeric amounts
                            if isinstance(amount, str):
                                # Remove any currency symbols or commas
                                amount = amount.replace('$', '').replace(',', '')
                            total += float(amount)
                    except (ValueError, TypeError) as e:
                        print(Fore.RED + f"Error parsing amount: {amount}, {str(e)}" + Style.RESET_ALL)
                        continue
            stage_amounts[stage] = total
        
        # Create summary data
        summary = [
            {
                "stage": stage,
                "count": count,
                "amount": stage_amounts.get(stage, 0)
            }
            for stage, count in stage_counts.items()
        ]
        
        # Sort by count descending
        summary = sorted(summary, key=lambda x: x["count"], reverse=True)
        
        return summary
    except Exception as e:
        print(Fore.RED + f"Pipeline summary error: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()  # Print full traceback for debugging
        raise HTTPException(status_code=500, detail=f"Error creating pipeline summary: {str(e)}")

@router.get("/all-deals", response_model=List[Dict[str, Any]])
async def get_all_deals():
    """Get a list of all deals for dropdown selection"""
    print(Fore.BLUE + "#### Getting all deals" + Style.RESET_ALL)
    try:
        service = HubspotService()
        # measure the time it takes to get the all deals
        start_time = time.time()
        all_deals = service.get_all_deals()
        end_time = time.time()
        print(Fore.BLUE + f"[PERFORMANCE][all-deals] Time took: {end_time - start_time} s" + Style.RESET_ALL)
        
        deal_list = [
            {
                "id": index,  # Using index as ID since HubSpot IDs might be complex
                "name": f"{deal.get('dealname', 'Unnamed Deal')}",
                "createdate": datetime.fromisoformat(deal.get('createdate', '').replace('Z', '+00:00')),
                "stage": deal.get('stage', 'Unknown Stage'),  # Changed from deal_stage to stage
                "owner": deal.get('owner', 'Unknown Owner')  # Keep owner for reference
            }
            for index, deal in enumerate(all_deals)
            if deal.get('dealname')  # Skip deals without names
        ]
        # sort the deal_list by createdate descending
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
        # Get browser ID from request headers
        browser_id = request.headers.get("X-Browser-ID")
        if not browser_id:
            raise HTTPException(status_code=400, detail="Browser ID is required")
        
        # measure the time it takes to get the timeline data
        start_time = time.time()
        timeline_data = hubspot_service.get_deal_timeline(dealName, include_content=True)
        end_time = time.time()
        print(Fore.BLUE + f"[GetDealTimeline] Took: {end_time - start_time} s" + Style.RESET_ALL)
        
        # Check for error key in the response
        if "error" in timeline_data:
            print(Fore.RED + f"Error in timeline data: {timeline_data['error']}" + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Error fetching timeline: {timeline_data['error']}")

        return timeline_data
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(Fore.RED + f"Unexpected error in deal_timeline endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching deal timeline: {str(e)}")


@router.get("/deal-info", response_model=Dict[str, Any])
async def get_deal_info(dealName: str = Query(..., description="The name of the deal")):
    print(Fore.BLUE + f"#### Getting deal info for: {dealName}" + Style.RESET_ALL)
    try:
        service = HubspotService()
        deal_owner = "Unknown"
        start_time = time.time()
        all_deals = service.get_all_deals()
        end_time = time.time()
        print(Fore.BLUE + f"Fetched {len(all_deals)} deals. Took: {end_time - start_time} s" + Style.RESET_ALL)
        deal_id = None
        
        # Find the deal
        for deal in all_deals:
            deal_name = deal.get('dealname')

            if deal_name.strip() == dealName.strip():
                deal_id = deal.get('dealId')
                deal_owner = deal.get('owner', "Unknown")
                break
        
        if not deal_id:
            print(Fore.RED + f"Deal not found: {dealName}" + Style.RESET_ALL)
            return {
                "dealId": "Not found",
                "dealOwner": "Not found",
                "activityCount": 0,
                "startDate": None,
                "endDate": None
            }
        engagement_url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}/associations/engagements"
        engagement_response = requests.get(engagement_url, headers=service.headers)
        deal_stage = deal.get('stage', "Unknown")
        
        if engagement_response.status_code != 200:
            return {
                "dealId": deal_id,
                "dealOwner": deal_owner,
                "dealStage": deal_stage,
                "activityCount": 0,
                "startDate": None,
                "endDate": None
            }

        # Get engagement IDs
        engagement_results = engagement_response.json().get("results", [])
        engagement_ids = [result.get("id") for result in engagement_results]
        activity_count = len(engagement_ids)

        
        # Find start and end dates
        start_date = None
        end_date = None
        
        # Fetch details for each engagement to find dates
        if engagement_ids:
            dates = []
            for eng_id in engagement_ids:
                detail_url = f"https://api.hubapi.com/crm/v3/objects/engagements/{eng_id}"
                detail_response = requests.get(detail_url, headers=service.headers, params={
                    "properties": "hs_timestamp"
                })
                
                if detail_response.status_code == 200:
                    props = detail_response.json().get("properties", {})
                    timestamp = props.get("hs_timestamp")
                    
                    if timestamp:
                        try:
                            # Try to parse timestamp
                            date_time = parse_date(timestamp)
                            if date_time:
                                dates.append(date_time)
                        except:
                            pass
            
            if dates:
                start_date = min(dates).strftime('%Y-%m-%d')
                end_date = max(dates).strftime('%Y-%m-%d')
        
        return {
            "dealId": deal_id,
            "dealOwner": deal_owner,
            "dealStage": deal_stage,
            "activityCount": activity_count,
            "startDate": start_date,
            "endDate": end_date
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching deal info: {str(e)}")

@router.get("/deal-activities-count", response_model=Dict[str, int])
async def get_deal_activities_count(dealName: str = Query(..., description="The name of the deal")):
    """Get the count of activities for a specific deal"""
    print(Fore.BLUE + f"#### Getting deal activities count for: {dealName}" + Style.RESET_ALL)
    try:
        service = HubspotService()
        # measure the time it takes to get the deal activities count
        start_time = time.time()
        activity_count = service.get_deal_activities_count(dealName)
        end_time = time.time()
        print(Fore.BLUE + f"[PERFORMANCE][deal-activities-count] Time took: {end_time - start_time} s. Got {activity_count} activities for deal: {dealName}" + Style.RESET_ALL)

        return {"count": activity_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching deal activities count: {str(e)}")

class ChampionResponse(BaseModel):
    champion: bool
    explanation: str
    email: str
    speakerName: str
    business_pain: Optional[str] = None  # Add this field as optional

class ContactsAndChampionResponse(BaseModel):
    contacts: List[ChampionResponse]
    total_contacts: int
    champions_count: int

def process_champion_request_sync(browser_id: str, deal_name: str, target_date: datetime):
    """Process the champion request in the background (synchronous version)"""
    try:
        print(Fore.BLUE + f"Calling get_speaker_champion_results for {deal_name}" + Style.RESET_ALL)
        # measure the time it takes to process
        start_time = time.time()
        speaker_champion_results = gong_service.get_speaker_champion_results(deal_name, target_date=target_date)
        end_time = time.time()
        
        print(Fore.BLUE + f"[PERFORMANCE][contacts-and-champion] Time took: {end_time - start_time} s" + Style.RESET_ALL)
        
        # Count champions
        champions_count = sum(1 for result in speaker_champion_results if result.get('champion', False))
        
        # Create a composite cache key without browser_id
        cache_key = f"{deal_name}_{target_date.strftime('%Y-%m-%d')}"
        
        # Store the results
        result = {
            "contacts": speaker_champion_results,
            "total_contacts": len(speaker_champion_results),
            "champions_count": champions_count
        }
        
        print(Fore.BLUE + f"[CACHE] Writing result to Champion cache: {cache_key}" + Style.RESET_ALL)
        gong_service.champion_cache.put(cache_key, result)
        print(Fore.BLUE + f"Successfully processed champion request for {deal_name}" + Style.RESET_ALL)
        return result  # Return the result directly
    except Exception as e:
        print(Fore.RED + f"Error in process_champion_request_sync: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise  # Re-raise the exception

@router.get("/contacts-and-champion", response_model=ContactsAndChampionResponse)
async def get_contacts_and_champion(
    background_tasks: BackgroundTasks,
    request: Request,
    dealName: str = Query(..., description="The name of the deal"),
    date: str = Query(..., description="The date to search around in YYYY-MM-DD format")
):
    print(Fore.BLUE + f"[{date}] Contacts and champion for deal: {dealName}" + Style.RESET_ALL)
    try:
        # Parse the input date
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Please use YYYY-MM-DD format.")
        
        # Get browser ID from request headers
        browser_id = request.headers.get("X-Browser-ID")
        if not browser_id:
            raise HTTPException(status_code=400, detail="Browser ID is required")

        # Create composite cache key without browser_id
        cache_key = f"{dealName}_{date}"
        print(Fore.BLUE + f"Processing request for deal: {dealName}(client/browser: {browser_id})" + Style.RESET_ALL)

        # First check if we have the result in cache
        cached_result = gong_service.champion_cache.get(cache_key)
        
        if cached_result:
            print(Fore.BLUE + f"[CACHE] Reading from Champion cache: {cache_key}" + Style.RESET_ALL)
            # Ensure cached result matches expected structure
            if isinstance(cached_result, list):
                # If cached result is just a list of contacts, convert it to proper structure
                cached_result = {
                    "contacts": cached_result,
                    "total_contacts": len(cached_result),
                    "champions_count": sum(1 for contact in cached_result if contact.get('champion', False))
                }
            elif not isinstance(cached_result, dict):
                print(Fore.RED + f"[CACHE] Invalid cached result type: {type(cached_result)}" + Style.RESET_ALL)
                cached_result = None
            
            if cached_result and all(key in cached_result for key in ["contacts", "total_contacts", "champions_count"]):
                print(Fore.BLUE + f"[CACHE] Returning cached result for browser {browser_id}, deal {dealName}" + Style.RESET_ALL)
                return cached_result
            else:
                print(Fore.RED + f"[CACHE] Invalid cached result structure" + Style.RESET_ALL)
                cached_result = None

        if not cached_result:
            print(Fore.RED + f"[CACHE] Missing or invalid cache entry for key: {cache_key}" + Style.RESET_ALL)

        # If no valid cached result, start the background task
        print(Fore.BLUE + f"Creating background task for browser {browser_id}, deal {dealName}" + Style.RESET_ALL)
        
        # Submit the task to the thread pool and wait for it to complete
        future = thread_pool.submit(
            process_champion_request_sync,
            browser_id,
            dealName,
            target_date
        )
        
        try:
            # Wait for the task to complete with a timeout
            result = future.result(timeout=120)  # 2 minutes timeout
            print(Fore.BLUE + f"Background task completed for {dealName}" + Style.RESET_ALL)
            
            # Validate the result structure
            if (result and 
                "contacts" in result and 
                "total_contacts" in result and 
                "champions_count" in result):
                print(Fore.BLUE + f"Request successfully completed for deal {dealName}" + Style.RESET_ALL)
                return result
            else:
                print(Fore.RED + f"Invalid result structure for browser {browser_id}, deal {dealName}" + Style.RESET_ALL)
                raise HTTPException(status_code=500, detail="Invalid result structure")
                
        except TimeoutError:
            print(Fore.RED + f"Request timed out after 120 seconds for browser {browser_id}, deal {dealName}" + Style.RESET_ALL)
            raise HTTPException(
                status_code=504, 
                detail="Request timed out after 120 seconds. The operation is still processing in the background."
            )
        except Exception as e:
            print(Fore.RED + f"Background task failed: {str(e)}" + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Background task failed: {str(e)}")

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(Fore.RED + f"Unexpected error in contacts-and-champion endpoint: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error identifying contacts and champion: {str(e)}")

def parse_date(timestamp):
    if not timestamp:
        return None
        
    formats = [
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ'
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(timestamp, fmt)
        except (ValueError, TypeError):
            continue
            
    try:
        return datetime.fromtimestamp(int(timestamp) / 1000)
    except (ValueError, TypeError):
        return None

@router.delete("/browser-cache/{browser_id}")
async def delete_browser_cache(
    browser_id: str,
    request: Request
):
    """Delete all cache entries associated with a browser ID"""
    try:
        print(Fore.BLUE + f"[CACHE] Deleting all cache entries for browser: {browser_id}" + Style.RESET_ALL)
        
        # Get browser ID from request headers to verify it matches
        request_browser_id = request.headers.get("X-Browser-ID")
        if not request_browser_id or request_browser_id != browser_id:
            raise HTTPException(status_code=403, detail="Browser ID mismatch")
        
        # Find and remove all cache entries for this browser
        keys_to_remove = [key for key in ongoing_requests.keys() if key.startswith(f"{browser_id}_")]
        for key in keys_to_remove:
            del ongoing_requests[key]
            print(Fore.MAGENTA + f"[CACHE] Removed cache entry: {key}" + Style.RESET_ALL)
        
        return {
            "message": f"Successfully deleted {len(keys_to_remove)} cache entries for browser {browser_id}",
            "deleted_entries": keys_to_remove
        }
    except Exception as e:
        print(Fore.RED + f"[CACHE] Error deleting browser cache: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting browser cache: {str(e)}")

@router.delete("/clear-all-cache/{browser_id}")
async def clear_all_cache(
    browser_id: str,
    request: Request
):
    """Delete all cache entries associated with a browser ID and clear the champion data cache"""
    try:
        print(Fore.BLUE + f"[CACHE] Clearing all caches for browser: {browser_id}" + Style.RESET_ALL)
        
        # Get browser ID from request headers to verify it matches
        request_browser_id = request.headers.get("X-Browser-ID")
        if not request_browser_id or request_browser_id != browser_id:
            raise HTTPException(status_code=403, detail="Browser ID mismatch")
        
        # 1. Clear ongoing requests cache
        keys_to_remove = [key for key in ongoing_requests.keys() if key.startswith(f"{browser_id}_")]
        for key in keys_to_remove:
            del ongoing_requests[key]
            print(Fore.MAGENTA + f"[CACHE] Removed ongoing request entry: {key}" + Style.RESET_ALL)
        
        # 2. Clear champion data cache entries for this browser
        gong_service = GongService()
        champion_cache_keys = gong_service.champion_cache.keys()
        champion_keys_to_remove = [key for key in champion_cache_keys if key.startswith(f"{browser_id}_")]
        for key in champion_keys_to_remove:
            gong_service.champion_cache.remove(key)
            print(Fore.MAGENTA + f"[CACHE] Removed champion cache entry: {key}" + Style.RESET_ALL)
        
        return {
            "message": f"Successfully cleared all caches for browser {browser_id}",
            "deleted_ongoing_entries": keys_to_remove,
            "deleted_champion_entries": champion_keys_to_remove
        }
    except Exception as e:
        print(Fore.RED + f"[CACHE] Error clearing caches: {str(e)}" + Style.RESET_ALL)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error clearing caches: {str(e)}")
