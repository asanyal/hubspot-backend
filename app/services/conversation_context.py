from typing import Dict, Optional
import threading

class ConversationContextService:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ConversationContextService, cls).__new__(cls)
                    cls._instance._context: Dict[str, str] = {}
        return cls._instance
    
    def set_company_name(self, browser_id: str, company_name: str) -> None:
        """Set the company name for a given browser ID."""
        with self._lock:
            self._context[browser_id] = company_name
    
    def get_company_name(self, browser_id: str) -> Optional[str]:
        """Get the company name for a given browser ID."""
        with self._lock:
            return self._context.get(browser_id)
    
    def clear_context(self, browser_id: str) -> None:
        """Clear the context for a given browser ID."""
        with self._lock:
            if browser_id in self._context:
                del self._context[browser_id] 