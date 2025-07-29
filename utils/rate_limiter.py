"""Rate limiter for managing API request rates."""

import time
from collections import deque
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any, List, Optional

class RateLimiter:
    """Rate limiter that ensures operations don't exceed a specified rate."""
    
    def __init__(self, max_requests: int = 10, time_window: float = 1.0):
        """Initialize the rate limiter.
        
        Args:
            max_requests (int): Maximum number of requests allowed in the time window
            time_window (float): Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = Lock()
    
    def wait_for_slot(self):
        """Wait until a request slot is available.
        
        This method will block until a request can be made without exceeding
        the rate limit.
        """
        with self.lock:
            now = time.time()
            
            # Remove old requests from the window
            while self.requests and now - self.requests[0] >= self.time_window:
                self.requests.popleft()
            
            # If we've hit the limit, wait until the oldest request expires
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] + self.time_window - now
                if sleep_time > 0:
                    time.sleep(sleep_time)
                now = time.time()
                self.requests.popleft()
            
            # Add the new request
            self.requests.append(now)

class RateLimitedExecutor:
    """Executor that manages rate-limited parallel operations."""
    
    def __init__(self, max_workers: int = 10):
        """Initialize executor.
        
        Args:
            max_workers: Maximum number of worker threads
        """
        self.max_workers = max_workers
        self.rate_limiter = RateLimiter(max_requests=max_workers)
        self.error_occurred = False
        
    def execute_parallel(self, 
                        operations: List[Callable[[], Any]], 
                        error_callback: Optional[Callable[[Exception], None]] = None) -> bool:
        """Execute operations in parallel with rate limiting.
        
        Args:
            operations: List of callable operations to execute
            error_callback: Optional callback to handle errors
            
        Returns:
            bool: True if all operations completed successfully, False otherwise
        """
        self.error_occurred = False
        
        def rate_limited_operation(operation: Callable[[], Any]) -> Any:
            """Execute an operation with rate limiting."""
            if self.error_occurred:
                return None
                
            try:
                self.rate_limiter.wait_for_slot()
                return operation()
            except Exception as e:
                self.error_occurred = True
                if error_callback:
                    error_callback(e)
                raise
                
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(rate_limited_operation, op) for op in operations]
            
            # Wait for all operations to complete
            for future in futures:
                try:
                    future.result()
                except Exception:
                    # Error already handled in rate_limited_operation
                    pass
                    
        return not self.error_occurred 