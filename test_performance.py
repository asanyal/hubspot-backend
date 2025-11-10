#!/usr/bin/env python3
"""
Performance test script for optimized endpoints
Tests the three-tier cache system: Memory -> MongoDB -> HubSpot API
"""

import requests
import time
from colorama import Fore, Style, init

init()

BASE_URL = "http://localhost:8000/api/hubspot"
DEAL_NAME = "YourDealName"  # Replace with actual deal name

def test_endpoint(endpoint: str, params: dict, test_name: str):
    """Test an endpoint and measure response time"""
    print(f"\n{'='*60}")
    print(f"Testing: {test_name}")
    print(f"{'='*60}")

    # Test 1: First call (should hit MongoDB or API)
    print(f"\n{Fore.YELLOW}[Test 1] First call (MongoDB/API){Style.RESET_ALL}")
    start = time.time()
    response = requests.get(f"{BASE_URL}{endpoint}", params=params)
    duration = (time.time() - start) * 1000
    print(f"Status: {response.status_code}")
    print(f"Duration: {Fore.CYAN}{duration:.2f} ms{Style.RESET_ALL}")
    print(f"Response: {response.json()}")

    # Test 2: Second call (should hit memory cache - SUPER FAST)
    print(f"\n{Fore.YELLOW}[Test 2] Second call (Memory Cache){Style.RESET_ALL}")
    start = time.time()
    response = requests.get(f"{BASE_URL}{endpoint}", params=params)
    duration = (time.time() - start) * 1000
    print(f"Status: {response.status_code}")
    print(f"Duration: {Fore.GREEN}{duration:.2f} ms{Style.RESET_ALL}")
    if duration < 5:
        print(f"{Fore.GREEN}✓ Cache hit! (< 5ms){Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}✗ Slower than expected for cache hit{Style.RESET_ALL}")

    # Test 3: Third call (verify consistent fast performance)
    print(f"\n{Fore.YELLOW}[Test 3] Third call (Memory Cache){Style.RESET_ALL}")
    start = time.time()
    response = requests.get(f"{BASE_URL}{endpoint}", params=params)
    duration = (time.time() - start) * 1000
    print(f"Status: {response.status_code}")
    print(f"Duration: {Fore.GREEN}{duration:.2f} ms{Style.RESET_ALL}")

def test_concurrent_requests():
    """Test that requests can now execute concurrently"""
    print(f"\n{'='*60}")
    print(f"Testing: Concurrent Request Handling")
    print(f"{'='*60}")

    import concurrent.futures

    endpoints = [
        ("/deal-activities-count", {"dealName": DEAL_NAME}),
        ("/deal-timeline", {"dealName": DEAL_NAME}),
        ("/deal-info", {"dealName": DEAL_NAME}),
    ]

    def call_endpoint(endpoint_info):
        endpoint, params = endpoint_info
        start = time.time()
        response = requests.get(f"{BASE_URL}{endpoint}", params=params)
        duration = (time.time() - start) * 1000
        return endpoint, duration, response.status_code

    print(f"\n{Fore.YELLOW}Making 3 concurrent requests...{Style.RESET_ALL}")
    overall_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(call_endpoint, endpoints))

    overall_duration = (time.time() - overall_start) * 1000

    print(f"\n{Fore.CYAN}Results:{Style.RESET_ALL}")
    for endpoint, duration, status in results:
        print(f"  {endpoint}: {duration:.2f} ms (status: {status})")

    print(f"\n{Fore.GREEN}Total time for all 3 requests: {overall_duration:.2f} ms{Style.RESET_ALL}")

    max_individual = max(duration for _, duration, _ in results)
    if overall_duration < (max_individual * 1.5):
        print(f"{Fore.GREEN}✓ Requests executed concurrently!{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}✗ Requests may be executing sequentially{Style.RESET_ALL}")

def test_cache_management():
    """Test cache management endpoints"""
    print(f"\n{'='*60}")
    print(f"Testing: Cache Management")
    print(f"{'='*60}")

    # Get cache stats
    print(f"\n{Fore.YELLOW}Getting cache stats...{Style.RESET_ALL}")
    response = requests.get(f"{BASE_URL}/cache-stats")
    print(f"Status: {response.status_code}")
    print(f"Cache Stats: {response.json()}")

    # Clear cache
    print(f"\n{Fore.YELLOW}Clearing cache...{Style.RESET_ALL}")
    response = requests.delete(f"{BASE_URL}/clear-endpoint-cache")
    print(f"Status: {response.status_code}")
    print(f"Result: {response.json()}")

if __name__ == "__main__":
    print(f"\n{Fore.BLUE}{'='*60}")
    print(f"Performance Test Suite for Optimized Endpoints")
    print(f"{'='*60}{Style.RESET_ALL}")
    print(f"\nBase URL: {BASE_URL}")
    print(f"Deal Name: {DEAL_NAME}")
    print(f"\n{Fore.YELLOW}Note: Replace DEAL_NAME with an actual deal from your system{Style.RESET_ALL}")

    try:
        # Test individual endpoints
        test_endpoint("/deal-activities-count", {"dealName": DEAL_NAME},
                     "Deal Activities Count Endpoint")

        test_endpoint("/deal-timeline", {"dealName": DEAL_NAME},
                     "Deal Timeline Endpoint")

        # Test concurrent execution
        test_concurrent_requests()

        # Test cache management
        test_cache_management()

        print(f"\n{Fore.GREEN}{'='*60}")
        print(f"All tests completed!")
        print(f"{'='*60}{Style.RESET_ALL}\n")

    except requests.exceptions.ConnectionError:
        print(f"\n{Fore.RED}Error: Could not connect to {BASE_URL}")
        print(f"Make sure the server is running with: python main.py{Style.RESET_ALL}\n")
    except Exception as e:
        print(f"\n{Fore.RED}Error: {str(e)}{Style.RESET_ALL}\n")
        import traceback
        traceback.print_exc()
