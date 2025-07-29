# Door Hardware Schedule Comparison Tool

## Overview
This solution provides a comparison tool for analyzing differences between two versions of door hardware schedules exported from AVAproject in XML format. The tool identifies changes in both door information and hardware specifications for each opening.

## Core Functionality
- Compares two XML files representing different versions of the same project's door hardware schedule
- Users designate which file is "old" and which is "new" through file dialogs
- Focuses exclusively on Division8 section of the XML
- Provides both summary and detailed views of changes
- Supports export of change reports in both JSON and Excel formats

## Implementation

### Project Structure
```
door-hardware-comparison/
├── src/
│   ├── __init__.py        # Package version and metadata
│   ├── main.py           # CLI entry point using Typer
│   ├── models.py         # Pydantic data models
│   ├── parser.py         # XML parsing logic
│   ├── comparator.py     # Change detection logic
│   ├── ui.py            # Terminal UI using Rich + tkinter dialogs
│   └── exporter.py      # JSON and Excel export functionality
└── README.md            # Usage instructions
```

### Dependencies
- xmltodict (0.13.0): XML parsing
- rich (13.7.0): Terminal UI
- typer (0.9.0): CLI interface
- pydantic (2.6.1): Data validation
- openpyxl (3.1.2): Excel file creation
- tkinter: File dialogs (built into Python)

### Running the Tool
During development:
```bash
# From the src directory
python main.py compare
```

For deployment:
- The application can be packaged using PyInstaller
- This will create a standalone executable that doesn't require Python installation

## User Interface

### File Selection
- Native file dialog windows for selecting XML files
- Filters to show only relevant file types:
  - XML files (*.xml) for input files
  - JSON files (*.json) for export
- Clear distinction between OLD and NEW version selection
- Validation to ensure files are selected

### Summary Statistics Screen
- Total number of changed Openings
- Breakdown of change types
- Overview of modifications

### Changed Openings List
- Lists all Openings with changes (Door Info and/or Hardware)
- Excludes unchanged Openings
- Provides high-level change summary for each Opening
- Interactive selection for detailed view

### Detailed Opening View
- Accessed by selecting an Opening from the list
- Shows detailed Door Information changes
- Lists Hardware changes (additions, deletions, modifications)
- Color-coded changes:
  - Added (green)
  - Deleted (red)
  - Modified (yellow)
- Option to return to main list

## Data Models

### Opening Identification
- Each Opening is uniquely identified by its `Number` attribute
- All values are handled as strings for comparison
- Changes are tracked at two levels:
  1. Door Information
  2. Hardware Items

### Door Information Attributes
The following attributes are compared for each Opening:
```xml
<Opening Number="[unique-identifier]">
    <Quantity/>          <!-- Stored as string -->
    <Type/>             <!-- Stored as string -->
    <NominalWidth/>     <!-- Stored as string -->
    <NominalHeight/>    <!-- Stored as string -->
    <Hand/>             <!-- Stored as string -->
    <Location1/>        <!-- Stored as string -->
    <ToFrom/>          <!-- Stored as string -->
    <Location2/>        <!-- Stored as string -->
    <HardwareGroup/>    <!-- Stored as string -->
</Opening>
```

### Hardware Items
Hardware items within each Opening are identified by a composite key of:
```xml
<Item>
    <ShortCode/>        <!-- Stored as string -->
    <ProductCode/>      <!-- Stored as string -->
    <SubCategory/>      <!-- Stored as string -->
</Item>
```

Additional hardware attributes compared for modifications:
```xml
<Item>
    <QuantityActive/>   <!-- Optional, stored as string -->
    <Handing/>         <!-- Optional, stored as string -->
    <Finish_ANSI/>     <!-- Optional, stored as string -->
</Item>
```

## Change Detection Logic

### Opening Level Changes
- Added: Opening exists in new version but not in old
  ```python
  # Example: Opening "2/646" exists in new but not in old
  old_openings = {
      "2/645": Opening(...),
      "2/647": Opening(...)
  }
  new_openings = {
      "2/645": Opening(...),
      "2/646": Opening(...),  # Added
      "2/647": Opening(...)
  }
  # All hardware in Opening "2/646" will be reported as "added"
  # Example hardware report for new Opening:
  opening_change = {
      "number": "2/646",
      "doorInfo": {
          "modified": {
              "status": {
                  "old": "non-existent",
                  "new": "added"
              }
          }
      },
      "hardware": {
          "added": [
              {
                  "shortCode": "1103",
                  "productCode": "SL14 HD600",
                  "subCategory": "Continuous Hinge",
                  "quantityActive": "1",
                  "handing": "RH",
                  "finishANSI": "C28"
              },
              # All hardware items from the new Opening
          ],
          "deleted": [],
          "modified": []
      }
  }
  ```

- Deleted: Opening exists in old version but not in new
  ```python
  # Example: Opening "2/646" exists in old but not in new
  old_openings = {
      "2/645": Opening(...),
      "2/646": Opening(...),  # Deleted
      "2/647": Opening(...)
  }
  new_openings = {
      "2/645": Opening(...),
      "2/647": Opening(...)
  }
  # All hardware in Opening "2/646" will be reported as "deleted"
  # Example hardware report for deleted Opening:
  opening_change = {
      "number": "2/646",
      "doorInfo": {
          "modified": {
              "status": {
                  "old": "existed",
                  "new": "deleted"
              }
          }
      },
      "hardware": {
          "added": [],
          "deleted": [
              {
                  "shortCode": "1103",
                  "productCode": "SL14 HD600",
                  "subCategory": "Continuous Hinge",
                  "quantityActive": "1",
                  "handing": "RH",
                  "finishANSI": "C28"
              },
              # All hardware items from the old Opening
          ],
          "modified": []
      }
  }
  ```

- Modified: Opening exists in both versions with changes in Door Information attributes
  ```python
  # Example: Opening "2/646" has different Location1 value
  old_openings = {
      "2/646": Opening(
          door_info=DoorInfo(
              location1="WAITING ROOM",
              ...
          )
      )
  }
  new_openings = {
      "2/646": Opening(
          door_info=DoorInfo(
              location1="EXAM ROOM",  # Changed
              ...
          )
      )
  }
  ```

### Comparison Process
1. **Opening Level**
   - Tool creates sets of Opening numbers from both old and new versions
   - Set operations identify:
     - Added: `new_numbers - old_numbers`
     - Deleted: `old_numbers - new_numbers`
     - Common: `old_numbers & new_numbers`
   - For common Openings, compares all Door Info attributes

2. **Hardware Level**
   - For each Opening, hardware items are compared using composite keys
   - Composite key = (ShortCode, ProductCode, SubCategory)
   - Example composite key: ("1103", "SL14 HD600", "Continuous Hinge")
   - Set operations on composite keys identify:
     ```python
     # Example: Hardware changes in Opening "2/646"
     old_hardware = {
         ("1103", "SL14 HD600", "Continuous Hinge"),
         ("1006", "EPT-10-689", "Power Transfer")
     }
     new_hardware = {
         ("1103", "SL14 HD600", "Continuous Hinge"),
         ("1008", "64 RX-8204", "Lockset")  # Added
     }
     # Result:
     added = {("1008", "64 RX-8204", "Lockset")}
     deleted = {("1006", "EPT-10-689", "Power Transfer")}
     common = {("1103", "SL14 HD600", "Continuous Hinge")}
     ```

3. **Hardware Modifications**
   - For common hardware items (matching composite keys), compares:
     - QuantityActive
     - Handing
     - Finish_ANSI
   ```python
   # Example: Modified hardware item
   old_item = HardwareItem(
       short_code="1103",
       product_code="SL14 HD600",
       sub_category="Continuous Hinge",
       quantity_active="1",
       handing="RH",
       finish_ansi="C28"
   )
   new_item = HardwareItem(
       short_code="1103",
       product_code="SL14 HD600",
       sub_category="Continuous Hinge",
       quantity_active="2",  # Changed
       handing="RH",
       finish_ansi="C28"
   )
   ```

### String-Based Comparison
- All comparisons use string equality
- No type conversion or numeric comparison
- Examples:
  ```python
  # These are considered different values
  "2135" != "2135.0"
  "RH" != "rh"
  "1" != "01"
  ```
- Empty or missing values become empty strings
  ```python
  # These are considered equal
  "" == ""  # Missing value vs missing value
  None -> ""  # None converted to empty string
  ```

## Export Formats

### JSON Export
JSON structure for programmatic use:
```json
{
    "metadata": {
        "oldVersion": "path/to/old.xml",
        "newVersion": "path/to/new.xml",
        "comparisonDate": "2024-03-19T12:00:00Z",
        "summary": {
            "totalChangedOpenings": 25,
            "openingsWithDoorInfoChanges": 15,
            "openingsWithHardwareChanges": 20
        }
    },
    "changes": {
        "openings": [
            {
                "number": "2/646",
                "doorInfo": {
                    "modified": {
                        "field": {
                            "old": "old_value",
                            "new": "new_value"
                        }
                    }
                },
                "hardware": {
                    "added": [...],
                    "deleted": [...],
                    "modified": [...]
                }
            }
        ]
    }
}
```

### Excel Export
Multi-sheet workbook for human readability:

1. **Summary Sheet**
   - Project information
   - File names and comparison date
   - Overall statistics
   - Formatted for easy reading

2. **Door Info Changes Sheet**
   - Columns:
     - Opening Number
     - Field
     - Old Value
     - New Value
   - Color-coded yellow for modifications
   - Auto-sized columns

3. **Hardware Changes Sheet**
   - Organized by Opening
   - Separate sections per opening:
     - Added Hardware (green)
     - Deleted Hardware (red)
     - Modified Hardware (yellow)
   - Hardware sections include:
     - Short Code
     - Product Code
     - Sub Category
     - Quantity
     - Handing
     - Finish
   - Clear section headers
   - Visual spacing between openings

### Export Features
- Automatic creation of both JSON and Excel files
- Excel file uses same name as JSON with .xlsx extension
- Color coding for change types:
  - Added items (light green)
  - Deleted items (light red)
  - Modified items (light yellow)
- Auto-adjusted column widths
- Bold headers
- Clear section organization
- Spacing between sections

## Validation & Error Handling

### XML Structure Validation
- Required Opening attributes:
  ```xml
  <Opening Number="[unique-identifier]">
      <Quantity/>          <!-- Any value, stored as string -->
      <Type/>             <!-- Any value, stored as string -->
      <NominalWidth/>     <!-- Any value, stored as string -->
      <NominalHeight/>    <!-- Any value, stored as string -->
      <Hand/>             <!-- Any value, stored as string -->
      <Location1/>        <!-- Any value, stored as string -->
      <ToFrom/>          <!-- Any value, stored as string -->
      <Location2/>        <!-- Any value, stored as string -->
      <HardwareGroup/>    <!-- Any value, stored as string -->
  </Opening>
  ```

### Common Errors
1. **Missing Required Fields**
   - Cause: XML missing one or more required fields
   - Resolution: Missing fields will be stored as empty strings

2. **File Selection Errors**
   - Cause: No file selected in file dialog
   - Resolution: Must select both OLD and NEW version files

### Error Messages
- File Selection: "No file selected for [OLD/NEW] version"
- XML Parsing: Field name in error message indicates problematic field
- Missing Field: Empty string used for missing fields

## Technical Notes
- All values are stored and compared as strings
- No type conversion or validation performed
- Empty or missing values handled as empty strings
- Hardware groups vary by project
- ShortCodes are project-specific
- No standardized version naming convention
- Uses Pydantic for data modeling
- Rich library for terminal UI rendering
- Typer for CLI argument handling
- Native file dialogs using tkinter
- Color-coded change presentation
- Excel export using openpyxl
- Automatic file format handling

### Hardware Reporting Rules
1. **For New Openings**
   - All hardware items in the new Opening are reported as "added"
   - No hardware comparisons needed
   - Appears in green in Excel export
   - Full hardware details included in report

2. **For Deleted Openings**
   - All hardware items in the old Opening are reported as "deleted"
   - No hardware comparisons needed
   - Appears in red in Excel export
   - Full hardware details included in report

3. **For Modified Openings**
   - Hardware items compared using composite keys
   - Changes reported as added/deleted/modified
   - Each type color-coded in Excel export
   - Detailed changes shown for modified items

### Excel Report Example
```
Opening 2/646 (New Opening)
Added Hardware (green)
| Short Code | Product Code | Sub Category      | Quantity | Handing | Finish |
|------------|--------------|-------------------|----------|---------|---------|
| 1103       | SL14 HD600  | Continuous Hinge  | 1        | RH      | C28     |
| 1006       | EPT-10-689  | Power Transfer    | 1        | N       | 689     |

Opening 2/647 (Deleted Opening)
Deleted Hardware (red)
| Short Code | Product Code | Sub Category      | Quantity | Handing | Finish |
|------------|--------------|-------------------|----------|---------|---------|
| 1103       | SL14 HD600  | Continuous Hinge  | 1        | RH      | C28     |
| 1006       | EPT-10-689  | Power Transfer    | 1        | N       | 689     |
```

## Deployment

### Creating Executable with PyInstaller
From the root directory of the project:
```batch
:: Install PyInstaller if not already installed
pip install pyinstaller

:: Create single-file executable with console window
pyinstaller --onefile --name="HWS Comparison v2" --add-data="src;src" src/main.py

:: The executable will be created in the dist/ directory
:: Run the executable from command prompt:
dist\"HWS Comparison v2.exe"
```

### PyInstaller Options Used
- `--onefile`: Create a single executable file that includes all dependencies
- `--name="..."`: Specify the name of the executable (use quotes for names with spaces)
- `--add-data="src;src"`: Include the entire src directory in the executable (first 'src' is source, second is destination)

### Project Setup for PyInstaller
1. **Directory Structure**
   ```
   project_root/
   ├── src/
   │   ├── __init__.py        # Makes src a proper Python package
   │   ├── main.py            # Entry point
   │   ├── parser.py          # XML parsing
   │   ├── models.py          # Data models
   │   ├── comparator.py      # Comparison logic
   │   ├── ui.py             # User interface
   │   └── exporter.py        # Export functionality
   ```

2. **Package Recognition**
   - The `src` directory must be a proper Python package
   - Requires `__init__.py` file in the `src` directory
   - All imports must use absolute paths from `src` package
   - PyInstaller needs `--add-data` to include the package

3. **Dependencies**
   - PyInstaller automatically detects and bundles dependencies
   - The entire `src` package is included via `--add-data`
   - All required packages must be installed in the Python environment

### Output Location
- The executable will be created in the `dist` directory as "HWS Comparison v2.exe"
- Additional build files will be in the `build` directory
- A `.spec` file will be created in the root directory

### Common Issues
1. **Module Not Found Errors**
   - Cause: PyInstaller can't find modules due to import structure
   - Solution: Use absolute imports from `src` package
   - Example: `from src.parser import XMLParser`

2. **Spaces in Names**
   - Use quotes around executable name if it contains spaces
   - Example: `--name="HWS Comparison v2"`

3. **Working Directory**
   - Run PyInstaller command from project root (where `src` is located)
   - Keep consistent package structure
   - Use absolute imports

### Notes
- The executable will include all necessary Python dependencies
- No Python installation required on target machine
- Console window will show program output
- File dialogs will use native Windows UI
- Size of executable will be larger as it includes all dependencies 