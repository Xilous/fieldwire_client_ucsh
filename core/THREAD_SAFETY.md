# Thread Safety Implementation for Token Management

## Overview

This document describes the improvements made to `TokenManager` and `AuthManager` classes to support thread-safe operations in multi-threaded environments such as parallel API requests.

## Problem Statement

The original implementation of `TokenManager` was designed for single-threaded use. When used in multi-threaded contexts (such as `process_door_hardware_sequence` and `process_task_locations`), the following issues could occur:

1. **Race Conditions**: Multiple threads detecting token expiration simultaneously could lead to redundant token refreshes.
2. **Inconsistent State**: One thread might update the token while another is using it, leading to inconsistent authentication state.
3. **Resource Waste**: Multiple unnecessary token refresh requests could be made.

## Implementation Details

### Thread-Safe TokenManager

The implementation adds the following thread-safety mechanisms:

1. **Singleton Creation Lock**: Uses a class-level lock to ensure thread-safe singleton creation.
   ```python
   _instance_lock = threading.Lock()
   ```

2. **Token Operation Lock**: Uses a reentrant lock for token operations to allow nested calls within the same thread.
   ```python
   self._token_lock = threading.RLock()
   ```

3. **Wait-If-Refreshing Pattern**: Uses a threading.Event to allow threads to wait for a token refresh to complete rather than attempting duplicate refreshes.
   ```python
   self._refresh_in_progress = False
   self._refresh_complete = threading.Event()
   ```

4. **Double-Check Pattern**: Optimizes performance by checking token validity before and after acquiring the lock.
   ```python
   # Quick check without full lock
   if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
       return self.access_token

   # Full lock for token refresh
   with self._token_lock:
       # Double-check pattern: check again after acquiring lock
       if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
           return self.access_token
   ```

5. **Thread-Safe Rate Limiting**: Ensures rate limiting works correctly across threads.
   ```python
   def _wait_for_rate_limit(self):
       with self._token_lock:
           # Rate limiting logic
   ```

### AuthManager Changes

The `AuthManager` class has minimal changes since it delegates token management to `TokenManager`:

1. **Unchanged Public Interface**: All method signatures and behaviors are maintained.
2. **Automatic Thread Safety**: Inherits thread safety from the improved TokenManager.

## Usage

The changes are fully backward compatible. Existing code will automatically benefit from the improved thread safety without any changes.

## Performance Considerations

There is a minimal performance impact due to lock acquisition, but this is typically negligible compared to the time required for network operations. The implementation optimizes for reliability over absolute performance by ensuring correct behavior in multi-threaded environments.

The double-check pattern minimizes lock contention in the common case where tokens are still valid.