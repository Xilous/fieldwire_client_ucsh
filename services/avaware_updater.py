"""Avaware Hardware Schedule Updater for Fieldwire."""

from core.auth import AuthManager
from utils.decorators import update_last_response, paginate_response
from utils.input_helpers import get_user_input, prompt_user_for_xml_file
from processors.xml_processor import parse_xml_file, parse_hardware_items
from config.constants import HARDWARE_FILTERS
from utils.rate_limiter import RateLimitedExecutor
import re
import time

class AvawareUpdater(AuthManager):
    """Service for updating hardware schedules on Fieldwire."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.NEW_PREFIX = "NEW "
        self.DELETED_PREFIX = "DELETED "
    
    def update_hardware_from_xml(self, project_id, user_id, task_service, attribute_service):
        """Update hardware schedules from XML file.
        
        This process:
        1. Gets the existing tasks and checklist items from Fieldwire
        2. Parses the new hardware schedule XML
        3. Compares the XML data with existing Fieldwire data
        4. Updates task names and checklist items with NEW/DELETED prefixes
        5. Propagates attribute changes from UCI to other tasks
        6. Sorts checklist items to match the order in the XML file
        """
        try:
            # Step 1: Get XML file
            print("\n=== Step 1: Select XML File ===")
            file_path = prompt_user_for_xml_file()
            if not file_path:
                print("No file selected. Aborting.")
                return
            
            # Step 2: Parse the XML file
            print("\n=== Step 2: Parse XML File ===")
            new_openings = parse_xml_file(file_path)
            new_hardware_items = parse_hardware_items(file_path)
            
            print(f"Parsed {len(new_openings)} openings and {len(new_hardware_items)} hardware items from XML file.")
            
            if not new_openings or not new_hardware_items:
                print("No valid data found in XML file. Aborting.")
                return
            
            # Create hardware by group map
            new_hardware_by_group = self._create_hardware_by_group(new_hardware_items)
            
            # Step 3: Get existing Fieldwire data
            print("\n=== Step 3: Retrieve Fieldwire Data ===")
            
            # Get tasks
            existing_tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            print(f"Retrieved {len(existing_tasks)} tasks from Fieldwire.")
            
            # Get task attributes
            task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
            print(f"Retrieved {len(task_attributes)} task attributes from Fieldwire.")
            
            # Get task type attributes
            task_type_attributes = attribute_service.get_all_task_type_attributes_in_project(project_id)
            print(f"Retrieved {len(task_type_attributes)} task type attributes from Fieldwire.")
            
            # Get checklist items
            checklist_items = attribute_service.get_all_task_check_items_in_project(project_id)
            print(f"Retrieved {len(checklist_items)} checklist items from Fieldwire.")
            
            # Step 4: Organize the data
            print("\n=== Step 4: Analyzing Data ===")
            
            # Create lookup maps
            task_type_attribute_map = {}
            for attr in task_type_attributes:
                task_type_attribute_map[attr['id']] = attr['name']
                if attr['name'] == 'HardwareGroup':
                    hardware_group_attribute_id = attr['id']
            
            # Organize tasks by prefix
            task_maps = self._create_task_maps(existing_tasks)
            uci_tasks, uca_tasks, fc_tasks, def_tasks = task_maps
            
            # Group checklist items by task
            checklist_items_by_task = {}
            for item in checklist_items:
                task_id = item['task_id']
                if task_id not in checklist_items_by_task:
                    checklist_items_by_task[task_id] = []
                checklist_items_by_task[task_id].append(item)
            
            # Group attributes by task
            attributes_by_task = {}
            for attr in task_attributes:
                task_id = attr['task_id']
                if task_id not in attributes_by_task:
                    attributes_by_task[task_id] = {}
                
                attr_type_id = attr['task_type_attribute_id']
                attr_name = task_type_attribute_map.get(attr_type_id)
                if attr_name:
                    attr_value = attr.get('text_value') or attr.get('number_value') or attr.get('uuid_value')
                    attributes_by_task[task_id][attr_name] = {
                        'value': attr_value,
                        'id': attr['id'],
                        'type_id': attr_type_id
                    } 
            
            # Step 5: Compare the data and generate change plan
            print("\n=== Step 5: Analyzing Changes ===")
            
            changes = self._compare_hardware_schedules(
                new_openings=new_openings,
                new_hardware_by_group=new_hardware_by_group,
                uci_tasks=uci_tasks,
                uca_tasks=uca_tasks,
                fc_tasks=fc_tasks,
                def_tasks=def_tasks,
                attributes_by_task=attributes_by_task,
                checklist_items_by_task=checklist_items_by_task,
                task_type_attribute_map=task_type_attribute_map
            )
            
            # Step 6: Display summary and confirm
            print("\n=== Step 6: Change Summary ===")
            self._display_changes_summary(changes)
            
            proceed = get_user_input("\nProceed with updating Fieldwire? (y/n): ")
            if proceed.lower() != 'y':
                print("Operation cancelled.")
                return
            
            # Step 7: Apply changes
            print("\n=== Step 7: Applying Changes ===")
            self._apply_changes(
                project_id=project_id,
                user_id=user_id,
                changes=changes,
                task_service=task_service,
                attribute_service=attribute_service
            )
            
            # Ask for confirmation before sorting
            sort_confirmation = get_user_input("\nProceed with sorting checklist items? (y/n): ")
            if sort_confirmation.lower() != 'y':
                print("Sorting skipped. Hardware schedule update complete!")
                return
            
            # Step 8: Sort checklist items to match XML order
            print("\n=== Step 8: Sorting Checklist Items ===")
            self._sort_checklist_items(
                project_id=project_id,
                user_id=user_id,
                new_hardware_by_group=new_hardware_by_group,
                task_service=task_service,
                attribute_service=attribute_service
            )
            
            print("\nHardware schedule update complete!")
            
        except Exception as e:
            print(f"\nError: Process stopped due to an error: {str(e)}")
            print("No further updates will be processed.")
    
    def _create_hardware_by_group(self, hardware_items):
        """Create a map of hardware items by group name."""
        hardware_by_group = {}
        
        for item in hardware_items:
            group_name = item["GroupName"]
            if not group_name:
                continue
                
            if group_name not in hardware_by_group:
                hardware_by_group[group_name] = []
            
            # Create a checklist item name from the hardware item
            name_parts = []
            for field in ['QuantityOffDoor', 'QuantityActive', 'ShortCode', 
                          'SubCategory', 'ProductCode', 'Finish_ANSI']:
                if item[field]:
                    name_parts.append(f"({item[field]})")
            
            name = " ".join(name_parts)
            if name:
                hardware_by_group[group_name].append(name)
        
        return hardware_by_group
    
    def _create_task_maps(self, tasks):
        """Create task maps for different task types."""
        uci_tasks = {}  # {original_number: task}
        uca_tasks = {}  # {original_number: task}
        fc_tasks = {}   # {original_number: task}
        def_tasks = {}  # {original_number: task}
        
        for task in tasks:
            name = task['name']
            if not name:
                continue
            
            # Skip tasks that are already marked as deleted (unless we want to handle them)
            # if name.startswith(self.DELETED_PREFIX):
            #     continue
                
            # Extract the opening number based on prefix
            if name.startswith("UCI "):
                original_number = name[4:].strip()  # Remove "UCI " prefix
                uci_tasks[original_number] = task
            elif name.startswith("UCA "):
                original_number = name[4:].strip()  # Remove "UCA " prefix
                uca_tasks[original_number] = task
            elif name.startswith("FC "):
                original_number = name[3:].strip()  # Remove "FC " prefix
                fc_tasks[original_number] = task
            elif name.startswith("DEF "):
                original_number = name[4:].strip()  # Remove "DEF " prefix
                def_tasks[original_number] = task
            
        return uci_tasks, uca_tasks, fc_tasks, def_tasks 

    def _compare_hardware_schedules(self, new_openings, new_hardware_by_group, uci_tasks, uca_tasks, 
                                  fc_tasks, def_tasks, attributes_by_task, checklist_items_by_task,
                                  task_type_attribute_map):
        """Compare hardware schedules and generate change list."""
        changes = {
            'new_openings': [],         # Openings in XML not in Fieldwire
            'deleted_openings': [],     # Openings in Fieldwire not in XML
            'updated_openings': [],     # Openings in both with changes
            'task_name_changes': [],    # Tasks that need name changes
            'attribute_changes': [],    # Task attribute changes
            'checklist_changes': []     # Checklist item changes
        }
        
        # Step 1: Find new openings (in XML but not in Fieldwire)
        xml_opening_numbers = {opening['Number'] for opening in new_openings}
        fw_opening_numbers = set(uci_tasks.keys())
        
        # New openings that don't exist in Fieldwire
        new_opening_numbers = xml_opening_numbers - fw_opening_numbers
        for opening_number in new_opening_numbers:
            opening = next((o for o in new_openings if o['Number'] == opening_number), None)
            if opening:
                changes['new_openings'].append({
                    'number': opening_number,
                    'opening': opening
                })
        
        # Step 2: Find deleted openings (in Fieldwire but not in XML)
        deleted_opening_numbers = fw_opening_numbers - xml_opening_numbers
        for opening_number in deleted_opening_numbers:
            # Check if any of the task names for this opening already start with DELETED
            uci_task = uci_tasks.get(opening_number)
            uca_task = uca_tasks.get(opening_number)
            fc_task = fc_tasks.get(opening_number)
            def_task = def_tasks.get(opening_number)
            
            if uci_task and not uci_task['name'].startswith(self.DELETED_PREFIX):
                changes['task_name_changes'].append({
                    'task_id': uci_task['id'],
                    'old_name': uci_task['name'],
                    'new_name': f"{self.DELETED_PREFIX}{uci_task['name']}",
                    'reason': 'opening_deleted'
                })
            
            if uca_task and not uca_task['name'].startswith(self.DELETED_PREFIX):
                changes['task_name_changes'].append({
                    'task_id': uca_task['id'],
                    'old_name': uca_task['name'],
                    'new_name': f"{self.DELETED_PREFIX}{uca_task['name']}",
                    'reason': 'opening_deleted'
                })
            
            if fc_task and not fc_task['name'].startswith(self.DELETED_PREFIX):
                changes['task_name_changes'].append({
                    'task_id': fc_task['id'],
                    'old_name': fc_task['name'],
                    'new_name': f"{self.DELETED_PREFIX}{fc_task['name']}",
                    'reason': 'opening_deleted'
                })
            
            if def_task and not def_task['name'].startswith(self.DELETED_PREFIX):
                changes['task_name_changes'].append({
                    'task_id': def_task['id'],
                    'old_name': def_task['name'],
                    'new_name': f"{self.DELETED_PREFIX}{def_task['name']}",
                    'reason': 'opening_deleted'
                })
            
            # Mark checklist items as deleted if they're not already
            if uci_task and uci_task['id'] in checklist_items_by_task:
                for item in checklist_items_by_task[uci_task['id']]:
                    if not item['name'].startswith(self.DELETED_PREFIX):
                        changes['checklist_changes'].append({
                            'task_id': uci_task['id'],
                            'item_id': item['id'],
                            'old_name': item['name'],
                            'new_name': f"{self.DELETED_PREFIX}{item['name']}",
                            'reason': 'opening_deleted'
                        })
            
            if uca_task and uca_task['id'] in checklist_items_by_task:
                for item in checklist_items_by_task[uca_task['id']]:
                    if not item['name'].startswith(self.DELETED_PREFIX):
                        changes['checklist_changes'].append({
                            'task_id': uca_task['id'],
                            'item_id': item['id'],
                            'old_name': item['name'],
                            'new_name': f"{self.DELETED_PREFIX}{item['name']}",
                            'reason': 'opening_deleted'
                        })
            
            changes['deleted_openings'].append({
                'number': opening_number,
                'uci_task': uci_task,
                'uca_task': uca_task,
                'fc_task': fc_task,
                'def_task': def_task
            })
        
        # Step 3: Process existing openings for changes
        common_opening_numbers = xml_opening_numbers.intersection(fw_opening_numbers)
        
        for opening_number in common_opening_numbers:
            # Get new opening data from XML
            new_opening = next((o for o in new_openings if o['Number'] == opening_number), None)
            if not new_opening:
                continue
            
            # Get existing tasks for this opening
            uci_task = uci_tasks.get(opening_number)
            if not uci_task:
                continue  # Should not happen since we're working with common openings
            
            uca_task = uca_tasks.get(opening_number)
            fc_task = fc_tasks.get(opening_number)
            def_task = def_tasks.get(opening_number)
            
            opening_changes = {
                'number': opening_number,
                'uci_task': uci_task,
                'uca_task': uca_task,
                'fc_task': fc_task,
                'def_task': def_task,
                'attribute_changes': [],
                'hardware_changes': []
            }
            
            # Compare attributes
            self._compare_attributes(
                opening_number=opening_number,
                new_opening=new_opening,
                uci_task=uci_task,
                uca_task=uca_task,
                fc_task=fc_task,
                def_task=def_task,
                attributes_by_task=attributes_by_task,
                task_type_attribute_map=task_type_attribute_map,
                changes=changes,
                opening_changes=opening_changes
            )
            
            # Compare hardware/checklist items
            self._compare_hardware_items(
                opening_number=opening_number,
                new_opening=new_opening,
                new_hardware_by_group=new_hardware_by_group,
                uci_task=uci_task,
                uca_task=uca_task,
                attributes_by_task=attributes_by_task,
                checklist_items_by_task=checklist_items_by_task,
                changes=changes,
                opening_changes=opening_changes
            )
            
            # Add to updated openings if there were any changes
            if opening_changes['attribute_changes'] or opening_changes['hardware_changes']:
                changes['updated_openings'].append(opening_changes)
        
        return changes 

    def _compare_attributes(self, opening_number, new_opening, uci_task, uca_task, fc_task, def_task, 
                          attributes_by_task, task_type_attribute_map, changes, opening_changes):
        """Compare attributes between new opening and existing tasks."""
        relevant_attributes = [
            "Quantity", "Label", "NominalWidth", "NominalHeight", 
            "Hand", "Material", "HardwareGroup"
        ]
        
        # Map attribute names to their type IDs
        attribute_type_ids = {}
        for type_id, name in task_type_attribute_map.items():
            if name in relevant_attributes:
                attribute_type_ids[name] = type_id
        
        # Get existing UCI attributes
        uci_attributes = attributes_by_task.get(uci_task['id'], {})
        
        # Process each attribute in the new opening
        for attr_name in relevant_attributes:
            # Get the value from the new opening (XML)
            new_value = ""
            if attr_name in new_opening.get("Attributes", {}):
                new_value = new_opening["Attributes"][attr_name]
            
            # If empty, skip
            if not new_value:
                continue
                
            # Check if the attribute type exists in the project
            if attr_name not in attribute_type_ids:
                continue
                
            attr_type_id = attribute_type_ids[attr_name]
            
            # First, check UCI task attributes
            existing_attr = uci_attributes.get(attr_name)
            
            if not existing_attr:
                # Attribute doesn't exist, create it
                changes['attribute_changes'].append({
                    'task_id': uci_task['id'],
                    'task_name': uci_task['name'],
                    'attr_name': attr_name,
                    'attr_type_id': attr_type_id,
                    'new_value': new_value,
                    'old_value': None,
                    'action': 'create'
                })
                
                opening_changes['attribute_changes'].append({
                    'task_id': uci_task['id'],
                    'task_name': uci_task['name'],
                    'attr_name': attr_name,
                    'new_value': new_value,
                    'old_value': None,
                    'action': 'create'
                })
            elif existing_attr['value'] != new_value:
                # Attribute exists but value is different, update it
                changes['attribute_changes'].append({
                    'task_id': uci_task['id'],
                    'task_name': uci_task['name'],
                    'attr_name': attr_name,
                    'attr_type_id': attr_type_id,
                    'attr_id': existing_attr['id'],
                    'new_value': new_value,
                    'old_value': existing_attr['value'],
                    'action': 'update'
                })
                
                opening_changes['attribute_changes'].append({
                    'task_id': uci_task['id'],
                    'task_name': uci_task['name'],
                    'attr_name': attr_name,
                    'new_value': new_value,
                    'old_value': existing_attr['value'],
                    'action': 'update'
                })
            
            # Now, propagate attribute changes to UCA, FC, and DEF tasks
            if uca_task:
                self._propagate_attribute(
                    task=uca_task,
                    attr_name=attr_name,
                    attr_type_id=attr_type_id,
                    new_value=new_value,
                    attributes_by_task=attributes_by_task,
                    changes=changes,
                    opening_changes=opening_changes
                )
            
            if fc_task:
                self._propagate_attribute(
                    task=fc_task,
                    attr_name=attr_name,
                    attr_type_id=attr_type_id,
                    new_value=new_value,
                    attributes_by_task=attributes_by_task,
                    changes=changes,
                    opening_changes=opening_changes
                )
            
            if def_task:
                self._propagate_attribute(
                    task=def_task,
                    attr_name=attr_name,
                    attr_type_id=attr_type_id,
                    new_value=new_value,
                    attributes_by_task=attributes_by_task,
                    changes=changes,
                    opening_changes=opening_changes
                )
    
    def _propagate_attribute(self, task, attr_name, attr_type_id, new_value, 
                            attributes_by_task, changes, opening_changes):
        """Propagate attribute changes to related tasks."""
        # Get existing attributes for the task
        task_attributes = attributes_by_task.get(task['id'], {})
        existing_attr = task_attributes.get(attr_name)
        
        if not existing_attr:
            # Attribute doesn't exist, create it
            changes['attribute_changes'].append({
                'task_id': task['id'],
                'task_name': task['name'],
                'attr_name': attr_name,
                'attr_type_id': attr_type_id,
                'new_value': new_value,
                'old_value': None,
                'action': 'create'
            })
            
            opening_changes['attribute_changes'].append({
                'task_id': task['id'],
                'task_name': task['name'],
                'attr_name': attr_name,
                'new_value': new_value,
                'old_value': None,
                'action': 'create'
            })
        elif existing_attr['value'] != new_value:
            # Attribute exists but value is different, update it
            changes['attribute_changes'].append({
                'task_id': task['id'],
                'task_name': task['name'],
                'attr_name': attr_name,
                'attr_type_id': attr_type_id,
                'attr_id': existing_attr['id'],
                'new_value': new_value,
                'old_value': existing_attr['value'],
                'action': 'update'
            })
            
            opening_changes['attribute_changes'].append({
                'task_id': task['id'],
                'task_name': task['name'],
                'attr_name': attr_name,
                'new_value': new_value,
                'old_value': existing_attr['value'],
                'action': 'update'
            })
    
    def _compare_hardware_items(self, opening_number, new_opening, new_hardware_by_group, uci_task, uca_task, 
                               attributes_by_task, checklist_items_by_task, changes, opening_changes):
        """Compare hardware items between new opening and existing tasks."""
        # Get hardware group from attributes
        uci_attributes = attributes_by_task.get(uci_task['id'], {})
        hardware_group = None
        if 'HardwareGroup' in uci_attributes:
            hardware_group = uci_attributes['HardwareGroup']['value']
        
        # Get the hardware group from the new opening
        new_hardware_group = ""
        if "HardwareGroup" in new_opening.get("Attributes", {}):
            new_hardware_group = new_opening["Attributes"]["HardwareGroup"]
        
        # Check if hardware group has changed
        if hardware_group != new_hardware_group:
            # Add attribute change for hardware group
            opening_changes['attribute_changes'].append({
                'task_id': uci_task['id'],
                'task_name': uci_task['name'],
                'attr_name': 'HardwareGroup',
                'new_value': new_hardware_group,
                'old_value': hardware_group,
                'action': 'update'
            })
        
        # Get checklist items for UCI task
        uci_checklist_items = checklist_items_by_task.get(uci_task['id'], [])
        
        # Create a set of normalized existing checklist item names (removing prefixes)
        existing_items = {}
        for item in uci_checklist_items:
            item_name = item['name']
            # Remove prefixes for comparison
            normalized_name = item_name
            if item_name.startswith(self.NEW_PREFIX):
                normalized_name = item_name[len(self.NEW_PREFIX):]
            elif item_name.startswith(self.DELETED_PREFIX):
                normalized_name = item_name[len(self.DELETED_PREFIX):]
            
            existing_items[normalized_name] = {
                'id': item['id'],
                'name': item['name'],
                'prefixed': item_name.startswith(self.NEW_PREFIX) or item_name.startswith(self.DELETED_PREFIX)
            }
        
        # Get new hardware items for this group
        new_items = []
        if new_hardware_group and new_hardware_group in new_hardware_by_group:
            new_items = new_hardware_by_group[new_hardware_group]
        
        # Find deleted items (in Fieldwire but not in XML)
        for normalized_name, item_info in existing_items.items():
            # Skip items already marked as deleted
            if item_info['name'].startswith(self.DELETED_PREFIX):
                continue
                
            # Check if item exists in new hardware items
            if normalized_name not in new_items:
                # Item was deleted
                changes['checklist_changes'].append({
                    'task_id': uci_task['id'],
                    'item_id': item_info['id'],
                    'old_name': item_info['name'],
                    'new_name': f"{self.DELETED_PREFIX}{normalized_name}",
                    'reason': 'hardware_deleted'
                })
                
                opening_changes['hardware_changes'].append({
                    'task_id': uci_task['id'],
                    'item_name': normalized_name,
                    'old_name': item_info['name'],
                    'new_name': f"{self.DELETED_PREFIX}{normalized_name}",
                    'action': 'delete'
                })
        
        # Find new items (in XML but not in Fieldwire)
        for new_item in new_items:
            if new_item not in existing_items:
                # Item is new
                opening_changes['hardware_changes'].append({
                    'task_id': uci_task['id'],
                    'item_name': new_item,
                    'old_name': None,
                    'new_name': f"{self.NEW_PREFIX}{new_item}",
                    'action': 'create'
                })
            else:
                # Item exists - handle prefix updates
                item_info = existing_items[new_item]
                
                if item_info['name'].startswith(self.NEW_PREFIX):
                    # Remove NEW prefix for items that were previously new
                    changes['checklist_changes'].append({
                        'task_id': uci_task['id'],
                        'item_id': item_info['id'],
                        'old_name': item_info['name'],
                        'new_name': new_item,
                        'reason': 'remove_new_prefix'
                    })
                    
                    opening_changes['hardware_changes'].append({
                        'task_id': uci_task['id'],
                        'item_name': new_item,
                        'old_name': item_info['name'],
                        'new_name': new_item,
                        'action': 'update'
                    })
        
        # If UCA task exists, also update its hardware items
        if uca_task:
            self._update_uca_hardware_items(
                opening_number=opening_number,
                new_hardware_group=new_hardware_group,
                new_hardware_by_group=new_hardware_by_group,
                uci_task=uci_task,
                uca_task=uca_task,
                checklist_items_by_task=checklist_items_by_task,
                changes=changes,
                opening_changes=opening_changes
            )
    
    def _update_uca_hardware_items(self, opening_number, new_hardware_group, new_hardware_by_group,
                                 uci_task, uca_task, checklist_items_by_task, changes, opening_changes):
        """Update UCA task hardware items based on UCI hardware and HARDWARE_FILTERS."""
        # Get checklist items for UCA task
        uca_checklist_items = checklist_items_by_task.get(uca_task['id'], [])
        
        # Create a map of existing checklist items
        existing_items = {}
        for item in uca_checklist_items:
            item_name = item['name']
            # Remove prefixes for comparison
            normalized_name = item_name
            if item_name.startswith(self.NEW_PREFIX):
                normalized_name = item_name[len(self.NEW_PREFIX):]
            elif item_name.startswith(self.DELETED_PREFIX):
                normalized_name = item_name[len(self.DELETED_PREFIX):]
            
            existing_items[normalized_name] = {
                'id': item['id'],
                'name': item_name,
                'prefixed': item_name.startswith(self.NEW_PREFIX) or item_name.startswith(self.DELETED_PREFIX)
            }
        
        # Get new hardware items for this group
        new_items = []
        if new_hardware_group and new_hardware_group in new_hardware_by_group:
            new_items = new_hardware_by_group[new_hardware_group]
        
        # Process each hardware item through the UCA filters
        for item_name in new_items:
            matching_hardware_types = []
            for hardware_type, filter_def in HARDWARE_FILTERS.items():
                for condition_set in filter_def.get('conditions', []):
                    # Check if the item matches any of the conditions
                    if self._uca_check_conditions(item_name, condition_set):
                        matching_hardware_types.append(hardware_type)
                        break
            
            # For each matching hardware type, check if we need to create items
            for hardware_type in matching_hardware_types:
                filter_def = HARDWARE_FILTERS[hardware_type]
                
                # Check if we need to create additional items for this hardware type
                if 'create_items' in filter_def:
                    for additional_item in filter_def['create_items']:
                        if additional_item not in existing_items:
                            # New additional item
                            opening_changes['hardware_changes'].append({
                                'task_id': uca_task['id'],
                                'item_name': additional_item,
                                'old_name': None,
                                'new_name': f"{self.NEW_PREFIX}{additional_item}",
                                'action': 'create'
                            })
                        else:
                            # Additional item exists - handle prefix updates
                            item_info = existing_items[additional_item]
                            
                            if item_info['name'].startswith(self.NEW_PREFIX):
                                # Remove NEW prefix for items that were previously new
                                changes['checklist_changes'].append({
                                    'task_id': uca_task['id'],
                                    'item_id': item_info['id'],
                                    'old_name': item_info['name'],
                                    'new_name': additional_item,
                                    'reason': 'remove_new_prefix'
                                })
                                
                                opening_changes['hardware_changes'].append({
                                    'task_id': uca_task['id'],
                                    'item_name': additional_item,
                                    'old_name': item_info['name'],
                                    'new_name': additional_item,
                                    'action': 'update'
                                })
    
    def _uca_check_conditions(self, text, condition_set, use_word_boundaries=True):
        """Check if text matches UCA hardware filter condition set."""
        if use_word_boundaries:
            # Use enhanced checking with word boundaries
            from config.constants import check_enhanced_conditions
            # Convert single condition_set to list format expected by enhanced function
            return check_enhanced_conditions(text, [condition_set])
        else:
            # Original substring matching (for backward compatibility)
            text = text.lower()
            
            if 'any' in condition_set:
                any_match = any(term.lower() in text for term in condition_set['any'])
                if not any_match:
                    return False
                    
            if 'all' in condition_set:
                all_match = all(term.lower() in text for term in condition_set['all'])
                if not all_match:
                    return False
                    
            if 'none' in condition_set:
                none_match = not any(term.lower() in text for term in condition_set['none'])
                if not none_match:
                    return False
                    
            return True
    
    def _display_changes_summary(self, changes):
        """Display a summary of the changes."""
        print("\n=== Change Summary ===")
        
        # New openings
        if changes['new_openings']:
            print(f"\nNew Openings: {len(changes['new_openings'])}")
            for opening in changes['new_openings']:
                print(f"  - {opening['number']}")
        
        # Deleted openings
        if changes['deleted_openings']:
            print(f"\nDeleted Openings: {len(changes['deleted_openings'])}")
            for opening in changes['deleted_openings']:
                print(f"  - {opening['number']}")
        
        # Updated openings
        if changes['updated_openings']:
            print(f"\nUpdated Openings: {len(changes['updated_openings'])}")
            for opening in changes['updated_openings']:
                print(f"  - {opening['number']}")
                
                # Attribute changes
                if opening['attribute_changes']:
                    print(f"    Attribute Changes: {len(opening['attribute_changes'])}")
                    for change in opening['attribute_changes']:
                        print(f"      - {change['attr_name']}: {change['old_value']} -> {change['new_value']}")
                
                # Hardware changes
                if opening['hardware_changes']:
                    print(f"    Hardware Changes: {len(opening['hardware_changes'])}")
                    for change in opening['hardware_changes']:
                        if change['action'] == 'create':
                            print(f"      - New: {change['new_name']}")
                        elif change['action'] == 'delete':
                            print(f"      - Deleted: {change['old_name']}")
                        elif change['action'] == 'update':
                            print(f"      - Updated: {change['old_name']} -> {change['new_name']}")
        
        # Task name changes
        if changes['task_name_changes']:
            print(f"\nTask Name Changes: {len(changes['task_name_changes'])}")
            for change in changes['task_name_changes']:
                print(f"  - {change['old_name']} -> {change['new_name']}")
        
        # Attribute changes
        if changes['attribute_changes']:
            print(f"\nAttribute Changes: {len(changes['attribute_changes'])}")
            for change in changes['attribute_changes']:
                print(f"  - Task: {change['task_name']}")
                print(f"    {change['attr_name']}: {change['old_value']} -> {change['new_value']}")
        
        # Checklist changes
        if changes['checklist_changes']:
            print(f"\nChecklist Changes: {len(changes['checklist_changes'])}")
            for change in changes['checklist_changes']:
                print(f"  - {change['old_name']} -> {change['new_name']}")
    
    def _apply_changes(self, project_id, user_id, changes, task_service, attribute_service):
        """Apply the changes to Fieldwire using parallel processing."""
        # Create executor for parallel operations
        executor = RateLimitedExecutor()
        
        # Phase 1: Process task name changes in parallel
        if changes['task_name_changes']:
            print(f"\nApplying {len(changes['task_name_changes'])} task name changes...")
            
            # Prepare operations
            task_name_operations = []
            for change in changes['task_name_changes']:
                def update_task_name(change=change):
                    return task_service.update_task_name(
                        project_id=project_id,
                        task_id=change['task_id'],
                        new_name=change['new_name'],
                        last_editor_user_id=user_id
                    )
                task_name_operations.append((update_task_name, change))
            
            # Execute operations in parallel
            operations = [op[0] for op in task_name_operations]
            results = executor.execute_parallel(operations)
            
            # Process results
            successful_updates = 0
            if isinstance(results, bool):
                if results:
                    successful_updates = len(task_name_operations)
                    for _, change in task_name_operations:
                        print(f"  ✓ Updated task name: {change['old_name']} -> {change['new_name']}")
                else:
                    print("  ✗ Error: All task name updates failed")
            else:
                for (_, change), result in zip(task_name_operations, results):
                    if result:
                        successful_updates += 1
                        print(f"  ✓ Updated task name: {change['old_name']} -> {change['new_name']}")
                    else:
                        print(f"  ✗ Error updating task name: {change['old_name']}")
            
            print(f"Task name changes: {successful_updates}/{len(task_name_operations)} successful")
        
        # Phase 2: Process attribute changes in parallel
        if changes['attribute_changes']:
            print(f"\nApplying {len(changes['attribute_changes'])} attribute changes...")
            
            # Prepare operations
            attribute_operations = []
            for change in changes['attribute_changes']:
                def update_attribute(change=change):
                    # Both create and update actions use create_a_task_attribute_in_task
                    return attribute_service.create_a_task_attribute_in_task(
                        project_id=project_id,
                        task_id=change['task_id'],
                        task_type_attribute_id=change['attr_type_id'],
                        attribute_value=change['new_value'],
                        user_id=user_id
                    )
                attribute_operations.append((update_attribute, change))
            
            # Execute operations in parallel
            operations = [op[0] for op in attribute_operations]
            results = executor.execute_parallel(operations)
            
            # Process results
            successful_updates = 0
            if isinstance(results, bool):
                if results:
                    successful_updates = len(attribute_operations)
                    for _, change in attribute_operations:
                        if change['action'] == 'create':
                            print(f"  ✓ Created attribute {change['attr_name']} = {change['new_value']} for task {change['task_name']}")
                        else:
                            print(f"  ✓ Updated attribute {change['attr_name']}: {change['old_value']} -> {change['new_value']} for task {change['task_name']}")
                else:
                    print("  ✗ Error: All attribute updates failed")
            else:
                for (_, change), result in zip(attribute_operations, results):
                    if result:
                        successful_updates += 1
                        if change['action'] == 'create':
                            print(f"  ✓ Created attribute {change['attr_name']} = {change['new_value']} for task {change['task_name']}")
                        else:
                            print(f"  ✓ Updated attribute {change['attr_name']}: {change['old_value']} -> {change['new_value']} for task {change['task_name']}")
                    else:
                        print(f"  ✗ Error updating attribute {change['attr_name']} for task {change['task_name']}")
            
            print(f"Attribute changes: {successful_updates}/{len(attribute_operations)} successful")
        
        # Phase 3: Process checklist changes in parallel
        if changes['checklist_changes']:
            print(f"\nApplying {len(changes['checklist_changes'])} checklist changes...")
            
            # Prepare operations
            checklist_operations = []
            for change in changes['checklist_changes']:
                def update_checklist_item(change=change):
                    return attribute_service.update_task_check_item(
                        project_id=project_id,
                        task_id=change['task_id'],
                        check_item_id=change['item_id'],
                        new_name=change['new_name'],
                        last_editor_user_id=user_id
                    )
                checklist_operations.append((update_checklist_item, change))
            
            # Execute operations in parallel
            operations = [op[0] for op in checklist_operations]
            results = executor.execute_parallel(operations)
            
            # Process results
            successful_updates = 0
            if isinstance(results, bool):
                if results:
                    successful_updates = len(checklist_operations)
                    for _, change in checklist_operations:
                        print(f"  ✓ Updated checklist item: {change['old_name']} -> {change['new_name']}")
                else:
                    print("  ✗ Error: All checklist updates failed")
            else:
                for (_, change), result in zip(checklist_operations, results):
                    if result:
                        successful_updates += 1
                        print(f"  ✓ Updated checklist item: {change['old_name']} -> {change['new_name']}")
                    else:
                        print(f"  ✗ Error updating checklist item: {change['old_name']} (ID: {change['item_id']})")
            
            print(f"Checklist changes: {successful_updates}/{len(checklist_operations)} successful")
        
        # Phase 4: Process hardware changes in parallel
        if changes['updated_openings']:
            print(f"\nApplying hardware changes for {len(changes['updated_openings'])} openings...")
            
            # Collect all hardware operations across all openings
            all_hardware_operations = []
            for opening in changes['updated_openings']:
                opening_number = opening['number']
                uci_task = opening['uci_task']
                uca_task = opening['uca_task']
                
                if opening['hardware_changes']:
                    for change in opening['hardware_changes']:
                        task_id = change['task_id']
                        task_name = task_id == uci_task['id'] and "UCI" or "UCA"
                        
                        if change['action'] == 'create':
                            def create_checklist_item(change=change, task_id=task_id):
                                return attribute_service.create_a_new_task_check_item(
                                    project_id=project_id,
                                    task_id=task_id,
                                    creator_user_id=user_id,
                                    last_editor_user_id=user_id,
                                    name=change['new_name']
                                )
                            all_hardware_operations.append((
                                create_checklist_item, 
                                change, 
                                task_name, 
                                opening_number, 
                                'create'
                            ))
                        elif change['action'] == 'update' and 'item_id' in change:
                            def update_checklist_item(change=change, task_id=task_id):
                                return attribute_service.update_task_check_item(
                                    project_id=project_id,
                                    task_id=task_id,
                                    check_item_id=change['item_id'],
                                    new_name=change['new_name'],
                                    last_editor_user_id=user_id
                                )
                            all_hardware_operations.append((
                                update_checklist_item, 
                                change, 
                                task_name, 
                                opening_number, 
                                'update'
                            ))
            
            if all_hardware_operations:
                # Execute operations in parallel
                operations = [op[0] for op in all_hardware_operations]
                results = executor.execute_parallel(operations)
                
                # Process results
                successful_updates = 0
                if isinstance(results, bool):
                    if results:
                        successful_updates = len(all_hardware_operations)
                        for _, change, task_name, opening_number, action in all_hardware_operations:
                            if action == 'create':
                                print(f"  ✓ Created checklist item {change['new_name']} for {task_name} task {opening_number}")
                            else:
                                print(f"  ✓ Updated checklist item: {change['old_name']} -> {change['new_name']} for {task_name} task {opening_number}")
                    else:
                        print("  ✗ Error: All hardware updates failed")
                else:
                    for (_, change, task_name, opening_number, action), result in zip(all_hardware_operations, results):
                        if result:
                            successful_updates += 1
                            if action == 'create':
                                print(f"  ✓ Created checklist item {change['new_name']} for {task_name} task {opening_number}")
                            else:
                                print(f"  ✓ Updated checklist item: {change['old_name']} -> {change['new_name']} for {task_name} task {opening_number}")
                        else:
                            if action == 'create':
                                print(f"  ✗ Error creating checklist item {change['new_name']} for {task_name} task {opening_number}")
                            else:
                                print(f"  ✗ Error updating checklist item {change['old_name']} (ID: {change.get('item_id', 'unknown')}) for {task_name} task {opening_number}")
                
                print(f"Hardware changes: {successful_updates}/{len(all_hardware_operations)} successful")
        
        print("\nAll changes applied!")
    
    def _sort_checklist_items(self, project_id, user_id, new_hardware_by_group, task_service, attribute_service):
        """Sort checklist items within each task to match the order in the XML file.
        
        Args:
            project_id: The ID of the project
            user_id: The ID of the user performing the update
            new_hardware_by_group: Dictionary mapping hardware groups to hardware items in XML order
            task_service: Task service instance
            attribute_service: Attribute service instance
        """
        try:
            # Import hardware filters
            from config.constants import HARDWARE_FILTERS
            
            # Step 1: Get latest tasks with attributes
            print("Retrieving updated task data...")
            tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
            
            # Get task attributes
            task_attributes = attribute_service.get_all_task_attributes_in_project(project_id)
            
            # Get task type attributes
            task_type_attributes = attribute_service.get_all_task_type_attributes_in_project(project_id)
            
            # Create lookup maps
            task_type_attribute_map = {}
            hardware_group_attribute_id = None
            for attr in task_type_attributes:
                task_type_attribute_map[attr['id']] = attr['name']
                if attr['name'] == 'HardwareGroup':
                    hardware_group_attribute_id = attr['id']
            
            if not hardware_group_attribute_id:
                print("Error: HardwareGroup attribute not found")
                return
            
            # Group attributes by task
            attributes_by_task = {}
            for attr in task_attributes:
                task_id = attr['task_id']
                if task_id not in attributes_by_task:
                    attributes_by_task[task_id] = {}
                
                attr_type_id = attr['task_type_attribute_id']
                if attr_type_id == hardware_group_attribute_id:
                    attr_value = attr.get('text_value') or attr.get('number_value') or attr.get('uuid_value')
                    attributes_by_task[task_id]['HardwareGroup'] = attr_value
            
            # Step 2: Get latest checklist items
            print("Retrieving updated checklist items...")
            checklist_items = attribute_service.get_all_task_check_items_in_project(project_id)
            
            # Group checklist items by task
            checklist_items_by_task = {}
            for item in checklist_items:
                task_id = item['task_id']
                if task_id not in checklist_items_by_task:
                    checklist_items_by_task[task_id] = []
                checklist_items_by_task[task_id].append(item)
            
            # Step 3: Sort checklist items for each task
            print("Sorting checklist items...")
            tasks_sorted = 0
            items_updated = 0
            
            # Helper function to identify hardware type from item name
            def identify_hardware_type(item_name):
                """Identify hardware type based on item name using HARDWARE_FILTERS."""
                item_name_lower = item_name.lower()
                
                for hardware_type, config in HARDWARE_FILTERS.items():
                    conditions = config.get('conditions', [])
                    
                    for condition in conditions:
                        matches_any = True
                        matches_all = True
                        matches_none = True
                        
                        if 'any' in condition:
                            matches_any = any(keyword.lower() in item_name_lower for keyword in condition['any'])
                        
                        if 'all' in condition:
                            matches_all = all(keyword.lower() in item_name_lower for keyword in condition['all'])
                        
                        if 'none' in condition:
                            matches_none = not any(keyword.lower() in item_name_lower for keyword in condition['none'])
                        
                        if matches_any and matches_all and matches_none:
                            return hardware_type, config.get('create_items', [])
                
                return None, []
            
            # Create a mapping function to match checklist items to hardware items
            def get_base_name(item_name):
                # Remove NEW or DELETED prefix if present
                if item_name.startswith('NEW '):
                    item_name = item_name[4:]
                elif item_name.startswith('DELETED '):
                    item_name = item_name[8:]
                return item_name
            
            # Process tasks
            for task in tasks:
                task_id = task['id']
                task_name = task['name']
                
                # Skip FC and DEF tasks
                if task_name.startswith('FC ') or task_name.startswith('DEF '):
                    continue
                
                # Skip if task has no checklist items
                if task_id not in checklist_items_by_task or not checklist_items_by_task[task_id]:
                    continue
                
                # Skip if task has no hardware group attribute
                if task_id not in attributes_by_task or 'HardwareGroup' not in attributes_by_task[task_id]:
                    continue
                
                # Get hardware group for this task
                hardware_group = attributes_by_task[task_id]['HardwareGroup']
                
                # Skip if hardware group not in XML data
                if hardware_group not in new_hardware_by_group:
                    continue
                
                # Get hardware items in XML order
                hardware_items = new_hardware_by_group[hardware_group]
                
                # Get checklist items for this task
                task_checklist_items = checklist_items_by_task[task_id]
                
                # Work with the full list - don't separate DELETED items yet
                print(f"Processing {len(task_checklist_items)} total items in task: {task_name}")
                
                # Count DELETED vs non-DELETED for info
                deleted_count = sum(1 for item in task_checklist_items if item['name'].startswith('DELETED'))
                non_deleted_count = len(task_checklist_items) - deleted_count
                print(f"Found {deleted_count} DELETED items and {non_deleted_count} non-DELETED items")
                
                # Skip if no non-DELETED items
                if non_deleted_count == 0:
                    continue
                
                # Create a list of only non-DELETED items for sorting purposes
                non_deleted_items = [item for item in task_checklist_items if not item['name'].startswith('DELETED')]
                
                # Determine the final sorted order for non-DELETED items
                sorted_non_deleted_items = []
                
                # Special handling for UCA tasks
                if task_name.startswith('UCA '):
                    # Group items by their parent hardware item
                    hardware_groups = []
                    
                    # First pass: identify hardware items and their positions
                    hardware_positions = {}
                    for i, item in enumerate(non_deleted_items):
                        base_name = get_base_name(item['name'])
                        
                        # Check if this is a hardware item (matches format in XML)
                        is_hardware_item = any(hw_item == base_name for hw_item in hardware_items)
                        
                        if is_hardware_item:
                            hardware_positions[item['id']] = i
                    
                    # Second pass: group items with their hardware parent
                    for hw_id, hw_pos in hardware_positions.items():
                        # Find the hardware item
                        hw_item = next(item for item in non_deleted_items if item['id'] == hw_id)
                        base_name = get_base_name(hw_item['name'])
                        
                        # Create a new group with this hardware item
                        current_group = [hw_item]
                        
                        # Identify hardware type and expected additional items
                        hardware_type, expected_items = identify_hardware_type(base_name)
                        
                        # Find additional items that belong to this hardware item
                        # They should be immediately after the hardware item
                        pos = hw_pos + 1
                        while pos < len(non_deleted_items):
                            next_item = non_deleted_items[pos]
                            next_base_name = get_base_name(next_item['name'])
                            
                            # If this is another hardware item, stop
                            if next_item['id'] in hardware_positions:
                                break
                                
                            # If this matches an expected additional item, add it
                            if hardware_type and any(expected == next_base_name for expected in expected_items):
                                current_group.append(next_item)
                                
                            pos += 1
                            
                            # If we've found all expected items, stop looking
                            if len(current_group) - 1 >= len(expected_items):
                                break
                        
                        hardware_groups.append(current_group)
                    
                    # Sort hardware groups based on XML order
                    def get_hardware_position(group):
                        if not group:
                            return float('inf')
                        
                        # Get the hardware item (first item in the group)
                        hardware_item = group[0]
                        base_name = get_base_name(hardware_item['name'])
                        
                        # Find its position in the XML
                        return next((idx for idx, hw_item in enumerate(hardware_items) 
                                    if hw_item == base_name), float('inf'))
                    
                    # Sort groups by their hardware item's position in XML
                    hardware_groups.sort(key=get_hardware_position)
                    
                    # Flatten the sorted groups into our result list
                    for group in hardware_groups:
                        sorted_non_deleted_items.extend(group)
                    
                    # Add any remaining non-hardware items at the end
                    # (items not associated with any hardware group)
                    all_grouped_ids = set(item['id'] for group in hardware_groups for item in group)
                    remaining_items = [item for item in non_deleted_items if item['id'] not in all_grouped_ids]
                    sorted_non_deleted_items.extend(remaining_items)
                
                # Standard sorting for UCI tasks
                elif task_name.startswith('UCI '):
                    # Create a list of (item, position) pairs for sorting
                    items_with_positions = []
                    for item in non_deleted_items:
                        base_name = get_base_name(item['name'])
                        
                        # Find position in XML order
                        position = next((idx for idx, hw_item in enumerate(hardware_items) 
                                        if hw_item == base_name), float('inf'))
                        
                        # Debug output for sorting
                        print(f"  Item: {item['name']}, Base name: {base_name}, Position: {position if position != float('inf') else 'Not found'}")
                        
                        items_with_positions.append((item, position))
                    
                    # Sort by position
                    items_with_positions.sort(key=lambda x: x[1])
                    
                    # Extract just the items
                    sorted_non_deleted_items = [item for item, _ in items_with_positions]
                    
                    # Debug output for sorted items
                    print("\nSorted items (before adding DELETED items):")
                    for i, item in enumerate(sorted_non_deleted_items):
                        print(f"  {i}: {item['name']}")
                
                # Create the final sorted order: sorted non-DELETED items + DELETED items at the end
                final_sorted_order = []
                
                # Add sorted non-DELETED items first
                final_sorted_order.extend(sorted_non_deleted_items)
                
                # Add DELETED items at the end (preserve their relative order from original list)
                deleted_items = [item for item in task_checklist_items if item['name'].startswith('DELETED')]
                final_sorted_order.extend(deleted_items)
                
                # Debug output for final sorted items
                print("\nFinal sorted items (with DELETED items at the end):")
                for i, item in enumerate(final_sorted_order):
                    print(f"  {i}: {item['name']} (ID: {item['id']})")
                
                # Debug output for current order
                print("\nCurrent order in Fieldwire:")
                for i, item in enumerate(task_checklist_items):
                    print(f"  {i}: {item['name']} (ID: {item['id']})")
                
                # Now we have the final desired order in final_sorted_order
                # Check if any reordering is needed by comparing item names in order
                current_names = [item['name'] for item in task_checklist_items]
                desired_names = [item['name'] for item in final_sorted_order]
                
                if current_names == desired_names:
                    print(f"Task {task_name} is already properly sorted")
                    continue
                
                # We need to delete all items and recreate them in the correct order
                print(f"Reordering {len(final_sorted_order)} items in task {task_name}")
                print("Current order:", [item['name'] for item in task_checklist_items])
                print("Desired order:", [item['name'] for item in final_sorted_order])
                
                
                # Step 1: Delete all existing checklist items in parallel
                print(f"\nDeleting {len(task_checklist_items)} existing checklist items...")
                
                # Create executor for parallel deletion
                delete_executor = RateLimitedExecutor()
                
                # Prepare deletion operations
                delete_operations = []
                for item in task_checklist_items:
                    def delete_item(item_id=item['id']):
                        return attribute_service.delete_task_check_item(
                            project_id=project_id,
                            check_item_id=item_id
                        )
                    delete_operations.append((delete_item, item))
                
                # Execute deletions in parallel
                operations = [op[0] for op in delete_operations]
                delete_results = delete_executor.execute_parallel(operations)
                
                # Process deletion results
                items_deleted = 0
                if isinstance(delete_results, bool):
                    if delete_results:
                        items_deleted = len(delete_operations)
                        for _, item in delete_operations:
                            print(f"  ✓ Deleted: {item['name']} (ID: {item['id']})")
                    else:
                        print("  ✗ Error: All deletions failed")
                else:
                    for (_, item), result in zip(delete_operations, delete_results):
                        if result:
                            items_deleted += 1
                            print(f"  ✓ Deleted: {item['name']} (ID: {item['id']})")
                        else:
                            print(f"  ✗ Failed to delete: {item['name']} (ID: {item['id']})")
                
                print(f"Successfully deleted {items_deleted} out of {len(task_checklist_items)} items")
                
                # Step 2: Recreate items in the correct order in parallel
                print(f"\nRecreating {len(final_sorted_order)} checklist items in sorted order...")
                
                # Create executor for parallel creation
                create_executor = RateLimitedExecutor()
                
                # Prepare creation operations
                create_operations = []
                for i, item in enumerate(final_sorted_order):
                    # Preserve original creator and last editor user IDs if available
                    creator_user_id = item.get('creator_user_id', user_id)
                    last_editor_user_id = item.get('last_editor_user_id', user_id)
                    state = item.get('state')  # Preserve original state
                    
                    def create_item(task_id=task_id, creator_user_id=creator_user_id, 
                                  last_editor_user_id=last_editor_user_id, 
                                  name=item['name'], state=state):
                        return attribute_service.create_a_new_task_check_item(
                            project_id=project_id,
                            task_id=task_id,
                            creator_user_id=creator_user_id,
                            last_editor_user_id=last_editor_user_id,
                            name=name,
                            state=state
                        )
                    create_operations.append((create_item, item, i + 1))
                
                # Execute creations in parallel
                operations = [op[0] for op in create_operations]
                create_results = create_executor.execute_parallel(operations)
                
                # Process creation results
                items_created = 0
                if isinstance(create_results, bool):
                    if create_results:
                        items_created = len(create_operations)
                        for _, item, position in create_operations:
                            state = item.get('state')
                            print(f"  ✓ Created {position}/{len(final_sorted_order)}: {item['name']} (state: {state or 'empty'})")
                    else:
                        print("  ✗ Error: All creations failed")
                else:
                    for (_, item, position), result in zip(create_operations, create_results):
                        if result:
                            items_created += 1
                            state = item.get('state')
                            print(f"  ✓ Created {position}/{len(final_sorted_order)}: {item['name']} (state: {state or 'empty'})")
                        else:
                            print(f"  ✗ Failed to create: {item['name']}")
                
                print(f"Successfully created {items_created} out of {len(final_sorted_order)} items")
                
                tasks_sorted += 1
                items_updated += items_created
                print(f"Completed sorting task {task_name}: {items_deleted} items deleted, {items_created} items recreated")
            
            print(f"Sorting complete. {tasks_sorted} tasks sorted with {items_updated} items updated.")
            
        except Exception as e:
            print(f"Error during checklist item sorting: {str(e)}")
            print("Some items may not be properly sorted.")
    
    def _create_hardware_by_group(self, hardware_items):
        """Create a map of hardware items by group name."""
        hardware_by_group = {}
        
        for item in hardware_items:
            group_name = item["GroupName"]
            if not group_name:
                continue
                
            if group_name not in hardware_by_group:
                hardware_by_group[group_name] = []
            
            # Create a checklist item name from the hardware item
            name_parts = []
            for field in ['QuantityOffDoor', 'QuantityActive', 'ShortCode', 
                          'SubCategory', 'ProductCode', 'Finish_ANSI']:
                if item[field]:
                    name_parts.append(f"({item[field]})")
            
            name = " ".join(name_parts)
            if name:
                hardware_by_group[group_name].append(name)
        
        return hardware_by_group
    
    def _create_task_maps(self, tasks):
        """Create task maps for different task types."""
        uci_tasks = {}  # {original_number: task}
        uca_tasks = {}  # {original_number: task}
        fc_tasks = {}   # {original_number: task}
        def_tasks = {}  # {original_number: task}
        
        for task in tasks:
            name = task['name']
            if not name:
                continue
            
            # Skip tasks that are already marked as deleted (unless we want to handle them)
            # if name.startswith(self.DELETED_PREFIX):
            #     continue
                
            # Extract the opening number based on prefix
            if name.startswith("UCI "):
                original_number = name[4:].strip()  # Remove "UCI " prefix
                uci_tasks[original_number] = task
            elif name.startswith("UCA "):
                original_number = name[4:].strip()  # Remove "UCA " prefix
                uca_tasks[original_number] = task
            elif name.startswith("FC "):
                original_number = name[3:].strip()  # Remove "FC " prefix
                fc_tasks[original_number] = task
            elif name.startswith("DEF "):
                original_number = name[4:].strip()  # Remove "DEF " prefix
                def_tasks[original_number] = task
            
        return uci_tasks, uca_tasks, fc_tasks, def_tasks 