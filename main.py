from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import hubspot, hubspot_mongo
from app.middleware.session_middleware import SessionMiddleware
from app.middleware.response_middleware import ResponseMiddleware
from app.middleware.performance_middleware import PerformanceMiddleware

app = FastAPI(title="HubSpot CRM API")

allow_origins=[
    "https://hubspot-gong-db-atin4.replit.app",
    "https://midnight-snack-a7x9bq.replit.app",
    "http://localhost:3000"
]

# Configure CORS - moved to top and updated configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Add performance tracking middleware (first to measure total time)
app.add_middleware(PerformanceMiddleware)

# Add session middleware
app.add_middleware(SessionMiddleware)

# Add response middleware (must be after session middleware)
app.add_middleware(ResponseMiddleware)

# Include routers
app.include_router(hubspot.router, prefix="/api/hubspot", tags=["hubspot"])
app.include_router(hubspot_mongo.router, prefix="/api/hubspot/v2", tags=["hubspot-v2"])

if __name__ == "__main__":
    import uvicorn
    import os

    port = int(os.environ.get("PORT", 8000))  # <-- this is key for Heroku

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,       # Turn off reload in production
        workers=1,          # Single worker with async is efficient
        loop="uvloop",      # uvloop for better async performance
        limit_concurrency=1000,  # Allow up to 1000 concurrent requests
        backlog=2048,       # Queue size for pending connections
        timeout_keep_alive=75,  # Keep connections alive longer
        access_log=False,   # Disable for better performance (enable for debugging)
        # Performance optimizations
        limit_max_requests=10000,  # Restart worker after 10k requests to prevent memory leaks
        h11_max_incomplete_event_size=16384,  # Increase buffer size
    )