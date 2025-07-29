"""API configuration settings."""

# API Base URLs
PROJECT_BASE_URL = "https://client-api.us.fieldwire.com/api/v3"
ACCOUNT_BASE_URL = "https://client-api.super.fieldwire.com"
TOKEN_URL = "https://client-api.super.fieldwire.com/api_keys/jwt"

# API Version - Required for all requests
# Format: YYYY-MM-DD
API_VERSION = "2023-12-25"  # Using a recent stable version

# Pagination settings
DEFAULT_PER_PAGE = 100
