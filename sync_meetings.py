#!/usr/bin/env python3
"""
Script to delete existing deal data and sync meetings for specified deals within a date range.
Usage: python sync_meetings.py <start_date> <end_date> --deals-file deals.txt
Example: python sync_meetings.py 2025-07-30 2025-08-05 --deals-file deals.txt
"""

import sys
import os
import argparse
import requests
import time
import signal
from pathlib import Path
from datetime import datetime, timedelta
from typing import List
from urllib.parse import quote

# Add the project root directory to Python path
project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from app.db.mongo_client import MongoConnection
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_insights_repository import DealInsightsRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.meeting_insights_repository import MeetingInsightsRepository
from colorama import Fore, Style, init

init()

# Global flag to handle graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global shutdown_requested
    print(Fore.YELLOW + "\n\n⚠️  Shutdown requested. Finishing current operation and stopping..." + Style.RESET_ALL)
    shutdown_requested = True

def load_env_variable(key: str) -> str:
    """Load environment variable from .env file."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Environment variable {key} not found in .env file")
        return value
    except Exception as e:
        print(Fore.RED + f"Error loading environment variable {key}: {str(e)}" + Style.RESET_ALL)
        sys.exit(1)

def delete_deal_data(deal_id: str, repositories: dict) -> dict:
    """
    Delete all data for a specific deal from all collections.
    
    Args:
        deal_id: The deal ID to delete data for
        repositories: Dictionary containing all repository instances
    
    Returns:
        dict: Summary of deletion results
    """
    results = {
        'deal_info_deleted': False,
        'deal_insights_deleted': False,
        'deal_timeline_deleted': False,
        'meeting_insights_deleted': 0
    }
    
    try:
        # Delete deal_info entry
        if repositories['deal_info'].delete_one({"deal_id": deal_id}):
            results['deal_info_deleted'] = True
            print(Fore.GREEN + f"  ✓ Deleted deal_info for {deal_id}" + Style.RESET_ALL)
        
        # Delete deal_insights entry
        if repositories['deal_insights'].delete_one({"deal_id": deal_id}):
            results['deal_insights_deleted'] = True
            print(Fore.GREEN + f"  ✓ Deleted deal_insights for {deal_id}" + Style.RESET_ALL)
        
        # Delete deal_timeline entry
        if repositories['deal_timeline'].delete_one({"deal_id": deal_id}):
            results['deal_timeline_deleted'] = True
            print(Fore.GREEN + f"  ✓ Deleted deal_timeline for {deal_id}" + Style.RESET_ALL)
        
        # Delete all meeting_insights entries for this deal
        meeting_insights = repositories['meeting_insights'].find_many({"deal_id": deal_id})
        deleted_count = 0
        for meeting in meeting_insights:
            meeting_id = meeting.get('meeting_id')
            if meeting_id:
                if repositories['meeting_insights'].delete_one({"meeting_id": meeting_id}):
                    deleted_count += 1
        
        results['meeting_insights_deleted'] = deleted_count
        if deleted_count > 0:
            print(Fore.GREEN + f"  ✓ Deleted {deleted_count} meeting_insights for {deal_id}" + Style.RESET_ALL)
        
    except Exception as e:
        print(Fore.RED + f"  ✗ Error deleting data for {deal_id}: {str(e)}" + Style.RESET_ALL)
    
    return results

def sync_deal_via_api(deal_id: str, start_date: str, end_date: str, api_base_url: str) -> bool:
    """
    Sync a deal via the API for the given date range.
    
    Args:
        deal_id: The deal ID to sync
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        api_base_url: Base URL for the API
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Construct the API URL
        encoded_deal = quote(deal_id)
        api_url = f"{api_base_url}/api/hubspot/v2/sync/deal/date-range?deal={encoded_deal}&start_date={start_date}&end_date={end_date}"
        
        print(Fore.CYAN + f"  🔄 Syncing {deal_id} from {start_date} to {end_date}" + Style.RESET_ALL)
        print(Fore.BLUE + f"  🌐 Full API URL: {api_url}" + Style.RESET_ALL)
        
        # Make the API request
        response = requests.post(api_url, timeout=30)
        
        # Print the API response
        print(Fore.CYAN + f"  📡 API Response for {deal_id}:" + Style.RESET_ALL)
        print(Fore.YELLOW + f"## Status Code: {response.status_code}" + Style.RESET_ALL)
        print(Fore.YELLOW + f"## Response Body: {response.text}" + Style.RESET_ALL)
        
        if response.status_code == 200:
            print(Fore.GREEN + f"  ✓ Successfully initiated sync for {deal_id}" + Style.RESET_ALL)
            return True
        else:
            print(Fore.RED + f"  ✗ API call failed for {deal_id}" + Style.RESET_ALL)
            return False
            
    except requests.exceptions.RequestException as e:
        print(Fore.RED + f"  ✗ Network error syncing {deal_id}: {str(e)}" + Style.RESET_ALL)
        return False
    except Exception as e:
        print(Fore.RED + f"  ✗ Unexpected error syncing {deal_id}: {str(e)}" + Style.RESET_ALL)
        return False

def process_deals(deals: List[str], start_date: str, end_date: str, api_base_url: str):
    """
    Process all deals: delete existing data and sync via API.
    
    Args:
        deals: List of deal IDs to process
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        api_base_url: Base URL for the API
    """
    global shutdown_requested
    
    print(Fore.BLUE + f"Starting sync process for {len(deals)} deals from {start_date} to {end_date}" + Style.RESET_ALL)
    
    # Initialize repositories
    repositories = {
        'deal_info': DealInfoRepository(),
        'deal_insights': DealInsightsRepository(),
        'deal_timeline': DealTimelineRepository(),
        'meeting_insights': MeetingInsightsRepository()
    }
    
    # Parse dates
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        print(Fore.YELLOW + f"Date range: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}" + Style.RESET_ALL)
    except ValueError as e:
        print(Fore.RED + f"Invalid date format: {str(e)}" + Style.RESET_ALL)
        return
    
    total_deals = len(deals)
    successful_deletions = 0
    successful_syncs = 0
    failed_deals = []
    
    for i, deal_id in enumerate(deals, 1):
        if shutdown_requested:
            print(Fore.YELLOW + f"\n🛑 Stopping execution after processing {i-1} deals" + Style.RESET_ALL)
            break
        
        print(Fore.CYAN + f"\n[{i}/{total_deals}] Processing deal: {deal_id}" + Style.RESET_ALL)
        
        try:
            # Step 1: Delete existing data
            print(Fore.YELLOW + "  🗑️  Deleting existing data..." + Style.RESET_ALL)
            deletion_results = delete_deal_data(deal_id, repositories)
            
            if any([deletion_results['deal_info_deleted'], deletion_results['deal_insights_deleted'], 
                   deletion_results['deal_timeline_deleted'], deletion_results['meeting_insights_deleted'] > 0]):
                successful_deletions += 1
            
            # Step 2: Sync via API
            print(Fore.YELLOW + "  🔄 Syncing via API..." + Style.RESET_ALL)
            if sync_deal_via_api(deal_id, start_date, end_date, api_base_url):
                successful_syncs += 1
            else:
                failed_deals.append(deal_id)
            
            # Add delay between deals (except for the last one)
            if i < total_deals and not shutdown_requested:
                print(Fore.YELLOW + "  ⏳ Waiting 2 seconds before next deal..." + Style.RESET_ALL)
                time.sleep(2)
                
        except Exception as e:
            print(Fore.RED + f"  ✗ Unexpected error processing {deal_id}: {str(e)}" + Style.RESET_ALL)
            failed_deals.append(deal_id)
    
    # Summary
    print(Fore.BLUE + f"\n=== SYNC SUMMARY ===" + Style.RESET_ALL)
    print(Fore.GREEN + f"Total deals processed: {min(i, total_deals)}" + Style.RESET_ALL)
    print(Fore.GREEN + f"Successful deletions: {successful_deletions}" + Style.RESET_ALL)
    print(Fore.GREEN + f"Successful syncs: {successful_syncs}" + Style.RESET_ALL)
    print(Fore.YELLOW + f"Date range: {start_date} to {end_date}" + Style.RESET_ALL)
    
    if failed_deals:
        print(Fore.RED + f"Failed deals ({len(failed_deals)}):" + Style.RESET_ALL)
        for failed_deal in failed_deals:
            print(Fore.RED + f"  - {failed_deal}" + Style.RESET_ALL)
    
    if shutdown_requested:
        print(Fore.YELLOW + "Script was interrupted by user." + Style.RESET_ALL)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Delete existing deal data and sync meetings for specified deals within a date range",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sync_meetings.py 2025-07-30 2025-08-05 --deals-file deals.txt
  python sync_meetings.py 2025-07-30 2025-07-30 --deals-file deals.txt --force
        """
    )
    
    parser.add_argument(
        'start_date',
        help='Start date in YYYY-MM-DD format (e.g., 2025-07-30)'
    )
    
    parser.add_argument(
        'end_date',
        help='End date in YYYY-MM-DD format (e.g., 2025-08-05)'
    )
    
    parser.add_argument(
        '--deals-file',
        required=True,
        help='Path to a text file containing deal IDs (one per line)'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompt'
    )
    
    return parser.parse_args()

def read_deals_from_file(file_path: str) -> List[str]:
    """Read deal IDs from a text file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            deals = [line.strip() for line in f if line.strip()]
        return deals
    except FileNotFoundError:
        print(Fore.RED + f"Error: File '{file_path}' not found." + Style.RESET_ALL)
        sys.exit(1)
    except Exception as e:
        print(Fore.RED + f"Error reading file '{file_path}': {str(e)}" + Style.RESET_ALL)
        sys.exit(1)

def validate_date_format(date_str: str) -> bool:
    """Validate date format."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False

def main():
    """Main function to run the sync script."""
    
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Validate date formats
    if not validate_date_format(args.start_date):
        print(Fore.RED + f"Error: Invalid start date format '{args.start_date}'. Expected YYYY-MM-DD format." + Style.RESET_ALL)
        sys.exit(1)
    
    if not validate_date_format(args.end_date):
        print(Fore.RED + f"Error: Invalid end date format '{args.end_date}'. Expected YYYY-MM-DD format." + Style.RESET_ALL)
        sys.exit(1)
    
    # Validate date range
    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d")
    
    if start_dt > end_dt:
        print(Fore.RED + f"Error: Start date '{args.start_date}' cannot be after end date '{args.end_date}'." + Style.RESET_ALL)
        sys.exit(1)
    
    # Load API base URL from environment
    api_base_url = load_env_variable('SPOTLIGHT_BACKEND_URL')
    print(Fore.CYAN + f"Using API base URL: {api_base_url}" + Style.RESET_ALL)
    
    # Read deals from file
    deals = read_deals_from_file(args.deals_file)
    
    if not deals:
        print(Fore.RED + "Error: No deals found in the file." + Style.RESET_ALL)
        sys.exit(1)
    
    print(Fore.RED + "⚠️  WARNING: This script will permanently delete existing deal data!" + Style.RESET_ALL)
    print(Fore.YELLOW + f"Start date: {args.start_date}" + Style.RESET_ALL)
    print(Fore.YELLOW + f"End date: {args.end_date}" + Style.RESET_ALL)
    print(Fore.YELLOW + f"Number of deals: {len(deals)}" + Style.RESET_ALL)
    print(Fore.CYAN + "Deals to process:" + Style.RESET_ALL)
    for i, deal in enumerate(deals, 1):
        print(Fore.CYAN + f"  {i}. {deal}" + Style.RESET_ALL)
    
    # Ask for confirmation (unless --force is used)
    if not args.force:
        response = input(Fore.RED + "\nAre you sure you want to proceed? (yes/no): " + Style.RESET_ALL)
        if response.lower() not in ['yes', 'y']:
            print(Fore.YELLOW + "Sync cancelled." + Style.RESET_ALL)
            return
    
    # Process the deals
    process_deals(deals, args.start_date, args.end_date, api_base_url)
    
    if not shutdown_requested:
        print(Fore.GREEN + "\n✅ Sync process completed successfully!" + Style.RESET_ALL)
    else:
        print(Fore.YELLOW + "\n⚠️  Sync process was interrupted." + Style.RESET_ALL)

if __name__ == "__main__":
    main() 