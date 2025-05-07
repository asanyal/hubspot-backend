from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import hubspot, hubspot_mongo
from app.middleware.session_middleware import SessionMiddleware
from app.middleware.response_middleware import ResponseMiddleware

app = FastAPI(title="HubSpot CRM API")

# Configure CORS - moved to top and updated configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Your frontend URL
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

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
        workers=1,          # Heroku dynos don't need 8 workers unless you're using gunicorn
        loop="uvloop",
        limit_concurrency=1000,
        backlog=2048,
        timeout_keep_alive=30,
        access_log=True
    )