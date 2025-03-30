import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional
from colorama import Fore, Style, init

init()

class SessionService:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SessionService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            # Store active sessions with their metadata
            self._sessions: Dict[str, Dict] = {}
            self._session_ttl = timedelta(days=30)  # Sessions expire after 30 days
            self._initialized = True
            print(Fore.GREEN + "[SINGLETON] Initialized new SessionService instance" + Style.RESET_ALL)
        else:
            print(Fore.CYAN + "[SINGLETON] Reusing existing SessionService instance" + Style.RESET_ALL)

    def create_session(self, browser_id: str) -> str:
        """Create a new session for a browser"""
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {
            "browser_id": browser_id,
            "created_at": datetime.now(),
            "last_accessed": datetime.now()
        }
        print(Fore.GREEN + f"Created new session: {session_id} for browser: {browser_id}" + Style.RESET_ALL)
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data if it exists and is not expired"""
        if session_id not in self._sessions:
            return None

        session = self._sessions[session_id]
        if datetime.now() - session["last_accessed"] > self._session_ttl:
            del self._sessions[session_id]
            return None

        session["last_accessed"] = datetime.now()
        return session

    def validate_session(self, session_id: str) -> bool:
        """Check if a session is valid and not expired"""
        session = self.get_session(session_id)
        return session is not None

    def get_browser_id(self, session_id: str) -> Optional[str]:
        """Get the browser ID associated with a session"""
        session = self.get_session(session_id)
        return session["browser_id"] if session else None

    def cleanup_expired_sessions(self):
        """Remove all expired sessions"""
        current_time = datetime.now()
        expired_sessions = [
            session_id for session_id, session in self._sessions.items()
            if current_time - session["last_accessed"] > self._session_ttl
        ]
        for session_id in expired_sessions:
            del self._sessions[session_id]
        print(Fore.YELLOW + f"Cleaned up {len(expired_sessions)} expired sessions" + Style.RESET_ALL) 