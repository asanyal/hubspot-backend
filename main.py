from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import hubspot, hubspot_mongo
from app.middleware.session_middleware import SessionMiddleware
from app.middleware.response_middleware import ResponseMiddleware

app = FastAPI(title="HubSpot CRM API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=8,  # Number of worker processes
        loop="uvloop",  # Use uvloop for better performance
        limit_concurrency=1000,  # Maximum number of connections
        backlog=2048,  # Maximum number of pending connections
        timeout_keep_alive=30,  # Keep-alive timeout
        access_log=True
    )