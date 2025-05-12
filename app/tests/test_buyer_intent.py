from app.services.gong_service import GongService
from datetime import datetime, timedelta
from colorama import Fore, Style, init
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from app.utils.prompts import extract_company_name

init()

def test_buyer_intent():
    gong_service = GongService()
    
    # Test parameters
    call_title = "Galileo <> Freshworks| Demo"
    call_date = "2025-03-27"
    seller_name = "Galileo"
    
    print(Fore.YELLOW + f"\nTesting buyer intent for:" + Style.RESET_ALL)
    print(f"Call Title: {call_title}")
    print(f"Call Date: {call_date}")
    print(f"Seller Name: {seller_name}\n")
    
    # First, let's check if we can find the call
    print(Fore.CYAN + "Step 1: Checking if call exists..." + Style.RESET_ALL)
    calls = gong_service.list_calls(call_date)
    print(f"Found {len(calls)} calls on {call_date}")
    
    # Print all calls to help debug
    print("\nAll calls on this date:")
    for call in calls:
        print(f"- {call.get('title', 'No title')} (ID: {call.get('id', 'No ID')})")
    
    # Try to get the call ID
    company_name = extract_company_name(call_title)
    call_id = gong_service.get_call_id(calls, company_name)
    print(f"\nCall ID found: {call_id}")
    
    if not call_id:
        print(Fore.RED + "Could not find call ID. Trying next day..." + Style.RESET_ALL)
        next_date = datetime.strptime(call_date, "%Y-%m-%d") + timedelta(days=1)
        next_date_str = next_date.strftime("%Y-%m-%d")
        calls = gong_service.list_calls(next_date_str)
        print(f"Found {len(calls)} calls on {next_date_str}")
        
        print("\nAll calls on next date:")
        for call in calls:
            print(f"- {call.get('title', 'No title')} (ID: {call.get('id', 'No ID')})")
        
        call_id = gong_service.get_call_id(calls, call_title)
        print(f"\nCall ID found on next day: {call_id}")
    
    # Get buyer intent
    print(Fore.CYAN + "\nStep 2: Getting buyer intent..." + Style.RESET_ALL)
    buyer_intent = gong_service.get_buyer_intent(call_title, call_date, seller_name)
    
    print("\nBuyer Intent Result:")
    print(f"Intent: {buyer_intent.get('intent', 'N/A')}")
    print(f"Explanation: {buyer_intent.get('explanation', 'N/A')}")
    
    # If we found a call ID, let's also check the transcript
    if call_id:
        print(Fore.CYAN + "\nStep 3: Checking transcript..." + Style.RESET_ALL)
        start_time = f"{call_date}T00:00:00Z"
        end_time = f"{call_date}T23:59:59Z"
        transcript, topics = gong_service.get_transcript_and_topics(call_id, start_time, end_time)
        
        if transcript:
            print(f"Transcript length: {len(transcript)} characters")
            print("\nFirst 500 characters of transcript:")
            print(transcript[:500] + "...")
        else:
            print(Fore.RED + "No transcript found" + Style.RESET_ALL)

if __name__ == "__main__":
    test_buyer_intent() 