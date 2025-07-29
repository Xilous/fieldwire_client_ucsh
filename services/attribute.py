"""Attribute service for Fieldwire API."""

from core.auth import AuthManager
from utils.decorators import paginate_response, update_last_response
from utils.input_helpers import get_user_input, prompt_user_for_xml_file
from processors.xml_processor import parse_xml_file

class AttributeService(AuthManager):
    """Service for task attribute operations."""

    @paginate_response()
    def get_all_task_type_attributes_in_project(self, project_id):
        """Get all task type attributes in a project with pagination support."""
        url = f"{self.project_base_url}/projects/{project_id}/task_type_attributes"
        headers = {'Fieldwire-Filter': 'active'}  # Define headers specific to this endpoint
        return url, headers  # Return both URL and headers for the paginator to use

    @paginate_response()
    def get_all_task_attributes_in_project(self, project_id):
        """Get all task attributes in a project with pagination support."""
        url = f"{self.project_base_url}/projects/{project_id}/task_attributes"
        headers = {'Fieldwire-Filter': 'active'}  # Define headers specific to this endpoint
        return url, headers  # Return both URL and headers for the paginator to use

    @update_last_response()
    def create_a_task_attribute_in_task(self, project_id, task_id, task_type_attribute_id, attribute_value, user_id):
        """Create a task attribute in a task."""
        url = f"{self.project_base_url}/projects/{project_id}/tasks/{task_id}/task_attributes"

        payload = {
            "task_type_attribute_id": task_type_attribute_id,
            "text_value": attribute_value,
            "creator_user_id": user_id,
            "last_editor_user_id": user_id
        }

        response = self.send_request(
            "POST", 
            url, 
            json=payload,
            expected_status_codes=[200, 201]
        )
        
        if not self.validate_response(response, [200, 201]):
            raise Exception(f"Failed to create task attribute. Status code: {response.status_code}")
        
        print("Task attribute created successfully.")
        return response.json()

    @paginate_response()
    def get_all_task_check_items_in_project(self, project_id):
        """Get all active task check items in a project with pagination support.
        
        Args:
            project_id: The ID of the project to get check items from.
            
        Returns:
            tuple: URL and headers for the API endpoint.
        """
        url = f"{self.project_base_url}/projects/{project_id}/task_check_items"
        headers = {'Fieldwire-Filter': 'active'}  # Always get active items
        return url, headers  # Return both URL and headers for the paginator to use

    @update_last_response()
    def create_a_new_task_check_item(self, project_id, task_id, creator_user_id, last_editor_user_id, name, state=None):
        """Create a new task check item.
        
        Args:
            project_id (str): Project ID
            task_id (str): Task ID
            creator_user_id (int): Creator user ID
            last_editor_user_id (int): Last editor user ID  
            name (str): Name of the checklist item
            state (str, optional): State of the checklist item (empty, yes, no, not_applicable)
        
        Returns:
            dict: Created check item data if successful, None otherwise
        """
        url = f"{self.project_base_url}/projects/{project_id}/tasks/{task_id}/task_check_items"
        
        payload = {
            "creator_user_id": creator_user_id,
            "last_editor_user_id": last_editor_user_id,
            "name": name
        }
        
        # Add state if provided
        if state is not None:
            payload["state"] = state

        response = self.send_request(
            "POST", 
            url, 
            json=payload,
            expected_status_codes=[201]
        )
        
        if self.validate_response(response, [201]):
            print("Task check item created successfully.")
            return response.json()
        return None

    @update_last_response()
    def create_multiple_checklist_items_in_task(self, project_id, task_id, names):
        """Create multiple task check items at once."""
        url = f"{self.project_base_url}/projects/{project_id}/tasks/{task_id}/task_check_items/batch"
        
        payload = {
            "checklist_item_attrs": [
                {
                    "name": name,
                    "device_created_at": None
                }
                for name in names
            ]
        }

        response = self.send_request(
            "POST", 
            url, 
            json=payload,
            expected_status_codes=[201]
        )
        
        if self.validate_response(response, [201]):
            print(f"Successfully created {len(names)} checklist items.")
            return response.json()
        return None

    def get_all_teams_in_project(self, project_id):
        """Get all active teams in a project.
        
        Args:
            project_id: The ID of the project to get teams from.
            
        Returns:
            dict: JSON response containing the teams data.
        """
        url = f"{self.project_base_url}/projects/{project_id}/teams"
        headers = {'Fieldwire-Filter': 'active'}  # Always get active items
        
        print(f"\nRetrieving teams for project_id: {project_id}")
        response = self.send_request('GET', url, headers=headers)
        
        if self.validate_response(response):
            print(f"Successfully retrieved teams.")
            return response.json()
        return None

    def initialize_task_attributes(self, project_id, task_service):
        """Initialize task attributes for a project."""
        try:
            # Get the XML file path from the user
            file_path = prompt_user_for_xml_file()
            if not file_path:
                print("No file selected.")
                return

            # Parse the XML file to extract openings
            print("Parsing XML file...")
            openings = parse_xml_file(file_path)
            print(f"Parsed {len(openings)} openings from the XML file.")

            print(f"Retrieving active tasks for project_id: {project_id}...")
            tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            if not tasks:
                raise Exception("Failed to retrieve active tasks from project")
            print(f"Retrieved {len(tasks)} active tasks.")

            print("Retrieving task type attributes...")
            task_type_attributes = self.get_all_task_type_attributes_in_project(project_id)
            if not task_type_attributes:
                raise Exception("Failed to retrieve task type attributes")
            print(f"Retrieved {len(task_type_attributes)} task type attributes.")

            # Create a mapping of task type attribute names to their IDs
            relevant_attributes = [
                "Quantity", "Type", "NominalWidth", "NominalHeight", 
                "Hand", "Location1", "ToFrom", "Location2", "HardwareGroup"
            ]

            task_type_attribute_map = {
                attr['name']: attr['id']
                for attr in task_type_attributes
                if attr['name'] in relevant_attributes
            }
            print(f"Filtered Task Type Attribute Map: {task_type_attribute_map}")

            user_id = get_user_input("Enter the user_id to be used for task attributes: ")

            for opening in openings:
                opening_number = opening["Number"]
                print(f"\nProcessing Opening Number: {opening_number}")
        
                # Find the matching task by name
                matching_task = None
                for task in tasks:
                    print(f"Comparing with Task Name: {task['name']}")
                    if task['name'] == opening_number:
                        matching_task = task
                        print(f"Match found: Task ID {task['id']} matches Opening Number {opening_number}")
                        break
        
                if not matching_task:
                    raise Exception(f"No matching task found for Opening Number: {opening_number}")

                task_id = matching_task['id']
            
                attributes_dict = opening.get("Attributes", {})
                for attribute_name, attribute_value in attributes_dict.items():
                    print(f"Checking attribute '{attribute_name}' with value '{attribute_value}'...")
                
                    if attribute_name in task_type_attribute_map:
                        task_type_attribute_id = task_type_attribute_map[attribute_name]
                        print(f"Creating task attribute for '{attribute_name}' with value '{attribute_value}'")
                        result = self.create_a_task_attribute_in_task(project_id, task_id, task_type_attribute_id, attribute_value, user_id)
                        if not result:
                            raise Exception(f"Failed to create task attribute '{attribute_name}' with value '{attribute_value}' for task {task_id}")
                        print(f"Task attribute for '{attribute_name}' created successfully.")
                    else:
                        print(f"No task type attribute found for '{attribute_name}'. Skipping...")

            print("\nAll task attributes initialized successfully!")

        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further attributes will be processed.")

    @update_last_response()
    def update_task_check_item(self, project_id, task_id, check_item_id, new_name, last_editor_user_id):
        """Update a task check item's name.
        
        Args:
            project_id (str): Project ID
            task_id (str): Task ID (not used in URL but kept for backward compatibility)
            check_item_id (str): Check item ID to update
            new_name (str): New name for the check item
            last_editor_user_id (int): User ID of the person making the update
            
        Returns:
            dict: Updated check item data if successful, None otherwise
        """
        url = f"{self.project_base_url}/projects/{project_id}/task_check_items/{check_item_id}"
        
        payload = {
            "name": new_name,
            "last_editor_user_id": last_editor_user_id
        }
        
        response = self.send_request(
            "PATCH", 
            url, 
            json=payload,
            expected_status_codes=[200, 201]
        )
        
        if self.validate_response(response, [200, 201]):
            return response.json()
        return None

    def delete_task_check_item(self, project_id, check_item_id):
        """Delete a task check item by ID.
        
        Args:
            project_id (str): Project ID
            check_item_id (str): Check item ID to delete
            
        Returns:
            bool: True if deletion successful, False otherwise
        """
        url = f"{self.project_base_url}/projects/{project_id}/task_check_items/{check_item_id}"
        
        response = self.send_request(
            "DELETE", 
            url,
            expected_status_codes=[204]
        )
        
        return self.validate_response(response, [204])
