import os
import sys
import asyncio

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

    def sync(self, stage: str = "all", epoch0: str = "2025-02-15") -> None:
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

                print(Fore.YELLOW + f"\n### Syncing Global Data for: {deal_name} ###" + Style.RESET_ALL)
                
                self.sync_global_deal_data(deal_name, epoch0)
                self.sync_company_overviews(deal_name)

                today = datetime.now().strftime("%Y-%m-%d")
                current_date = datetime.strptime(epoch0, "%Y-%m-%d")
                end_date = datetime.strptime(today, "%Y-%m-%d")

                print(Fore.YELLOW + f"\n### Syncing Meeting Data for: {deal_name} from {epoch0} to {today} ###" + Style.RESET_ALL)

                while current_date <= end_date:
                    current_date_str = current_date.strftime("%Y-%m-%d")
                    self._sync_meeting_insights(deal_name, current_date_str)
                    current_date += timedelta(days=1)

            except Exception as e:
                print(Fore.RED + f"Error syncing deal data: {str(e)}" + Style.RESET_ALL)
                continue
                
        return

    def sync_global_deal_data(self, deal_name: str, epoch0: str) -> None:

        stats = {
            "deal_info_updated": False,
            "activities_synced": 0,
            "meetings_synced": 0,
            "timeline_events": 0,
            "errors": []
        }

        try:

            company_name = extract_company_name(deal_name)
            if company_name == "Unknown Company":
                print(Fore.RED + f"Could not extract company name from deal name: {deal_name}" + Style.RESET_ALL)
                return


            self._sync_deal_info(deal_name, company_name, stats) ### Global
            self._sync_deal_insights(deal_name, epoch0, stats) ### Global
            self._sync_timeline_events(deal_name, epoch0, stats) ### Global

            return

        except Exception as e:
            print(Fore.RED + f"Unexpected error in sync_deal_data: {str(e)}" + Style.RESET_ALL)
            return

    def _sync_deal_info(self, deal_name: str, company_name: str, stats: Dict) -> None:
        """
        Sync deal information to MongoDB
        Args:
            deal_name: Full deal name
            company_name: Extracted company name
            stats: Statistics dictionary to update
        """
        try:

            hubspot_deal = self._get_hubspot_deal_info(deal_name)
            if not hubspot_deal:
                print(Fore.RED + f"Could not find deal '{deal_name}' in HubSpot" + Style.RESET_ALL)
                return


            amount = hubspot_deal.get("amount", "N/A")
            if amount and amount != "N/A":
                try:
                    amount = f"${float(amount):,.2f}"
                except (ValueError, TypeError):
                    amount = "N/A"


            deal_info = {
                "deal_id": hubspot_deal.get("dealId", deal_name),  # Use HubSpot ID if available
                "deal_name": deal_name,
                "company_name": company_name,
                "stage": hubspot_deal.get("stage", "Unknown"),
                "owner": hubspot_deal.get("owner", "Unknown"),
                "amount": amount,
                "created_date": self._parse_date(hubspot_deal.get("createdate")),
                "last_modified_date": datetime.now()
            }

            # Update in MongoDB
            print(Fore.BLUE + f"[MongoDB] Updating DealInfo for {deal_name}." + Style.RESET_ALL)
            self.deal_info_repo.upsert_deal(deal_name, deal_info)
            stats["deal_info_updated"] = True

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

    def _sync_deal_insights(self, deal_name: str, epoch0: str, stats: Dict) -> None:
        """Sync deal insights and concerns"""

        company_name = extract_company_name(deal_name)

        # loop each day from epoch0 to today
        start_date = datetime.strptime(epoch0, "%Y-%m-%d")
        end_date = datetime.now()

        concerns = []

        while start_date <= end_date:
            current_date = start_date.strftime("%Y-%m-%d")

            # check if a call exists for this deal on this date
            calls = self.gong_service.list_calls(current_date)
            call_id = self.gong_service.get_call_id(calls, company_name)

            if not call_id:
                start_date += timedelta(days=1)
                continue

            concerns.append(self.gong_service.get_concerns(deal_name, current_date))
            start_date += timedelta(days=1)

        if len(concerns) > 0:
            deal_insights_data = self._create_deal_insights_data(deal_name, concerns)
            print(Fore.BLUE + f"[MongoDB] Updating DealInsights for {deal_name}." + Style.RESET_ALL)
            self.deal_insights_repo.upsert_activity(deal_name, deal_insights_data)

    def _create_deal_insights_data(self, deal_name: str, concerns: Dict) -> Dict:
        """Create activity data structure from concerns"""
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

    def _sync_meeting_insights(self, deal_name: str, call_date: str) -> None:
        """Sync meeting information including champion analysis and buyer intent"""
        try:
            # First check if there are any meetings for this deal on the given date
            company_name = extract_company_name(deal_name)
            calls = self.gong_service.list_calls(call_date)
            call_id = self.gong_service.get_call_id(calls, company_name)
            
            if not call_id:
                return

            print(Fore.GREEN + f"A meeting was found for {deal_name} on {call_date}. Proceeding with sync..." + Style.RESET_ALL)

            print(Fore.GREEN + f"Getting buyer intent for {deal_name} on {call_date}..." + Style.RESET_ALL)
            buyer_intent = self.gong_service.get_buyer_intent(deal_name, call_date, "Galileo")

            print(Fore.GREEN + f"Getting champion results for {deal_name} on {call_date}..." + Style.RESET_ALL)
            call_datetime = datetime.strptime(call_date, "%Y-%m-%d")
            champion_results = self.gong_service.get_champions(deal_name, target_date=call_datetime)
            champion_data = []
            # Process champion results if available 
            if champion_results:
                print(Fore.GREEN + f"Processing champion results for {deal_name} on {call_date}..." + Style.RESET_ALL)

                for champion in champion_results:
                    # Ensure champion data is properly structured
                    champion_data.append({
                        "champion": champion.get("champion", False),
                        "explanation": champion.get("explanation", ""),
                        "email": champion.get("email", ""),
                        "speakerName": champion.get("speakerName", ""),
                        "business_pain": champion.get("business_pain", ""),
                        "parr_analysis": champion.get("parr_analysis", {})
                    })
            try:
                meeting_data = {
                    "deal_id": deal_name,
                    "meeting_id": f"{deal_name}_{call_date}",
                    "meeting_title": f"Call with {deal_name} on {call_date}",
                    "meeting_date": call_datetime,
                    "buyer_intent": buyer_intent,
                    "champion_analysis": champion_data,
                    "last_updated": datetime.now()
                }

                print(Fore.BLUE + f"[MongoDB] Updating MeetingInsights for {deal_name}." + Style.RESET_ALL)
                self.meeting_insights_repo.upsert_meeting(
                    deal_name,
                    meeting_data["meeting_id"],
                    meeting_data
                )
            except Exception as e:
                print(Fore.RED + f"Error processing champion {champion.get('speakerName', 'Unknown')}: {str(e)}" + Style.RESET_ALL)
                return 

        except Exception as e:
            print(Fore.RED + f"Error syncing meetings: {str(e)}" + Style.RESET_ALL)
            return

    def _sync_timeline_events(self, deal_name: str, call_datetime: datetime, stats: Dict) -> None:
        """Sync timeline events from activities and meetings"""
        try:
            # Get timeline data from Hubspot
            print(Fore.YELLOW + f"Getting timeline data from Hubspot for {deal_name}..." + Style.RESET_ALL)
            timeline_data = self.hubspot_service.get_deal_timeline(deal_name, include_content=True)

            stats["timeline_events"] = 0  # Reset counter since we're not processing events yet
            # add to mongo db
            print(Fore.BLUE + f"[MongoDB] Updating DealTimeline for {deal_name}." + Style.RESET_ALL)
            self.deal_timeline_repo.upsert_timeline(deal_name, timeline_data)
            stats["timeline_events"] = len(timeline_data)
        except Exception as e:
            print(Fore.RED + f"Error getting timeline data: {str(e)}" + Style.RESET_ALL)
            stats["errors"].append(f"Error getting timeline data: {str(e)}")

    def sync_company_overviews(self, deal_name: str) -> None:
        """Sync company overviews for a specific deal"""
        try:
            # Extract company name from deal name
            company_name = extract_company_name(deal_name)
            
            if not company_name or company_name == "Unknown Company":
                print(Fore.RED + f"No valid company name found for deal {deal_name}" + Style.RESET_ALL)
                return
            
            # Get company analysis from Firecrawl
            overview = get_company_analysis(company_name)

            # Store in MongoDB
            self.company_overview_repo.upsert_by_deal_id(deal_name, overview)
            print(Fore.GREEN + f"Synced company overview for {company_name}" + Style.RESET_ALL)
                
        except Exception as e:
            print(Fore.RED + f"Error syncing company overviews: {str(e)}" + Style.RESET_ALL)
            raise

    def sync_single_deal(self, deal_name: str, epoch0: str = "2025-02-15") -> None:
        """
        Sync data for a single deal across all collections
        Args:
            deal_name: The name of the deal to sync
            epoch0: The start date for syncing historical data
        """
        try:
            print(Fore.YELLOW + f"\n### Syncing Global Data for: {deal_name} ###" + Style.RESET_ALL)
            
            # Sync global deal data (deal info, insights, timeline)
            self.sync_global_deal_data(deal_name, epoch0)
            
            # Sync company overview
            # self.sync_company_overviews(deal_name)

            # Sync meeting data from epoch0 to today
            today = datetime.now().strftime("%Y-%m-%d")
            current_date = datetime.strptime(epoch0, "%Y-%m-%d")
            end_date = datetime.strptime(today, "%Y-%m-%d")

            print(Fore.YELLOW + f"\n### Syncing Meeting Data for: {deal_name} from {epoch0} to {today} ###" + Style.RESET_ALL)

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
