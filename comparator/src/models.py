from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class DoorInfo(BaseModel):
    """Represents the door information attributes of an Opening."""
    quantity: str
    type: str
    nominal_width: str
    nominal_height: str
    hand: str
    location1: str
    to_from: str
    location2: str
    hardware_group: str

class HardwareItem(BaseModel):
    """Represents a hardware item within an Opening."""
    # Composite key fields
    short_code: str
    product_code: str
    sub_category: str
    # Additional fields for modification tracking
    quantity_active: Optional[str] = None
    handing: Optional[str] = None
    finish_ansi: Optional[str] = None

class Opening(BaseModel):
    """Represents an Opening with its door info and hardware items."""
    number: str
    door_info: DoorInfo
    hardware_items: List[HardwareItem]

class DoorInfoChange(BaseModel):
    """Represents changes in door information attributes."""
    field: str
    old_value: str
    new_value: str

class HardwareChange(BaseModel):
    """Represents changes in hardware items."""
    type: str = Field(..., description="Type of change: 'added', 'deleted', or 'modified'")
    item: HardwareItem
    modifications: Optional[Dict[str, dict[str, str]]] = None

class OpeningChange(BaseModel):
    """Represents all changes for an Opening."""
    number: str
    door_info_changes: List[DoorInfoChange]
    hardware_changes: List[HardwareChange]

class ComparisonSummary(BaseModel):
    """Represents the summary of all changes."""
    total_changed_openings: int
    openings_with_door_info_changes: int
    openings_with_hardware_changes: int
    changes: List[OpeningChange] 