# app/web_services/__init__.py
"""
Web Services package initializer.
Exports domain-specific web services and provides a unified facade.
"""

from app.web_services.auth import AuthWebService
from app.web_services.emails import EmailWebService
from app.web_services.search import SearchWebService
from app.web_services.threads import ThreadWebService
from app.web_services.tasks import TaskWebService

__all__ = [
    "AuthWebService",
    "EmailWebService",
    "SearchWebService",
    "ThreadWebService",
    "TaskWebService",
]
