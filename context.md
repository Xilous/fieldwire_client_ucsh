# Fieldwire Client Architecture Context

## Service Architecture

The Fieldwire Client follows a specific architecture pattern for all service classes. Understanding this pattern is critical when adding new services to the codebase.

### Authentication and Service Initialization

1. **AuthManager Base Class**
   - All service classes inherit from `AuthManager` (defined in `core/auth.py`)
   - `AuthManager` handles authentication, token management, and API requests
   - Requires a `bearer_token` in its constructor

2. **Service Class Initialization Pattern**
   - Service classes use a flexible `__init__` method that accepts either an `AuthManager` instance or a `bearer_token`
   - The pattern used is: `def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)`
   - This allows services to be initialized in the CLI with `service = ServiceClass(api)` where `api` is an `AuthManager` instance

3. **Application Initialization Flow**
   - In `main.py`, an `AuthManager` instance is created: `api = AuthManager(bearer_token)`
   - This `api` object is passed to `run_cli(api, project_service)`
   - In `cli.py`, all services are initialized with this `api` object: `service = ServiceClass(api)`

### API Request Handling and Error Management

1. **Service Layer Abstraction**
   - NEVER make direct API calls using `self.send_request()` in business logic
   - ALWAYS use the appropriate service methods that wrap the API calls
   - Example: Use `attribute_service.update_task_check_item()` rather than manually constructing and sending a PATCH request

2. **Error Handling Pattern**
   - Service methods use the `@update_last_response()` decorator which handles response validation
   - When catching exceptions from service methods, check for specific error types:
     ```python
     try:
         attribute_service.update_task_check_item(...)
     except Exception as e:
         if "404" in str(e):
             # Handle resource not found gracefully
         else:
             # Handle other errors
     ```

3. **Resource Existence Verification**
   - Do not manually send GET requests to verify if resources exist before updating
   - Instead, attempt the update and handle 404 errors gracefully
   - This reduces unnecessary API calls and follows the established pattern

4. **Response Status Codes**
   - 200/201: Successful operations
   - 404: Resource not found (common when updating items that were deleted)
   - 401: Authentication issue (handled automatically by `AuthManager`)
   - Services define expected status codes in their method signatures

5. **Headers and Authentication**
   - All headers, including authentication, are managed by the service methods
   - The `AuthManager` class handles token refresh automatically when needed
   
### Adding New Services

When adding a new service class:

1. Create a new file in the `services/` directory
2. Define a class that inherits from `AuthManager`
3. Use the flexible initialization pattern:
   ```python
   def __init__(self, *args, **kwargs):
       super().__init__(*args, **kwargs)
       # Additional service-specific initialization
   ```
4. Add any service-specific properties and methods
5. When initializing the service in `cli.py`, use `service = YourServiceClass(api)`

### Example Service Class Structure

```python
from core.auth import AuthManager
from utils.decorators import paginate_response, update_last_response

class YourServiceClass(AuthManager):
    """Service for your specific operations."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Service-specific properties
        self.some_property = "value"
    
    @paginate_response()
    def get_some_data(self, project_id):
        """Get data with pagination support."""
        url = f"{self.project_base_url}/projects/{project_id}/some_endpoint"
        return url, {}  # Return URL and optional headers
    
    @update_last_response()
    def create_some_resource(self, project_id, data):
        """Create a resource."""
        url = f"{self.project_base_url}/projects/{project_id}/some_endpoint"
        response = self.send_request("POST", url, json=data)
        if self.validate_response(response, [201]):
            return response.json()
        return None
```

## Common Patterns and Best Practices

1. **Pagination Support**
   - Use the `@paginate_response()` decorator for methods that retrieve lists of resources
   - Return the URL and headers from these methods for the decorator to handle pagination

2. **Response Tracking**
   - Use the `@update_last_response()` decorator for methods that modify resources
   - This helps with tracking the last API response for debugging

3. **Error Handling**
   - Use `self.validate_response()` to check API responses
   - Provide detailed error messages when API calls fail

4. **Rate Limiting**
   - For batch operations, use `RateLimitedExecutor` from `utils.rate_limiter`
   - This prevents exceeding API rate limits when performing many operations

5. **Service Composition**
   - Services are often used together (e.g., `task_service` and `attribute_service`)
   - Pass service instances as parameters instead of creating new instances
   - This maintains authentication context and prevents token duplication

## Fieldwire API Pagination

The Fieldwire API uses cursor-based pagination for endpoints that return large collections of resources. Understanding and properly handling pagination is critical when working with the Fieldwire API.

### Pagination Implementation Details

1. **Pagination Header**
   - The API uses the `Fieldwire-Per-Page` header to control the number of items per page (up to 1000)
   - Responses include `X-Has-More: true` header when more items are available
   - The `X-Last-Synced-At` header provides the cursor value for retrieving the next page

2. **Pagination Decorator**
   - The codebase implements pagination through the `@paginate_response()` decorator (defined in `utils/decorators.py`)
   - This decorator wraps methods that need to retrieve potentially large collections of data
   - Decorated methods MUST return:
     - A URL for the API endpoint (required)
     - Additional headers as a dictionary (optional)
     - Query parameters as a dictionary (optional)

3. **Pagination Handler**
   - The `handle_paginated_response` method in `AuthManager` (defined in `core/auth.py`) handles the actual pagination logic
   - It automatically fetches all pages of results and combines them into a single list
   - It uses the `X-Has-More` and `X-Last-Synced-At` headers to determine when to stop requesting pages

### Implementing Paginated Endpoints

To implement a new method that retrieves a potentially large collection:

```python
@paginate_response()
def get_all_resources_in_project(self, project_id, filter_option='all'):
    """Get all resources in a project with pagination support."""
    url = f"{self.project_base_url}/projects/{project_id}/resources"
    
    # Optional: Add filter headers if needed
    headers = {'Fieldwire-Filter': filter_option}
    
    # Return URL and headers for the decorator to handle
    return url, headers
```

The pagination system will then:
1. Make the initial request to the URL with the provided headers
2. Check if there are more pages (`X-Has-More: true`)
3. If yes, make additional requests with the `last_synced_at` parameter from the `X-Last-Synced-At` header
4. Combine all results into a single list and return it

### Important Considerations

1. **Unpaginated Methods**: 
   - Methods NOT decorated with `@paginate_response()` will only return the first page of results
   - This can lead to incomplete data and hard-to-detect bugs

2. **Working with Paginated Results**:
   - Always use a paginated method when retrieving collections of resources
   - The return value is the combined list of all items across all pages

3. **Debugging Pagination Issues**:
   - Enable verbose output to see the pagination headers
   - Check for the expected structure in response headers
   - Verify the cursor value is being properly passed

4. **Performance Considerations**:
   - Pagination can result in multiple API calls for large datasets
   - Be mindful of rate limits and execution time
   - Consider implementing filtering at the API level when possible

Remember that all service methods that retrieve collections of resources (tasks, attributes, locations, etc.) should use the `@paginate_response()` decorator to ensure complete data retrieval.

## Parallel Processing with Rate Limiting

The Fieldwire API enforces rate limits on API requests. To maximize throughput while respecting these limits, the codebase implements parallel processing with rate limiting.

### RateLimitedExecutor Implementation

1. **RateLimitedExecutor Class**:
   - Defined in `utils/rate_limiter.py`
   - Uses Python's `concurrent.futures` module to create a thread pool
   - Controls the rate of API requests to prevent hitting rate limits

2. **Parallel Execution Pattern**:
   - Create a `RateLimitedExecutor` instance
   - Prepare a list of operations (functions) to execute in parallel
   - Call `executor.execute_parallel(operations)` with the list of functions
   - Process the results, which can be either a boolean or a list of individual results

### Implementation Example

```python
# Create executor for parallel operations
executor = RateLimitedExecutor()

# Prepare operations
operations = []
for item_id in items_to_process:
    def process_item(item_id=item_id):  # Capture item_id in closure
        return service.update_item(project_id, item_id, new_value)
    operations.append(process_item)

# Execute operations in parallel
results = executor.execute_parallel(operations)

# Process results
if isinstance(results, bool):
    # All operations succeeded or failed together
    if results:
        print(f"All {len(operations)} operations succeeded")
    else:
        print("All operations failed")
else:
    # Individual results for each operation
    success_count = sum(1 for result in results if result)
    print(f"Successfully processed {success_count} of {len(operations)} items")
```

### Important Considerations

1. **Lambda Capture Pitfall**:
   - When using lambdas or nested functions, always capture loop variables in default arguments
   - Example: `lambda item_id=item_id: ...` instead of `lambda: ... item_id ...`
   - Without this, all operations will use the last value from the loop

2. **Result Handling**:
   - `execute_parallel()` returns either a boolean (for all-or-nothing execution) or a list of results
   - Always check the type of the result before processing

3. **Operation Definition**:
   - Each operation should be a function that takes no arguments
   - Use default arguments in lambda or nested functions to capture values from the outer scope

4. **Error Handling**:
   - The executor catches exceptions from individual operations
   - Failed operations return `False` or `None` in the results list
   - Check each result to determine if the corresponding operation succeeded

5. **Progress Reporting**:
   - For long-running operations, consider adding progress reporting
   - Use tqdm or similar libraries to show progress bars

This pattern is extensively used throughout the codebase for operations that require multiple API calls, such as updating tasks, creating checklist items, or processing attributes.

## CLI Integration

When adding a new service to the CLI:

1. Import the service class in `cli/cli.py`
2. Initialize the service with `api` in the `run_cli` function
3. Add appropriate menu options and handlers that use the service

Remember that services are passed to each other in method calls, not recreated in each method. For example, when `hardware_service.method(project_id, user_id, task_service, attribute_service)` is called, it uses the already initialized services. 

## Fieldwire API Endpoint Structure

When working with the Fieldwire API, it's critical to use the correct endpoint structure. The official Fieldwire API documentation should be referenced for the most up-to-date endpoint patterns.

### Task Check Item Endpoints

A particularly important note is the endpoint structure for task check items:

* **Correct**: `/projects/{project_id}/task_check_items/{check_item_id}`
* **Incorrect**: `/projects/{project_id}/tasks/{task_id}/task_check_items/{check_item_id}`

Even though the task_id is often needed for logical operations and is passed to methods for context, it should not be included in the URL path for certain endpoints. Always check the official Fieldwire API documentation for the correct endpoint structure.

### API Version Headers

All Fieldwire API requests require a `Fieldwire-Version` header. This is set in the config/settings.py file as `API_VERSION`. The format is YYYY-MM-DD and determines which version of the API is used. Be careful when updating this version as it may change endpoint behavior.

### Fieldwire API Status Codes

The Fieldwire API uses standard HTTP status codes, but with some particularities:

* **200 OK**: Standard success response for most operations
* **201 Created**: Success response for creation operations, but also returned for some PATCH operations (like updating task check items)
* **404 Not Found**: Resource doesn't exist or has been deleted
* **401 Unauthorized**: Authentication token is invalid or expired

When validating responses, always include both 200 and 201 as expected success codes for operations that modify resources:

```python
response = self.send_request(
    "PATCH", 
    url, 
    json=payload,
    expected_status_codes=[200, 201]
)

if self.validate_response(response, [200, 201]):
    # Success handling
``` 