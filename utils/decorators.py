"""Decorators for API response handling."""

from functools import wraps
from config.settings import API_VERSION

def paginate_response():
    """Decorator for handling pagination in API responses."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Get the URL and any additional headers from the decorated function
            result = func(self, *args, **kwargs)
            
            # Check if result is a tuple containing URL, headers, and optionally params
            if isinstance(result, tuple):
                if len(result) == 3:
                    url, additional_headers, params = result
                elif len(result) == 2:
                    url, additional_headers = result
                    params = {}
                else:
                    url = result[0]
                    additional_headers = {}
                    params = {}
            else:
                url = result
                additional_headers = {}
                params = {}
            
            # Let AuthManager handle the pagination
            return self.handle_paginated_response(url, additional_headers, params)
            
        return wrapper
    return decorator

def update_last_response():
    """Decorator that updates the last_json_response attribute of the class."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            response = func(self, *args, **kwargs)
            if isinstance(response, (dict, list)):
                self.last_json_response = response
            return response
        return wrapper
    return decorator
