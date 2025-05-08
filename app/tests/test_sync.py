import os
import sys
import argparse
from datetime import datetime, timedelta
from colorama import Fore, Style
# Add the project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from app.services.data_sync_service import DataSyncService

def get_epoch_date(days_ago: int) -> str:
    """Calculate epoch date based on days ago from today"""
    today = datetime.now()
    epoch_date = today - timedelta(days=days_ago)
    return epoch_date.strftime("%Y-%m-%d")

def test_sync(stage: str = "all", epoch0: str = None):
    # If epoch0 is not provided, default to today
    if epoch0 is None:
        epoch0 = datetime.now().strftime("%Y-%m-%d")
        
    print(Fore.YELLOW + f"\nSyncing deals (or deals from stage: {stage}) from {epoch0} to {datetime.now().strftime('%Y-%m-%d')}" + Style.RESET_ALL)
    # Initialize the service
    sync_service = DataSyncService()

    sync_service.sync(
        stage=stage,
        epoch0=epoch0
    )
    print(Fore.GREEN + "Sync completed successfully" + Style.RESET_ALL)

def test_sync_single_deal(deal_name: str, epoch0: str = None):
    """Test syncing data for a single deal"""
    # If epoch0 is not provided, default to today
    if epoch0 is None:
        epoch0 = datetime.now().strftime("%Y-%m-%d")
        
    # Initialize the service
    sync_service = DataSyncService()

    # Set up test parameters
    print(Fore.YELLOW + f"\nSyncing deal: {deal_name} from {epoch0} to {datetime.now().strftime('%Y-%m-%d')}" + Style.RESET_ALL)

    try:
        sync_service.sync_single_deal(
            deal_name=deal_name,
            epoch0=epoch0
        )
        print(Fore.GREEN + f"Successfully synced single deal: {deal_name}" + Style.RESET_ALL)
    except Exception as e:
        print(Fore.RED + f"Error syncing single deal: {str(e)}" + Style.RESET_ALL)
        raise

def main():
    parser = argparse.ArgumentParser(description='Sync data from HubSpot and Gong')
    parser.add_argument('--epoch-days', type=int, help='Number of days ago to start syncing from')
    parser.add_argument('--deal', type=str, help='Specific deal name to sync')
    parser.add_argument('--stage', type=str, help='Specific stage to sync deals from')
    
    args = parser.parse_args()
    
    if args.deal:
        # If deal is specified, sync only that deal
        epoch0 = get_epoch_date(args.epoch_days) if args.epoch_days else None
        test_sync_single_deal(args.deal, epoch0)
    else:
        # If no deal specified, sync all deals or deals from specific stage
        epoch0 = get_epoch_date(args.epoch_days) if args.epoch_days else None
        stage = args.stage if args.stage else "all"
        test_sync(stage, epoch0)

if __name__ == "__main__":
    main()
