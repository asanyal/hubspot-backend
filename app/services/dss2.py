import os
from datetime import datetime
from typing import Dict, List, Optional

from app.services.gong_service import GongService
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_insights_repository import DealInsightsRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.meeting_insights_repository import MeetingInsightsRepository
from app.utils.general_utils import extract_company_name
from app.services.hubspot_service import HubspotService
from colorama import Fore, Style

class DataSyncService2:

    def __init__(self):
        self.gong_service = GongService()
        self.hubspot_service = HubspotService()
        self.deal_info_repo = DealInfoRepository()
        self.deal_insights_repo = DealInsightsRepository()
        self.deal_timeline_repo = DealTimelineRepository()
        self.meeting_insights_repo = MeetingInsightsRepository()

    def sync(self, date_str: str, stage: str = "all", deal_name: Optional[str] = None) -> None:

        if deal_name:
            print(Fore.YELLOW + f"Syncing data for DEAL: {deal_name}, DATE: {date_str}" + Style.RESET_ALL)
        else:
            print(Fore.MAGENTA + f"Syncing data for date: {date_str}, stage: {stage}" + Style.RESET_ALL)

        if deal_name:
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
            except Exception as e:
                print(Fore.RED + f"Error processing deal {deal_name}: {str(e)}" + Style.RESET_ALL)

            print(Fore.YELLOW + f"Successfully synced deal {deal_name}" + Style.RESET_ALL)

            return

        all_deals = self.hubspot_service.get_all_deals()

        if stage != "all":
            all_deals = [deal for deal in all_deals if deal.get("stage", "").lower() == stage.lower()]
            print(Fore.MAGENTA + f"Filtered to {len(all_deals)} deals in stage: {stage}" + Style.RESET_ALL)

        for deal in all_deals:
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

    def _sync_deal_info(self, deal_name: str) -> None:
        """Sync deal info if it doesn't exist in MongoDB"""
        try:
            # Check if deal exists in MongoDB
            existing_deal = self.deal_info_repo.get_by_deal_id(deal_name)
            if existing_deal:
                return

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

    def _sync_deal_insights(self, deal_name: str, date_str: str) -> None:
        """Sync deal insights for a specific date"""
        try:
            calls = self.gong_service.list_calls(date_str)
            company_name = extract_company_name(deal_name)
            call_id = self.gong_service.get_call_id(calls, company_name)
            
            new_concerns = []
            if call_id:
                new_concerns = self.gong_service.get_concerns(deal_name, date_str)
                if not isinstance(new_concerns, dict):
                    new_concerns = str(new_concerns)
            
            # Update insights data
            insights_data = {
                "deal_id": deal_name,
                "last_updated": datetime.now()
            }
            
            # Update counts based on new concerns
            if new_concerns:
                insights_data["concerns"] = new_concerns
                # Safely check concerns with proper error handling
                pricing_concerns = any(
                    isinstance(c, dict) and 
                    c.get("pricing_concerns", {}).get("has_concerns", False) 
                    for c in new_concerns
                )
                no_decision_maker = any(
                    isinstance(c, dict) and 
                    c.get("no_decision_maker", {}).get("is_issue", False) 
                    for c in new_concerns
                )
                existing_vendor = any(
                    isinstance(c, dict) and 
                    c.get("already_has_vendor", {}).get("has_vendor", False) 
                    for c in new_concerns
                )
                
                insights_data["pricing_concerns"] = 1 if pricing_concerns else 0
                insights_data["no_decision_maker"] = 1 if no_decision_maker else 0
                insights_data["existing_vendor"] = 1 if existing_vendor else 0
            
            print(Fore.BLUE + f"[MongoDB] Updating DealInsights." + Style.RESET_ALL)
            self.deal_insights_repo.upsert_activity(deal_name, insights_data)
            
        except Exception as e:
            print(Fore.RED + f"Error syncing deal insights: {str(e)}" + Style.RESET_ALL)

    def _sync_timeline_events(self, deal_name: str, date_str: str) -> None:
        try:
            start_date = datetime.strptime(date_str, '%Y-%m-%d')
            end_date = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)

            print(f"Getting timeline data between dates {start_date} and {end_date} (inclusive).")
            timeline_data = self.hubspot_service.get_deal_timeline(deal_name, date_range=(start_date, end_date))

            if not timeline_data:
                print("No timeline data found.")
                return

            if "events" not in timeline_data:
                print("No events found in timeline data.")
                return

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
                            print(f"Adding new event with subject: {subject}")
                            self.deal_timeline_repo.add_event(deal_name, new_event)
                else:
                    timeline_data["last_updated"] = datetime.now()
                    self.deal_timeline_repo.upsert_timeline(deal_name, timeline_data)
                    print(Fore.GREEN + f"Successfully created new timeline for deal: {deal_name}" + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f"Error syncing deal_timeline. Deal: {deal_name}. Error: {str(e)}" + Style.RESET_ALL)

    def _sync_meeting_insights(self, deal_name: str, date_str: str) -> None:
        try:
            calls = self.gong_service.list_calls(date_str)
            company_name = extract_company_name(deal_name)
            call_id = self.gong_service.get_call_id(calls, company_name)
            
            if call_id:
                
                insights = self.gong_service.get_meeting_insights(call_id)

                if insights:
                    insights["deal_name"] = deal_name
                    insights["date"] = date_str
                    
                    print(Fore.BLUE + f"[MongoDB] Updating MeetingInsights for {deal_name}" + Style.RESET_ALL)
                    meeting_id = f"{deal_name}_{date_str}"
                    self.meeting_insights_repo.upsert_meeting(deal_name, meeting_id, insights)
                    
        except Exception as e:
            print(Fore.RED + f"Error syncing meeting insights: {str(e)}" + Style.RESET_ALL)

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