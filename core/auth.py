"""Authentication manager for Fieldwire API."""

import requests
import json
import time
import threading
from datetime import datetime, timedelta
from config.settings import ACCOUNT_BASE_URL, PROJECT_BASE_URL, TOKEN_URL, API_VERSION

class TokenManager:
    """Singleton class to manage API tokens with thread safety."""
    _instance = None
    _instance_lock = threading.Lock()  # Class-level lock for singleton creation
    _request_interval = 0.1  # Minimum time between requests in seconds (10 requests per second)
    
    def __new__(cls, bearer_token=None):
        with cls._instance_lock:  # Thread-safe singleton creation
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.bearer_token = bearer_token
                cls._instance.access_token = None
                cls._instance.token_expiry = None
                cls._instance._last_request_time = None
                cls._instance._token_lock = threading.RLock()  # Reentrant lock for token operations
                cls._instance._refresh_in_progress = False
                cls._instance._refresh_complete = threading.Event()
                cls._instance._refresh_complete.set()  # Initially not refreshing
        return cls._instance
    
    def _wait_for_rate_limit(self):
        """Implement rate limiting to prevent exceeding API quota with thread safety."""
        with self._token_lock:
            if self._last_request_time is not None:
                elapsed = time.time() - self._last_request_time
                if elapsed < self._request_interval:
                    time.sleep(self._request_interval - elapsed)
            self._last_request_time = time.time()
    
    def get_access_token(self):
        """Request a new access token using the bearer token with thread safety."""
        # Quick check without full lock
        if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.access_token

        # Full lock for token refresh
        with self._token_lock:
            # Double-check pattern: check again after acquiring lock
            if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
                return self.access_token
                
            # Check if another thread is already refreshing
            if self._refresh_in_progress:
                # Release lock and wait for refresh to complete
                self._token_lock.release()
                self._refresh_complete.wait()  # Wait for refresh to complete
                self._token_lock.acquire()  # Re-acquire lock
                # Return the token which should now be refreshed
                return self.access_token
                
            # We'll handle the refresh
            self._refresh_in_progress = True
            self._refresh_complete.clear()
            
        # Release lock during the actual API call to prevent blocking
        try:
            # Implement rate limiting
            self._wait_for_rate_limit()
            
            headers = {
                'accept': 'application/json',
                'content-type': 'application/json',
                'Fieldwire-Version': API_VERSION
            }
            
            response = requests.post(
                TOKEN_URL,
                headers=headers,
                json={"api_token": self.bearer_token}
            )
            
            # Re-acquire lock to update token state
            with self._token_lock:
                if response.status_code == 201:  # Success status for token creation
                    data = response.json()
                    if 'access_token' not in data:
                        raise Exception("Access token not found in response")
                    self.access_token = data['access_token']
                    # Set token expiry to 1 hour from now (typical JWT expiry)
                    self.token_expiry = datetime.now() + timedelta(hours=1)
                    return self.access_token
                else:
                    raise Exception(f"Failed to get access token: {response.status_code} {response.text}")
                    
        except Exception as e:
            print(f"Error getting access token: {str(e)}")
            raise
        finally:
            # Always mark refresh as complete and allow other threads to continue
            with self._token_lock:
                self._refresh_in_progress = False
                self._refresh_complete.set()

    def refresh_access_token(self):
        """Refresh the access token with thread safety."""
        return self.get_access_token()

    def get_current_token(self):
        """Get the current access token, requesting a new one if needed."""
        if not self.access_token:
            return self.get_access_token()
        return self.access_token

class AuthManager:
    """Base class for API authentication and request handling."""
    
    def __init__(self, bearer_token):
        """Initialize with bearer token and set up token management."""
        self.bearer_token = bearer_token
        self.token_manager = TokenManager(bearer_token)
        self.project_base_url = PROJECT_BASE_URL
        self.account_base_url = ACCOUNT_BASE_URL
        self.last_json_response = None
        
        # Get initial access token
        self.token_manager.get_access_token()
    
    @property
    def headers(self):
        """Default headers for API requests."""
        return {
            'Authorization': f'Bearer {self.token_manager.get_current_token()}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Fieldwire-Version': API_VERSION
        }
    
    def merge_headers(self, additional_headers=None):
        """Merge additional headers with default headers."""
        final_headers = self.headers.copy()
        if additional_headers:
            final_headers.update(additional_headers)
        return final_headers
    
    def validate_response(self, response, expected_status_codes=None):
        """Validate API response."""
        if expected_status_codes is None:
            expected_status_codes = [200, 201]
            
        if response.status_code in expected_status_codes:
            return True
            
        error_msg = f"Request failed with status {response.status_code}"
        if response.text:
            try:
                error_details = response.json()
                error_msg += f": {error_details}"
            except ValueError:
                error_msg += f": {response.text}"
        
        print(error_msg)
        return False

    def send_request(self, method, url, headers=None, expected_status_codes=None, **kwargs):
        """Send a request to the Fieldwire API.
        
        Args:
            method (str): HTTP method (GET, POST, etc.)
            url (str): The URL to send the request to
            headers (dict, optional): Additional headers to include
            expected_status_codes (list, optional): List of expected success status codes
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            requests.Response: The response from the API
        """
        # Merge headers
        request_headers = self.merge_headers(headers)
        
        # Print request details for debugging
        print(f"\nSending {method} request to: {url}")
        print("Headers:", request_headers)
        if 'json' in kwargs:
            print("Payload:", kwargs['json'])
        
        response = requests.request(method, url, headers=request_headers, **kwargs)
        
        # Handle 401 (unauthorized) by refreshing token and retrying once
        if response.status_code == 401:
            print("Access token expired, refreshing...")
            # This will now be thread-safe:
            self.token_manager.refresh_access_token()
            request_headers = self.merge_headers(headers)  # Get fresh headers with new token
            response = requests.request(method, url, headers=request_headers, **kwargs)
        
        # Only print error messages for unexpected status codes
        if expected_status_codes and response.status_code in expected_status_codes:
            # This is an expected status code, don't print an error message
            pass
        else:
            # Validate response
            self.validate_response(response, expected_status_codes)
        
        return response

    def handle_paginated_response(self, url, headers=None, params=None):
        """Handle paginated API responses.
        
        Args:
            url (str): Base URL for the request
            headers (dict, optional): Additional headers to include
            params (dict, optional): Query parameters to include
            
        Returns:
            list: Combined results from all pages
        """
        all_items = []
        has_more = True
        last_synced_at = None
        
        # Add pagination header
        request_headers = headers.copy() if headers else {}
        request_headers['Fieldwire-Per-Page'] = '1000'  # Maximum recommended for efficiency
        
        while has_more:
            # Build URL with query parameters
            paginated_url = url
            query_params = params.copy() if params else {}
            
            # Add last_synced_at to params if we have it
            if last_synced_at:
                query_params['last_synced_at'] = last_synced_at
            
            # Make the request
            response = self.send_request(
                'GET', 
                paginated_url, 
                headers=request_headers,
                params=query_params,
                expected_status_codes=[200, 404]  # 404 is valid for empty results
            )
            
            # Debug information
            print("\nResponse Details:")
            print(f"Status Code: {response.status_code}")
            print("Response Headers:")
            for header, value in response.headers.items():
                print(f"  {header}: {value}")
            print("\nResponse Content:")
            try:
                print(json.dumps(response.json(), indent=2))
            except:
                print(response.text)
            
            # Handle 404 (no items found)
            if response.status_code == 404:
                break
                
            # Break if request failed with other error
            if not self.validate_response(response, [200, 404]):
                break
                
            # Parse the response
            try:
                items = response.json()
                if not items:  # No more items
                    break
                    
                all_items.extend(items)
            except json.JSONDecodeError as e:
                print(f"\nError decoding JSON response: {e}")
                print("Raw response content:")
                print(response.text)
                break
            
            # Check if there are more items
            has_more = response.headers.get('X-Has-More') == 'true'
            if has_more:
                last_synced_at = response.headers.get('X-Last-Synced-At')
                if not last_synced_at:  # If we don't get the header, stop pagination
                    break
        
        return all_items
