"""XML file processing functions."""

import xml.etree.ElementTree as ET

def parse_xml_file(file_path):
    """Parse XML file for openings and their attributes"""
    tree = ET.parse(file_path)
    root = tree.getroot()
    openings = []
    for opening in root.findall(".//Opening"):
        # Get basic opening attributes
        attributes = {child.tag: child.text for child in opening}
        
        # Get Door element attributes
        door_element = opening.find("Door")
        if door_element is not None:
            # Add Door attributes with "Door_" prefix to avoid naming conflicts
            door_attributes = {
                child.tag: child.text for child in door_element
            }
            # Add specific Door attributes we care about to main attributes
            if "Material" in door_attributes:
                attributes["DoorMaterial"] = door_attributes["Material"]
        
        # Get Frame element attributes
        frame_element = opening.find("Frame")
        if frame_element is not None:
            # Add Frame attributes
            frame_attributes = {
                child.tag: child.text for child in frame_element
            }
            # Add specific Frame attributes we care about to main attributes
            if "Material" in frame_attributes:
                attributes["FrameMaterial"] = frame_attributes["Material"]
        
        openings.append({
            "Number": opening.get("Number"),
            "Attributes": attributes
        })
    return openings

def parse_hardware_items(file_path):
    """Parse XML file for hardware items"""
    tree = ET.parse(file_path)
    root = tree.getroot()
    
    hardware_items = []
    for group in root.findall(".//Group"):
        group_name = group.get('Name')
        
        items = [{
            "GroupName": group_name,
            "QuantityOffDoor": item.findtext('QuantityOffDoor'),
            "QuantityActive": item.findtext('QuantityActive'),
            "ShortCode": item.findtext('ShortCode'),
            "SubCategory": item.findtext('SubCategory'),
            "ProductCode": item.findtext('ProductCode'),
            "Finish_ANSI": item.findtext('Finish_ANSI')
        } for item in group.findall('Item')]
        
        hardware_items.extend(items)

    print(f"Parsed {len(hardware_items)} hardware items from the XML file.")
    return hardware_items
