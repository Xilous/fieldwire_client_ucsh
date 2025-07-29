"""Project service for Fieldwire API."""

from core.auth import AuthManager
from utils.decorators import paginate_response, update_last_response
from utils.input_helpers import get_user_input

class ProjectService(AuthManager):
    """Service for project operations."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._projects_cache = None

    def initialize_project_cache(self):
        """Initialize project cache during application startup.
        
        Returns:
            bool: True if cache was successfully initialized
        """
        try:
            print("Retrieving projects...")
            projects = self.get_projects(filter_option='active')
            
            # Store only id and name in cache
            self._projects_cache = [
                {
                    'id': project['id'],
                    'name': project['name']
                }
                for project in projects
            ]
            
            print(f"Successfully cached {len(self._projects_cache)} projects")
            return True
            
        except Exception as e:
            print(f"Error initializing project cache: {str(e)}")
            return False

    def refresh_project_cache(self):
        """Refresh the project cache with updated data from the API.
        
        Returns:
            bool: True if cache was successfully refreshed
        """
        try:
            print("Refreshing project cache...")
            projects = self.get_projects(filter_option='active')
            
            # Store only id and name in cache
            self._projects_cache = [
                {
                    'id': project['id'],
                    'name': project['name']
                }
                for project in projects
            ]
            
            print(f"Successfully refreshed cache with {len(self._projects_cache)} projects")
            return True
            
        except Exception as e:
            print(f"Error refreshing project cache: {str(e)}")
            return False

    def get_project_id_from_name_or_id(self, input_value):
        """Get project ID from name or ID input.
        
        Args:
            input_value (str): Project name or ID
            
        Returns:
            str: Project ID if found, None if not found
        """
        if not self._projects_cache:
            print("Project cache not initialized")
            return None
            
        # First check if input is a UUID
        if len(input_value) == 36 and '-' in input_value:
            return input_value
            
        # Look for exact name match
        for project in self._projects_cache:
            if project['name'] == input_value:
                return project['id']
                
        return None

    @paginate_response()
    def get_projects(self, filter_option='all'):
        """Get all projects with pagination support."""
        url = f"{self.project_base_url}/account/projects"
        
        # Validate filter option
        if filter_option not in ['all', 'active', 'deleted']:
            print(f"Invalid filter option '{filter_option}'. Defaulting to 'all'.")
            filter_option = 'all'
        
        # Return URL and headers for the decorator to handle
        headers = {'Fieldwire-Filter': filter_option}
        return url, headers

    @update_last_response()
    def create_project(self):
        """Create a new project."""
        # Prompt the user for project-related inputs
        name = get_user_input("Enter the project name: ")
        is_email_notifications_enabled = get_user_input("Enable email notifications? (true/false): ").strip().lower() == "true"
        prompt_effort_on_complete = get_user_input("Prompt effort on complete? (true/false): ").strip().lower() == "true"
        address = get_user_input("Enter the project address: ")
        code = get_user_input("Enter the project number: ")
        is_plan_email_notifications_enabled = get_user_input("Enable plan email notifications? (true/false): ").strip().lower() == "true"

        # Static source parameters
        source = {
            "project_template_id": "b0fba303-9f09-4602-b160-c63ffc0fe577",
            "copy_teams": True,
            "copy_users": True,
            "copy_template_checklists": True,
            "copy_report_templates": True,
            "copy_locations": True,
            "copy_form_templates": True,
            "copy_folders": True,
            "copy_settings": True,
            "copy_statuses": True,
            "copy_tags": True
        }

        # Create the payload
        payload = {
            "project": {
                "has_logo": True,
                "is_email_notifications_enabled": is_email_notifications_enabled,
                "name": name,
                "prompt_effort_on_complete": prompt_effort_on_complete,
                "address": address,
                "code": code,
                "is_plan_email_notifications_enabled": is_plan_email_notifications_enabled,
                "tz_name": "America/New_York"
            },
            "source": source
        }

        # API URL
        url = f"{self.project_base_url}/projects"

        # Send the request
        response = self.send_request(
            "POST", 
            url, 
            json=payload,
            expected_status_codes=[200, 201]
        )
        
        if self.validate_response(response, [200, 201]):
            print("Project created successfully.")
            return response.json()
        return None
