from typing import Dict, List, Tuple, Set
from src.models import (
    Opening, DoorInfo, HardwareItem,
    DoorInfoChange, HardwareChange, OpeningChange, ComparisonSummary
)

class Comparator:
    """Compares two versions of door hardware schedules."""
    
    @staticmethod
    def compare(
        old_openings: Dict[str, Opening],
        new_openings: Dict[str, Opening]
    ) -> ComparisonSummary:
        """
        Compare two sets of openings and generate a comparison summary.
        """
        changes: List[OpeningChange] = []
        door_info_changes_count = 0
        hardware_changes_count = 0
        
        # Get all opening numbers from both versions
        all_numbers = set(old_openings.keys()) | set(new_openings.keys())
        
        for number in sorted(all_numbers):
            old_opening = old_openings.get(number)
            new_opening = new_openings.get(number)
            
            # Handle added/deleted/modified openings
            if not old_opening:
                # Opening was added
                changes.append(Comparator._create_added_opening_change(new_opening))
                door_info_changes_count += 1
                hardware_changes_count += 1
            elif not new_opening:
                # Opening was deleted
                changes.append(Comparator._create_deleted_opening_change(old_opening))
                door_info_changes_count += 1
                hardware_changes_count += 1
            else:
                # Opening exists in both versions - check for changes
                door_info_changes = Comparator._compare_door_info(
                    old_opening.door_info,
                    new_opening.door_info
                )
                hardware_changes = Comparator._compare_hardware(
                    old_opening.hardware_items,
                    new_opening.hardware_items
                )
                
                if door_info_changes or hardware_changes:
                    changes.append(OpeningChange(
                        number=number,
                        door_info_changes=door_info_changes,
                        hardware_changes=hardware_changes
                    ))
                    if door_info_changes:
                        door_info_changes_count += 1
                    if hardware_changes:
                        hardware_changes_count += 1
        
        return ComparisonSummary(
            total_changed_openings=len(changes),
            openings_with_door_info_changes=door_info_changes_count,
            openings_with_hardware_changes=hardware_changes_count,
            changes=changes
        )
    
    @staticmethod
    def _compare_door_info(old_info: DoorInfo, new_info: DoorInfo) -> List[DoorInfoChange]:
        """Compare door information and return list of changes."""
        changes = []
        
        # Compare each field
        old_dict = old_info.dict()
        new_dict = new_info.dict()
        
        for field in old_dict:
            if old_dict[field] != new_dict[field]:
                changes.append(DoorInfoChange(
                    field=field,
                    old_value=str(old_dict[field]),
                    new_value=str(new_dict[field])
                ))
        
        return changes
    
    @staticmethod
    def _compare_hardware(
        old_items: List[HardwareItem],
        new_items: List[HardwareItem]
    ) -> List[HardwareChange]:
        """Compare hardware items and return list of changes."""
        changes = []
        
        # Create composite key sets for comparison
        old_keys = {Comparator._get_hardware_key(item) for item in old_items}
        new_keys = {Comparator._get_hardware_key(item) for item in new_items}
        
        # Find added and deleted items
        added_keys = new_keys - old_keys
        deleted_keys = old_keys - new_keys
        common_keys = old_keys & new_keys
        
        # Process added items
        for key in added_keys:
            item = next(item for item in new_items
                       if Comparator._get_hardware_key(item) == key)
            changes.append(HardwareChange(type='added', item=item))
        
        # Process deleted items
        for key in deleted_keys:
            item = next(item for item in old_items
                       if Comparator._get_hardware_key(item) == key)
            changes.append(HardwareChange(type='deleted', item=item))
        
        # Process modified items
        for key in common_keys:
            old_item = next(item for item in old_items
                          if Comparator._get_hardware_key(item) == key)
            new_item = next(item for item in new_items
                          if Comparator._get_hardware_key(item) == key)
            
            modifications = Comparator._compare_hardware_item(old_item, new_item)
            if modifications:
                changes.append(HardwareChange(
                    type='modified',
                    item=new_item,
                    modifications=modifications
                ))
        
        return changes
    
    @staticmethod
    def _get_hardware_key(item: HardwareItem) -> Tuple[str, str, str]:
        """Get composite key for hardware item."""
        return (item.short_code, item.product_code, item.sub_category)
    
    @staticmethod
    def _compare_hardware_item(
        old_item: HardwareItem,
        new_item: HardwareItem
    ) -> Dict[str, dict[str, str]]:
        """Compare individual hardware items and return modifications."""
        modifications = {}
        
        # Compare modifiable fields
        if old_item.quantity_active != new_item.quantity_active:
            modifications['quantity_active'] = {
                'old': str(old_item.quantity_active),
                'new': str(new_item.quantity_active)
            }
        
        if old_item.handing != new_item.handing:
            modifications['handing'] = {
                'old': str(old_item.handing),
                'new': str(new_item.handing)
            }
        
        if old_item.finish_ansi != new_item.finish_ansi:
            modifications['finish_ansi'] = {
                'old': str(old_item.finish_ansi),
                'new': str(new_item.finish_ansi)
            }
        
        return modifications
    
    @staticmethod
    def _create_added_opening_change(opening: Opening) -> OpeningChange:
        """Create change record for added opening."""
        return OpeningChange(
            number=opening.number,
            door_info_changes=[DoorInfoChange(
                field='status',
                old_value='non-existent',
                new_value='added'
            )],
            hardware_changes=[
                HardwareChange(type='added', item=item)
                for item in opening.hardware_items
            ]
        )
    
    @staticmethod
    def _create_deleted_opening_change(opening: Opening) -> OpeningChange:
        """Create change record for deleted opening."""
        return OpeningChange(
            number=opening.number,
            door_info_changes=[DoorInfoChange(
                field='status',
                old_value='existed',
                new_value='deleted'
            )],
            hardware_changes=[
                HardwareChange(type='deleted', item=item)
                for item in opening.hardware_items
            ]
        ) 