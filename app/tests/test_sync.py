import os
import sys
from colorama import Fore, Style
# Add the project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from app.services.data_sync_service import DataSyncService

def test_sync():
    # Initialize the service
    sync_service = DataSyncService()
    
    # Set up test parameters
    stage = "3. Technical Validation"
    epoch0 = "2025-02-01"

    sync_service.sync(
        stage=stage,
        epoch0=epoch0
    )
    print(Fore.GREEN + "Sync completed successfully" + Style.RESET_ALL)


if __name__ == "__main__":
    test_sync() 