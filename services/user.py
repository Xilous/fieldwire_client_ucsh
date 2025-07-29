"""User service for Fieldwire API."""

from core.auth import AuthManager
from utils.decorators import paginate_response, update_last_response

class UserService(AuthManager):
    """Service for user operations."""

    @paginate_response()
    def get_users(self):
        """Get all users with pagination support."""
        url = f"{self.account_base_url}/account/users"
        return url

    @update_last_response()
    def get_user_by_id_or_name(self, user_input):
        """Get a user by their ID or full name."""
        # First try by ID
        url = f"{self.account_base_url}/account/users/{user_input}"
        response = self.send_request(
            "GET", 
            url, 
            expected_status_codes=[200, 404]  # 404 is expected if user not found
        )
        
        if response.status_code == 200:
            return response.json()
            
        # If not found by ID, get all users and search by name
        users = self.get_users()
        for user in users:
            if user.get('full_name') == user_input:
                return user
                
        print("No user found with the provided ID or name.")
        return None
