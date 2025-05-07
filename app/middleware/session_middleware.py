from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from app.services.session_service import SessionService
from colorama import Fore, Style, init

init()

class SessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.session_service = SessionService()

    async def dispatch(self, request: Request, call_next):
        # Debug print the path
        print(Fore.BLUE + f"Request path: {request.url.path}" + Style.RESET_ALL)
        
        # Skip session validation for health check and transcript endpoints
        if any(request.url.path.endswith(path) for path in [
            "/health",
            "/load-customer-transcripts",
            "/ask-customer"
        ]) or request.method == "OPTIONS":
            print(Fore.GREEN + f"Skipping session validation for {request.url.path}" + Style.RESET_ALL)
            return await call_next(request)

        # Get browser ID from request headers
        browser_id = request.headers.get("X-Browser-ID")
        if not browser_id:
            raise HTTPException(status_code=400, detail="Browser ID is required")

        # Get session ID from request headers
        session_id = request.headers.get("X-Session-ID")

        # If no session ID, create a new session
        if not session_id:
            session_id = self.session_service.create_session(browser_id)
            response = await call_next(request)
            response.headers["X-Session-ID"] = session_id
            return response

        # Validate existing session
        if not self.session_service.validate_session(session_id):
            # If session is invalid, create a new one
            session_id = self.session_service.create_session(browser_id)
            response = await call_next(request)
            response.headers["X-Session-ID"] = session_id
            return response

        # Session is valid, proceed with the request
        response = await call_next(request)
        response.headers["X-Session-ID"] = session_id
        return response 