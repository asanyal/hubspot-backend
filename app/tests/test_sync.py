import os
import sys
from colorama import Fore, Style
# Add the project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from app.services.data_sync_service import DataSyncService

def test_sync(stage, epoch0):
    # Initialize the service
    sync_service = DataSyncService()

    sync_service.sync(
        stage=stage,
        epoch0=epoch0
    )
    print(Fore.GREEN + "Sync completed successfully" + Style.RESET_ALL)

def test_sync_single_deal(deal_name, epoch0):
    """Test syncing data for a single deal"""
    # Initialize the service
    sync_service = DataSyncService()

    # Set up test parameters

    print(Fore.YELLOW + f"\nTesting sync for single deal: {deal_name}" + Style.RESET_ALL)
    
    try:
        sync_service.sync_single_deal(
            deal_name=deal_name,
            epoch0=epoch0
        )
        print(Fore.GREEN + f"Successfully synced single deal: {deal_name}" + Style.RESET_ALL)
    except Exception as e:
        print(Fore.RED + f"Error syncing single deal: {str(e)}" + Style.RESET_ALL)
        raise

if __name__ == "__main__":
    # Uncomment the test you want to run
    test_sync("2. Needs Analysis & Solution Mapping", "2025-02-01")
    # test_sync_single_deal("Deutsche Telekom - 001", "2025-02-01")
