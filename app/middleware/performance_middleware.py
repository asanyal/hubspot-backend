import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from colorama import Fore, Style, init

init()

class PerformanceMiddleware(BaseHTTPMiddleware):
    """Middleware to track request timing and concurrent request handling"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Get the path for logging
        path = request.url.path
        method = request.method

        # Log request start
        print(Fore.CYAN + f"→ [{method}] {path} - Request started" + Style.RESET_ALL)

        # Process the request
        response = await call_next(request)

        # Calculate elapsed time
        elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds

        # Color code based on performance
        if elapsed_time < 100:
            color = Fore.GREEN
            perf_label = "FAST"
        elif elapsed_time < 1000:
            color = Fore.YELLOW
            perf_label = "OK"
        else:
            color = Fore.RED
            perf_label = "SLOW"

        # Log request completion with timing
        print(color + f"← [{method}] {path} - Completed in {elapsed_time:.2f}ms [{perf_label}]" + Style.RESET_ALL)

        # Add timing header to response
        response.headers["X-Response-Time"] = f"{elapsed_time:.2f}ms"

        return response
