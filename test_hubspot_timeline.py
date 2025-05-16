import os
import json
import requests
from dotenv import load_dotenv
from datetime import datetime

def test_hubspot_timeline():
    """
    Test function to fetch timeline data from HubSpot API directly.
    This loads API keys from .env file and returns the raw JSON response.
    """
    # Load environment variables from .env file
    load_dotenv()
    
    # Get API key from environment
    api_key = "pat-na1-4c2808e2-99e9-4803-960e-36416400ed0e"
    if not api_key:
        print("Error: HUBSPOT_API_KEY not found in .env file")
        return None
    
    # Set up headers for authentication
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Create a session for connection reuse
    session = requests.Session()
    session.headers.update(headers)
    
    # Get deal name from command line or use default
    deal_name = input("Enter deal name to fetch timeline for (or press Enter for default): ")
    if not deal_name:
        deal_name = "Freshworks - GenAI"  # Default deal name
    
    print(f"Fetching timeline for deal: {deal_name}")
    
    # Step 1: Get the deal ID
    deals_url = "https://api.hubapi.com/crm/v3/objects/deals"
    params = {"properties": "dealname,id", "limit": "100"}
    
    all_deals = []
    after = None
    deal_id = None
    
    # Fetch all deals to find the matching one
    while True:
        if after:
            params["after"] = after
            
        response = session.get(deals_url, params=params)
        
        if response.status_code == 200:
            result = response.json()
            deals_page = result.get("results", [])
            all_deals.extend(deals_page)
            
            # Check if we found the deal already to avoid unnecessary API calls
            for deal in deals_page:
                if deal.get('properties', {}).get('dealname') == deal_name:
                    deal_id = deal.get('id')
                    break
            
            if deal_id:
                break
                
            # Continue pagination if needed
            pagination = result.get("paging", {})
            if "next" in pagination and "after" in pagination["next"]:
                after = pagination["next"]["after"]
            else:
                break
        else:
            print(f"Error fetching deals: {response.status_code}, {response.text}")
            return None
    
    # If deal not found
    if not deal_id:
        print(f"Deal with name '{deal_name}' not found.")
        return None
    
    print(f"Found deal ID: {deal_id}")
    
    # Step 2: Get engagements (timeline events) for this deal
    engagement_url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}/associations/engagements"
    engagement_response = session.get(engagement_url)
    
    if engagement_response.status_code != 200:
        print(f"Error fetching engagements: {engagement_response.status_code}, {engagement_response.text}")
        return None
    
    engagement_results = engagement_response.json()
    print(f"Found {len(engagement_results.get('results', []))} engagements")
    
    # Step 3: Get detailed data for all engagements
    engagement_ids = [result.get("id") for result in engagement_results.get("results", [])]  # Get all engagements
    
    detailed_engagements = []
    for eng_id in engagement_ids:
        detail_url = f"https://api.hubapi.com/crm/v3/objects/engagements/{eng_id}"
        detail_params = {
            "properties": "hs_engagement_type,hs_timestamp,hs_email_subject,hs_email_text,hs_note_body,hs_call_body,hs_meeting_title,hs_meeting_body,hs_task_body"
        }
        
        detail_response = session.get(detail_url, params=detail_params)
        
        if detail_response.status_code == 200:
            details = detail_response.json()
            detailed_engagements.append(details)
        else:
            print(f"Error fetching details for engagement {eng_id}: {detail_response.status_code}")
    
    # Create the final response
    final_response = {
        "deal_id": deal_id,
        "deal_name": deal_name,
        "engagements_count": len(engagement_ids),
        "engagement_samples": detailed_engagements,
        "raw_engagements_list": engagement_results
    }
    
    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"hubspot_timeline_{timestamp}.json"
    with open(filename, 'w') as f:
        json.dump(final_response, f, indent=2)
    
    print(f"Response saved to {filename}")
    
    return final_response

if __name__ == "__main__":
    # When run directly, execute the test function and print the result
    result = test_hubspot_timeline()
    if result:
        print("\nSummary of timeline data:")
        print(f"Deal ID: {result['deal_id']}")
        print(f"Total engagements: {result['engagements_count']}")
        print(f"Sample engagement types: {[eng.get('properties', {}).get('hs_engagement_type') for eng in result['engagement_samples']]}")
        print(f"\nDetailed data saved to JSON file. Use that for complete response.") 