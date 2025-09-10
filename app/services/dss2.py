import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.services.gong_service import GongService
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_insights_repository import DealInsightsRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.meeting_insights_repository import MeetingInsightsRepository
from app.utils.general_utils import extract_company_name
from app.services.hubspot_service import HubspotService
from colorama import Fore, Style
import time
from app.repositories.deal_owner_performance_repository import DealOwnerPerformanceRepository

class DataSyncService2:

    def __init__(self):
        self.gong_service = GongService()
        self.hubspot_service = HubspotService()
        self.deal_info_repo = DealInfoRepository()
        self.deal_insights_repo = DealInsightsRepository()
        self.deal_timeline_repo = DealTimelineRepository()
        self.meeting_insights_repo = MeetingInsightsRepository()
        self.deal_owner_performance_repo = DealOwnerPerformanceRepository()

    def _format_signal_date(self, event_date) -> str:
        """Convert event date to format like '31 Mar 2025'"""
        if isinstance(event_date, datetime):
            dt = event_date
        elif isinstance(event_date, str):
            try:
                # Parse ISO format date
                dt = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                return ""
        else:
            return ""
        
        # Format as "DD MMM YYYY"
        return dt.strftime('%d %b %Y').lstrip('0')  # Remove leading zero from day

    def sync_stage_on_date(self, stage_name: str, date_str: str) -> None:
        """Sync all deals in a specific stage for a single date"""
        print(Fore.MAGENTA + f"Syncing data for stage: {stage_name}, date: {date_str}" + Style.RESET_ALL)
        
        all_deals = self.hubspot_service.get_all_deals()
        filtered_deals = [deal for deal in all_deals if deal.get("stage", "").lower() == stage_name.lower()]
        print(Fore.MAGENTA + f"Filtered to {len(filtered_deals)} deals in stage: {stage_name}" + Style.RESET_ALL)

        for deal in filtered_deals:
            try:
                deal_name = deal.get("dealname")
                if not deal_name:
                    continue

                print(Fore.YELLOW + f"\nProcessing deal: {deal_name}" + Style.RESET_ALL)
                self._sync_deal_info(deal_name)
                self._sync_deal_insights(deal_name, date_str)
                self._sync_timeline_events(deal_name, date_str)
                self._sync_meeting_insights(deal_name, date_str)

            except Exception as e:
                print(Fore.RED + f"Error processing deal {deal_name}: {str(e)}" + Style.RESET_ALL)
                continue
        print(Fore.GREEN + f"Successfully synced stage {stage_name} for date: {date_str}" + Style.RESET_ALL)

    def sync_stage_date_range(self, stage_name: str, start_date: str, end_date: str) -> None:
        """Sync all deals in a specific stage for a date range"""
        print(Fore.MAGENTA + f"Syncing data for stage: {stage_name}, from {start_date} to {end_date}" + Style.RESET_ALL)
        
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        current_date = start

        while current_date <= end:
            current_date_str = current_date.strftime("%Y-%m-%d")
            self.sync_stage_on_date(stage_name, current_date_str)
            current_date += timedelta(days=1)

        print(Fore.GREEN + f"Successfully synced stage {stage_name} for date range: {start_date} to {end_date}" + Style.RESET_ALL)


    def sync_deal_on_date(self, deal_name: str, date_str: str) -> None:
        """Sync a specific deal for a single date"""
        print(Fore.YELLOW + f"Syncing data for DEAL: {deal_name}, DATE: {date_str}" + Style.RESET_ALL)
        
        try:
            # 1. Sync deal info if it's a new deal
            print('## Syncing deal_info')
            self._sync_deal_info(deal_name)

            # 2. Sync deal insights
            print('## Syncing deal_insights')
            self._sync_deal_insights(deal_name, date_str)

            # 3. Sync timeline events
            print('## Syncing deal_timeline')
            self._sync_timeline_events(deal_name, date_str)

            # 4. Sync meeting insights
            print('## Syncing meeting_insights')
            self._sync_meeting_insights(deal_name, date_str)
            
            print(Fore.GREEN + f"Successfully synced deal {deal_name} for date {date_str}" + Style.RESET_ALL)
            
        except Exception as e:
            print(Fore.RED + f"Error processing deal {deal_name}: {str(e)}" + Style.RESET_ALL)

    def sync_deal_date_range(self, deal_name: str, start_date: str, end_date: str) -> None:
        """Sync a specific deal for a date range"""
        print(Fore.YELLOW + f"Syncing data for DEAL: {deal_name}, from {start_date} to {end_date}" + Style.RESET_ALL)
        
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        current_date = start

        while current_date <= end:
            current_date_str = current_date.strftime("%Y-%m-%d")
            self.sync_deal_on_date(deal_name, current_date_str)
            current_date += timedelta(days=1)

        print(Fore.GREEN + f"Successfully synced deal {deal_name} for date range {start_date} to {end_date}" + Style.RESET_ALL)

    def sync_all_stages_on_date(self, date_str: str) -> None:
        """Sync all deals across all stages for a single date"""
        print(Fore.MAGENTA + f"Syncing data for ALL stages on date: {date_str}" + Style.RESET_ALL)
        
        all_deals = self.hubspot_service.get_all_deals()
        print(Fore.MAGENTA + f"Found {len(all_deals)} total deals to sync" + Style.RESET_ALL)

        # Track if any deals had new activity
        any_activity_found = False
        deals_with_activity = []

        for deal in all_deals:
            try:
                deal_name = deal.get("dealname")
                if not deal_name:
                    continue

                print(Fore.YELLOW + f"Processing deal: {deal_name}" + Style.RESET_ALL)
                t = time.time()
                
                # Sync deal info (always runs, doesn't indicate new activity)
                self._sync_deal_info(deal_name)
                
                # Track activity from these sync operations
                insights_activity = self._sync_deal_insights(deal_name, date_str)
                timeline_activity = self._sync_timeline_events(deal_name, date_str)
                meeting_activity = self._sync_meeting_insights(deal_name, date_str)
                
                # Check if this deal had any new activity
                deal_had_activity = insights_activity or timeline_activity or meeting_activity
                if deal_had_activity:
                    any_activity_found = True
                    deals_with_activity.append(deal_name)
                    print(Fore.GREEN + f"✓ Found new activity for deal: {deal_name}" + Style.RESET_ALL)
                else:
                    print(Fore.GRAY + f"- No new activity for deal: {deal_name}" + Style.RESET_ALL)
                
                elapsed = time.time() - t
                print(Fore.GREEN + f"Done syncing deal {deal_name} for date {date_str}.\nTook {elapsed:.2f} seconds" + Style.RESET_ALL)

            except Exception as e:
                print(Fore.RED + f"Error processing deal {deal_name}: {str(e)}" + Style.RESET_ALL)
                continue

        # Only sync deal owner performance if there was any activity
        if any_activity_found:
            print(Fore.CYAN + f"🔄 Found activity in {len(deals_with_activity)} deals: {', '.join(deals_with_activity[:5])}" + 
                  (f" and {len(deals_with_activity) - 5} more..." if len(deals_with_activity) > 5 else "") + Style.RESET_ALL)
            print(Fore.CYAN + "Syncing deal owner performance data due to new activity..." + Style.RESET_ALL)
            self.sync_deal_owner_performance()
        else:
            print(Fore.YELLOW + "⏭️  No new activity found for any deals. Skipping deal owner performance sync." + Style.RESET_ALL)

        print(Fore.GREEN + f"## Successfully synced all stages for date: {date_str}" + Style.RESET_ALL)

    # Keeping the original sync method for backward compatibility
    def sync(self, date_str: str, stage: str = "all", deal_name: Optional[str] = None) -> None:
        """Legacy sync method that routes to the appropriate new sync method"""
        if deal_name:
            self.sync_deal_on_date(deal_name, date_str)
        elif stage != "all":
            self.sync_stage_on_date(stage, date_str)
        else:
            # Handle the "all" stage case
            all_deals = self.hubspot_service.get_all_deals()
            for deal in all_deals:
                try:
                    deal_name = deal.get("dealname")
                    if not deal_name:
                        continue
                    self.sync_deal_on_date(deal_name, date_str)
                except Exception as e:
                    print(Fore.RED + f"Error processing deal {deal_name}: {str(e)}" + Style.RESET_ALL)
                    continue

    def sync_deal_owner_performance(self) -> None:
        """Sync deal owner performance data to MongoDB"""
        print(Fore.MAGENTA + "Syncing deal owner performance data" + Style.RESET_ALL)

        # Step 1: Get all deals
        all_deals = self.deal_info_repo.get_all_deals()
        print(Fore.GREEN + f"Found {len(all_deals)} deals" + Style.RESET_ALL)

        # Step 2: Group deals by owner
        owner_deals_map = {}
        for deal in all_deals:
            owner = deal.get('owner')
            if owner is None or owner == {}:
                owner = "Unknown Owner"
            if owner not in owner_deals_map:
                owner_deals_map[owner] = []
            owner_deals_map[owner].append(deal.get('deal_name'))

        # Step 4: Calculate performance for each owner
        for owner, deals in owner_deals_map.items():
            print(Fore.GREEN + f"Syncing numbers for {owner}" + Style.RESET_ALL)

            performance = {
                "likely to buy": {"count": 0, "deals": {}},
                "very likely to buy": {"count": 0, "deals": {}},
                "less likely to buy": {"count": 0, "deals": {}},
                "neutral": {"count": 0, "deals": {}}
            }

            for deal_name in deals:
                timeline_data = self.deal_timeline_repo.get_by_deal_id(deal_name)
                if not timeline_data:
                    continue

                deal_sentiment_dates = {}

                for event in timeline_data.get('events', []):
                    if event.get('event_type') != 'Meeting':
                        continue
                    
                    buyer_intent = str(event.get('buyer_intent', 'Unknown')).lower()
                    if buyer_intent not in ('very likely to buy', 'likely to buy', 'less likely to buy', 'neutral'):
                        continue
                    
                    # Get the event date and format it
                    event_date = event.get('event_date')
                    formatted_date = self._format_signal_date(event_date)
                    
                    if formatted_date:
                        if buyer_intent not in deal_sentiment_dates:
                            deal_sentiment_dates[buyer_intent] = set()
                        deal_sentiment_dates[buyer_intent].add(formatted_date)
                        performance[buyer_intent]["count"] += 1

                # Add deal to the deals dict for sentiments it contributed to
                for buyer_intent, dates in deal_sentiment_dates.items():
                    if deal_name not in performance[buyer_intent]["deals"]:
                        performance[buyer_intent]["deals"][deal_name] = set()
                    performance[buyer_intent]["deals"][deal_name].update(dates)

            # Convert sets to lists for JSON serialization
            formatted_performance = {}
            for sentiment, data in performance.items():
                deals_list = []
                for deal_name, signal_dates in data["deals"].items():
                    # Sort dates by recency (most recent first)
                    def parse_date_for_sorting(date_str):
                        try:
                            return datetime.strptime(date_str, '%d %b %Y')
                        except ValueError:
                            # If parsing fails, return a very old date so it goes to the end
                            return datetime(1900, 1, 1)
                    
                    sorted_dates = sorted(list(signal_dates), key=parse_date_for_sorting, reverse=True)
                    deals_list.append({
                        "deal_name": deal_name,
                        "signal_dates": sorted_dates
                    })
                
                formatted_performance[sentiment] = {
                    "count": data["count"],
                    "deals": deals_list
                }

            print(Fore.MAGENTA + f"Performance for {owner}: {formatted_performance}" + Style.RESET_ALL)

            print(Fore.RED + f"Deleting owner performance for {owner}" + Style.RESET_ALL)
            self.deal_owner_performance_repo.delete_owner_performance(owner)
            print(Fore.RED + f"Inserting owner performance for {owner}" + Style.RESET_ALL)
            self.deal_owner_performance_repo.insert_owner_performance(owner, formatted_performance)

        print(Fore.GREEN + "Successfully synced deal owner performance data" + Style.RESET_ALL)

    def _sync_deal_info(self, deal_name: str) -> None:
        """Sync deal info if it doesn't exist in MongoDB"""
        try:

            # Get deal info from HubSpot
            hubspot_deal = self._get_hubspot_deal_info(deal_name)
            if not hubspot_deal:
                print(Fore.RED + f"Could not find deal '{deal_name}' in HubSpot" + Style.RESET_ALL)
                return

            company_name = extract_company_name(deal_name)
            if company_name == "Unknown Company":
                print(Fore.RED + f"Could not extract company name from deal name: {deal_name}" + Style.RESET_ALL)
                return

            amount = hubspot_deal.get("amount", "N/A")
            if amount and amount != "N/A":
                try:
                    amount = f"${float(amount):,.2f}"
                except (ValueError, TypeError):
                    amount = "N/A"

            deal_info = {
                "deal_id": hubspot_deal.get("dealId", deal_name),
                "deal_name": deal_name,
                "company_name": company_name,
                "stage": hubspot_deal.get("stage", "Unknown"),
                "owner": hubspot_deal.get("owner", "Unknown"),
                "amount": amount,
                "created_date": self._parse_date(hubspot_deal.get("createdate")),
                "last_modified_date": datetime.now()
            }

            print(Fore.BLUE + f"[MongoDB] Creating new DealInfo for {deal_name}" + Style.RESET_ALL)
            self.deal_info_repo.upsert_deal(deal_name, deal_info)

        except Exception as e:
            print(Fore.RED + f"Error syncing deal info: {str(e)}" + Style.RESET_ALL)

    def _sync_deal_insights(self, deal_name: str, date_str: str) -> bool:
        """Sync deal insights for a specific date
        
        Returns:
            bool: True if new insights were found and processed, False otherwise
        """
        try:
            print(f"Listing all the calls on date {date_str}")
            calls = self.gong_service.list_calls(date_str)
            print(f"Found {len(calls)} calls on date {date_str}")
            for call in calls:
                if "title" in call:
                    print(Fore.GREEN + f"Call: {call['title']}" + Style.RESET_ALL)
            
            company_name = extract_company_name(deal_name)
            print(f"Extracting call ID for a call with company name: {company_name}")
            call_id = self.gong_service.get_call_id(calls, company_name)
            
            if call_id:
                print(Fore.YELLOW + f"Found Call ID: {call_id}" + Style.RESET_ALL)
                new_concerns = self.gong_service.get_concerns(deal_name, date_str)
                if not isinstance(new_concerns, dict):
                    new_concerns = str(new_concerns)
                print(Fore.YELLOW + f"Concerns on date {date_str}: {new_concerns}" + Style.RESET_ALL)
                
                if isinstance(new_concerns, dict):
                    # Update insights data
                    insights_data = {
                        "deal_id": deal_name,
                        "last_updated": datetime.now()
                    }
                    
                    # Update counts based on new concerns
                    pricing_concerns = new_concerns.get("pricing_concerns", {}).get("has_concerns", False)
                    no_decision_maker = new_concerns.get("no_decision_maker", {}).get("is_issue", False)
                    existing_vendor = new_concerns.get("already_has_vendor", {}).get("has_vendor", False)
                    
                    insights_data["pricing_concerns"] = 1 if pricing_concerns else 0
                    insights_data["no_decision_maker"] = 1 if no_decision_maker else 0
                    insights_data["existing_vendor"] = 1 if existing_vendor else 0
                    
                    print(Fore.BLUE + f"[MongoDB] Updating DealInsights with new concerns from {date_str}." + Style.RESET_ALL)
                    self.deal_insights_repo.upsert_activity_with_concerns_list(deal_name, insights_data, new_concerns)
                    return True  # Found and processed new insights
            else:
                print(Fore.RED + f"Did not find a call for {company_name} on {date_str}" + Style.RESET_ALL)
                return False  # No call found, no new insights
            
        except Exception as e:
            print(Fore.RED + f"Error syncing deal insights: {str(e)}" + Style.RESET_ALL)
            return False  # Error occurred, no new insights processed

    def _sync_timeline_events(self, deal_name: str, date_str: str) -> bool:
        """Sync timeline events for a specific date
        
        Returns:
            bool: True if new timeline events were found and processed, False otherwise
        """
        try:
            start_date = datetime.strptime(date_str, '%Y-%m-%d')
            end_date = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)

            print(f"Getting timeline data between dates {start_date} and {end_date} (inclusive).")
            timeline_data = self.hubspot_service.get_deal_timeline(deal_name, date_range=(start_date, end_date))

            if not timeline_data:
                print("No timeline data found.")
                return False

            if "events" not in timeline_data:
                print("No events found in timeline data.")
                return False

            if timeline_data["events"]:
                deal_timeline_document = self.deal_timeline_repo.get_by_deal_id(deal_name)

                if deal_timeline_document:
                    existing_events_by_subject = {}
                    for event in deal_timeline_document["events"]:
                        if event.get("subject"):
                            subject = event.get("subject").strip().lower()
                            existing_events_by_subject[subject] = event

                    for new_event in timeline_data["events"]:
                        if new_event.get("subject"):
                            subject = new_event.get("subject").strip().lower()
                            # If an event with this subject exists, remove it first
                            if subject in existing_events_by_subject:
                                print(f"Removing older event with subject: {subject}")
                                self.deal_timeline_repo.remove_event(deal_name, existing_events_by_subject[subject])
                            # Add the new event
                            print(Fore.YELLOW + f"Adding new event with subject: {subject}" + Style.RESET_ALL)
                            self.deal_timeline_repo.add_event(deal_name, new_event)
                    return True  # Successfully processed timeline events
                else:
                    timeline_data["last_updated"] = datetime.now()
                    self.deal_timeline_repo.upsert_timeline(deal_name, timeline_data)
                    print(Fore.GREEN + f"Successfully created new timeline for deal: {deal_name}" + Style.RESET_ALL)
                    return True  # Successfully created new timeline
            else:
                print("No events to process in timeline data.")
                return False  # No events found
        except Exception as e:
            print(Fore.RED + f"Error syncing deal_timeline. Deal: {deal_name}. Error: {str(e)}" + Style.RESET_ALL)
            return False  # Error occurred, no timeline events processed

    def _sync_meeting_insights(self, deal_name: str, date_str: str) -> bool:
        """Sync meeting insights for a specific date
        
        Returns:
            bool: True if new meeting insights were found and processed, False otherwise
        """
        try:

            calls = self.gong_service.list_calls(date_str)
            print(Fore.BLUE + f"Total calls on {date_str}: {len(calls)}" + Style.RESET_ALL)

            company_name = extract_company_name(deal_name)
            print(f"Company name: {company_name}")

            call_id = self.gong_service.get_call_id(calls, company_name)
            
            if call_id:
                print(Fore.GREEN + f"Found 1 call match for {company_name} on {date_str}" + Style.RESET_ALL)    
                insights = self.gong_service.get_meeting_insights(call_id)

                if insights:
                    insights["deal_name"] = deal_name
                    insights["date"] = date_str
                    
                    # Ensure buyer_attendees is included
                    if "buyer_attendees" not in insights:
                        insights["buyer_attendees"] = []
                    
                    print(Fore.BLUE + f"[MongoDB] Updating MeetingInsights for {deal_name}" + Style.RESET_ALL)
                    meeting_id = f"{deal_name}_{date_str}"
                    self.meeting_insights_repo.upsert_meeting(deal_name, meeting_id, insights)
                    return True  # Successfully processed meeting insights
                else:
                    print(Fore.YELLOW + f"No insights returned for call {call_id}" + Style.RESET_ALL)
                    return False  # Call found but no insights
            else:
                print(Fore.RED + f"No call found for {company_name} on {date_str}" + Style.RESET_ALL)
                return False  # No call found

        except Exception as e:
            print(Fore.RED + f"Error syncing meeting insights: {str(e)}" + Style.RESET_ALL)
            return False  # Error occurred, no meeting insights processed

    def _get_hubspot_deal_info(self, deal_name: str) -> Optional[Dict]:
        """Get deal information from HubSpot"""
        try:
            all_deals = self.hubspot_service.get_all_deals()
            for deal in all_deals:
                if deal.get("dealname", "").lower().strip() == deal_name.lower().strip():
                    return deal
            return None
        except Exception as e:
            print(Fore.RED + f"Error getting HubSpot deal info: {str(e)}" + Style.RESET_ALL)
            return None

    def _parse_date(self, date_str: Optional[str]) -> datetime:
        if not date_str:
            return datetime.now()
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return datetime.now() 