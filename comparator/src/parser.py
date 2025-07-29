import xmltodict
from typing import Dict, List, Any
from src.models import Opening, DoorInfo, HardwareItem

class XMLParser:
    """Parser for door hardware schedule XML files."""
    
    @staticmethod
    def parse_file(file_path: str) -> Dict[str, Opening]:
        """
        Parse XML file and return a dictionary of Openings keyed by number.
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            xml_dict = xmltodict.parse(f.read())
        
        # Navigate to Division8/OpeningsSchedules/Schedule/Opening
        try:
            division8 = xml_dict['Project']['Division8']
            
            # First, parse hardware groups for later reference
            hardware_groups = XMLParser._parse_hardware_groups(division8)
            
            # Then parse openings
            schedules = division8['OpeningsSchedules']
            schedule = schedules['Schedule']
            openings_data = schedule['Opening']
            
            # If there's only one opening, xmltodict won't create a list
            if not isinstance(openings_data, list):
                openings_data = [openings_data]
                
            openings = {}
            for opening_data in openings_data:
                try:
                    opening = XMLParser._parse_opening(opening_data, hardware_groups)
                    openings[opening.number] = opening
                except Exception as e:
                    print(f"Error parsing opening {opening_data.get('@Number', 'unknown')}: {str(e)}")
                    raise
                
            return openings
            
        except KeyError as e:
            raise ValueError(f"Invalid XML structure. Missing required section: {str(e)}")
    
    @staticmethod
    def _parse_hardware_groups(division8: Dict[str, Any]) -> Dict[str, List[HardwareItem]]:
        """Parse all hardware groups into a dictionary keyed by group name."""
        groups = {}
        
        try:
            hardware_groups = division8.get('HardwareGroups', {})
            if not hardware_groups:
                return groups
                
            group_list = hardware_groups.get('Group', [])
            if not isinstance(group_list, list):
                group_list = [group_list]
                
            for group in group_list:
                group_name = str(group.get('@Name', ''))
                items = group.get('Item', [])
                if not isinstance(items, list):
                    items = [items]
                    
                hardware_items = []
                for item in items:
                    hardware_items.append(HardwareItem(
                        short_code=str(item.get('ShortCode', '')),
                        product_code=str(item.get('ProductCode', '')),
                        sub_category=str(item.get('SubCategory', '')),
                        quantity_active=str(item.get('QuantityActive', '')),
                        handing=str(item.get('Handing', '')),
                        finish_ansi=str(item.get('Finish_ANSI', ''))
                    ))
                    
                groups[group_name] = hardware_items
                
        except Exception as e:
            print(f"Warning: Error parsing hardware groups: {str(e)}")
            
        return groups
    
    @staticmethod
    def _parse_opening(opening_data: Dict[str, Any], hardware_groups: Dict[str, List[HardwareItem]]) -> Opening:
        """Parse Opening data from XML dictionary."""
        try:
            # Extract door info with safe value handling
            door_info = DoorInfo(
                quantity=str(opening_data.get('Quantity', '')),
                type=str(opening_data.get('Type', '')),
                nominal_width=str(opening_data.get('NominalWidth', '')),
                nominal_height=str(opening_data.get('NominalHeight', '')),
                hand=str(opening_data.get('Hand', '')),
                location1=str(opening_data.get('Location1', '')),
                to_from=str(opening_data.get('ToFrom', '')),
                location2=str(opening_data.get('Location2', '')),
                hardware_group=str(opening_data.get('HardwareGroup', ''))
            )
            
            # Get hardware items from the hardware groups
            hardware_group = str(opening_data.get('HardwareGroup', ''))
            hardware_items = hardware_groups.get(hardware_group, [])
            
            return Opening(
                number=str(opening_data.get('@Number', '')),
                door_info=door_info,
                hardware_items=hardware_items
            )
        except KeyError as e:
            raise ValueError(f"Missing required field in Opening: {str(e)}")
        except ValueError as e:
            raise ValueError(f"Invalid value in Opening: {str(e)}") 