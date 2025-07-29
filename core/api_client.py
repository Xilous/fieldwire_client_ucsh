"""Base API client for Fieldwire API."""

from .auth import AuthManager

class BaseAPIClient(AuthManager):
    """Base API client with request handling."""
    pass
