# Door Hardware Schedule Comparison Tool

A tool for comparing two versions of door hardware schedules exported from AVAproject in XML format. The tool identifies changes in both door information and hardware specifications for each opening.

## Features

- Compare door hardware schedules between two XML files
- Identify changes in door information and hardware specifications
- Interactive terminal UI for viewing changes
- Export comparison results to JSON format
- Support for metric measurements
- Detailed change tracking for openings and hardware items

## Installation

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Command Line Interface

Run the comparison tool:
```bash
python -m src.main compare [OLD_FILE] [NEW_FILE] [--export EXPORT_FILE]
```

Arguments:
- `OLD_FILE`: Path to the old version XML file (optional)
- `NEW_FILE`: Path to the new version XML file (optional)
- `--export/-e`: Path to export JSON report (optional)

If file paths are not provided as arguments, the tool will prompt for them interactively.

### Interactive Mode

1. The tool will display a summary of changes
2. You can browse through the list of changed openings
3. Select an opening to view detailed changes
4. Choose to export the comparison report to JSON

### Export Format

The JSON export includes:
- Metadata about the comparison
- Summary statistics
- Detailed changes for each opening
- Hardware modifications, additions, and deletions

## Data Structure

### Opening Changes
- Door Information changes
- Hardware changes (additions, deletions, modifications)

### Hardware Identification
Hardware items are identified by a composite key of:
- Short Code
- Product Code
- Sub Category

### Tracked Changes
- Door Information attributes
- Hardware quantities
- Hardware handing
- Hardware finishes

## Development

### Project Structure
```
src/
  ├── __init__.py
  ├── main.py          # Entry point
  ├── models.py        # Data models
  ├── parser.py        # XML parser
  ├── comparator.py    # Comparison logic
  ├── ui.py           # User interface
  └── exporter.py     # JSON export
```

### Running Tests
```bash
# TODO: Add test instructions
```