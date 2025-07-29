"""Service for managing Fieldwire entity tags and taggings."""

from datetime import datetime
from tqdm import tqdm
from core.auth import AuthManager
from utils.decorators import paginate_response
from utils.input_helpers import get_user_input, get_pasted_column_data, get_project_id_input

class TagService(AuthManager):
    """Service for tag operations."""

    @paginate_response()
    def get_all_entity_tags_in_project(self, project_id):
        """Get all entity tags in a project with pagination support.
        
        Args:
            project_id (str): Project ID
            
        Returns:
            tuple: URL and headers for pagination decorator
        """
        url = f"{self.project_base_url}/projects/{project_id}/entity_tags"
        return url, {}

    def create_new_entity_tag(self, project_id, name, user_id):
        """Create a new entity tag in project.
        
        Args:
            project_id (str): Project ID
            name (str): Name of the entity tag
            user_id (int): User ID for creator and last editor
            
        Returns:
            dict: Created entity tag data
        """
        url = f"{self.project_base_url}/projects/{project_id}/entity_tags"
        current_time = datetime.now().isoformat()
        
        payload = {
            "name": name,
            "creator_user_id": user_id,
            "last_editor_user_id": user_id,
            "device_created_at": current_time,
            "device_updated_at": current_time
        }
        
        response = self.send_request(
            "POST", 
            url, 
            json=payload,
            expected_status_codes=[201]
        )
        
        if self.validate_response(response, [201]):
            return response.json()
        return None

    @paginate_response()
    def get_all_entity_taggings_in_project(self, project_id):
        """Get all entity taggings in a project with pagination support.
        
        Args:
            project_id (str): Project ID
            
        Returns:
            tuple: URL and headers for pagination decorator
        """
        url = f"{self.project_base_url}/projects/{project_id}/entity_taggings"
        return url, {}

    def batch_create_new_entity_taggings(self, project_id, entity_tag_id, task_ids, user_id):
        """Batch create new entity taggings.
        
        Args:
            project_id (str): Project ID
            entity_tag_id (str): ID of the entity tag
            task_ids (list): List of task IDs to tag
            user_id (int): User ID for creator and last editor
            
        Returns:
            dict: Response data from batch creation
        """
        url = f"{self.project_base_url}/projects/{project_id}/entity_taggings/batch"
        current_time = datetime.now().isoformat()
        
        taggings = [{
            "entity_id": task_id,
            "entity_tag_id": entity_tag_id,
            "entity_type": "Task",
            "creator_user_id": user_id,
            "last_editor_user_id": user_id,
            "device_created_at": current_time,
            "device_updated_at": current_time
        } for task_id in task_ids]
        
        response = self.send_request(
            "POST", 
            url, 
            json={"entity_taggings": taggings},
            expected_status_codes=[201]
        )
        
        if self.validate_response(response, [201]):
            return response.json()
        return None

    def batch_validate_tags(self, task_service, attribute_service, project_service):
        """Sequence to validate and ensure entity tags are applied to specified tasks.
        
        Args:
            task_service: TaskService instance for fetching tasks
            attribute_service: AttributeService instance for team operations
            project_service: ProjectService instance for project ID resolution
            
        Flow:
            1. Collect inputs (project_id, user_id, task names)
            2. Optional team filtering
            3. Match tasks by name
            4. Validate/create entity tag
            5. Check existing taggings
            6. Create missing taggings
            7. Validate results
        """
        # 1. Collect inputs
        project_id = get_project_id_input(project_service)
        user_id = int(get_user_input("Enter user ID: "))  # Convert to int for API
        
        # 2. Optional team filtering
        selected_team = None
        filter_by_team = get_user_input("\nDo you want to filter tasks by team? (yes/no): ").lower().strip() == 'yes'
        
        if filter_by_team:
            teams = attribute_service.get_all_teams_in_project(project_id)
            if not teams:
                print("No teams found in the project.")
                return
                
            print("\nAvailable Teams:")
            for team in teams:
                print(f"- {team['name']}")
            
            while True:
                team_filter = get_user_input("\nEnter Team Name (or 'cancel' to process all tasks): ")
                if team_filter.lower() == 'cancel':
                    filter_by_team = False
                    break
                    
                selected_team = next((team for team in teams if team['name'] == team_filter), None)
                if selected_team:
                    break
                print("\nTeam not found. Please try again or enter 'cancel'.")
        
        print("\nEnter task names from Excel:")
        task_names = get_pasted_column_data()
        if not task_names:
            print("No task names provided. Canceling sequence.")
            return
            
        # 3. Match tasks by name
        print("\nMatching tasks...")
        matched_tasks = []
        with tqdm(desc="Matching tasks") as pbar:
            all_tasks = task_service.get_all_tasks_in_project(project_id)
            
            # Apply team filter if selected
            if filter_by_team and selected_team:
                all_tasks = [task for task in all_tasks if task.get('team_id') == selected_team['id']]
                print(f"\nFiltered to {len(all_tasks)} tasks in team: {selected_team['name']}")
            
            for task in all_tasks:
                if task['name'].lower() in [name.lower() for name in task_names]:
                    matched_tasks.append(task)
                pbar.update(1)
        
        if not matched_tasks:
            print("No matching tasks found. Canceling sequence.")
            return
        
        print(f"\nFound {len(matched_tasks)} matching tasks.")
        
        # 4. Get/Create entity tag
        tag_name = get_user_input("Enter the entity tag name to validate: ")
        
        entity_tags = self.get_all_entity_tags_in_project(project_id)
        entity_tag = next((tag for tag in entity_tags if tag['name'].lower() == tag_name.lower()), None)
        
        if not entity_tag:
            print(f"\nEntity tag '{tag_name}' not found. Creating new tag...")
            entity_tag = self.create_new_entity_tag(project_id, tag_name, user_id)
            if not entity_tag:
                print("Failed to create entity tag. Canceling sequence.")
                return
            print("Entity tag created successfully.")
        
        # 5. Check existing taggings
        existing_taggings = self.get_all_entity_taggings_in_project(project_id)
        
        # Filter taggings for our tag and tasks
        task_ids = {task['id'] for task in matched_tasks}
        relevant_taggings = [
            tagging for tagging in existing_taggings 
            if tagging['entity_tag_id'] == entity_tag['id'] 
            and tagging['entity_type'] == 'Task'
            and tagging['entity_id'] in task_ids
        ]
        
        already_tagged_tasks = {tagging['entity_id'] for tagging in relevant_taggings}
        tasks_to_tag = task_ids - already_tagged_tasks
        
        # Show summary
        print(f"\nTasks Summary:")
        print(f"- Tasks already tagged: {len(already_tagged_tasks)}")
        print(f"- Tasks to be tagged: {len(tasks_to_tag)}")
        
        if not tasks_to_tag:
            print("\nAll matching tasks are already tagged. Nothing to do.")
            return
        
        # 6. Create missing taggings
        print("\nCreating missing taggings...")
        result = self.batch_create_new_entity_taggings(
            project_id, 
            entity_tag['id'], 
            list(tasks_to_tag), 
            user_id
        )
        
        if not result:
            print("Failed to create entity taggings. Canceling sequence.")
            return
        
        # 7. Validate results
        print("\nValidating results...")
        final_taggings = self.get_all_entity_taggings_in_project(project_id)
        
        final_tagged_tasks = {
            tagging['entity_id'] 
            for tagging in final_taggings 
            if tagging['entity_tag_id'] == entity_tag['id'] 
            and tagging['entity_type'] == 'Task'
            and tagging['entity_id'] in task_ids
        }
        
        if final_tagged_tasks >= task_ids:  # Using set comparison
            print("\nSuccess! All tasks have been tagged successfully.")
        else:
            missing_tags = task_ids - final_tagged_tasks
            print(f"\nError: {len(missing_tags)} tasks failed to be tagged properly.") 