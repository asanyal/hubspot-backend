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
        # Process the request and return response directly
        return await call_next(request) 