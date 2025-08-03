#!/usr/bin/env python3
"""
Script to delete meeting insights and timeline events for specified deals on a given date.
Usage: python delete_meeting.py <date> <deal1> <deal2> <deal3> ...
Example: python delete_meeting.py 2025-07-30 "Jack Henry & Associates, Inc. - New Deal" "Ernst & Young Nederland LLP - New Deal"
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime
from typing import List

# Add the project root directory to Python path
project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from app.db.mongo_client import MongoConnection
from app.repositories.meeting_insights_repository import MeetingInsightsRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from colorama import Fore, Style, init

init()

def delete_meetings_for_deals(deals: List[str], target_date: str):
    """
    Delete meeting insights and timeline events for specified deals on a given date.
    
    Args:
        deals: List of deal names
        target_date: Date in YYYY-MM-DD format
    """
    print(Fore.BLUE + f"Starting deletion process for {len(deals)} deals on {target_date}" + Style.RESET_ALL)
    
    # Initialize repositories
    meeting_insights_repo = MeetingInsightsRepository()
    deal_timeline_repo = DealTimelineRepository()
    
    # Parse target date
    try:
        target_datetime = datetime.strptime(target_date, "%Y-%m-%d")
        print(Fore.YELLOW + f"Target date: {target_datetime.strftime('%Y-%m-%d')}" + Style.RESET_ALL)
    except ValueError as e:
        print(Fore.RED + f"Invalid date format: {target_date}. Expected YYYY-MM-DD" + Style.RESET_ALL)
        return
    
    total_meeting_insights_deleted = 0
    total_timeline_events_deleted = 0
    
    for deal_name in deals:
        print(Fore.CYAN + f"\nProcessing deal: {deal_name}" + Style.RESET_ALL)
        
        # 1. Delete from meeting_insights collection
        try:
            # Find all meeting insights for this deal
            meeting_insights = meeting_insights_repo.find_many({"deal_id": deal_name})
            
            deleted_meeting_insights = 0
            for meeting in meeting_insights:
                meeting_date = meeting.get('meeting_date')
                if meeting_date:
                    # Handle different date formats
                    if isinstance(meeting_date, str):
                        try:
                            meeting_datetime = datetime.strptime(meeting_date, "%Y-%m-%d")
                        except ValueError:
                            continue
                    elif isinstance(meeting_date, datetime):
                        meeting_datetime = meeting_date
                    else:
                        continue
                    
                    # Check if meeting is on target date
                    if meeting_datetime.date() == target_datetime.date():
                        # Delete this meeting insight
                        meeting_id = meeting.get('meeting_id')
                        if meeting_id:
                            delete_result = meeting_insights_repo.delete_one({"meeting_id": meeting_id})
                            if delete_result:
                                deleted_meeting_insights += 1
                                print(Fore.GREEN + f"  ✓ Deleted meeting insight: {meeting.get('meeting_title', 'No title')}" + Style.RESET_ALL)
            
            total_meeting_insights_deleted += deleted_meeting_insights
            print(Fore.YELLOW + f"  Deleted {deleted_meeting_insights} meeting insights for {deal_name}" + Style.RESET_ALL)
            
        except Exception as e:
            print(Fore.RED + f"  Error deleting meeting insights for {deal_name}: {str(e)}" + Style.RESET_ALL)
        
        # 2. Delete from deal_timeline collection
        try:
            # Get timeline for this deal
            timeline = deal_timeline_repo.get_by_deal_id(deal_name)
            
            if timeline and timeline.get('events'):
                events = timeline.get('events', [])
                events_to_remove = []
                deleted_timeline_events = 0
                
                for event in events:
                    if event.get('event_type') == 'Meeting':
                        event_date = event.get('event_date')
                        
                        if event_date:
                            # Handle different date formats
                            if isinstance(event_date, str):
                                try:
                                    event_datetime = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
                                except ValueError:
                                    continue
                            elif isinstance(event_date, datetime):
                                event_datetime = event_date
                            else:
                                continue
                            
                            # Check if event is on target date
                            if event_datetime.date() == target_datetime.date():
                                events_to_remove.append(event)
                                deleted_timeline_events += 1
                                print(Fore.GREEN + f"  ✓ Marked timeline event for deletion: {event.get('subject', 'No subject')}" + Style.RESET_ALL)
                
                # Remove the marked events
                if events_to_remove:
                    for event_to_remove in events_to_remove:
                        # Remove the event from the timeline
                        deal_timeline_repo.collection.update_one(
                            {"deal_id": deal_name},
                            {"$pull": {"events": event_to_remove}}
                        )
                
                total_timeline_events_deleted += deleted_timeline_events
                print(Fore.YELLOW + f"  Deleted {deleted_timeline_events} timeline events for {deal_name}" + Style.RESET_ALL)
            else:
                print(Fore.YELLOW + f"  No timeline found for {deal_name}" + Style.RESET_ALL)
                
        except Exception as e:
            print(Fore.RED + f"  Error deleting timeline events for {deal_name}: {str(e)}" + Style.RESET_ALL)
    
    # Summary
    print(Fore.BLUE + f"\n=== DELETION SUMMARY ===" + Style.RESET_ALL)
    print(Fore.GREEN + f"Total meeting insights deleted: {total_meeting_insights_deleted}" + Style.RESET_ALL)
    print(Fore.GREEN + f"Total timeline events deleted: {total_timeline_events_deleted}" + Style.RESET_ALL)
    print(Fore.BLUE + f"Date processed: {target_date}" + Style.RESET_ALL)
    print(Fore.BLUE + f"Deals processed: {len(deals)}" + Style.RESET_ALL)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Delete meeting insights and timeline events for specified deals on a given date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python delete_meeting.py 2025-07-30 "Jack Henry & Associates, Inc. - New Deal"
  python delete_meeting.py 2025-07-30 "Deal 1" "Deal 2" "Deal 3"
  python delete_meeting.py 2025-07-30 --deals-file deals.txt
        """
    )
    
    parser.add_argument(
        'date',
        help='Target date in YYYY-MM-DD format (e.g., 2025-07-30)'
    )
    
    parser.add_argument(
        'deals',
        nargs='*',
        help='List of deal names to process'
    )
    
    parser.add_argument(
        '--deals-file',
        help='Path to a text file containing deal names (one per line)'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompt'
    )
    
    return parser.parse_args()

def read_deals_from_file(file_path: str) -> List[str]:
    """Read deal names from a text file."""
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

def main():
    """Main function to run the deletion script."""
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Validate date format
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(Fore.RED + f"Error: Invalid date format '{args.date}'. Expected YYYY-MM-DD format." + Style.RESET_ALL)
        sys.exit(1)
    
    # Get deals list
    deals = []
    if args.deals_file:
        deals = read_deals_from_file(args.deals_file)
    elif args.deals:
        deals = args.deals
    else:
        print(Fore.RED + "Error: No deals specified. Use --deals-file or provide deal names as arguments." + Style.RESET_ALL)
        sys.exit(1)
    
    if not deals:
        print(Fore.RED + "Error: No deals found to process." + Style.RESET_ALL)
        sys.exit(1)
    
    print(Fore.RED + "WARNING: This script will permanently delete meeting data!" + Style.RESET_ALL)
    print(Fore.YELLOW + f"Target date: {args.date}" + Style.RESET_ALL)
    print(Fore.YELLOW + f"Number of deals: {len(deals)}" + Style.RESET_ALL)
    print(Fore.CYAN + "Deals to process:" + Style.RESET_ALL)
    for i, deal in enumerate(deals, 1):
        print(Fore.CYAN + f"  {i}. {deal}" + Style.RESET_ALL)
    
    # Ask for confirmation (unless --force is used)
    if not args.force:
        response = input(Fore.RED + "\nAre you sure you want to proceed? (yes/no): " + Style.RESET_ALL)
        if response.lower() not in ['yes', 'y']:
            print(Fore.YELLOW + "Deletion cancelled." + Style.RESET_ALL)
            return
    
    delete_meetings_for_deals(deals, args.date)
    print(Fore.GREEN + "\nDeletion process completed!" + Style.RESET_ALL)

if __name__ == "__main__":
    main() 