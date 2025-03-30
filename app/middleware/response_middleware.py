from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.services.session_service import SessionService
from colorama import Fore, Style, init

init()

class ResponseMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.session_service = SessionService()

    async def dispatch(self, request: Request, call_next):
        # Get browser ID from request headers
        browser_id = request.headers.get("X-Browser-ID")
        session_id = request.headers.get("X-Session-ID")

        # Process the request
        response = await call_next(request)

        # If we have a browser ID but no session ID, create a new session
        if browser_id and not session_id:
            session_id = self.session_service.create_session(browser_id)
            print(Fore.GREEN + f"Created new session: {session_id} for browser: {browser_id}" + Style.RESET_ALL)
        # If we have both, validate the session
        elif browser_id and session_id:
            if not self.session_service.validate_session(session_id):
                session_id = self.session_service.create_session(browser_id)
                print(Fore.YELLOW + f"Invalid session, created new one: {session_id}" + Style.RESET_ALL)

        # Add session ID to response headers if we have one
        if session_id:
            response.headers["X-Session-ID"] = session_id

        return response 