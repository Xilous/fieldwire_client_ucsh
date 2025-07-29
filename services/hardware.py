"""Hardware service for Fieldwire API."""

from core.auth import AuthManager
from utils.decorators import paginate_response, update_last_response
from utils.input_helpers import get_user_input, prompt_user_for_xml_file, prompt_user_for_excel_file
from processors.xml_processor import parse_xml_file, parse_hardware_items
from config.constants import HARDWARE_FILTERS, FC_CHECKLIST_ITEMS
from utils.rate_limiter import RateLimitedExecutor
import pandas as pd
from tqdm import tqdm
from utils.task_helpers import compare_openings_with_tasks

class HardwareService(AuthManager):
    """Service for hardware operations."""

    def initialize_hardware_items(self, project_id, attribute_service):
        """Initialize hardware items from XML file."""
        try:
            # Step 1: Get XML file
            print("\n=== Step 1: Select XML File ===")
            file_path = prompt_user_for_xml_file()
            if not file_path:
                print("No file selected.")
                return

            # Step 2: Parse XML
            print("\n=== Step 2: Parse XML File ===")
            print("Parsing XML file...")
            hardware_items = parse_hardware_items(file_path)
            total_items = len(hardware_items)
            print(f"Successfully parsed {total_items} hardware items from the XML file.")

            # Step 3: Get user inputs
            print("\n=== Step 3: Collect User Information ===")
            creator_user_id = get_user_input("Enter the creator_user_id: ")
            last_editor_user_id = get_user_input("Enter the last_editor_user_id: ")

            # Step 4: Retrieve task attributes
            print("\n=== Step 4: Retrieve Task Attributes ===")
            print("Retrieving task attributes from project...")
            task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
            print(f"Retrieved {len(task_attributes)} task attributes.")
            
            # Step 5: Create lookup dictionary
            print("\n=== Step 5: Process Task Attributes ===")
            task_attribute_map = {
                attr.get("text_value"): attr["task_id"] 
                for attr in task_attributes 
                if attr.get("text_value")
            }
            print(f"Created lookup map with {len(task_attribute_map)} task attributes.")

            # Step 6: Process hardware items
            print("\n=== Step 6: Create Hardware Items ===")
            processed_count = 0
            skipped_count = 0
            created_count = 0
            
            # Group checklist items by task_id for batch creation
            task_checklist_items = {}
            
            for index, item in enumerate(hardware_items, 1):
                group_name = item["GroupName"]
                if not group_name or group_name not in task_attribute_map:
                    skipped_count += 1
                    continue

                task_id = task_attribute_map[group_name]
                if task_id not in task_checklist_items:
                    task_checklist_items[task_id] = []
                
                # Build name string
                name_parts = []
                for field in ['QuantityOffDoor', 'QuantityActive', 'ShortCode', 
                            'SubCategory', 'ProductCode', 'Finish_ANSI']:
                    if item[field]:
                        name_parts.append(f"({item[field]})")
                
                name = " ".join(name_parts)
                
                if name:
                    task_checklist_items[task_id].append(name)
                processed_count += 1
                
                # Print progress every 100 items
                if index % 100 == 0:
                    print(f"Progress: {index}/{total_items} items processed ({(index/total_items)*100:.1f}%)")
            
            # Create checklist items in batches for each task
            for task_id, checklist_names in task_checklist_items.items():
                if checklist_names:
                    result = attribute_service.create_multiple_checklist_items_in_task(
                        project_id=project_id,
                        task_id=task_id,
                        names=checklist_names
                    )
                    if result:
                        created_count += len(checklist_names)
                        print(f"Created {len(checklist_names)} checklist items for task {task_id}")

            # Final summary
            print("\n=== Summary ===")
            print(f"Total items processed: {processed_count}")
            print(f"Successfully created: {created_count}")
            print(f"Skipped (no matching task): {skipped_count}")
            print("\nOperation complete!")

        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further items will be processed.")

    def process_door_hardware_sequence(self, project_id, user_id, task_service, attribute_service):
        """Process door hardware sequence from XML file(s)."""
        try:
            # Initial Setup (keep sequential)
            print("\n=== Step 1: Select XML Files ===")
            print("Choose file selection mode:")
            print("1. Single combined XML file")
            print("2. Multiple XML files")
            
            mode = get_user_input("Enter selection (1 or 2): ").strip()
            if mode not in ["1", "2"]:
                print("Invalid selection. Aborting sequence.")
                return
                
            xml_files = []
            if mode == "1":
                # Single file selection
                file_path = prompt_user_for_xml_file()
                if not file_path:
                    print("No file selected. Aborting sequence.")
                    return
                xml_files.append(file_path)
            else:
                # Multiple file selection
                print("\nSelect XML files one at a time. Press Cancel when done.")
                while True:
                    file_path = prompt_user_for_xml_file()
                    if not file_path:
                        break
                    xml_files.append(file_path)
                    
                    if not get_user_input("Add another file? (y/n): ").lower() == 'y':
                        break
                
                if not xml_files:
                    print("No files selected. Aborting sequence.")
                    return
                    
            print(f"\nSelected {len(xml_files)} file(s)")

            # Get UCI team ID (keep sequential)
            print("\n=== Getting UCI Team ID ===")
            print("Retrieving teams from project...")
            teams = attribute_service.get_all_teams_in_project(project_id)
            if teams is None:
                print("Failed to retrieve teams from project")
                return
                
            # Find UCI team
            uci_team = next((team for team in teams if team['name'] == 'UCI'), None)
            if not uci_team:
                print("Error: No team found with name 'UCI' in the project")
                print("Process stopped - UCI team is required.")
                return
                
            uci_team_id = uci_team['id']
            print(f"Found UCI team (ID: {uci_team_id})")

            # Parse and validate all XML files (keep sequential)
            print("\n=== Step 2: Processing XML Files ===")
            all_openings = []
            all_hardware_items = []
            filtered_hardware_count = 0
            
            for file_path in xml_files:
                try:
                    # Parse current file
                    current_openings = parse_xml_file(file_path)
                    current_hardware = parse_hardware_items(file_path)
                    
                    # Filter out openings with empty or invalid numbers
                    valid_openings = []
                    for opening in current_openings:
                        opening_number = opening.get("Number", "").strip()
                        if opening_number and opening_number != "UCI":  # Filter out empty and "UCI" only
                            valid_openings.append(opening)
                        else:
                            print(f"Warning: Skipping invalid opening number: {opening_number}")
                    
                    # Filter out hardware items containing "revised" or "revision" (case insensitive)
                    filtered_hardware = []
                    for item in current_hardware:
                        # Check if any field contains "revised" or "revision" (case insensitive)
                        has_revised = any(
                            any(keyword in str(value).lower() 
                                for keyword in ["revised", "revision"])
                            for value in item.values() 
                            if value is not None
                        )
                        if not has_revised:
                            filtered_hardware.append(item)
                        else:
                            filtered_hardware_count += 1
                    
                    # Combine data
                    all_openings.extend(valid_openings)
                    all_hardware_items.extend(filtered_hardware)
                    
                    print(f"Processed file {file_path}:")
                    print(f"- Valid openings: {len(valid_openings)}")
                    print(f"- Hardware items: {len(filtered_hardware)}")
                    if filtered_hardware_count > 0:
                        print(f"- Filtered out {filtered_hardware_count} hardware items containing 'revised' or 'revision'")
                    
                except Exception as e:
                    print(f"\nError processing file {file_path}: {str(e)}")
                    print("Stopping processing.")
                    return

            print(f"\nTotal valid openings loaded: {len(all_openings)}")
            print(f"Total hardware items loaded: {len(all_hardware_items)}")
            if filtered_hardware_count > 0:
                print(f"Total hardware items filtered out (containing 'revised' or 'revision'): {filtered_hardware_count}")
            if not all_openings:
                print("WARNING: No valid openings were loaded from XML files!")
                return
            if not all_hardware_items:
                print("WARNING: No hardware items were loaded from XML files!")
                return

            # Create hardware by group map (keep sequential)
            hardware_by_group = {}
            for item in all_hardware_items:
                group_name = item["GroupName"]
                if group_name:
                    if group_name not in hardware_by_group:
                        hardware_by_group[group_name] = []
                    
                    name_parts = []
                    for field in ['QuantityOffDoor', 'QuantityActive', 'ShortCode',
                                'SubCategory', 'ProductCode', 'Finish_ANSI']:
                        if item[field]:
                            name_parts.append(f"({item[field]})")
                    
                    name = " ".join(name_parts)
                    if name:
                        hardware_by_group[group_name].append(name)
                        print(f"Added hardware item for group {group_name}: {name}")

            print(f"\nHardware items grouped by {len(hardware_by_group)} groups")
            for group, items in hardware_by_group.items():
                print(f"Group {group}: {len(items)} items")

            # Task Verification & Creation (parallelize creation)
            print("\n=== Step 3: Task Verification ===")
            existing_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            task_map = {task['name']: task for task in existing_tasks if task['name'].startswith('UCI ')}
            
            # Create a set of valid opening numbers from XML data
            valid_opening_numbers = {opening["Number"] for opening in all_openings}
            print(f"\nFound {len(valid_opening_numbers)} valid opening numbers in XML files")
            
            # Check for missing tasks
            missing_tasks = []
            for opening in all_openings:
                opening_number = opening["Number"]
                uci_opening_number = f"UCI {opening_number}"
                if uci_opening_number not in task_map:
                    missing_tasks.append(opening_number)
            
            if missing_tasks:
                print("\nMissing tasks found:")
                for task in missing_tasks:
                    print(f"- UCI {task}")
                
                proceed = get_user_input("\nProceed with creating missing tasks? (y/n): ")
                if proceed.lower() != 'y':
                    print("Operation cancelled.")
                    return
                
                print("\n=== Creating Missing Tasks ===")
                
                # Create executor for parallel task creation
                executor = RateLimitedExecutor()
                
                # Prepare operations
                operations = []
                for opening_number in missing_tasks:
                    def create_task(opening_number=opening_number):
                        return task_service.create_task_for_opening(
                        project_id=project_id,
                        owner_user_id=user_id,
                        creator_user_id=user_id,
                            opening_number=f"UCI {opening_number}",
                        team_id=uci_team_id
                    )
                    operations.append(create_task)
                
                # Execute operations in parallel
                if not executor.execute_parallel(operations):
                    print("Error occurred during task creation. Stopping process.")
                    return
                
                # Refresh task data
                print("\nRefreshing task data...")
                existing_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
                task_map = {task['name']: task for task in existing_tasks if task['name'].startswith('UCI ')}
                print(f"Tasks created: {len(missing_tasks)}")
            else:
                print("No missing tasks found.")

            # Task Attribute Creation (parallelize creation)
            print("\n=== Step 4: Task Attribute Verification ===")
            # Define relevant attributes
            relevant_attributes = [
                "Quantity", "Label", "NominalWidth", "NominalHeight", 
                "Hand", "DoorMaterial", "FrameMaterial", "HardwareGroup"
            ]

            # Get task type attributes (keep sequential)
            task_type_attributes = attribute_service.get_all_task_type_attributes_in_project(project_id)
            task_type_attribute_map = {}
            for attr in task_type_attributes:
                if attr['name'] in relevant_attributes:
                    task_type_attribute_map[attr['name']] = attr['id']

            if 'HardwareGroup' not in task_type_attribute_map:
                print("Error: HardwareGroup task type attribute not found in project")
                return

            # Get existing attributes (keep sequential)
            existing_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
            task_attributes_map = {}
            for attr in existing_attributes:
                task_id = attr['task_id']
                if task_id not in task_attributes_map:
                    task_attributes_map[task_id] = {}
                
                attr_name = next((name for name, id in task_type_attribute_map.items() 
                                if id == attr['task_type_attribute_id']), None)
                if attr_name:
                    task_attributes_map[task_id][attr_name] = attr['text_value']

            # Check for missing attributes
            missing_attributes = []
            for opening in all_openings:
                opening_number = opening["Number"]
                uci_opening_number = f"UCI {opening_number}"
                if uci_opening_number not in task_map:
                    continue
                
                task = task_map[uci_opening_number]
                task_id = task['id']
                
                if task_id not in task_attributes_map:
                    task_attributes_map[task_id] = {}
                
                for attr_name, attr_value in opening.get("Attributes", {}).items():
                    if attr_name in relevant_attributes and attr_name in task_type_attribute_map:
                        if (attr_name not in task_attributes_map[task_id] or 
                            task_attributes_map[task_id][attr_name] != attr_value):
                            missing_attributes.append({
                                'task_id': task_id,
                                'opening_number': uci_opening_number,
                                'attr_name': attr_name,
                                'value': attr_value,
                                'type_attr_id': task_type_attribute_map[attr_name]
                            })
            
            if missing_attributes:
                print("\nMissing task attributes found:")
                by_task = {}
                for attr in missing_attributes:
                    task_num = attr['opening_number']
                    if task_num not in by_task:
                        by_task[task_num] = []
                    by_task[task_num].append(f"{attr['attr_name']} = {attr['value']}")
                
                for task_num, attrs in by_task.items():
                    print(f"\nTask {task_num} missing attributes:")
                    for attr in attrs:
                        print(f"- {attr}")
                
                proceed = get_user_input("\nProceed with creating missing attributes? (y/n): ")
                if proceed.lower() != 'y':
                    print("Operation cancelled.")
                    return
                
                print("\n=== Creating Missing Attributes ===")
                
                # Create executor for parallel attribute creation
                executor = RateLimitedExecutor()
                
                # Prepare operations
                operations = []
                for attr in missing_attributes:
                    def create_attribute(attr=attr):
                        return attribute_service.create_a_task_attribute_in_task(
                        project_id=project_id,
                        task_id=attr['task_id'],
                        task_type_attribute_id=attr['type_attr_id'],
                        attribute_value=attr['value'],
                        user_id=user_id
                    )
                    operations.append(create_attribute)
                
                # Execute operations in parallel
                if not executor.execute_parallel(operations):
                    print("Error occurred during attribute creation. Stopping process.")
                    return
                
                print(f"Attributes created: {len(missing_attributes)}")
            else:
                print("No missing attributes found.")

            # Get updated attributes after creation (this is the key change)
            print("\nRetrieving updated task attributes...")
            existing_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
            task_attributes_map = {}
            for attr in existing_attributes:
                task_id = attr['task_id']
                if task_id not in task_attributes_map:
                    task_attributes_map[task_id] = {}
                
                attr_name = next((name for name, id in task_type_attribute_map.items() 
                                if id == attr['task_type_attribute_id']), None)
                if attr_name:
                    task_attributes_map[task_id][attr_name] = attr['text_value']

            # Checklist Item Creation (parallelize creation)
            print("\n=== Step 5: Checklist Item Verification ===")
            # Get existing checklist items (keep sequential)
            existing_checklist_items = attribute_service.get_all_task_check_items_in_project(project_id)
            checklist_items_map = {}
            for item in existing_checklist_items:
                task_id = item['task_id']
                if task_id not in checklist_items_map:
                    checklist_items_map[task_id] = set()
                checklist_items_map[task_id].add(item['name'])

            # Initialize summary tracking
            summary = {
                'created': {},  # {task_name: {'attributes': [], 'checklist_items': []}}
                'updated': {}   # {task_name: {'attributes': [], 'checklist_items': []}}
            }

            # Check for missing checklist items
            missing_checklist_items = {}
            for task in task_map.values():
                task_id = task['id']
                
                # Find the hardware group for this task
                hardware_group = None
                if task_id in task_attributes_map and 'HardwareGroup' in task_attributes_map[task_id]:
                    hardware_group = task_attributes_map[task_id]['HardwareGroup']
                
                if not hardware_group or hardware_group not in hardware_by_group:
                    if hardware_group:
                        print(f"Task {task['name']} has hardware group {hardware_group} but no matching items found")
                    continue
                
                # Get existing checklist items for this task
                existing_items = checklist_items_map.get(task_id, set())
                
                # Get all hardware items for this group
                hardware_items = hardware_by_group[hardware_group]
                
                # Find missing items
                missing_names = [name for name in hardware_items if name not in existing_items]
                
                if missing_names:
                    missing_checklist_items[task_id] = {
                        'task_name': task['name'],
                        'hardware_group': hardware_group,
                        'names': missing_names
                    }
                    print(f"Task {task['name']} missing {len(missing_names)} checklist items")

            if missing_checklist_items:
                print("\nMissing checklist items found:")
                total_missing = sum(len(info['names']) for info in missing_checklist_items.values())
                print(f"Total missing checklist items: {total_missing}")
                
                for task_id, info in missing_checklist_items.items():
                    print(f"\nTask {info['task_name']} (HardwareGroup: {info['hardware_group']}) missing {len(info['names'])} items:")
                    for name in info['names']:
                        print(f"- {name}")
                
                proceed = get_user_input("\nProceed with creating missing checklist items? (y/n): ")
                if proceed.lower() != 'y':
                    print("Operation cancelled.")
                    return
                
                print("\n=== Creating Missing Checklist Items ===")
                
                # Create executor for parallel checklist item creation
                executor = RateLimitedExecutor()
                
                # Prepare operations
                checklist_operations = []
                for task_id, info in missing_checklist_items.items():
                    def create_checklist_items(task_id=task_id, info=info):
                        return attribute_service.create_multiple_checklist_items_in_task(
                        project_id=project_id,
                        task_id=task_id,
                        names=info['names']
                    )
                    checklist_operations.append((
                        create_checklist_items,
                        info['task_name'],
                        info['names']
                    ))
                
                # Execute operations in parallel
                if checklist_operations:
                    operations = [op[0] for op in checklist_operations]
                    results = executor.execute_parallel(operations)
                    
                    # Update status based on results
                    if isinstance(results, bool):
                        # If we got a single boolean result, all operations succeeded or failed
                        if not results:
                            print("Error occurred during checklist item creation")
                    else:
                        # If we got a list of results, process each individually
                        for (_, task_name, items), result in zip(checklist_operations, results):
                            if result:
                                # Ensure task is in summary
                                if task_name not in summary['created'] and task_name not in summary['updated']:
                                    summary['created'][task_name] = {'attributes': [], 'checklist_items': []}
                                
                                # Add checklist items to appropriate summary
                                if task_name in summary['updated']:
                                    summary['updated'][task_name]['checklist_items'].extend([
                                        {'name': item, 'status': 'added'} for item in items
                                    ])
                                else:
                                    summary['created'][task_name]['checklist_items'].extend([
                                        {'name': item, 'status': 'added'} for item in items
                                    ])
                            else:
                                print(f"Error creating checklist items for task {task_name}")

            # Final Summary
            print("\n=== Final Summary ===")
            if summary['created']:
                print("\nNewly Created Checklist Items:")
                for task_name, details in summary['created'].items():
                    print(f"\n{task_name}:")
                    if details['checklist_items']:
                        print("  Checklist Items:")
                        for item in details['checklist_items']:
                            print(f"    - {item['name']} ({item['status']})")

            if summary['updated']:
                print("\nUpdated Checklist Items:")
                for task_name, details in summary['updated'].items():
                    print(f"\n{task_name}:")
                    if details['checklist_items']:
                        print("  Checklist Items:")
                        for item in details['checklist_items']:
                            print(f"    - {item['name']} ({item['status']})")

            print("\nOperation complete!")

        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further items will be processed.")

    def process_uca_tasks(self, project_id, user_id, task_service, attribute_service):
        """Process UCA tasks based on hardware filters.
        
        Creates UCA tasks based on UCI tasks that match hardware filter conditions.
        """
        def uca_check_conditions(text, conditions, exclusions=None, use_word_boundaries=True):
            """Check if text matches any UCA hardware filter condition sets."""
            if use_word_boundaries:
                # Use enhanced checking with word boundaries
                from config.constants import check_enhanced_conditions
                return check_enhanced_conditions(text, conditions, exclusions)
            else:
                # Original substring matching (for backward compatibility)
                text = text.lower()
                for condition_set in conditions:
                    if 'any' in condition_set:
                        any_match = any(term.lower() in text for term in condition_set['any'])
                        if not any_match:
                            continue
                    if 'all' in condition_set:
                        all_match = all(term.lower() in text for term in condition_set['all'])
                        if not all_match:
                            continue
                    if 'none' in condition_set:
                        none_match = not any(term.lower() in text for term in condition_set['none'])
                        if not none_match:
                            continue
                    return True
                return False

        # Get UCA team ID
        print("\n=== Getting UCA Team ID ===")
        print("Retrieving teams from project...")
        teams = attribute_service.get_all_teams_in_project(project_id)
        if teams is None:
            print("Failed to retrieve teams from project")
            return
            
        # Find UCA team
        uca_team = next((team for team in teams if team['name'] == 'UCA'), None)
        if not uca_team:
            print("Error: No team found with name 'UCA' in the project")
            print("Process stopped - UCA team is required.")
            return
            
        uca_team_id = uca_team['id']
        print(f"Found UCA team (ID: {uca_team_id})")

        # Get all tasks, checklist items, and task attributes
        print("\nRetrieving project data...")
        tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
        check_items = attribute_service.get_all_task_check_items_in_project(project_id)
        task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)

        # Get task type attributes and create mapping
        task_type_attributes = attribute_service.get_all_task_type_attributes_in_project(project_id)
        task_type_attribute_map = {}
        for attr in task_type_attributes:
            task_type_attribute_map[attr['id']] = attr['name']

        # Separate UCI source tasks and existing UCA tasks
        uci_tasks = {}  # {task_name: task}
        existing_uca_tasks = {}  # {original_opening_number: uca_task}
        for task in tasks:
            task_name = task['name']
            if task_name.startswith('UCI '):
                uci_tasks[task_name] = task
            elif task_name.startswith('UCA '):
                original_number = task_name[4:]  # Remove 'UCA ' prefix
                existing_uca_tasks[original_number] = task

        # Group checklist items by task
        task_check_items = {}
        for item in check_items:
            task_id = item['task_id']
            if task_id not in task_check_items:
                task_check_items[task_id] = []
            task_check_items[task_id].append(item)

        # Create a lookup of task attributes by task_id
        task_attribute_map = {}
        for attr in task_attributes:
            task_id = attr['task_id']
            if task_id not in task_attribute_map:
                task_attribute_map[task_id] = []
            task_attribute_map[task_id].append(attr)

        # Initialize summary tracking
        summary = {
            'created': {},  # {uca_task_name: {'attributes': [], 'checklist_items': []}}
            'updated': {}   # {uca_task_name: {'attributes': [], 'checklist_items': []}}
        }

        # Phase 1: Identify and Create Missing UCA Tasks
        print("\n=== Phase 1: Creating Missing UCA Tasks ===")
        tasks_to_process = {}  # {original_number: {'uci_task': uci_task, 'uca_task': uca_task}}
        
        # First, identify all tasks that need to be created
        tasks_to_create = []
        for uci_task_name, uci_task in uci_tasks.items():
            uci_task_id = uci_task['id']
            if uci_task_id not in task_check_items:
                continue

            # Extract original opening number from UCI task name
            original_number = uci_task_name[4:]  # Remove 'UCI ' prefix

            # Find matching UCA items in UCI task
            matching_items = {}  # {hardware_type: [matching_items]}
            for check_item in task_check_items[uci_task_id]:
                item_name = check_item['name']
                for hardware_type, filter_def in HARDWARE_FILTERS.items():
                    exclusions = filter_def.get('exclusions', None)
                    if uca_check_conditions(item_name, filter_def['conditions'], exclusions):
                        if hardware_type not in matching_items:
                            matching_items[hardware_type] = []
                        matching_items[hardware_type].append(check_item)

            if not matching_items:
                continue  # Skip if no UCA items found

            uca_task_name = f"UCA {original_number}"
            existing_uca_task = existing_uca_tasks.get(original_number)

            if not existing_uca_task:
                # Add to list of tasks to create
                tasks_to_create.append({
                    'original_number': original_number,
                    'uci_task': uci_task,
                    'matching_items': matching_items,
                    'uca_task_name': uca_task_name
                })
            else:
                # Add existing task to processing list
                tasks_to_process[original_number] = {
                    'uci_task': uci_task,
                    'uca_task': existing_uca_task,
                    'matching_items': matching_items
                }
                summary['updated'][uca_task_name] = {'attributes': [], 'checklist_items': []}

        # Create tasks in parallel
        if tasks_to_create:
            print(f"\nCreating {len(tasks_to_create)} new UCA tasks...")
            
            # Prepare operations for parallel execution
            task_operations = []
            for task_data in tasks_to_create:
                # Use the original opening number for task creation
                task_operations.append((
                    lambda opening_number=task_data['original_number']: task_service.create_task_for_opening(
                        project_id=project_id,
                        owner_user_id=user_id,
                        creator_user_id=user_id,
                        opening_number=f"UCA {opening_number}",  # Use the original opening number
                        team_id=uca_team_id
                    ),
                    task_data
                ))

            # Execute task creation operations in parallel
            executor = RateLimitedExecutor()
            operations = [op[0] for op in task_operations]
            results = executor.execute_parallel(operations)
            
            # Process results
            if isinstance(results, bool):
                # If we got a single boolean result, all operations succeeded or failed
                if results:
                    for _, task_data in task_operations:
                        tasks_to_process[task_data['original_number']] = {
                            'uci_task': task_data['uci_task'],
                            'uca_task': None,  # Will be updated in next phase
                            'matching_items': task_data['matching_items']
                        }
                else:
                    # If we got a list of results, process each individually
                    for (_, task_data), result in zip(task_operations, results):
                        if result:
                            tasks_to_process[task_data['original_number']] = {
                                'uci_task': task_data['uci_task'],
                                'uca_task': None,  # Will be updated in next phase
                                'matching_items': task_data['matching_items']
                            }
            else:
                # If we got a list of results, process each individually
                for (_, task_data), result in zip(task_operations, results):
                    if result:
                        tasks_to_process[task_data['original_number']] = {
                            'uci_task': task_data['uci_task'],
                            'uca_task': None,  # Will be updated in next phase
                            'matching_items': task_data['matching_items']
                        }

        # Refresh task data once after all creations
        if tasks_to_create:
            print("\nRefreshing task data after creation...")
            tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            task_map = {task['name']: task for task in tasks}
            
            # Update tasks_to_process with newly created tasks
            for original_number, task_data in list(tasks_to_process.items()):
                if task_data['uca_task'] is None:  # Only update if task was just created
                    uca_task_name = f"UCA {original_number}"
                    if uca_task_name in task_map:
                        task_data['uca_task'] = task_map[uca_task_name]
                        print(f"Successfully created and found task: {uca_task_name}")
                    else:
                        print(f"Warning: Created task {uca_task_name} not found after refresh")
                        del tasks_to_process[original_number]
                        if uca_task_name in summary['created']:
                            del summary['created'][uca_task_name]

        # Phase 2: Create/Update Attributes in Parallel
        print("\n=== Phase 2: Creating/Updating Attributes ===")
        if tasks_to_process:
            # Prepare all attribute operations
            attribute_operations = []
            for original_number, task_data in tasks_to_process.items():
                uci_task = task_data['uci_task']
                uca_task = task_data['uca_task']
                if not uca_task:  # Skip if task wasn't created successfully
                    print(f"Skipping attributes for task {original_number} - task not found")
                    continue

                uca_task_name = f"UCA {original_number}"

                if uci_task['id'] in task_attribute_map:
                    source_attrs = task_attribute_map[uci_task['id']]
                    existing_attrs = task_attribute_map.get(uca_task['id'], [])
                    
                    # Create lookup for existing attributes
                    existing_attr_map = {
                        attr['task_type_attribute_id']: attr 
                        for attr in existing_attrs
                    }

                    for source_attr in source_attrs:
                        attr_type_id = source_attr['task_type_attribute_id']
                        source_value = (source_attr.get('text_value') or 
                                      source_attr.get('number_value') or 
                                      source_attr.get('uuid_value'))
                        
                        # Log attribute check
                        attr_status = {
                            'name': task_type_attribute_map.get(attr_type_id, 'Unknown'),
                            'value': source_value,
                            'status': 'unchanged'
                        }

                        if attr_type_id in existing_attr_map:
                            existing_value = (existing_attr_map[attr_type_id].get('text_value') or 
                                           existing_attr_map[attr_type_id].get('number_value') or 
                                           existing_attr_map[attr_type_id].get('uuid_value'))
                            if existing_value != source_value:
                                # Add to operations for parallel execution
                                attribute_operations.append((
                                    lambda task_id=uca_task['id'], attr_type_id=attr_type_id, 
                                           source_value=source_value: attribute_service.create_a_task_attribute_in_task(
                                    project_id=project_id,
                                        task_id=task_id,
                                    task_type_attribute_id=attr_type_id,
                                    attribute_value=source_value,
                                    user_id=user_id
                                    ),
                                    attr_status,
                                    'updated',
                                    existing_value,
                                    uca_task_name
                                ))
                        else:
                            # Add to operations for parallel execution
                            attribute_operations.append((
                                lambda task_id=uca_task['id'], attr_type_id=attr_type_id, 
                                       source_value=source_value: attribute_service.create_a_task_attribute_in_task(
                                project_id=project_id,
                                    task_id=task_id,
                                task_type_attribute_id=attr_type_id,
                                attribute_value=source_value,
                                user_id=user_id
                                ),
                                attr_status,
                                'added',
                                None,
                                uca_task_name
                            ))

            # Execute attribute operations in parallel
            if attribute_operations:
                executor = RateLimitedExecutor()
                operations = [op[0] for op in attribute_operations]
                results = executor.execute_parallel(operations)
                
                # Update status based on results
                if isinstance(results, bool):
                    # If we got a single boolean result, all operations succeeded or failed
                    if results:
                        for _, attr_status, status, old_value, task_name in attribute_operations:
                            attr_status['status'] = status
                            if old_value is not None:
                                attr_status['old_value'] = old_value
                            # Ensure task is in summary
                            if task_name not in summary['created'] and task_name not in summary['updated']:
                                summary['created'][task_name] = {'attributes': [], 'checklist_items': []}
                            if task_name in summary['updated']:
                                summary['updated'][task_name]['attributes'].append(attr_status)
                            else:
                                summary['created'][task_name]['attributes'].append(attr_status)
                else:
                    # If we got a list of results, process each individually
                    for (_, attr_status, status, old_value, task_name), result in zip(attribute_operations, results):
                        if result:
                            attr_status['status'] = status
                            if old_value is not None:
                                attr_status['old_value'] = old_value
                            # Ensure task is in summary
                            if task_name not in summary['created'] and task_name not in summary['updated']:
                                summary['created'][task_name] = {'attributes': [], 'checklist_items': []}
                            if task_name in summary['updated']:
                                summary['updated'][task_name]['attributes'].append(attr_status)
                            else:
                                summary['created'][task_name]['attributes'].append(attr_status)

        # Phase 3: Create Checklist Items in Parallel
        print("\n=== Phase 3: Creating Checklist Items ===")
        if tasks_to_process:
            # Prepare all checklist item operations
            checklist_operations = []
            for original_number, task_data in tasks_to_process.items():
                uca_task = task_data['uca_task']
                if not uca_task:  # Skip if task wasn't created successfully
                    print(f"Skipping checklist items for task {original_number} - task not found")
                    continue

                matching_items = task_data['matching_items']
                uca_task_name = f"UCA {original_number}"

                # Add new checklist items
                existing_items = set(item['name'] for item in task_check_items.get(uca_task['id'], []))
                new_items = []

                for hardware_type, items in matching_items.items():
                    # Add original matching items
                    for item in items:
                        if item['name'] not in existing_items:
                            new_items.append(item['name'])
                            if uca_task_name in summary['updated']:
                                summary['updated'][uca_task_name]['checklist_items'].append({
                                    'name': item['name'],
                                    'status': 'added'
                                })
                            else:
                                summary['created'][uca_task_name]['checklist_items'].append({
                                    'name': item['name'],
                                    'status': 'added'
                                })
                    
                    # Add additional items if they exist
                    if 'create_items' in HARDWARE_FILTERS[hardware_type]:
                        for item_name in HARDWARE_FILTERS[hardware_type]['create_items']:
                            if item_name not in existing_items:
                                new_items.append(item_name)
                                if uca_task_name in summary['updated']:
                                    summary['updated'][uca_task_name]['checklist_items'].append({
                                        'name': item_name,
                                        'status': 'added'
                                    })
                                else:
                                    summary['created'][uca_task_name]['checklist_items'].append({
                                        'name': item_name,
                                        'status': 'added'
                                    })
                    
                if new_items:
                    # Add to operations for parallel execution
                    checklist_operations.append((
                        lambda task_id=uca_task['id'], items=new_items: attribute_service.create_multiple_checklist_items_in_task(
                            project_id=project_id,
                            task_id=task_id,
                            names=items
                        ),
                        uca_task_name,
                        new_items
                    ))

            # Execute checklist operations in parallel
            if checklist_operations:
                executor = RateLimitedExecutor()
                operations = [op[0] for op in checklist_operations]
                results = executor.execute_parallel(operations)
                
                # Update status based on results
                if isinstance(results, bool):
                    # If we got a single boolean result, all operations succeeded or failed
                    if not results:
                        print("Error occurred during checklist item creation")
                else:
                    # If we got a list of results, process each individually
                    for (_, task_name, items), result in zip(checklist_operations, results):
                        if result:
                            # Ensure task is in summary
                            if task_name not in summary['created'] and task_name not in summary['updated']:
                                summary['created'][task_name] = {'attributes': [], 'checklist_items': []}
                                
                                # Add checklist items to appropriate summary
                                if task_name in summary['updated']:
                                    summary['updated'][task_name]['checklist_items'].extend([
                                        {'name': item, 'status': 'added'} for item in items
                                    ])
                                else:
                                    summary['created'][task_name]['checklist_items'].extend([
                                        {'name': item, 'status': 'added'} for item in items
                                    ])
                            else:
                                print(f"Error creating checklist items for task {task_name}")

        # Print Summary
        print("\n=== UCA Tasks Summary ===")
        
        if summary['created']:
            print("\nNewly Created UCA Tasks:")
            for task_name, details in summary['created'].items():
                print(f"\n{task_name}:")
                if details['attributes']:
                    print("  Attributes:")
                    for attr in details['attributes']:
                        print(f"    - {attr['name']}: {attr['value']} ({attr['status']})")
                if details['checklist_items']:
                    print("  Checklist Items:")
                    for item in details['checklist_items']:
                        print(f"    - {item['name']} ({item['status']})")

        if summary['updated']:
            print("\nUpdated UCA Tasks:")
            for task_name, details in summary['updated'].items():
                print(f"\n{task_name}:")
                if details['attributes']:
                    print("  Attributes:")
                    for attr in details['attributes']:
                        status_info = f"({attr['status']})"
                        if 'old_value' in attr:
                            status_info = f"(changed from: {attr['old_value']})"
                        print(f"    - {attr['name']}: {attr['value']} {status_info}")
                if details['checklist_items']:
                    print("  Checklist Items:")
                    for item in details['checklist_items']:
                        print(f"    - {item['name']} ({item['status']})")

        print("\nUCA task processing complete!")

    def process_misc_tasks(self, project_id, user_id, task_service, attribute_service):
        """Process DEF and FC tasks based on UCI tasks.
        
        Creates DEF and FC tasks for each UCI task, copying all attributes.
        FC tasks get standard checklist items.
        """
        try:
            # Step 1: Validate Teams
            print("\n=== Getting Required Teams ===")
            print("Retrieving teams from project...")
            teams = attribute_service.get_all_teams_in_project(project_id)
            if teams is None:
                print("Failed to retrieve teams from project")
                return
                
            # Find required teams
            def_team = next((team for team in teams if team['name'] == 'Deficiency'), None)
            fc_team = next((team for team in teams if team['name'] == 'Frame Check'), None)
            
            if not def_team or not fc_team:
                print("Error: Required teams not found:")
                if not def_team:
                    print("- 'Deficiency' team is missing")
                if not fc_team:
                    print("- 'Frame Check' team is missing")
                print("Process stopped - all teams are required.")
                return

            def_team_id = def_team['id']
            fc_team_id = fc_team['id']
            print(f"Found Deficiency team (ID: {def_team_id})")
            print(f"Found Frame Check team (ID: {fc_team_id})")

            # Step 1.5: Get and validate "Commissioned" status
            print("\n=== Getting Commissioned Status ===")
            print("Retrieving statuses from project...")
            statuses = self.get_statuses_for_project_id(project_id)
            if statuses is None:
                print("Failed to retrieve statuses from project")
                return

            # Find commissioned status (case-insensitive)
            commissioned_status = None
            for status in statuses:
                status_name = status.get('name')
                status_id = status.get('id')
                
                # Verify status has both required fields
                if not status_name or not status_id:
                    print(f"Warning: Found invalid status missing name or id: {status}")
                    continue
                
                if status_name.lower() == 'commissioned':
                    commissioned_status = status
                    break

            if not commissioned_status:
                print("Error: No status found with name 'commissioned' (case-insensitive)")
                print("Available statuses:")
                for status in statuses:
                    status_name = status.get('name', 'Unknown')
                    status_id = status.get('id', 'Unknown')
                    print(f"- {status_name} (ID: {status_id})")
                print("Process cancelled - commissioned status is required for DEF tasks.")
                return

            commissioned_status_id = commissioned_status['id']
            print(f"Found commissioned status (ID: {commissioned_status_id}, Name: '{commissioned_status['name']}')")

            # Step 2: Get all tasks, checklist items, and task attributes
            print("\nRetrieving project data...")
            tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            check_items = attribute_service.get_all_task_check_items_in_project(project_id)
            task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)

            # Get task type attributes and create mapping
            task_type_attributes = attribute_service.get_all_task_type_attributes_in_project(project_id)
            task_type_attribute_map = {}
            for attr in task_type_attributes:
                task_type_attribute_map[attr['id']] = attr['name']

            # Step 3: Organize tasks and create lookups
            # Separate UCI source tasks and existing DEF/FC tasks
            uci_tasks = {}  # {task_name: task}
            existing_def_tasks = {}  # {original_opening_number: task}
            existing_fc_tasks = {}   # {original_opening_number: task}
            
            for task in tasks:
                task_name = task['name']
                if task_name.startswith('UCI '):
                    uci_tasks[task_name] = task
                elif task_name.startswith('DEF '):
                    original_number = task_name[4:]  # Remove 'DEF ' prefix
                    existing_def_tasks[original_number] = task
                elif task_name.startswith('FC '):
                    original_number = task_name[3:]  # Remove 'FC ' prefix
                    existing_fc_tasks[original_number] = task

            # Group checklist items by task
            task_check_items = {}
            for item in check_items:
                task_id = item['task_id']
                if task_id not in task_check_items:
                    task_check_items[task_id] = []
                task_check_items[task_id].append(item)

            # Create a lookup of task attributes by task_id
            task_attribute_map = {}
            for attr in task_attributes:
                task_id = attr['task_id']
                if task_id not in task_attribute_map:
                    task_attribute_map[task_id] = []
                task_attribute_map[task_id].append(attr)

            # Initialize summary tracking
            summary = {
                'created': {},  # {task_name: {'type': 'DEF/FC', 'attributes': [], 'checklist_items': []}}
                'updated': {},  # {task_name: {'type': 'DEF/FC', 'attributes': [], 'checklist_items': []}},
                'skipped': {}   # {task_name: {'type': 'DEF/FC', 'reason': 'Already exists'}}
            }

            # Phase 1: Create Missing DEF and FC Tasks
            print("\n=== Phase 1: Creating Missing Tasks ===")
            tasks_to_process = {}  # {original_number: {'uci_task': uci_task, 'def_task': def_task, 'fc_task': fc_task}}
            
            # First, identify all tasks that need to be created
            tasks_to_create = []
            for uci_task_name, uci_task in uci_tasks.items():
                original_number = uci_task_name[4:]  # Remove 'UCI ' prefix

                def_task_name = f"DEF {original_number}"
                fc_task_name = f"FC {original_number}"
                
                existing_def_task = existing_def_tasks.get(original_number)
                existing_fc_task = existing_fc_tasks.get(original_number)
                
                tasks_to_process[original_number] = {
                    'uci_task': uci_task,
                    'def_task': existing_def_task,
                    'fc_task': existing_fc_task
                }
                
                if not existing_def_task:
                    tasks_to_create.append({
                        'type': 'DEF',
                        'name': def_task_name,
                        'team_id': def_team_id,
                        'original_number': original_number
                    })
                
                if not existing_fc_task:
                    tasks_to_create.append({
                        'type': 'FC',
                        'name': fc_task_name,
                        'team_id': fc_team_id,
                        'original_number': original_number
                    })

            # Create tasks in parallel
            if tasks_to_create:
                print(f"\nCreating {len(tasks_to_create)} new tasks...")
                
                # Prepare operations for parallel execution
                task_operations = []
                for task_data in tasks_to_create:
                    task_operations.append((
                        lambda opening_number=task_data['name'], team_id=task_data['team_id'], task_type=task_data['type']: task_service.create_task_for_opening(
                        project_id=project_id,
                        owner_user_id=user_id,
                        creator_user_id=user_id,
                            opening_number=opening_number,
                            team_id=team_id,
                            status_id=commissioned_status_id if task_type == 'DEF' else None
                        ),
                        task_data
                    ))

                # Execute task creation operations in parallel
                executor = RateLimitedExecutor()
                operations = [op[0] for op in task_operations]
                results = executor.execute_parallel(operations)
                
                # Process results
                if isinstance(results, bool):
                    # If we got a single boolean result, all operations succeeded or failed
                    if results:
                        for _, task_data in task_operations:
                            original_number = task_data['original_number']
                            if task_data['type'] == 'DEF':
                                tasks_to_process[original_number]['def_task'] = None  # Will be updated in next phase
                                summary['created'][task_data['name']] = {'type': 'DEF', 'attributes': [], 'checklist_items': []}
                            else:
                                tasks_to_process[original_number]['fc_task'] = None  # Will be updated in next phase
                                summary['created'][task_data['name']] = {'type': 'FC', 'attributes': [], 'checklist_items': []}
                else:
                    # If we got a list of results, process each individually
                    for (_, task_data), result in zip(task_operations, results):
                        if result:
                            original_number = task_data['original_number']
                            if task_data['type'] == 'DEF':
                                tasks_to_process[original_number]['def_task'] = None  # Will be updated in next phase
                                summary['created'][task_data['name']] = {'type': 'DEF', 'attributes': [], 'checklist_items': []}
                            else:
                                tasks_to_process[original_number]['fc_task'] = None  # Will be updated in next phase
                                summary['created'][task_data['name']] = {'type': 'FC', 'attributes': [], 'checklist_items': []}

            # Refresh task data once after all creations
            if tasks_to_create:
                print("\nRefreshing task data after creation...")
                tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
                task_map = {task['name']: task for task in tasks}
                
                # Update tasks_to_process with newly created tasks
                for original_number, task_data in list(tasks_to_process.items()):
                    def_task_name = f"DEF {original_number}"
                    fc_task_name = f"FC {original_number}"
                    
                    if task_data['def_task'] is None and def_task_name in task_map:
                        task_data['def_task'] = task_map[def_task_name]
                        print(f"Successfully created and found task: {def_task_name}")
                    
                    if task_data['fc_task'] is None and fc_task_name in task_map:
                        task_data['fc_task'] = task_map[fc_task_name]
                        print(f"Successfully created and found task: {fc_task_name}")

            # Phase 2: Create/Update Attributes in Parallel
            print("\n=== Phase 2: Creating/Updating Attributes ===")
            if tasks_to_process:
                # Prepare all attribute operations
                attribute_operations = []
                for original_number, task_data in tasks_to_process.items():
                    uci_task = task_data['uci_task']
                    def_task = task_data['def_task']
                    fc_task = task_data['fc_task']
                    
                    if uci_task['id'] in task_attribute_map:
                        source_attrs = task_attribute_map[uci_task['id']]
                        
                        # Process DEF task attributes
                        if def_task:
                            existing_attrs = task_attribute_map.get(def_task['id'], [])
                        existing_attr_map = {
                            attr['task_type_attribute_id']: attr 
                            for attr in existing_attrs
                        }

                        for source_attr in source_attrs:
                            attr_type_id = source_attr['task_type_attribute_id']
                            source_value = (source_attr.get('text_value') or 
                                          source_attr.get('number_value') or 
                                          source_attr.get('uuid_value'))
                            
                            attr_status = {
                                'name': task_type_attribute_map.get(attr_type_id, 'Unknown'),
                                'value': source_value,
                                'status': 'unchanged'
                            }

                            if attr_type_id in existing_attr_map:
                                existing_value = (existing_attr_map[attr_type_id].get('text_value') or 
                                               existing_attr_map[attr_type_id].get('number_value') or 
                                               existing_attr_map[attr_type_id].get('uuid_value'))
                                if existing_value != source_value:
                                        attribute_operations.append((
                                            lambda task_id=def_task['id'], attr_type_id=attr_type_id, 
                                                   source_value=source_value: attribute_service.create_a_task_attribute_in_task(
                                        project_id=project_id,
                                                task_id=task_id,
                                        task_type_attribute_id=attr_type_id,
                                        attribute_value=source_value,
                                        user_id=user_id
                                            ),
                                            attr_status,
                                            'updated',
                                            existing_value,
                                            f"DEF {original_number}"
                                        ))
                            else:
                                    attribute_operations.append((
                                        lambda task_id=def_task['id'], attr_type_id=attr_type_id, 
                                               source_value=source_value: attribute_service.create_a_task_attribute_in_task(
                                    project_id=project_id,
                                            task_id=task_id,
                                    task_type_attribute_id=attr_type_id,
                                    attribute_value=source_value,
                                    user_id=user_id
                                        ),
                                        attr_status,
                                        'added',
                                        None,
                                        f"DEF {original_number}"
                                    ))
                        
                        # Process FC task attributes
                        if fc_task:
                            existing_attrs = task_attribute_map.get(fc_task['id'], [])
                        existing_attr_map = {
                            attr['task_type_attribute_id']: attr 
                            for attr in existing_attrs
                        }

                        for source_attr in source_attrs:
                            attr_type_id = source_attr['task_type_attribute_id']
                            source_value = (source_attr.get('text_value') or 
                                          source_attr.get('number_value') or 
                                          source_attr.get('uuid_value'))
                            
                            attr_status = {
                                'name': task_type_attribute_map.get(attr_type_id, 'Unknown'),
                                'value': source_value,
                                'status': 'unchanged'
                            }

                            if attr_type_id in existing_attr_map:
                                existing_value = (existing_attr_map[attr_type_id].get('text_value') or 
                                               existing_attr_map[attr_type_id].get('number_value') or 
                                               existing_attr_map[attr_type_id].get('uuid_value'))
                                if existing_value != source_value:
                                        attribute_operations.append((
                                            lambda task_id=fc_task['id'], attr_type_id=attr_type_id, 
                                                   source_value=source_value: attribute_service.create_a_task_attribute_in_task(
                                        project_id=project_id,
                                                task_id=task_id,
                                        task_type_attribute_id=attr_type_id,
                                        attribute_value=source_value,
                                        user_id=user_id
                                            ),
                                            attr_status,
                                            'updated',
                                            existing_value,
                                            f"FC {original_number}"
                                        ))
                            else:
                                    attribute_operations.append((
                                        lambda task_id=fc_task['id'], attr_type_id=attr_type_id, 
                                               source_value=source_value: attribute_service.create_a_task_attribute_in_task(
                                    project_id=project_id,
                                            task_id=task_id,
                                    task_type_attribute_id=attr_type_id,
                                    attribute_value=source_value,
                                    user_id=user_id
                                        ),
                                        attr_status,
                                        'added',
                                        None,
                                        f"FC {original_number}"
                                    ))

                # Execute attribute operations in parallel
                if attribute_operations:
                    executor = RateLimitedExecutor()
                    operations = [op[0] for op in attribute_operations]
                    results = executor.execute_parallel(operations)
                    
                    # Update status based on results
                    if isinstance(results, bool):
                        # If we got a single boolean result, all operations succeeded or failed
                        if results:
                            for _, attr_status, status, old_value, task_name in attribute_operations:
                                attr_status['status'] = status
                                if old_value is not None:
                                    attr_status['old_value'] = old_value
                                # Ensure task is in summary
                                if task_name not in summary['created'] and task_name not in summary['updated']:
                                    summary['created'][task_name] = {'type': task_name[:3], 'attributes': [], 'checklist_items': []}
                                if task_name in summary['updated']:
                                    summary['updated'][task_name]['attributes'].append(attr_status)
                            else:
                                summary['created'][task_name]['attributes'].append(attr_status)
                    else:
                        # If we got a list of results, process each individually
                        for (_, attr_status, status, old_value, task_name), result in zip(attribute_operations, results):
                            if result:
                                attr_status['status'] = status
                                if old_value is not None:
                                    attr_status['old_value'] = old_value
                                # Ensure task is in summary
                                if task_name not in summary['created'] and task_name not in summary['updated']:
                                    summary['created'][task_name] = {'type': task_name[:3], 'attributes': [], 'checklist_items': []}
                                if task_name in summary['updated']:
                                    summary['updated'][task_name]['attributes'].append(attr_status)
                                else:
                                    summary['created'][task_name]['attributes'].append(attr_status)

            # Phase 3: Create Checklist Items in Parallel
            print("\n=== Phase 3: Creating Checklist Items ===")
            if tasks_to_process:
                # Prepare all checklist item operations
                checklist_operations = []
                for original_number, task_data in tasks_to_process.items():
                    fc_task = task_data['fc_task']
                    if not fc_task:  # Skip if task wasn't created successfully
                        print(f"Skipping checklist items for FC task {original_number} - task not found")
                        continue

                    # Get existing checklist items for this task
                    existing_items = set(item['name'] for item in task_check_items.get(fc_task['id'], []))
                    
                    # Find missing items
                    missing_items = [item for item in FC_CHECKLIST_ITEMS if item not in existing_items]
                    
                    if missing_items:
                        # Add to operations for parallel execution
                        checklist_operations.append((
                            lambda task_id=fc_task['id'], items=missing_items: attribute_service.create_multiple_checklist_items_in_task(
                                project_id=project_id,
                                task_id=task_id,
                                names=items
                            ),
                            f"FC {original_number}",
                            missing_items
                        ))

                # Execute checklist operations in parallel
                if checklist_operations:
                    executor = RateLimitedExecutor()
                    operations = [op[0] for op in checklist_operations]
                    results = executor.execute_parallel(operations)
                    
                    # Update status based on results
                    if isinstance(results, bool):
                        # If we got a single boolean result, all operations succeeded or failed
                        if not results:
                            print("Error occurred during checklist item creation")
                    else:
                        # If we got a list of results, process each individually
                        for (_, task_name, items), result in zip(checklist_operations, results):
                            if result:
                                # Ensure task is in summary
                                if task_name not in summary['created'] and task_name not in summary['updated']:
                                    summary['created'][task_name] = {'type': 'FC', 'attributes': [], 'checklist_items': []}
                                
                                # Add checklist items to appropriate summary
                                if task_name in summary['updated']:
                                    summary['updated'][task_name]['checklist_items'].extend([
                                        {'name': item, 'status': 'added'} for item in items
                                    ])
                                else:
                                    summary['created'][task_name]['checklist_items'].extend([
                                        {'name': item, 'status': 'added'} for item in items
                                    ])
                            else:
                                print(f"Error creating checklist items for task {task_name}")

            # Print Summary
            print("\n=== Tasks Summary ===")
            
            if summary['created']:
                print("\nNewly Created Tasks:")
                for task_name, details in summary['created'].items():
                    print(f"\n{task_name} ({details['type']}):")
                    if details['attributes']:
                        print("  Attributes:")
                        for attr in details['attributes']:
                            print(f"    - {attr['name']}: {attr['value']} ({attr['status']})")
                    if details.get('checklist_items'):
                        print("  Checklist Items:")
                        for item in details['checklist_items']:
                            print(f"    - {item['name']} ({item['status']})")

            if summary['updated']:
                print("\nUpdated Tasks:")
                for task_name, details in summary['updated'].items():
                    print(f"\n{task_name} ({details['type']}):")
                    if details['attributes']:
                        print("  Attributes:")
                        for attr in details['attributes']:
                            status_info = f"({attr['status']})"
                            if 'old_value' in attr:
                                status_info = f"(changed from: {attr['old_value']})"
                            print(f"    - {attr['name']}: {attr['value']} {status_info}")
                    if details.get('checklist_items'):
                        print("  Checklist Items:")
                        for item in details['checklist_items']:
                            print(f"    - {item['name']} ({item['status']})")

            print("\nTask processing complete!")

        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further items will be processed.")

    def bc_initialize_checklists(self, project_id, task_service, attribute_service):
        """Initialize checklist items from BC Excel file."""
        try:
            # Step 1: Get user ID for task creation
            print("\n=== Step 1: Get User ID ===")
            user_id = get_user_input("Enter user ID: ")
            
            # Step 2: Get teams and user selection
            print("\n=== Step 2: Team Selection ===")
            teams = attribute_service.get_all_teams_in_project(project_id)
            if not teams:
                print("No teams found in the project.")
                return

            print("\nAvailable Teams:")
            for team in teams:
                print(f"- {team['name']}")

            selected_team = None
            while True:
                team_filter = get_user_input("\nEnter Team Category Name Filter: ")
                selected_team = next((team for team in teams if team['name'] == team_filter), None)
                
                if selected_team:
                    break
                
                print("\nTeam not found. Available teams:")
                for team in teams:
                    print(f"- {team['name']}")

            # Step 3: Get Excel file
            print("\n=== Step 3: Select Excel File ===")
            file_path = prompt_user_for_excel_file()
            if not file_path:
                print("No file selected.")
                return

            # Step 4: Load Excel Data
            print("\n=== Step 4: Parse Excel File ===")
            print("Loading Excel file...")
            try:
                # Read the entire Sheet0
                xl = pd.ExcelFile(file_path)
                if "Sheet0" not in xl.sheet_names:
                    print("Error: Sheet 'Sheet0' not found in Excel file")
                    print("Available sheets:", xl.sheet_names)
                    return
                
                df = pd.read_excel(file_path, sheet_name="Sheet0", dtype=str)
                
                # Case-insensitive check for Opening ID column
                opening_id_col = None
                for col in df.columns:
                    if col is not None and str(col).lower() == 'opening id':
                        opening_id_col = col
                        break
                
                if not opening_id_col:
                    print("Error: Required column 'Opening ID' (case insensitive) not found in the Excel file")
                    print("Available columns:", ", ".join(str(c) if c is not None else 'None' for c in df.columns))
                    return
                
                # Rename the column to our expected format if it's different
                if opening_id_col != 'Opening ID':
                    df = df.rename(columns={opening_id_col: 'Opening ID'})
                    
            except Exception as sheet_error:
                print(f"Error reading Excel file: {str(sheet_error)}")
                print("\nPlease ensure:")
                print("1. The file is a valid Excel file")
                print("2. The file contains a sheet named 'Sheet0'")
                print("3. The sheet contains an 'Opening ID' column (case insensitive)")
                return

            if df.empty:
                print("Error: No data found in the Excel file")
                return

            print(f"Successfully loaded {len(df)} rows from Excel file")
            print("\nFound columns:", ", ".join(str(c) if c is not None else 'None' for c in df.columns))

            # Step 5: Get unique Opening IDs from the Excel file
            unique_opening_ids = set()
            empty_opening_ids = 0
            
            for index, row in df.iterrows():
                opening_id = str(row['Opening ID']).strip()
                if opening_id:
                    unique_opening_ids.add(opening_id)
                else:
                    empty_opening_ids += 1
            
            print(f"\nFound {len(unique_opening_ids)} unique Opening IDs in the Excel file")
            if empty_opening_ids > 0:
                print(f"Note: {empty_opening_ids} rows have empty Opening IDs and will be skipped")
            
            # Step 6: Get existing tasks and filter by team
            print("\n=== Step 5: Retrieve Existing Tasks ===")
            existing_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            
            # Filter tasks by team_id
            filtered_tasks = [task for task in existing_tasks if task.get('team_id') == selected_team['id']]
            task_map = {task['name']: task for task in filtered_tasks}
            
            print(f"\nSelected Team: {selected_team['name']}")
            print(f"Tasks in selected team: {len(filtered_tasks)}")

            # Step 7: Identify missing tasks
            missing_opening_ids = [opening_id for opening_id in unique_opening_ids if opening_id not in task_map]
            print(f"\nFound {len(missing_opening_ids)} Opening IDs without existing tasks in team '{selected_team['name']}'")
            
            if missing_opening_ids:
                print("\nOpening IDs without tasks:")
                for opening_id in sorted(missing_opening_ids):
                    print(f"- {opening_id}")
                
                # Ask for confirmation to create tasks
                proceed = get_user_input("\nWould you like to create tasks for these Opening IDs? (y/n): ")
                if proceed.lower() != 'y':
                    print("Operation cancelled.")
                    return
                
                # Step 7.1: Create missing tasks
                print(f"\n=== Creating {len(missing_opening_ids)} Missing Tasks ===")
                
                # Create executor for parallel task creation
                executor = RateLimitedExecutor()
                
                # Prepare operations
                operations = []
                for opening_id in missing_opening_ids:
                    def create_task(opening_id=opening_id):
                        return task_service.create_task_for_opening(
                            project_id=project_id,
                            owner_user_id=user_id,
                            creator_user_id=user_id,
                            opening_number=opening_id,
                            team_id=selected_team['id']
                        )
                    operations.append((
                        create_task,
                        opening_id
                    ))
                
                # Execute operations in parallel
                if operations:
                    print(f"Creating {len(operations)} tasks...")
                    
                    # Extract just the operation functions
                    op_functions = [op[0] for op in operations]
                    
                    # Execute in parallel
                    results = executor.execute_parallel(op_functions)
                    
                    # Process results
                    created_tasks = []
                    failed_tasks = []
                    
                    if isinstance(results, bool):
                        # If we got a single boolean result
                        if results:
                            created_tasks = [op[1] for op in operations]
                        else:
                            print("Error: Failed to create tasks")
                            return
                    else:
                        # If we got individual results
                        for i, (result, (_, opening_id)) in enumerate(zip(results, operations)):
                            if result:
                                created_tasks.append(opening_id)
                            else:
                                failed_tasks.append(opening_id)
                    
                    # Summary of task creation
                    print(f"\nTasks created: {len(created_tasks)}")
                    if failed_tasks:
                        print(f"Tasks failed: {len(failed_tasks)}")
                        print("\nFailed to create tasks for these Opening IDs:")
                        for opening_id in failed_tasks[:10]:  # Show first 10 failures
                            print(f"- {opening_id}")
                        if len(failed_tasks) > 10:
                            print(f"... and {len(failed_tasks) - 10} more")
                    
                # Ask for confirmation to continue with checklist creation
                continue_op = get_user_input("\nContinue with creating checklist items? (y/n): ")
                if continue_op.lower() != 'y':
                    print("Operation completed - checklist items were not created.")
                    return
                
                # Step 7.2: Refresh task data
                print("\nRefreshing task data...")
                existing_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
                filtered_tasks = [task for task in existing_tasks if task.get('team_id') == selected_team['id']]
                task_map = {task['name']: task for task in filtered_tasks}
                print(f"Updated - Tasks in selected team: {len(filtered_tasks)}")
            
            # Step 8: Get existing checklist items
            print("\n=== Retrieving Existing Checklist Items ===")
            existing_checklist_items = attribute_service.get_all_task_check_items_in_project(project_id)
            checklist_map = {}
            for item in existing_checklist_items:
                task_id = item['task_id']
                if task_id not in checklist_map:
                    checklist_map[task_id] = set()
                checklist_map[task_id].add(item['name'])

            # Step 9: Process Excel rows and group by tasks
            print("\n=== Processing Excel Data for Checklist Items ===")
            task_checklist_items = {}  # {task_id: [checklist_items]}
            unmatched_openings = set()
            
            # Using tqdm for progress tracking
            total_rows = len(df)
            for index, row in tqdm(df.iterrows(), total=total_rows, desc="Processing rows"):
                opening_id = str(row['Opening ID']).strip()
                if not opening_id or opening_id not in task_map:
                    if opening_id.strip():  # Only track non-empty IDs
                        unmatched_openings.add(opening_id)
                    continue

                # Build checklist item name
                name_parts = []
                for field in ['Qty', 'Description', 'Part Number', 'Hand', 'Item']:
                    if field in df.columns and pd.notna(row[field]) and str(row[field]).strip():
                        name_parts.append(f"({str(row[field]).strip()})")

                if not name_parts:  # Skip if all fields are empty
                    continue

                checklist_name = " ".join(name_parts)
                task_id = task_map[opening_id]['id']

                # Skip if checklist item already exists
                if task_id in checklist_map and checklist_name in checklist_map[task_id]:
                    continue

                # Group checklist items by task
                if task_id not in task_checklist_items:
                    task_checklist_items[task_id] = []
                task_checklist_items[task_id].append(checklist_name)

            # Step 10: Create checklist items in parallel
            print("\n=== Creating Checklist Items ===")
            
            # Prepare operations for parallel execution
            checklist_operations = []
            for task_id, checklist_names in task_checklist_items.items():
                if checklist_names:
                    def create_checklist_items(task_id=task_id, names=checklist_names):
                        return attribute_service.create_multiple_checklist_items_in_task(
                            project_id=project_id,
                            task_id=task_id,
                            names=names
                        )
                    checklist_operations.append((
                        create_checklist_items,
                        task_id,
                        task_map[next(t['name'] for t in filtered_tasks if t['id'] == task_id)],
                        checklist_names
                    ))
            
            # Execute operations in parallel
            tasks_processed = 0
            items_created = 0
            failed_tasks = []
            
            if checklist_operations:
                print(f"Processing {len(checklist_operations)} tasks with {sum(len(op[3]) for op in checklist_operations)} checklist items")
                
                # Create executor for parallel checklist item creation
                executor = RateLimitedExecutor()
                
                # Extract just the operation functions
                operations = [op[0] for op in checklist_operations]
                
                # Execute in parallel
                results = executor.execute_parallel(operations)
                
                # Process results
                if isinstance(results, bool):
                    # If we got a single boolean result
                    if results:
                        tasks_processed = len(checklist_operations)
                        items_created = sum(len(op[3]) for op in checklist_operations)
                    else:
                        print("Error: All checklist operations failed")
                else:
                    # If we got individual results
                    for i, (result, (_, task_id, task_name, names)) in enumerate(zip(results, checklist_operations)):
                        if result:
                            tasks_processed += 1
                            items_created += len(names)
                        else:
                            failed_tasks.append(task_name)
                
                if failed_tasks:
                    print("\nFailed to create checklist items for these tasks:")
                    for task_name in failed_tasks[:10]:  # Show first 10 failures
                        print(f"- {task_name}")
                    if len(failed_tasks) > 10:
                        print(f"... and {len(failed_tasks) - 10} more")

            # Final Summary
            print("\n=== Summary ===")
            print(f"Total rows processed: {total_rows}")
            
            if missing_opening_ids:
                print(f"Tasks created: {len(created_tasks) if 'created_tasks' in locals() else 0}")
                if 'failed_tasks' in locals() and failed_tasks:
                    print(f"Task creation failed: {len(failed_tasks)}")
            
            print(f"Tasks updated with checklist items: {tasks_processed}")
            print(f"Checklist items created: {items_created}")
            
            if unmatched_openings:
                print("\nOpening IDs that could not be matched to tasks:")
                for opening in sorted(unmatched_openings):
                    print(f"- {opening}")
            
            print("\nOperation complete!")

        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further items will be processed.")

    def bc_initialize_task_attributes(self, project_id, task_service, attribute_service):
        """Initialize task attributes from BC Excel file with comprehensive verification.
        
        This function now processes both location tiers and task attributes from the same spreadsheet:
        1. If Tier 1-5 columns are found, it processes locations first
        2. Then processes any matching task attributes
        
        All processing uses the same Excel file to minimize user interaction.
        """
        try:
            # Get user ID first
            print("\n=== Step 1: Get User ID ===")
            user_id = get_user_input("Enter user ID: ")
            
            # Step 2: Get Excel file
            print("\n=== Step 2: Select Excel File ===")
            file_path = prompt_user_for_excel_file()
            if not file_path:
                print("No file selected.")
                return

            # Step 3: Load Excel Data
            print("\n=== Step 3: Parse Excel File ===")
            print("Loading Excel file...")
            try:
                # Read the entire Sheet0
                xl = pd.ExcelFile(file_path)
                if "Sheet0" not in xl.sheet_names:
                    print("Error: Sheet 'Sheet0' not found in Excel file")
                    print("Available sheets:", xl.sheet_names)
                    return
                
                df = pd.read_excel(file_path, sheet_name="Sheet0", dtype=str)
                
                # Case-insensitive check for Opening ID column
                opening_id_col = None
                for col in df.columns:
                    if col is not None and str(col).lower() == 'opening id':
                        opening_id_col = col
                        break
                
                if not opening_id_col:
                    print("Error: Required column 'Opening ID' (case insensitive) not found in the Excel file")
                    print("Available columns:", ", ".join(str(c) if c is not None else 'None' for c in df.columns))
                    return
                
                # Rename the column to our expected format if it's different
                if opening_id_col != 'Opening ID':
                    df = df.rename(columns={opening_id_col: 'Opening ID'})
                    
                # Check for tier columns
                tier_columns = []
                for i in range(1, 6):
                    tier_col = None
                    tier_name = f"Tier {i}"
                    for col in df.columns:
                        if col is not None and str(col).lower() == tier_name.lower():
                            tier_col = col
                            break
                    
                    if tier_col:
                        tier_columns.append(tier_col)
                    
                print(f"Successfully loaded {len(df)} rows from Excel file")
                print("\nFound columns:", ", ".join(str(c) if c is not None else 'None' for c in df.columns))
                
                # Process locations if tier columns exist
                if tier_columns:
                    print(f"\nFound {len(tier_columns)} Tier columns for location processing:", ", ".join(str(c) for c in tier_columns))
                    print("\n=== Starting Location Processing ===")
                    self.process_location_tiers(project_id, task_service, user_id, df, tier_columns)
                    print("\n=== Location Processing Complete ===")
                    print("\nContinuing with task attribute processing...")
                else:
                    print("No Tier columns found for location processing. Proceeding with task attribute processing only.")
                    
            except Exception as sheet_error:
                print(f"Error reading Excel file: {str(sheet_error)}")
                print("\nPlease ensure:")
                print("1. The file is a valid Excel file")
                print("2. The file contains a sheet named 'Sheet0'")
                print("3. The sheet contains an 'Opening ID' column (case insensitive)")
                return

            if df.empty:
                print("Error: No data found in the Excel file")
                return

            # Step 4: Get task type attributes
            print("\n=== Step 4: Retrieve Task Type Attributes ===")
            task_type_attributes = attribute_service.get_all_task_type_attributes_in_project(project_id)
            if not task_type_attributes:
                print("No task type attributes found in project")
                return

            print(f"Retrieved {len(task_type_attributes)} task type attributes")
            
            print("Creating task type attribute mapping...")
            # Create mapping of attribute names to IDs  
            task_type_attr_map = {attr['name']: attr['id'] for attr in task_type_attributes}
            print(f"Created task type attribute map with {len(task_type_attr_map)} attributes")
            
            # Check which columns match task type attributes
            print("Processing column matching...")
            # Filter out None columns and create mapping for safe access
            valid_df_columns = [c for c in df.columns if c is not None]
            excel_columns = set(str(c) for c in valid_df_columns) - {'Opening ID'}
            valid_columns = set(task_type_attr_map.keys())
            matched_columns = excel_columns & valid_columns
            unmatched_columns = excel_columns - valid_columns
            
            # Create a mapping from string column names back to actual DataFrame columns
            column_name_map = {str(c): c for c in valid_df_columns if str(c) != 'Opening ID'}
            print("Column matching complete.")

            print(f"\nFound {len(matched_columns)} matching task type attributes")
            if unmatched_columns:
                print(f"Found {len(unmatched_columns)} columns that don't match any task type attributes")
                print("Unmatched columns:")
                for col in sorted(unmatched_columns):
                    print(f"  - {col}")

            # Step 5: Get existing tasks
            print("\n=== Step 5: Retrieve Existing Tasks ===")
            existing_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            
            if not existing_tasks:
                print("No tasks found in project")
                return
            
            print(f"Retrieved {len(existing_tasks)} tasks from project")
            print("Creating task map...")
            
            # Build task map with detailed error handling - store lists to handle multiple tasks with same name
            task_map = {}
            none_name_tasks = []
            duplicate_names = {}
            
            for i, task in enumerate(existing_tasks):
                try:
                    task_name = task.get('name')
                    if task_name is None:
                        none_name_tasks.append((i, task.get('id', 'unknown_id')))
                        continue
                    
                    task_name_lower = task_name.lower()
                    if task_name_lower not in task_map:
                        task_map[task_name_lower] = []
                    else:
                        # Track duplicates for reporting
                        if task_name_lower not in duplicate_names:
                            duplicate_names[task_name_lower] = 1
                        duplicate_names[task_name_lower] += 1
                    
                    task_map[task_name_lower].append(task)
                except Exception as e:
                    print(f"Error processing task {i}: {e}")
                    print(f"Task data: {task}")
                    continue
            
            if none_name_tasks:
                print(f"Warning: Found {len(none_name_tasks)} tasks with None names:")
                for idx, task_id in none_name_tasks[:5]:  # Show first 5
                    print(f"  Task index {idx}, ID: {task_id}")
                if len(none_name_tasks) > 5:
                    print(f"  ... and {len(none_name_tasks) - 5} more")
            
            if duplicate_names:
                print(f"Found {len(duplicate_names)} opening IDs with multiple tasks:")
                for opening_id, count in list(duplicate_names.items())[:5]:  # Show first 5
                    print(f"  {opening_id}: {count} tasks")
                if len(duplicate_names) > 5:
                    print(f"  ... and {len(duplicate_names) - 5} more")
            
            total_tasks_mapped = sum(len(tasks) for tasks in task_map.values())
            print(f"Created task map with {len(task_map)} unique opening IDs covering {total_tasks_mapped} tasks")

            # Main verification and creation loop
            max_iterations = 5  # Prevent infinite loops
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                print(f"\n{'='*50}")
                print(f"ITERATION {iteration} - VERIFICATION AND CREATION")
                print(f"{'='*50}")
                
                # Step 6: Get existing task attributes for verification
                print("\n=== Step 6: Retrieve Current Task Attributes ===")
                existing_task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
                
                # Create lookup for existing attributes
                existing_attrs_map = {}  # {task_id: {attr_type_id: attribute_value}}
                for attr in existing_task_attributes:
                    task_id = attr['task_id']
                    attr_type_id = attr['task_type_attribute_id']
                    attr_value = (attr.get('text_value') or 
                                attr.get('number_value') or 
                                attr.get('uuid_value'))
                    
                    if task_id not in existing_attrs_map:
                        existing_attrs_map[task_id] = {}
                    existing_attrs_map[task_id][attr_type_id] = attr_value

                print(f"Retrieved {len(existing_task_attributes)} existing task attributes")

                # Step 7: Pre-verification - Identify missing/different attributes
                print("\n=== Step 7: Pre-Verification - Identify Missing Attributes ===")
                missing_attributes = []  # List of tuples: (task_id, opening_id, attr_name, attr_type_id, expected_value, current_value)
                unmatched_openings = set()
                tasks_with_data = set()
                
                print("Analyzing required vs existing attributes...")
                for index, row in tqdm(df.iterrows(), total=len(df), desc="Analyzing attributes"):
                    try:
                        opening_id = str(row['Opening ID']).strip()
                        if not opening_id:
                            continue
                        
                        # Safe lowercase conversion
                        opening_id_lower = opening_id.lower() if opening_id else ""
                        if not opening_id_lower or opening_id_lower not in task_map:
                            if opening_id.strip():  # Only track non-empty IDs
                                unmatched_openings.add(opening_id)
                            continue

                        tasks = task_map[opening_id_lower]  # Now this is a list of tasks
                        tasks_with_data.add(opening_id)
                    except Exception as e:
                        print(f"Error processing row {index}: {str(e)}")
                        print(f"Opening ID value: {repr(row.get('Opening ID', 'NOT_FOUND'))}")
                        continue
                    
                    # Check each matching column for all tasks with this opening ID
                    for column_name in matched_columns:
                        # Get the actual DataFrame column using our mapping
                        actual_column = column_name_map[column_name]
                        expected_value = str(row[actual_column]).strip() if pd.notna(row[actual_column]) else ""
                        if not expected_value:
                            continue
                        
                        attr_type_id = task_type_attr_map[column_name]
                        
                        # Check all tasks with this opening ID
                        for task in tasks:
                            task_id = task['id']
                            current_value = existing_attrs_map.get(task_id, {}).get(attr_type_id)
                            
                            # Check if attribute is missing or has different value
                            if current_value != expected_value:
                                missing_attributes.append((
                                    task_id,
                                    opening_id,
                                    column_name,
                                    attr_type_id,
                                    expected_value,
                                    current_value
                                ))

                # Display pre-verification results
                print(f"\nPre-verification Results:")
                print(f"  Tasks with data in Excel: {len(tasks_with_data)}")
                print(f"  Missing/Different attributes found: {len(missing_attributes)}")
                
                if unmatched_openings:
                    print(f"  Unmatched Opening IDs: {len(unmatched_openings)}")
                    if len(unmatched_openings) <= 10:
                        for opening in sorted(unmatched_openings):
                            print(f"    - {opening}")
                    else:
                        for opening in sorted(list(unmatched_openings)[:10]):
                            print(f"    - {opening}")
                        print(f"    ... and {len(unmatched_openings) - 10} more")

                # If no missing attributes, we're done
                if not missing_attributes:
                    print("\n✅ All attributes are up to date! No missing attributes found.")
                    break

                # Group missing attributes by task for better display
                missing_by_task = {}
                for task_id, opening_id, attr_name, attr_type_id, expected_value, current_value in missing_attributes:
                    if opening_id not in missing_by_task:
                        missing_by_task[opening_id] = []
                    status = "MISSING" if current_value is None else f"DIFFERENT (current: {current_value})"
                    missing_by_task[opening_id].append(f"  {attr_name}: {expected_value} ({status})")

                print(f"\nDetailed Missing Attributes Report:")
                print(f"Tasks requiring updates: {len(missing_by_task)}")
                
                # Show sample of missing attributes
                sample_tasks = list(missing_by_task.keys())[:10]
                for opening_id in sample_tasks:
                    print(f"\nTask {opening_id}:")
                    for attr_info in missing_by_task[opening_id]:
                        print(attr_info)
                
                if len(missing_by_task) > 10:
                    print(f"\n... and {len(missing_by_task) - 10} more tasks with missing attributes")

                # Step 8: User confirmation breakpoint
                print(f"\n{'='*50}")
                print("USER CONFIRMATION REQUIRED")
                print(f"{'='*50}")
                print(f"Found {len(missing_attributes)} missing/different attributes across {len(missing_by_task)} tasks")
                print("\nOptions:")
                print("1. Proceed with creating/updating these attributes")
                print("2. Cancel operation")
                print("3. Show detailed report of all missing attributes")
                
                while True:
                    choice = get_user_input("\nEnter your choice (1/2/3): ").strip()
                    
                    if choice == "3":
                        print(f"\n{'='*60}")
                        print("COMPLETE MISSING ATTRIBUTES REPORT")
                        print(f"{'='*60}")
                        for opening_id in sorted(missing_by_task.keys()):
                            print(f"\nTask {opening_id}:")
                            for attr_info in missing_by_task[opening_id]:
                                print(attr_info)
                        print(f"\nTotal: {len(missing_attributes)} missing/different attributes")
                        continue
                    elif choice == "2":
                        print("Operation cancelled by user.")
                        return
                    elif choice == "1":
                        break
                    else:
                        print("Invalid choice. Please enter 1, 2, or 3.")

                # Step 9: Create missing attributes
                print(f"\n=== Step 8: Creating Missing Attributes (Iteration {iteration}) ===")
                
                # Prepare operations for parallel execution
                attribute_operations = []
                for task_id, opening_id, attr_name, attr_type_id, expected_value, current_value in missing_attributes:
                    attribute_operations.append((
                        lambda task_id=task_id, attr_type_id=attr_type_id, 
                               attr_value=expected_value: attribute_service.create_a_task_attribute_in_task(
                            project_id=project_id,
                            task_id=task_id,
                            task_type_attribute_id=attr_type_id,
                            attribute_value=attr_value,
                            user_id=user_id
                        ),
                        task_id,
                        opening_id,
                        attr_name,
                        expected_value
                    ))

                if attribute_operations:
                    print(f"Executing {len(attribute_operations)} attribute operations in parallel...")
                    
                    # Create executor for parallel attribute creation
                    executor = RateLimitedExecutor()
                    
                    # Extract just the operation functions
                    operations = [op[0] for op in attribute_operations]
                    
                    # Execute in parallel
                    results = executor.execute_parallel(operations)
                    
                    # Process results
                    attributes_created = 0
                    failed_operations = []
                    
                    if isinstance(results, bool):
                        # If we got a single boolean result
                        if results:
                            attributes_created = len(attribute_operations)
                            print(f"✅ Successfully processed all {attributes_created} attribute operations")
                        else:
                            print("❌ Error: All attribute operations failed")
                            failed_operations = [(op[2], op[3], op[4]) for op in attribute_operations]
                    else:
                        # If we got individual results
                        for i, (result, (_, task_id, opening_id, attr_name, expected_value)) in enumerate(zip(results, attribute_operations)):
                            if result:
                                attributes_created += 1
                            else:
                                failed_operations.append((opening_id, attr_name, expected_value))
                    
                    print(f"\nIteration {iteration} Results:")
                    print(f"  Attributes successfully created: {attributes_created}")
                    print(f"  Attributes failed: {len(failed_operations)}")
                    
                    if failed_operations:
                        print(f"\nFailed operations (showing first 10):")
                        for opening_id, attr_name, value in failed_operations[:10]:
                            print(f"  - Task {opening_id}: {attr_name} = {value}")
                        if len(failed_operations) > 10:
                            print(f"  ... and {len(failed_operations) - 10} more")

                # Step 10: Post-verification
                print(f"\n=== Step 9: Post-Verification (Iteration {iteration}) ===")
                print("Retrieving updated task attributes for verification...")
                
                # Get fresh attribute data
                updated_task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
                
                # Create updated lookup
                updated_attrs_map = {}
                for attr in updated_task_attributes:
                    task_id = attr['task_id']
                    attr_type_id = attr['task_type_attribute_id']
                    attr_value = (attr.get('text_value') or 
                                attr.get('number_value') or 
                                attr.get('uuid_value'))
                    
                    if task_id not in updated_attrs_map:
                        updated_attrs_map[task_id] = {}
                    updated_attrs_map[task_id][attr_type_id] = attr_value

                # Check what's still missing
                still_missing = []
                for task_id, opening_id, attr_name, attr_type_id, expected_value, _ in missing_attributes:
                    current_value = updated_attrs_map.get(task_id, {}).get(attr_type_id)
                    if current_value != expected_value:
                        still_missing.append((task_id, opening_id, attr_name, attr_type_id, expected_value, current_value))

                print(f"Post-verification Results:")
                print(f"  Total attributes that were missing: {len(missing_attributes)}")
                print(f"  Attributes successfully created: {len(missing_attributes) - len(still_missing)}")
                print(f"  Attributes still missing: {len(still_missing)}")

                if not still_missing:
                    print(f"\n✅ SUCCESS: All attributes have been created successfully in iteration {iteration}!")
                    break
                else:
                    print(f"\n⚠️  {len(still_missing)} attributes are still missing. Will retry in next iteration.")
                    
                    # Show sample of still missing attributes
                    if len(still_missing) <= 20:
                        print("\nStill missing attributes:")
                        for task_id, opening_id, attr_name, attr_type_id, expected_value, current_value in still_missing:
                            status = "MISSING" if current_value is None else f"DIFFERENT (current: {current_value})"
                            print(f"  - Task {opening_id}: {attr_name} = {expected_value} ({status})")
                    else:
                        print(f"\nStill missing attributes (showing first 20):")
                        for task_id, opening_id, attr_name, attr_type_id, expected_value, current_value in still_missing[:20]:
                            status = "MISSING" if current_value is None else f"DIFFERENT (current: {current_value})"
                            print(f"  - Task {opening_id}: {attr_name} = {expected_value} ({status})")
                        print(f"  ... and {len(still_missing) - 20} more")

                    # Ask user if they want to continue
                    if iteration < max_iterations:
                        continue_choice = get_user_input(f"\nContinue with iteration {iteration + 1}? (y/n): ")
                        if continue_choice.lower() != 'y':
                            print("Operation stopped by user.")
                            break
                    else:
                        print(f"\nReached maximum iterations ({max_iterations}). Some attributes may still be missing.")
                        break

            # Final Summary 
            print(f"\n{'='*60}")
            print("FINAL SUMMARY")
            print(f"{'='*60}")
            print(f"Completed {iteration} iteration(s)")
            print(f"Excel file processed: {len(df)} rows")
            print(f"Tasks mapped from Excel: {len(tasks_with_data) if 'tasks_with_data' in locals() else 'Unknown'}")
            
            if unmatched_openings:
                print(f"Unmatched Opening IDs: {len(unmatched_openings)}")
            
            # Final verification
            final_task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
            final_attrs_map = {}
            for attr in final_task_attributes:
                task_id = attr['task_id']
                attr_type_id = attr['task_type_attribute_id']
                attr_value = (attr.get('text_value') or 
                            attr.get('number_value') or 
                            attr.get('uuid_value'))
                
                if task_id not in final_attrs_map:
                    final_attrs_map[task_id] = {}
                final_attrs_map[task_id][attr_type_id] = attr_value

            # Count final missing attributes
            final_missing = 0
            if 'tasks_with_data' in locals():
                for index, row in df.iterrows():
                    opening_id = str(row['Opening ID']).strip()
                    if not opening_id:
                        continue
                    
                    opening_id_lower = opening_id.lower()
                    if opening_id_lower not in task_map:
                        continue

                    tasks = task_map[opening_id_lower]
                    
                    for column_name in matched_columns:
                        actual_column = column_name_map[column_name]
                        expected_value = str(row[actual_column]).strip() if pd.notna(row[actual_column]) else ""
                        if not expected_value:
                            continue
                        
                        attr_type_id = task_type_attr_map[column_name]
                        
                        for task in tasks:
                            task_id = task['id']
                            current_value = final_attrs_map.get(task_id, {}).get(attr_type_id)
                            if current_value != expected_value:
                                final_missing += 1

            print(f"Final missing attributes: {final_missing}")
            
            if final_missing == 0:
                print("\n🎉 COMPLETE SUCCESS: All attributes have been created successfully!")
            else:
                print(f"\n⚠️  WARNING: {final_missing} attributes are still missing after {iteration} iterations.")
            
            print("\nOperation complete!")

        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further items will be processed.")

    @paginate_response()
    def get_statuses_for_project_id(self, project_id):
        """Get all statuses in a project with pagination support."""
        url = f"{self.project_base_url}/projects/{project_id}/statuses"
        return url

    def process_location_tiers(self, project_id, task_service, user_id=None, dataframe=None, tier_columns=None):
        """Process location tiers from an Excel file and update tasks with the appropriate location IDs.
        
        This function:
        1. Loads an Excel file containing Opening IDs and Tier 1-5 columns (if not provided)
        2. Extracts unique location paths
        3. Creates missing locations in Fieldwire
        4. Updates tasks with the deepest location ID for each Opening ID
        
        Args:
            project_id (str): Project ID
            task_service (TaskService): Task service instance
            user_id (int, optional): User ID for updates. If None, will prompt user.
            dataframe (pandas.DataFrame, optional): DataFrame containing Opening ID and Tier columns
            tier_columns (list, optional): List of column names for Tier 1-5 columns
        """
        try:
            # Step 1: Get user ID for task updates if not provided
            if user_id is None:
                print("\n=== Step 1: Get User ID ===")
                user_id = get_user_input("Enter user ID: ")
            
            # Use provided DataFrame or load from file
            df = dataframe
            if df is None:
                # Step 2: Get Excel file
                print("\n=== Step 2: Select Excel File ===")
                file_path = prompt_user_for_excel_file()
                if not file_path:
                    print("No file selected.")
                    return

                # Step 3: Load Excel Data
                print("\n=== Step 3: Parse Excel File ===")
                print("Loading Excel file...")
                try:
                    # Read the entire Sheet0
                    xl = pd.ExcelFile(file_path)
                    if "Sheet0" not in xl.sheet_names:
                        print("Error: Sheet 'Sheet0' not found in Excel file")
                        print("Available sheets:", xl.sheet_names)
                        return
                    
                    df = pd.read_excel(file_path, sheet_name="Sheet0", dtype=str)
                    
                    # Case-insensitive check for Opening ID column
                    opening_id_col = None
                    for col in df.columns:
                        if col is not None and str(col).lower() == 'opening id':
                            opening_id_col = col
                            break
                    
                    if not opening_id_col:
                        print("Error: Required column 'Opening ID' (case insensitive) not found in the Excel file")
                        print("Available columns:", ", ".join(str(c) if c is not None else 'None' for c in df.columns))
                        return
                    
                    # Rename the column to our expected format if it's different
                    if opening_id_col != 'Opening ID':
                        df = df.rename(columns={opening_id_col: 'Opening ID'})
                    
                    # Find tier columns if not provided
                    if tier_columns is None:
                        tier_columns = []
                        for i in range(1, 6):
                            tier_col = None
                            tier_name = f"Tier {i}"
                            for col in df.columns:
                                if col is not None and str(col).lower() == tier_name.lower():
                                    tier_col = col
                                    break
                            
                            if tier_col:
                                tier_columns.append(tier_col)
                            else:
                                print(f"Warning: Column '{tier_name}' not found. Location hierarchy may be incomplete.")
                        
                        if not tier_columns:
                            print("Error: No Tier columns (Tier 1, Tier 2, etc.) found in the Excel file")
                            return
                        
                    print(f"Found {len(tier_columns)} Tier columns:", ", ".join(str(c) for c in tier_columns))
                        
                except Exception as sheet_error:
                    print(f"Error reading Excel file: {str(sheet_error)}")
                    print("\nPlease ensure:")
                    print("1. The file is a valid Excel file")
                    print("2. The file contains a sheet named 'Sheet0'")
                    print("3. The sheet contains an 'Opening ID' column and at least one Tier column")
                    return

                if df.empty:
                    print("Error: No data found in the Excel file")
                    return

                print(f"Successfully loaded {len(df)} rows from Excel file")
            
            # Step 4: Extract unique location paths
            print("\n=== Step 4: Extract Unique Location Paths ===")
            unique_paths = set()
            opening_id_to_path = {}
            
            for index, row in tqdm(df.iterrows(), total=len(df), desc="Processing rows"):
                opening_id = str(row['Opening ID']).strip()
                if not opening_id:
                    continue
                
                # Extract path from tier columns
                path = []
                for col in tier_columns:
                    value = str(row[col]).strip() if pd.notna(row[col]) else ""
                    path.append(value)
                
                # Remove empty tiers from the end
                while path and not path[-1]:
                    path.pop()
                
                # Skip if path is empty
                if not path:
                    continue
                
                # Add to unique paths and map to opening ID
                path_tuple = tuple(path)  # Convert to tuple for set
                unique_paths.add(path_tuple)
                opening_id_to_path[opening_id] = path_tuple
            
            if not unique_paths:
                print("Error: No valid location paths found in the Excel file")
                return
            
            print(f"Extracted {len(unique_paths)} unique location paths")
            print(f"Mapped {len(opening_id_to_path)} opening IDs to location paths")
            
            # Step 5: Get existing locations
            print("\n=== Step 5: Retrieve Existing Locations ===")
            existing_locations = task_service.get_all_locations_in_project(project_id)
            if existing_locations is None:
                print("Failed to retrieve existing locations from project")
                return
            
            # Debug: Print detailed information about the response format
            print("\nDEBUG - Response from get_all_locations_in_project:")
            print(f"Response type: {type(existing_locations)}")
            
            if isinstance(existing_locations, list):
                print(f"Response is a list with {len(existing_locations)} items")
                if existing_locations and len(existing_locations) > 0:
                    print("First item type:", type(existing_locations[0]))
                    print("First item keys:", list(existing_locations[0].keys()) if isinstance(existing_locations[0], dict) else "Not a dict")
                    print("First item:", existing_locations[0])
            elif isinstance(existing_locations, dict):
                print("Response is a dictionary with keys:", list(existing_locations.keys()))
                if 'results' in existing_locations:
                    results = existing_locations.get('results', [])
                    print(f"'results' key contains a list with {len(results)} items")
                    if results and len(results) > 0:
                        print("First result item type:", type(results[0]))
                        print("First result keys:", list(results[0].keys()) if isinstance(results[0], dict) else "Not a dict")
                print("First 100 characters of response:", str(existing_locations)[:100])
            else:
                print("Response is neither a list nor a dictionary")
                print("First 100 characters of response:", str(existing_locations)[:100])
            
            # Process the locations response
            if isinstance(existing_locations, list):
                all_locations = existing_locations
            elif isinstance(existing_locations, dict) and 'results' in existing_locations:
                all_locations = existing_locations.get('results', [])
            else:
                print("Error: Unexpected response format from get_all_locations_in_project")
                print("Cannot continue without properly formatted location data")
                return
            
            print(f"Retrieved {len(all_locations)} existing locations")
            
            # Debug: Print all existing locations
            print("\nDEBUG - All existing locations:")
            for loc in all_locations:
                print(f"  ID: {loc.get('id')}, Name: {loc.get('name')}, Parent ID: {loc.get('location_id')}")
            
            # Build location map by path
            location_map = {}  # Map path to location ID
            
            # First, build parent-child map
            location_by_id = {loc['id']: loc for loc in all_locations if 'id' in loc}
            children_map = {}  # Map parent ID to list of child locations
            
            for loc in all_locations:
                if 'id' not in loc:
                    continue
                
                parent_id = loc.get('location_id')
                if parent_id:
                    if parent_id not in children_map:
                        children_map[parent_id] = []
                    children_map[parent_id].append(loc)
                else:
                    # Top-level location (Tier 1)
                    if None not in children_map:
                        children_map[None] = []
                    children_map[None].append(loc)
            
            # Helper function to recursively build paths
            def build_paths(loc_id, current_path=None):
                if current_path is None:
                    current_path = []
                
                loc = location_by_id.get(loc_id)
                if not loc:
                    return
                
                # Get the name of this location
                loc_name = loc.get('name', '')
                if not loc_name:
                    return
                
                # Append this location's name to the path
                new_path = current_path + [loc_name]
                path_tuple = tuple(new_path)
                location_map[path_tuple] = loc_id
                
                # Process children
                if loc_id in children_map:
                    for child in children_map[loc_id]:
                        build_paths(child['id'], new_path)
            
            # Build paths for top-level locations
            for loc in children_map.get(None, []):
                build_paths(loc['id'], [])
            
            print(f"Built paths for {len(location_map)} existing locations")
            
            # Debug: Print all paths in location map
            print("\nDEBUG - All paths in location map:")
            for path, loc_id in location_map.items():
                print(f"  {' > '.join(path)} -> {loc_id}")
            
            # Step 6: Determine missing paths
            print("\n=== Step 6: Determine Missing Paths ===")
            missing_paths = []
            for path in unique_paths:
                if path not in location_map:
                    missing_paths.append(list(path))  # Convert tuple back to list
            
            print(f"Found {len(missing_paths)} missing location paths")
            
            # Debug: Print all unique paths from Excel
            print("\nDEBUG - All unique paths from Excel:")
            for path in unique_paths:
                path_exists = "EXISTS" if path in location_map else "MISSING"
                print(f"  {' > '.join(path)} - {path_exists}")
            
            # Debug: Print all missing paths
            print("\nDEBUG - All missing paths:")
            for path in missing_paths:
                print(f"  {' > '.join(path)}")
            
            # Step 7: Create missing locations if needed
            created_locations = []
            if missing_paths:
                print("\n=== Step 7: Create Missing Locations ===")
                print(f"Creating {len(missing_paths)} new location paths...")
                
                # Show the missing paths we're about to create
                print("Paths to be created:")
                for path in missing_paths[:min(5, len(missing_paths))]:
                    print(f"  {' > '.join(path)}")
                if len(missing_paths) > 5:
                    print(f"  ... and {len(missing_paths) - 5} more")
                
                # Batch create locations with a maximum of 500 per request
                batch_size = 500
                
                for i in range(0, len(missing_paths), batch_size):
                    batch = missing_paths[i:i+batch_size]
                    print(f"Creating batch {i//batch_size + 1} of {(len(missing_paths) + batch_size - 1) // batch_size} ({len(batch)} paths)...")
                    
                    result = task_service.batch_create_locations(project_id, batch)
                    if result and isinstance(result, list):
                        created_locations.extend(result)
                        print(f"Successfully created {len(result)} new locations")
                    else:
                        print("Error: Failed to create locations")
                        print("Cannot continue without all required locations")
                        return
                
                print(f"Successfully created {len(created_locations)} new locations")
                
                # Update location map with newly created locations
                for loc in created_locations:
                    # We need to rebuild the path for each location
                    loc_id = loc['id']
                    loc_name = loc['name']
                    parent_id = loc.get('location_id')
                    
                    # Find the path
                    path = [loc_name]
                    current_parent_id = parent_id
                    
                    while current_parent_id:
                        parent_loc = next((l for l in created_locations if l['id'] == current_parent_id), None)
                        if not parent_loc:
                            parent_loc = location_by_id.get(current_parent_id)
                            
                        if parent_loc and 'name' in parent_loc:
                            path.insert(0, parent_loc['name'])
                            current_parent_id = parent_loc.get('location_id')
                        else:
                            break
                    
                    path_tuple = tuple(path)
                    location_map[path_tuple] = loc_id
                
                print(f"Updated location map, now contains {len(location_map)} paths")
                
                # Verify all paths are now available
                remaining_missing = []
                for path in unique_paths:
                    if path not in location_map:
                        remaining_missing.append(path)
                
                if remaining_missing:
                    print(f"Error: {len(remaining_missing)} paths are still missing after location creation")
                    print("Cannot continue without all required locations")
                    return
            
            # Step 8: Get all tasks
            print("\n=== Step 8: Retrieve Tasks ===")
            existing_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            if not existing_tasks:
                print("No tasks found in project")
                return
            
            print(f"Retrieved {len(existing_tasks)} tasks from project")
            
            # Build task map
            task_map = {}
            for task in existing_tasks:
                task_name = task.get('name', '').strip()
                if task_name:
                    task_map[task_name.lower()] = task
            
            print(f"Built task map with {len(task_map)} tasks")
            
            # Step 9: Update tasks with location IDs
            print("\n=== Step 9: Update Tasks with Location IDs ===")
            updated_tasks = 0
            skipped_tasks = 0
            failed_tasks = 0
            
            # Group opening IDs by location path for batch processing
            opening_ids_by_path = {}
            for opening_id, path_tuple in opening_id_to_path.items():
                if path_tuple not in opening_ids_by_path:
                    opening_ids_by_path[path_tuple] = []
                opening_ids_by_path[path_tuple].append(opening_id)
            
            # Create executor for parallel task updates
            executor = RateLimitedExecutor()
            
            # Prepare operations
            all_update_operations = []
            
            # Process each path
            for path_tuple, opening_ids in opening_ids_by_path.items():
                # Get location ID for this path
                location_id = location_map.get(path_tuple)
                if not location_id:
                    print(f"Warning: No location ID found for path {' > '.join(path_tuple)}")
                    skipped_tasks += len(opening_ids)
                    continue
                
                # Prepare update operations for all tasks with this location
                for opening_id in opening_ids:
                    task = task_map.get(opening_id.lower())
                    if not task:
                        print(f"Warning: No task found for opening ID {opening_id}")
                        skipped_tasks += 1
                        continue
                    
                    # Skip if task already has the correct location ID
                    if task.get('location_id') == location_id:
                        print(f"Task {opening_id} already has correct location ID {location_id}")
                        skipped_tasks += 1
                        continue
                    
                    # Add update operation
                    def update_task_location(task_id=task["id"], location_id=location_id):
                        return task_service.update_task_with_location(
                            project_id=project_id,
                            task_id=task_id,
                            location_id=location_id,
                            user_id=user_id
                        )
                    
                    all_update_operations.append((update_task_location, opening_id))
            
            # Execute operations in parallel with progress reporting
            if all_update_operations:
                print(f"Updating {len(all_update_operations)} tasks with location IDs...")
                
                # Extract just the operation functions
                operations = [op[0] for op in all_update_operations]
                
                # Execute in parallel
                results = executor.execute_parallel(operations)
                
                # Process results
                if isinstance(results, bool):
                    # If we got a single boolean result
                    if results:
                        updated_tasks = len(all_update_operations)
                    else:
                        failed_tasks = len(all_update_operations)
                else:
                    # If we got individual results
                    for (result, (_, opening_id)) in zip(results, all_update_operations):
                        if result:
                            updated_tasks += 1
                        else:
                            print(f"Error: Failed to update task for opening ID {opening_id}")
                            failed_tasks += 1
            else:
                print("No task updates needed.")
            
            # Final summary
            print("\n=== Summary ===")
            print(f"Total opening IDs processed: {len(opening_id_to_path)}")
            print(f"Total unique location paths: {len(unique_paths)}")
            print(f"New locations created: {len(created_locations)}")
            print(f"Tasks updated: {updated_tasks}")
            print(f"Tasks skipped: {skipped_tasks}")
            print(f"Tasks failed: {failed_tasks}")
            print("\nOperation complete!")

        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further items will be processed.")

    def sort_test_get_check_items_from_task(self, project_id, task_service, attribute_service):
        """Test the sorting order of checklist items as received from the API.
        
        This function allows the user to see checklist items for a specific task
        in the exact order they are returned from the API to verify if they match
        the visual order in the browser interface.
        """
        try:
            print("\n=== SORT TEST: Get Check Items From Task ===")
            
            # Get all tasks in the project
            print("Retrieving all tasks from the project...")
            all_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            if not all_tasks:
                print("No tasks found in the project.")
                return
            
            print(f"Retrieved {len(all_tasks)} tasks.")
            
            # Get all checklist items in the project
            print("Retrieving all checklist items from the project...")
            all_check_items = attribute_service.get_all_task_check_items_in_project(project_id)
            if not all_check_items:
                print("No checklist items found in the project.")
                return
                
            print(f"Retrieved {len(all_check_items)} checklist items.")
            
            # Create task name to task ID mapping
            task_map = {task['name']: task['id'] for task in all_tasks if 'name' in task and 'id' in task}
            
            # Create mapping of task ID to checklist items
            task_check_items = {}
            for item in all_check_items:
                task_id = item['task_id']
                if task_id not in task_check_items:
                    task_check_items[task_id] = []
                task_check_items[task_id].append(item)
            
            # Loop to allow checking multiple tasks
            while True:
                # Prompt user for task name
                task_name = get_user_input("\nEnter the exact name of the task to check (or press Enter to exit): ")
                if not task_name:
                    print("Exiting sort test.")
                    break
                
                # Check if task exists
                if task_name not in task_map:
                    print(f"Task with name '{task_name}' not found. Please enter an exact match.")
                    continue
                
                # Get task ID and checklist items
                task_id = task_map[task_name]
                items = task_check_items.get(task_id, [])
                
                if not items:
                    print(f"No checklist items found for task '{task_name}'.")
                    continue
                
                # Display checklist items in the order received from the API
                print(f"\nFound {len(items)} checklist items for task '{task_name}':")
                print("\nChecklist items in API response order:")
                print("="*50)
                for i, item in enumerate(items, 1):
                    print(f"{i}. {item['name']}")
                print("="*50)
                
                # Ask if user wants to check another task
                continue_check = get_user_input("\nCheck another task? (y/n): ")
                if continue_check.lower() != 'y':
                    print("Exiting sort test.")
                    break
                
        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further items will be processed.")

    def generate_UCA_sheet(self, project_id, task_service, attribute_service):
        """Generate UCA spreadsheet with task data, attributes, and hardware line checklist items.
        
        Creates an Excel file with:
        - Each row representing one UCA task
        - First column: Opening number (UCA prefix removed)
        - Next columns: Task attribute values
        - Hardware type columns: Original hardware line checklist item names
        """
        try:
            print("\n=== Generating UCA Spreadsheet ===")
            
            # Step 1: Get all tasks and filter UCA tasks
            print("Retrieving UCA tasks...")
            all_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            if not all_tasks:
                print("No tasks found in project")
                return
            
            uca_tasks = [task for task in all_tasks if task['name'].startswith('UCA ')]
            if not uca_tasks:
                print("No UCA tasks found in project")
                return
            
            print(f"Found {len(uca_tasks)} UCA tasks")
            
            # Step 2: Get task attributes and checklist items
            print("Retrieving task attributes and checklist items...")
            all_task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
            all_checklist_items = attribute_service.get_all_task_check_items_in_project(project_id)
            
            # Get task type attributes for mapping
            task_type_attributes = attribute_service.get_all_task_type_attributes_in_project(project_id)
            task_type_attr_map = {attr['id']: attr['name'] for attr in task_type_attributes}
            
            # Step 3: Organize data by UCA task
            uca_task_data = {}
            uca_task_ids = {task['id'] for task in uca_tasks}
            
            # Group attributes by task
            task_attributes_map = {}
            for attr in all_task_attributes:
                if attr['task_id'] in uca_task_ids:
                    task_id = attr['task_id']
                    if task_id not in task_attributes_map:
                        task_attributes_map[task_id] = {}
                    
                    attr_name = task_type_attr_map.get(attr['task_type_attribute_id'], 'Unknown')
                    attr_value = (attr.get('text_value') or 
                                attr.get('number_value') or 
                                attr.get('uuid_value') or '')
                    task_attributes_map[task_id][attr_name] = attr_value
            
            # Group checklist items by task
            task_checklist_map = {}
            for item in all_checklist_items:
                if item['task_id'] in uca_task_ids:
                    task_id = item['task_id']
                    if task_id not in task_checklist_map:
                        task_checklist_map[task_id] = []
                    task_checklist_map[task_id].append(item)
            
            # Step 4: Helper function to check conditions and identify hardware lines
            def uca_check_conditions(text, conditions):
                """Check if text matches any UCA hardware filter condition sets."""
                text = text.lower()
                for condition_set in conditions:
                    if 'any' in condition_set:
                        any_match = any(term.lower() in text for term in condition_set['any'])
                        if not any_match:
                            continue
                    if 'all' in condition_set:
                        all_match = all(term.lower() in text for term in condition_set['all'])
                        if not all_match:
                            continue
                    if 'none' in condition_set:
                        none_match = not any(term.lower() in text for term in condition_set['none'])
                        if not none_match:
                            continue
                    return True
                return False
            
            def is_hardware_line(item_name):
                """Determine if checklist item is an original hardware line (not additional item)."""
                for hardware_type, filter_def in HARDWARE_FILTERS.items():
                    exclusions = filter_def.get('exclusions', None)
                    if uca_check_conditions(item_name, filter_def['conditions'], exclusions):
                        # Check if this item is in the create_items list (additional item)
                        create_items = filter_def.get('create_items', [])
                        if item_name in create_items:
                            return False, None  # It's an additional item, exclude it
                        else:
                            return True, hardware_type  # It's a hardware line, include it
                return False, None  # Doesn't match any hardware type
            
            # Step 5: Process each UCA task
            print("Processing UCA task data...")
            
            for task in uca_tasks:
                task_id = task['id']
                task_name = task['name']
                opening_number = task_name[4:]  # Remove 'UCA ' prefix
                
                # Get attributes for this task
                attributes = task_attributes_map.get(task_id, {})
                
                # Process checklist items to find hardware lines
                hardware_items = {}  # {hardware_type: item_name}
                checklist_items = task_checklist_map.get(task_id, [])
                
                for item in checklist_items:
                    is_hw_line, hw_type = is_hardware_line(item['name'])
                    if is_hw_line and hw_type:
                        # For ambiguous matches, use first match only
                        if hw_type not in hardware_items:
                            hardware_items[hw_type] = item['name']
                
                uca_task_data[opening_number] = {
                    'task_name': task_name,
                    'attributes': attributes,
                    'hardware_items': hardware_items
                }
            
            if not uca_task_data:
                print("No UCA task data to export")
                return
            
            # Step 6: Determine which columns to include (only those with values)
            print("Determining columns with data...")
            attributes_with_values = set()
            hardware_types_with_values = set()
            
            for data in uca_task_data.values():
                # Check which attributes have non-empty values
                for attr_name, attr_value in data['attributes'].items():
                    if attr_value and str(attr_value).strip():  # Has non-empty value
                        attributes_with_values.add(attr_name)
                
                # Check which hardware types have items
                for hw_type in data['hardware_items'].keys():
                    hardware_types_with_values.add(hw_type)
            
            print(f"Found {len(attributes_with_values)} attributes with values")
            print(f"Found {len(hardware_types_with_values)} hardware types with items")
            
            # Step 7: Create Excel spreadsheet
            print("Creating Excel spreadsheet...")
            import pandas as pd
            from utils.export import get_export_file_path
            
            # Build column headers (only for columns that will have values)
            columns = ['Opening Number']
            
            # Add attribute columns (only those with values, sorted for consistency)
            sorted_attributes = sorted(attributes_with_values)
            columns.extend(sorted_attributes)
            
            # Add hardware type columns (only those with items, sorted for consistency)
            sorted_hardware_types = sorted(hardware_types_with_values)
            columns.extend(sorted_hardware_types)
            
            # Build data rows
            rows = []
            for opening_number in sorted(uca_task_data.keys()):
                data = uca_task_data[opening_number]
                row = [opening_number]
                
                # Add attribute values
                for attr_name in sorted_attributes:
                    row.append(data['attributes'].get(attr_name, ''))
                
                # Add hardware items
                for hw_type in sorted_hardware_types:
                    row.append(data['hardware_items'].get(hw_type, ''))
                
                rows.append(row)
            
            # Create DataFrame
            df = pd.DataFrame(rows, columns=columns)
            
            # Step 8: Export to Excel file
            file_path = get_export_file_path("UCA_Tasks_Export", "xlsx")
            if not file_path:
                print("Export cancelled by user")
                return
            
            print(f"Saving to: {file_path}")
            
            # Create Excel writer with formatting
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='UCA Tasks', index=False)
                
                # Get the workbook and worksheet
                workbook = writer.book
                worksheet = writer.sheets['UCA Tasks']
                
                # Auto-adjust column widths
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    
                    # Set minimum width of 10, maximum of 50
                    adjusted_width = min(max(max_length + 2, 10), 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
                
                # Format header row
                from openpyxl.styles import Font, PatternFill
                header_font = Font(bold=True)
                header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                
                for cell in worksheet[1]:
                    cell.font = header_font
                    cell.fill = header_fill
            
            # Step 9: Summary
            print(f"\n=== Export Complete ===")
            print(f"File saved: {file_path}")
            print(f"Total UCA tasks exported: {len(rows)}")
            print(f"Total attributes: {len(sorted_attributes)}")
            print(f"Total hardware types: {len(sorted_hardware_types)}")
            
            if sorted_attributes:
                print(f"\nAttribute columns: {', '.join(sorted_attributes)}")
            
            if sorted_hardware_types:
                print(f"\nHardware type columns: {', '.join(sorted_hardware_types)}")
            
            print("\nUCA spreadsheet generation complete!")
            
        except Exception as e:
            print(f"\nError: Failed to generate UCA spreadsheet: {str(e)}")
            print("Operation cancelled.")
