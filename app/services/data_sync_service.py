import os
import sys
import asyncio
import json

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from app.services.gong_service import GongService
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_insights_repository import DealInsightsRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.meeting_insights_repository import MeetingInsightsRepository
from app.repositories.company_overview_repository import CompanyOverviewRepository
from app.utils.general_utils import extract_company_name
from app.services.hubspot_service import HubspotService
from app.services.firecrawl_service import get_company_analysis
from app.core.config import settings
from colorama import Fore, Style

class DataSyncService:
    def __init__(self):
        self.gong_service = GongService()
        self.hubspot_service = HubspotService()
        self.deal_info_repo = DealInfoRepository()
        self.deal_insights_repo = DealInsightsRepository()
        self.deal_timeline_repo = DealTimelineRepository()
        self.meeting_insights_repo = MeetingInsightsRepository()
        self.company_overview_repo = CompanyOverviewRepository()

    def sync(self, stage: str = "all", epoch0: int = 0) -> None:
        """
        Sync data for all deals within the specified date range.
        Args:
            stage: Pipeline stage to filter deals (default: "all")
            epoch0: Number of days to look back from today (default: 3)
        """
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=epoch0)
        
        print(Fore.MAGENTA + f"Syncing data from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}" + Style.RESET_ALL)

        all_deals = self.hubspot_service.get_all_deals()

        if stage != "all":
            all_deals = [
                deal for deal in all_deals 
                if deal.get("stage", "").lower() == stage.lower()
            ]
            print(Fore.MAGENTA + f"Filtered to the {len(all_deals)} deals in stage '{stage}'" + Style.RESET_ALL) 

        for deal in all_deals:
            try:
                deal_name = deal.get("dealname")
                if not deal_name:
                    continue

                print(Fore.YELLOW + f"\n### Syncing Deal Info, Insights & Timeline: {deal_name} ###" + Style.RESET_ALL)
                # Sync company overview (this doesn't depend on date range)
                self.sync_company_overviews(deal_name)
                
                # Sync global deal data for the date range
                self.sync_global_deal_data(deal_name, start_date, end_date)

                # Sync meeting data for each day in the range
                current_date = start_date
                while current_date <= end_date:
                    self._sync_meeting_insights(deal_name, current_date.strftime("%Y-%m-%d"))
                    current_date += timedelta(days=1)

            except Exception as e:
                print(Fore.RED + f"Error syncing deal data: {str(e)}" + Style.RESET_ALL)
                continue
                
        return

    def sync_global_deal_data(self, deal_name: str, start_date: datetime, end_date: datetime) -> None:
        """
        Sync global deal data within the specified date range.
        Args:
            deal_name: Name of the deal to sync
            start_date: Start date for the sync period
            end_date: End date for the sync period
        """


        try:
            self._sync_deal_info(deal_name)
            self._sync_deal_insights(deal_name, start_date, end_date)
            self._sync_timeline_events(deal_name, start_date, end_date)
            return

        except Exception as e:
            print(Fore.RED + f"Unexpected error in sync_deal_data: {str(e)}" + Style.RESET_ALL)
            return

    def _sync_deal_info(self, deal_name: str) -> None:
        try:
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

            print(Fore.BLUE + f"[MongoDB] Updating DealInfo for {deal_name}." + Style.RESET_ALL)
            self.deal_info_repo.upsert_deal(deal_name, deal_info)

        except Exception as e:
            print(Fore.RED + f"Error syncing deal info: {str(e)}" + Style.RESET_ALL)

    def _get_hubspot_deal_info(self, deal_name: str) -> Optional[Dict]:
        """
        Get deal information from HubSpot
        Args:
            deal_name: Full deal name to search for
        Returns:
            Dict containing deal information or None if not found
        """
        try:
            # Get all deals from HubSpot
            all_deals = self.hubspot_service.get_all_deals()

            # Find matching deal
            for deal in all_deals:
                if deal.get("dealname", "").lower().strip() == deal_name.lower().strip():
                    print(Fore.GREEN + f"Found deal '{deal_name}' in HubSpot" + Style.RESET_ALL)
                    return deal
            return None
        except Exception as e:
            print(Fore.RED + f"Error getting HubSpot deal info: {str(e)}" + Style.RESET_ALL)
            return None

    def _parse_date(self, date_str: Optional[str]) -> datetime:
        """
        Parse date string from HubSpot format to datetime
        Args:
            date_str: Date string from HubSpot
        Returns:
            Datetime object or current time if parsing fails
        """
        if not date_str:
            return datetime.now()
            
        try:
            # Try to parse HubSpot date format
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return datetime.now()

    def _sync_deal_insights(self, deal_name: str, start_date: datetime, end_date: datetime) -> None:
        company_name = extract_company_name(deal_name)
        concerns = []
        current_date = start_date

        while current_date <= end_date:
            current_date_str = current_date.strftime("%Y-%m-%d")

            # check if a call exists for this deal on this date
            calls = self.gong_service.list_calls(current_date_str)
            call_id = self.gong_service.get_call_id(calls, company_name)

            if call_id:
                concerns.append(self.gong_service.get_concerns(deal_name, current_date_str))
            
            current_date += timedelta(days=1)

        if concerns:
            deal_insights_data = self._create_deal_insights_data(deal_name, concerns)
            print(Fore.BLUE + f"[MongoDB] Updating DealInsights for {deal_name}." + Style.RESET_ALL)
            self.deal_insights_repo.upsert_activity(deal_name, deal_insights_data)

    def _create_deal_insights_data(self, deal_name: str, concerns: Dict) -> Dict:
        # pricing_concerns should be 1 if any of the concerns have a pricing concern
        pricing_concerns = 0
        for concern in concerns:
            if concern.get("pricing_concerns", {}).get("has_concerns", False):
                pricing_concerns = 1

        # no_decision_maker should be 1 if any of the concerns have a no_decision_maker concern
        no_decision_maker = 0
        for concern in concerns:
            if concern.get("no_decision_maker", {}).get("is_issue", False):
                no_decision_maker = 1

        # existing_vendor should be 1 if any of the concerns have an existing_vendor concern
        existing_vendor = 0
        for concern in concerns:
            if concern.get("already_has_vendor", {}).get("has_vendor", False):
                existing_vendor = 1

        return {
            "deal_id": deal_name,
            "positive_emails": 0,
            "high_intent_signals": 0,
            "less_likely_to_buy": 0,
            "pricing_concerns": pricing_concerns,
            "no_decision_maker": no_decision_maker,
            "existing_vendor": existing_vendor,
            "concerns": concerns,
            "last_updated": datetime.now()
        }

    def _sync_meeting_insights(self, deal_name: str, date_str: str, force_update: bool = False) -> None:
        try:
            calls = self.gong_service.list_calls(date_str)
            company_name = extract_company_name(deal_name)
            call_id = self.gong_service.get_call_id(calls, company_name)
            meetings = self.meeting_insights_repo.find_by_deal_and_date(deal_name, date_str)
            if call_id and not meetings:
                meeting_id = f"{deal_name}_{date_str}"
                self.meeting_insights_repo.upsert_meeting(deal_name, meeting_id, {"meeting_date": date_str})
            
            for meeting in meetings:
                meeting_id = meeting.get("meeting_id")
                if not meeting_id:
                    continue
                    
                try:
                    insights = self.gong_service.get_meeting_insights(meeting_id)
                    
                    if insights:
                        # Add deal name and date to insights
                        insights["deal_name"] = deal_name
                        insights["date"] = date_str
                        
                        if force_update:
                            self.meeting_insights_repo.force_update_one(
                                {"meeting_id": meeting_id},
                                insights
                            )
                        else:
                            self.meeting_insights_repo.update_one(
                                {"meeting_id": meeting_id},
                                insights
                            )
                        
                except Exception as e:
                    print(Fore.RED + f"Error syncing meeting insights for meeting {meeting_id} in deal {deal_name}: {str(e)}" + Style.RESET_ALL)
                    continue
                    
        except Exception as e:
            print(Fore.RED + f"Error syncing meeting insights for deal {deal_name} on {date_str}: {str(e)}" + Style.RESET_ALL)
            raise

    def _sync_timeline_events(self, deal_name: str, start_date: datetime, end_date: datetime) -> None:
        try:
            print(Fore.YELLOW + f"Syncing timeline events for {deal_name}." + Style.RESET_ALL)
            timeline_data = self.hubspot_service.get_deal_timeline(deal_name)
            
            # Filter events to only include those within our date range
            if timeline_data and "events" in timeline_data:
                filtered_events = [
                    event for event in timeline_data["events"]
                    if start_date <= datetime.strptime(event["date_str"], "%Y-%m-%d") <= end_date
                ]
                timeline_data["events"] = filtered_events
                
            self.deal_timeline_repo.upsert_timeline(deal_name, timeline_data)
        except Exception as e:
            print(Fore.RED + f"Error getting timeline data: {str(e)}" + Style.RESET_ALL)

    def sync_company_overviews(self, deal_name: str) -> None:
        try:
            # Extract company name from deal name
            company_name = extract_company_name(deal_name)
            
            if not company_name or company_name == "Unknown Company":
                print(Fore.RED + f"Could not extract a valid company name for deal {deal_name}" + Style.RESET_ALL)
                return
            
            # Get company analysis from Firecrawl
            overview = get_company_analysis(company_name)

            # Store in MongoDB
            self.company_overview_repo.upsert_by_deal_id(deal_name, overview)
            print(Fore.GREEN + f"Synced company overview for {company_name}" + Style.RESET_ALL)
                
        except Exception as e:
            print(Fore.RED + f"Error syncing company overviews: {str(e)}" + Style.RESET_ALL)
            raise

    def sync_single_deal(self, deal_name: str, epoch0: int = 3) -> None:
        """
        Sync data for a single deal within the specified date range.
        Args:
            deal_name: Name of the deal to sync
            epoch0: Number of days to look back from today (default: 3)
        """
        try:
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=epoch0)
            
            print(Fore.YELLOW + f"\n### Syncing Global Data for: {deal_name} from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ###" + Style.RESET_ALL)
            
            # Sync global deal data
            self.sync_global_deal_data(deal_name, start_date, end_date)
            
            # Sync company overview
            self.sync_company_overviews(deal_name)

            # Sync meeting data for each day in the range
            current_date = start_date
            while current_date <= end_date:
                current_date_str = current_date.strftime("%Y-%m-%d")
                self._sync_meeting_insights(deal_name, current_date_str)
                current_date += timedelta(days=1)

            print(Fore.GREEN + f"\nSuccessfully synced all data for deal: {deal_name}" + Style.RESET_ALL)

        except Exception as e:
            print(Fore.RED + f"Error syncing deal data: {str(e)}" + Style.RESET_ALL)
            raise

if __name__ == "__main__":
    # Create event loop and run sync
    loop = asyncio.get_event_loop()
    sync_service = DataSyncService()
    loop.run_until_complete(sync_service.sync())
