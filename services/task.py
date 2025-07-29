"""Task service for Fieldwire API."""

from core.auth import AuthManager
from utils.decorators import paginate_response, update_last_response
from utils.input_helpers import get_user_input, prompt_user_for_xml_file
from processors.xml_processor import parse_xml_file
from utils.task_helpers import compare_openings_with_tasks
from tqdm import tqdm
from utils.executor import RateLimitedExecutor

class TaskService(AuthManager):
    """Service for task operations."""

    @paginate_response()
    def get_all_tasks_in_project(self, project_id, filter_option='all'):
        """Get all tasks in a project with pagination support."""
        url = f"{self.project_base_url}/projects/{project_id}/tasks"
        
        # Validate filter option
        if filter_option not in ['all', 'active', 'deleted']:
            print(f"Invalid filter option '{filter_option}'. Defaulting to 'all'.")
            filter_option = 'all'
        
        # Return URL and headers for the decorator to handle
        headers = {'Fieldwire-Filter': filter_option}
        return url, headers

    @update_last_response()
    def create_task_for_opening(self, project_id, owner_user_id, creator_user_id, opening_number, team_id=None, status_id=None):
        """Create a task for an opening.
        
        Args:
            project_id (str): Project ID
            owner_user_id (int): Owner user ID
            creator_user_id (int): Creator user ID
            opening_number (str): Opening number/name
            team_id (str, optional): Team ID for the task
            status_id (str, optional): Status ID for the task
            
        Returns:
            dict: Created task data if successful, None otherwise
        """
        url = f"{self.project_base_url}/projects/{project_id}/tasks"
        
        payload = {
            "name": opening_number,
            "owner_user_id": owner_user_id,
            "creator_user_id": creator_user_id,
            "last_editor_user_id": creator_user_id,
            "priority": 1
        }
        
        if team_id:
            payload["team_id"] = team_id
            
        if status_id:
            payload["status_id"] = status_id
        
        response = self.send_request(
            "POST", 
            url, 
            json=payload,
            expected_status_codes=[200, 201]
        )
        
        if self.validate_response(response, [200, 201]):
            return response.json()
        return None

    def process_xml_and_create_tasks(self, project_id):
        """Process XML file and create tasks for unmatched openings."""
        # Get XML file path from user
        file_path = prompt_user_for_xml_file()
        if not file_path:
            print("No file selected.")
            return

        openings = parse_xml_file(file_path)
        print(f"\nParsed {len(openings)} openings from XML file.")
        
        # Ask for filter option
        filter_option = get_user_input("Compare with 'all', 'active', or 'deleted' tasks? ").strip().lower()
        if filter_option not in ['all', 'active', 'deleted']:
            print(f"Invalid filter option '{filter_option}'. Defaulting to 'all'.")
            filter_option = 'all'
        
        tasks = self.get_all_tasks_in_project(project_id, filter_option)
        print(f"\nRetrieved {len(tasks) if tasks else 0} {filter_option} tasks from project.")
        
        unmatched_openings = compare_openings_with_tasks(openings, tasks)
        if not unmatched_openings:
            print("All openings have matching tasks.")
            return
        
        owner_user_id = get_user_input("Enter the owner_user_id: ")
        creator_user_id = get_user_input("Enter the creator_user_id: ")

        total_tasks = len(unmatched_openings)
        print(f"\nCreating {total_tasks} tasks...")
        created_count = 0
        failed_count = 0

        for index, opening in enumerate(unmatched_openings, 1):
            result = self.create_task_for_opening(project_id, owner_user_id, creator_user_id, opening["Number"])
            if result:
                created_count += 1
                print(f"Progress: {created_count}/{total_tasks} tasks created ({(created_count/total_tasks)*100:.1f}%) - Created task: {opening['Number']}", end="\r")
            else:
                failed_count += 1

        print("\n\nOperation complete:")
        print(f"Successfully created: {created_count} tasks")
        if failed_count > 0:
            print(f"Failed to create: {failed_count} tasks")

    def delete_task(self, project_id, task_id):
        """Delete a task by ID."""
        url = f"{self.project_base_url}/projects/{project_id}/tasks/{task_id}"
        
        response = self.send_request(
            "DELETE", 
            url,
            expected_status_codes=[204]
        )
        
        return self.validate_response(response, [204])

    def delete_all_tasks_in_project(self, project_id):
        """Delete all tasks in a project with confirmation."""
        # Ask for filter option
        filter_option = get_user_input("Retrieve 'all', 'active', or 'deleted' tasks? ").strip().lower()
        if filter_option not in ['all', 'active', 'deleted']:
            print(f"Invalid filter option '{filter_option}'. Defaulting to 'all'.")
            filter_option = 'all'
        
        # Get all tasks first
        tasks = self.get_all_tasks_in_project(project_id, filter_option)
        if not tasks:
            print(f"No {filter_option} tasks found in project.")
            return

        # Ask for confirmation
        confirmation = get_user_input(
            f"\nWARNING: This will delete {len(tasks)} {filter_option} tasks from the project. "
            "This action cannot be undone. Type 'DELETE' to confirm: "
        ).strip()

        if confirmation != "DELETE":
            print("Operation cancelled.")
            return

        total_tasks = len(tasks)
        print(f"\nDeleting {total_tasks} tasks...")

        # Create executor for parallel task deletion
        executor = RateLimitedExecutor()
        
        # Prepare operations
        operations = []
        for task in tasks:
            def delete_task(task=task):
                return self.delete_task(project_id, task["id"])
            operations.append(delete_task)

        # Execute operations in parallel
        results = executor.execute_parallel(operations)
        
        # Process results
        if isinstance(results, bool):
            # If we got a single boolean result, all operations succeeded or failed
            if results:
                print(f"\nSuccessfully deleted all {total_tasks} tasks")
            else:
                print("\nFailed to delete tasks")
        else:
            # If we got a list of results, process each individually
            deleted_count = sum(1 for result in results if result)
            failed_count = total_tasks - deleted_count
            
            print("\nOperation complete:")
            print(f"Successfully deleted: {deleted_count} tasks")
            if failed_count > 0:
                print(f"Failed to delete: {failed_count} tasks")

    @paginate_response()
    def get_all_task_relations_in_project(self, project_id):
        """Get all task relations in a project with pagination support.
        
        Args:
            project_id (str): Project ID
            
        Returns:
            tuple: URL and headers for pagination decorator
        """
        url = f"{self.project_base_url}/projects/{project_id}/task_relations"
        return url, {}

    @update_last_response()
    def create_task_relation(self, project_id, task_1_id, task_2_id, creator_user_id):
        """Create a new task relation between two tasks.
        
        Args:
            project_id (str): Project ID
            task_1_id (str): First task ID
            task_2_id (str): Second task ID
            creator_user_id (int): ID of the user creating the relation
            
        Returns:
            dict: Created task relation data if successful, None otherwise
        """
        url = f"{self.project_base_url}/projects/{project_id}/task_relations"
        
        payload = {
            "creator_user_id": creator_user_id,
            "task_1_id": task_1_id,
            "task_2_id": task_2_id
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

    def create_opening_task_relations(self, project_id, creator_user_id):
        """Create task relations between all tasks of the same opening number or name.
        
        This function can handle two scenarios:
        1. Prefixed tasks: Creates relations between tasks with same opening number (DEF, FC, UCA, UCI)
        2. Non-prefixed tasks: Creates relations between tasks with exact same name
        
        Args:
            project_id (str): Project ID
            creator_user_id (int): ID of the user creating the relations
            
        Returns:
            bool: True if successful, False if any error occurred
        """
        try:
            
            # Ask user about task naming convention
            print("\nTask Naming Convention:")
            print("1. Prefixed tasks (e.g., 'DEF 001', 'FC 001', 'UCA 001')")
            print("2. Non-prefixed tasks (e.g., '001', '001', '001')")
            naming_choice = get_user_input("Does this project use prefixed task names? (y/n): ").strip().lower()
            use_prefixes = naming_choice in ['y', 'yes', '1']
            
            # Step 1: Get all tasks and existing relations
            print("\nRetrieving tasks and existing relations...")
            tasks = self.get_all_tasks_in_project(project_id, filter_option='active')  # Only get active tasks
            if not tasks:
                print("No active tasks found in project.")
                return False
                
            existing_relations = self.get_all_task_relations_in_project(project_id)
            print(f"Retrieved {len(tasks)} active tasks and {len(existing_relations)} existing relations.")
            
            # Step 2: Organize tasks by opening number or name
            print(f"\nOrganizing tasks by {'opening number' if use_prefixes else 'exact name'}...")
            tasks_by_group = {}  # {group_key: [task1, task2, ...]}
            skipped_tasks = []
            
            if use_prefixes:
                # Handle prefixed tasks
                valid_prefixes = {'DEF', 'FC', 'UCA', 'UCI'}  # Removed 'COM'
                
                for task in tasks:
                    # Validate task has required fields
                    if not task.get('name') or not task.get('id'):
                        skipped_tasks.append(f"Task {task.get('id', 'unknown ID')} - Missing name or ID")
                        continue
                        
                    # Split task name and validate format
                    name_parts = task['name'].strip().split(' ', 1)
                    if len(name_parts) != 2:
                        skipped_tasks.append(f"Task {task['id']} - Invalid name format: {task['name']}")
                        continue
                        
                    prefix, opening_number = name_parts
                    if prefix not in valid_prefixes:
                        skipped_tasks.append(f"Task {task['id']} - Invalid prefix: {prefix}")
                        continue
                    
                    # Add task to opening group
                    if opening_number not in tasks_by_group:
                        tasks_by_group[opening_number] = []
                    tasks_by_group[opening_number].append(task)
            else:
                # Handle non-prefixed tasks - group by exact name
                for task in tasks:
                    # Validate task has required fields
                    if not task.get('name') or not task.get('id'):
                        skipped_tasks.append(f"Task {task.get('id', 'unknown ID')} - Missing name or ID")
                        continue
                    
                    task_name = task['name'].strip()
                    if not task_name:
                        skipped_tasks.append(f"Task {task['id']} - Empty task name")
                        continue
                    
                    # Add task to name group
                    if task_name not in tasks_by_group:
                        tasks_by_group[task_name] = []
                    tasks_by_group[task_name].append(task)
            
            # Report skipped tasks
            if skipped_tasks:
                print("\nSkipped tasks due to validation:")
                for msg in skipped_tasks:
                    print(f"- {msg}")
            
            # Step 3: Determine needed relations
            print("\nDetermining needed relations...")
            relations_to_create = []  # [(task_1_id, task_2_id), ...]
            existing_relation_pairs = {
                (r.get('task_1_id'), r.get('task_2_id')) 
                for r in existing_relations
            }
            existing_relation_pairs.update({
                (r.get('task_2_id'), r.get('task_1_id')) 
                for r in existing_relations
            })
            
            # Count tasks by group for reporting
            tasks_with_relations = 0
            groups_processed = 0
            
            for group_key, group_tasks in tasks_by_group.items():
                if len(group_tasks) > 1:  # Only process if there are at least 2 tasks
                    groups_processed += 1
                    tasks_with_relations += len(group_tasks)
                    
                    # Create relations between all tasks (many-to-many)
                    for i in range(len(group_tasks)):
                        for j in range(i + 1, len(group_tasks)):
                            task_1_id = group_tasks[i]['id']
                            task_2_id = group_tasks[j]['id']
                            
                            # Check if relation already exists (in either direction)
                            if (task_1_id, task_2_id) not in existing_relation_pairs:
                                # Ensure task_1_id is lexicographically less than task_2_id
                                if task_1_id > task_2_id:
                                    task_1_id, task_2_id = task_2_id, task_1_id
                                relations_to_create.append((task_1_id, task_2_id))
            
            # Report statistics
            group_type = "openings" if use_prefixes else "task names"
            print(f"\nFound {groups_processed} {group_type} with multiple tasks")
            print(f"Total tasks that will have relations: {tasks_with_relations}")
            
            # Step 4: Create the relations in parallel
            if not relations_to_create:
                print("No new relations needed.")
                return True
                
            print(f"\nCreating {len(relations_to_create)} new task relations...")
            
            # Prepare operations for parallel execution
            relation_operations = []
            for task_1_id, task_2_id in relations_to_create:
                relation_operations.append((
                    lambda task_1_id=task_1_id, task_2_id=task_2_id: self.create_task_relation(
                        project_id=project_id,
                        task_1_id=task_1_id,
                        task_2_id=task_2_id,
                        creator_user_id=creator_user_id
                    ),
                    (task_1_id, task_2_id)
                ))

            # Execute operations in parallel with rate limiting
            executor = RateLimitedExecutor()
            operations = [op[0] for op in relation_operations]
            results = executor.execute_parallel(operations)
            
            # Process results
            if isinstance(results, bool):
                if not results:
                    print("Error occurred during relation creation")
                    return False
            else:
                # Check for any failures
                failed_relations = []
                for (_, (task_1_id, task_2_id)), result in zip(relation_operations, results):
                    if not result:
                        failed_relations.append((task_1_id, task_2_id))
                
                if failed_relations:
                    print("\nFailed to create the following relations:")
                    for task_1_id, task_2_id in failed_relations:
                        print(f"- Between tasks {task_1_id} and {task_2_id}")
                    return False
            
            print("\nTask relations creation completed successfully")
            return True
            
        except Exception as e:
            print(f"\nError creating task relations: {str(e)}")
            return False

    def get_task_by_name(self, project_id, task_name):
        """Get a task by its name in a project.
        
        Args:
            project_id (str): The ID of the project
            task_name (str): The name of the task to find
            
        Returns:
            dict: The task if found, None otherwise
        """
        tasks = self.get_all_tasks_in_project(project_id, filter_option='active')
        if tasks is None:
            return None
            
        return next((task for task in tasks if task['name'] == task_name), None)

    @update_last_response()
    def update_task_name(self, project_id, task_id, new_name, last_editor_user_id):
        """Update a task's name.
        
        Args:
            project_id (str): Project ID
            task_id (str): Task ID to update
            new_name (str): New name for the task
            last_editor_user_id (int): User ID of the person making the update
            
        Returns:
            dict: Updated task data if successful, None otherwise
        """
        url = f"{self.project_base_url}/projects/{project_id}/tasks/{task_id}"
        
        payload = {
            "name": new_name,
            "last_editor_user_id": last_editor_user_id
        }
        
        response = self.send_request(
            "PATCH", 
            url, 
            json=payload,
            expected_status_codes=[200]
        )
        
        if self.validate_response(response, [200]):
            return response.json()
        return None

    @paginate_response()
    def get_all_locations_in_project(self, project_id):
        """Get all locations in a project with pagination support.
        
        Args:
            project_id (str): Project ID
            
        Returns:
            list: List of location objects across all pages
        """
        url = f"{self.project_base_url}/projects/{project_id}/locations"
        
        # Return URL for the decorator to handle pagination
        return url

    def update_task_with_location(self, project_id, task_id, location_id, user_id):
        """Update a task with a location ID.
        
        Args:
            project_id (str): Project ID
            task_id (str): Task ID
            location_id (str): Location ID
            user_id (int): Last editor user ID
            
        Returns:
            dict: Updated task data if successful, None otherwise
        """
        url = f"{self.project_base_url}/projects/{project_id}/tasks/{task_id}"
        
        payload = {
            "location_id": location_id,
            "last_editor_user_id": user_id
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

    def batch_create_locations(self, project_id, list_of_full_paths):
        """Batch create locations in a project.
        
        Args:
            project_id (str): Project ID
            list_of_full_paths (list): List of full paths arrays
            
        Returns:
            list: List of created location objects if successful, None otherwise
        """
        url = f"{self.project_base_url}/projects/{project_id}/locations/batch_create"
        
        payload = {
            "list_of_full_paths": list_of_full_paths
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
