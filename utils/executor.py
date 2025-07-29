"""Executor for handling parallel operations with rate limiting."""

import concurrent.futures
from typing import List, Union, Callable
from utils.rate_limiter import RateLimiter

class RateLimitedExecutor:
    """Executor that manages parallel operations with rate limiting."""
    
    def __init__(self, max_workers: int = 10):
        """Initialize the executor.
        
        Args:
            max_workers (int): Maximum number of worker threads. Defaults to 10.
        """
        self.max_workers = max_workers
        self.rate_limiter = RateLimiter()
    
    def execute_parallel(self, operations: List[Callable]) -> Union[bool, List[bool]]:
        """Execute a list of operations in parallel with rate limiting.
        
        Args:
            operations (List[Callable]): List of callable operations to execute
            
        Returns:
            Union[bool, List[bool]]: 
                - If all operations succeed, returns True
                - If any operation fails, returns False
                - If detailed results are needed, returns list of boolean results
        """
        if not operations:
            return True
            
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all operations to the executor
            future_to_op = {
                executor.submit(self._execute_with_rate_limit, op): op 
                for op in operations
            }
            
            # Process results as they complete
            for future in concurrent.futures.as_completed(future_to_op):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    print(f"Error executing operation: {str(e)}")
                    results.append(False)
        
        # Return appropriate result based on results
        if all(results):
            return True
        elif any(results):
            return results  # Return detailed results if some succeeded
        else:
            return False
    
    def _execute_with_rate_limit(self, operation: Callable) -> bool:
        """Execute a single operation with rate limiting.
        
        Args:
            operation (Callable): Operation to execute
            
        Returns:
            bool: True if operation succeeded, False otherwise
        """
        try:
            # Wait for rate limit slot
            self.rate_limiter.wait_for_slot()
            
            # Execute operation
            result = operation()
            return bool(result)
        except Exception as e:
            print(f"Error in operation: {str(e)}")
            return False 