"""CLI interface for Fieldwire API."""

from services.user import UserService
from services.project import ProjectService
from services.task import TaskService
from services.sheet import SheetService
from services.hardware import HardwareService
from services.attribute import AttributeService
from services.status import StatusService
from services.tags import TagService
from services.report_service import ReportService
from services.avaware_updater import AvawareUpdater
from utils.input_helpers import get_user_input, get_project_id_input
import json
import os

def get_and_validate_user_id(user_service):
    """Get and validate user ID against the users list.
    
    Returns:
        tuple: (user_id, user_name) or (None, None) if cancelled
    """
    print("\nRetrieving users list...")
    users = user_service.get_users()
    
    if not users:
        print("Error: Could not retrieve users list.")
        return None, None
    
    # Display available users
    print("\nAvailable users:")
    for user in users:
        user_data = user.get('user', {})
        user_id = user_data.get('id')
        first_name = user_data.get('first_name', '')
        last_name = user_data.get('last_name', '')
        email = user_data.get('email', '')
        print(f"  ID: {user_id} - {first_name} {last_name} ({email})")
    
    while True:
        user_id_input = get_user_input("\nEnter user ID: ")
        if not user_id_input:
            return None, None
            
        try:
            user_id = int(user_id_input)
            
            # Find the user in the list
            for user in users:
                user_data = user.get('user', {})
                if user_data.get('id') == user_id:
                    first_name = user_data.get('first_name', '')
                    last_name = user_data.get('last_name', '')
                    user_name = f"{first_name} {last_name}".strip()
                    print(f"Selected user: {user_id} ({user_name})")
                    return user_id, user_name
            
            print(f"Error: User ID {user_id} not found in the users list. Please try again.")
            
        except ValueError:
            print("Error: Please enter a valid numeric user ID.")

def get_or_create_project(project_service):
    """Get project by selection or creation and return project details.
    
    Returns:
        tuple: (project_id, project_name) or (None, None) if cancelled
    """
    # Check if project cache is available
    if not project_service._projects_cache:
        print("Error: Project cache not initialized.")
        return None, None
    
    while True:
        print("\n" + "="*50)
        print("           PROJECT SELECTION")
        print("="*50)
        
        print("\nChoose an option:")
        print("  1. Select an existing project")
        print("  2. Create a new project")
        print("  3. Cancel and exit")
        
        choice = get_user_input("\nEnter your choice (1-3): ").strip()
        
        if choice == "1":
            # Select existing project
            result = select_existing_project(project_service)
            if result[0] is not None:  # If a project was selected
                return result
            # If cancelled, continue the loop to show options again
            
        elif choice == "2":
            # Create new project
            result = create_and_target_project(project_service)
            if result[0] is not None:  # If a project was created
                return result
            # If creation failed or cancelled, continue the loop
            
        elif choice == "3" or choice == "":
            return None, None
            
        else:
            print("\nInvalid choice. Please try again.")

def select_existing_project(project_service):
    """Select from existing projects.
    
    Returns:
        tuple: (project_id, project_name) or (None, None) if cancelled
    """
    print("\nAvailable projects:")
    for project in project_service._projects_cache:
        print(f"  - {project['name']} (ID: {project['id']})")
    
    while True:
        project_name = get_user_input("\nEnter project name (or press Enter to go back): ")
        if not project_name:
            return None, None
            
        # Find the project by name using the existing method
        project_id = project_service.get_project_id_from_name_or_id(project_name)
        if project_id:
            # Find the full project details from cache
            for project in project_service._projects_cache:
                if project['id'] == project_id:
                    print(f"Selected project: {project['name']} (ID: {project['id']})")
                    return project['id'], project['name']
        
        print(f"Error: Project '{project_name}' not found. Please try again.")

def create_and_target_project(project_service):
    """Create a new project and return its details.
    
    Returns:
        tuple: (project_id, project_name) or (None, None) if creation failed or cancelled
    """
    print("\n" + "-"*50)
    print("           CREATE NEW PROJECT")
    print("-"*50)
    
    try:
        # Capture the project name before creation so we can find it later
        project_name = get_user_input("Enter the project name: ")
        if not project_name:
            print("Project creation cancelled.")
            return None, None
        
        # Create a modified create_project call that uses the captured name
        # We'll duplicate the creation logic here to avoid modifying the existing method
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
                "name": project_name,
                "prompt_effort_on_complete": prompt_effort_on_complete,
                "address": address,
                "code": code,
                "is_plan_email_notifications_enabled": is_plan_email_notifications_enabled,
                "tz_name": "America/New_York"
            },
            "source": source
        }

        # API URL
        url = f"{project_service.project_base_url}/projects"

        # Send the request
        response = project_service.send_request(
            "POST", 
            url, 
            json=payload,
            expected_status_codes=[200, 201]
        )
        
        if project_service.validate_response(response, [200, 201]):
            print("Project created successfully.")
            
            print("Refreshing project cache to include the new project...")
            
            # Always refresh the project cache after creation
            if project_service.refresh_project_cache():
                print("Project cache refreshed successfully.")
                
                # Now look for the project we just created by name
                project_id = project_service.get_project_id_from_name_or_id(project_name)
                if project_id:
                    # Find the full project details from cache
                    for project in project_service._projects_cache:
                        if project['id'] == project_id:
                            print(f"Successfully created and selected project: {project['name']} (ID: {project['id']})")
                            return project['id'], project['name']
                
                # If we can't find it by name, show available projects for manual selection
                print(f"\nWarning: Could not automatically find the created project '{project_name}' in the cache.")
                print("Please select it manually from the updated list:")
                
                print("\nAvailable projects:")
                for project in project_service._projects_cache:
                    print(f"  - {project['name']} (ID: {project['id']})")
                
                while True:
                    manual_project_name = get_user_input(f"\nEnter the project name (suggested: '{project_name}'): ")
                    if not manual_project_name:
                        print("Project creation completed, but no project selected for targeting.")
                        return None, None
                    
                    # Find the project by name
                    manual_project_id = project_service.get_project_id_from_name_or_id(manual_project_name)
                    if manual_project_id:
                        # Find the full project details from cache
                        for project in project_service._projects_cache:
                            if project['id'] == manual_project_id:
                                print(f"Successfully selected project: {project['name']} (ID: {project['id']})")
                                return project['id'], project['name']
                    
                    print(f"Error: Project '{manual_project_name}' not found. Please try again.")
            else:
                print("Warning: Project created but cache refresh failed.")
                print("The project was created successfully, but you may need to restart the application to see it.")
                return None, None
        else:
            print("Project creation failed.")
            return None, None
            
    except Exception as e:
        print(f"Error creating project: {str(e)}")
        return None, None

def run_bc_menu(api, project_service, hardware_service, task_service, attribute_service, user_id, project_id):
    """Run the BC operations menu (secret menu)."""
    # Initialize sheet service for BC operations
    sheet_service = SheetService(api)
    
    while True:
        print("\n" + "="*50)
        print("          BC OPERATIONS MENU")
        print("="*50)
        
        print("\n[BC Operations]")
        print("  1. BC Initialize Checklists")
        print("  2. BC Initialize Task Attributes")
        print("  3. BC Process Task Locations")
        print("  4. BC Process Location Tiers")
        print("  5. Return to Main Menu")
        
        print("\n" + "-"*50)
        choice = input("Enter your choice (1-5): ")
        print("-"*50)
        
        if choice == "1":
            hardware_service.bc_initialize_checklists(
                project_id,
                task_service,
                attribute_service
            )
        elif choice == "2":
            hardware_service.bc_initialize_task_attributes(
                project_id,
                task_service,
                attribute_service
            )
        elif choice == "3":
            sheet_service.bc_process_task_locations(
                project_id,
                task_service,
                user_id
            )
        elif choice == "4":
            hardware_service.process_location_tiers(project_id, task_service)
        elif choice == "5":
            break
        else:
            print("\nInvalid choice. Please try again.")

def run_cli(api, project_service):
    """Run the CLI interface.
    
    Args:
        api: AuthManager instance
        project_service: Initialized ProjectService instance with cached projects
    """
    # Initialize services
    user_service = UserService(api)
    task_service = TaskService(api)
    sheet_service = SheetService(api)
    hardware_service = HardwareService(api)
    attribute_service = AttributeService(api)
    status_service = StatusService(api)
    tag_service = TagService(api)
    
    # Initial setup - get user ID and project
    print("="*50)
    print("         FIELDWIRE API CLI - SETUP")
    print("="*50)
    print("\nPlease select the user and project for this session.")
    
    # Get and validate user ID
    user_id, user_name = get_and_validate_user_id(user_service)
    if user_id is None:
        print("Setup cancelled. Exiting...")
        return
    
    # Get and validate project
    project_id, project_name = get_or_create_project(project_service)
    if project_id is None:
        print("Setup cancelled. Exiting...")
        return
    
    while True:
        print("\n" + "="*50)
        print("             FIELDWIRE API CLI")
        print("="*50)
        print(f"Current User: {user_id} ({user_name})")
        print(f"Current Project: {project_name} (ID: {project_id})")
        print("="*50)
        
        print("\n[Session Management]")
        print("  Type 'change user id' to change the current user")
        print("  Type 'target project' to change the current project")
        
        print("\n[User Management]")
        print("  1. List Users")
        print("  2. Get User by ID or Name")
        
        print("\n[Project Management]")
        print("  3. List Projects")
        print("  4. Create a Project")
        
        print("\n[Hardware Management]")
        print("  5. Update Hardware Schedule")
        
        print("\n[Sequence Operations]")
        print("  6. Process Door Hardware Sequence")
        print("  7. Process UCA Tasks")
        print("  8. Batch Validate Tags")
        print("  9. Process Misc Tasks")
        print("  10. Create Task Relations")
        print("  11. Process Task Locations")
        
        print("\n[Reporting]")
        print("  12. Generate FC Task Report")
        print("  13. Generate UCA Sheet")
        
        print("\n[System]")
        print("  14. Exit")
        
        print("\n[Testing]")
        print("  15. SORT TEST Get check items from task")
        print("  16. TEST Delete task check item")
        
        print("\n" + "-"*50)
        choice = input("Enter your choice (1-16 or command): ").strip()
        print("-"*50)
        
        # Handle special commands (case insensitive)
        choice_lower = choice.lower()
        if choice_lower == "change user id":
            new_user_id, new_user_name = get_and_validate_user_id(user_service)
            if new_user_id is not None:
                user_id, user_name = new_user_id, new_user_name
            continue
        elif choice_lower == "target project":
            new_project_id, new_project_name = get_or_create_project(project_service)
            if new_project_id is not None:
                project_id, project_name = new_project_id, new_project_name
            continue
        
        # Handle numbered menu options
        if choice == "1":
            users = user_service.get_users()
            print("\nUsers:")
            print(json.dumps(users, indent=2))
        elif choice == "2":
            user_id_or_name = get_user_input("Enter user ID or full name: ")
            user = user_service.get_user_by_id_or_name(user_id_or_name)
            if user:
                print("\nUser found:")
                print(json.dumps(user, indent=2))
        elif choice == "3":
            projects = project_service.get_projects()
            print("\nProjects:")
            print(json.dumps(projects, indent=2))
        elif choice == "4":
            created_project = project_service.create_project()
            if created_project:
                # Refresh project cache to include the newly created project
                project_service.refresh_project_cache()
        elif choice == "5":
            avaware_updater = AvawareUpdater(api)
            avaware_updater.update_hardware_from_xml(
                project_id,
                user_id,
                task_service,
                attribute_service
            )
        elif choice == "6":
            hardware_service.process_door_hardware_sequence(
                project_id,
                user_id,
                task_service,
                attribute_service
            )
        elif choice == "7":
            hardware_service.process_uca_tasks(
                project_id,
                user_id,
                task_service,
                attribute_service
            )
        elif choice == "8":
            tag_service.batch_validate_tags(task_service, attribute_service, project_service)
        elif choice == "9":
            hardware_service.process_misc_tasks(
                project_id,
                user_id,
                task_service,
                attribute_service
            )
        elif choice == "10":
            task_service.create_opening_task_relations(project_id, user_id)
        elif choice == "11":
            sheet_service.process_task_locations(
                project_id,
                task_service,
                user_id
            )
        elif choice == "12":
            # Generate FC Task Report
            try:
                # Initialize Report Service
                report_service = ReportService(
                    project_service=project_service,
                    task_service=task_service,
                    attribute_service=attribute_service,
                    status_service=status_service,
                    team_service=attribute_service,
                    tag_service=tag_service
                )
                
                # Get output filename
                output_filename = get_user_input("Enter output filename (e.g., fc_report.xlsx): ")
                if not output_filename.endswith('.xlsx'):
                    output_filename += '.xlsx'
                
                # Generate the report using the current project name
                report_service.generate_fc_task_report(project_name, output_filename)
                
            except Exception as e:
                print(f"\nError generating FC Task Report: {str(e)}")
        elif choice == "13":
            # Generate UCA Sheet
            try:
                hardware_service.generate_UCA_sheet(
                    project_id,
                    task_service,
                    attribute_service
                )
            except Exception as e:
                print(f"\nError generating UCA Sheet: {str(e)}")
        elif choice == "14":
            print("\nExiting...")
            break
        elif choice == "15":
            hardware_service.sort_test_get_check_items_from_task(
                project_id,
                task_service,
                attribute_service
            )
        elif choice == "16":
            # Test delete task check item
            check_item_id = get_user_input("Enter the check item ID to delete: ")
            
            print(f"Attempting to delete check item with ID: {check_item_id}")
            success = attribute_service.delete_task_check_item(project_id, check_item_id)
            
            if success:
                print("Check item deleted successfully!")
            else:
                print("Failed to delete check item.")
        elif choice == "0200":
            # Secret BC menu
            run_bc_menu(api, project_service, hardware_service, task_service, attribute_service, user_id, project_id)
        else:
            print("\nInvalid choice. Please try again.")