"""Helper functions for user input and file operations."""

import os
import tempfile
import subprocess
import platform
import tkinter as tk
from tkinter import filedialog
import sys
import keyboard  # For global key listening
import time
from utils.pdf_helpers import close_preview_windows

# Import platform-specific modules
if platform.system() == 'Windows':
    import msvcrt
else:
    try:
        import tty
        import termios
    except ImportError:
        pass  # These modules aren't available on Windows

def get_single_keypress(allowed_keys=None):
    """Get a single keypress from the user without requiring window focus.
    
    Args:
        allowed_keys (list): List of allowed key characters. If None, accepts any key.
        
    Returns:
        str: The character pressed by the user
    """
    if allowed_keys is None:
        allowed_keys = []
    
    # Convert allowed_keys to lowercase for case-insensitive comparison
    allowed_keys = [k.lower() for k in allowed_keys]
    
    while True:
        # Wait for any key event
        event = keyboard.read_event(suppress=True)
        
        # Only process key down events
        if event.event_type == 'down':
            key = event.name.lower()
            
            # If allowed_keys is empty or the key is in allowed_keys
            if not allowed_keys or key in allowed_keys:
                return key
                
        # Small sleep to prevent high CPU usage
        time.sleep(0.01)

def get_location_confirmation():
    """Get user confirmation for location preview with global key listening.
    
    Returns:
        str: 'y' for yes, 'n' for no, 's' for skip
    """
    print("\nPlease review the location in the opened preview.")
    print("Press 'y' for yes, 'n' for no, or 's' to skip (works from any window)")
    choice = get_single_keypress(['y', 'n', 's'])
    close_preview_windows()  # Close preview windows immediately after input
    return choice

def get_preview_error_choice():
    """Get user choice when preview fails with global key listening.
    
    Returns:
        str: 'c' for continue, 'r' for retry, 's' for skip
    """
    print("Press 'c' to continue without preview, 'r' to retry preview, or 's' to skip this task")
    print("(Keys work from any window)")
    choice = get_single_keypress(['c', 'r', 's'])
    close_preview_windows()  # Close preview windows immediately after input
    return choice

def get_location_confirmation_with_adjustment():
    """Get user confirmation for location preview with distance adjustment options.
    
    Returns:
        str: 'y' for yes, 'n' for no, 's' for skip, 'z' to increase distance, 'x' to decrease distance
    """
    print("\nPlease review the location in the opened preview.")
    print("Press 'y' for yes, 'n' for no, or 's' to skip")
    print("Use 'z' to increase spacing (+10px) or 'x' to decrease spacing (-10px)")
    print("(Keys work from any window)")
    choice = get_single_keypress(['y', 'n', 's', 'z', 'x'])
    if choice not in ['z', 'x']:  # Only close preview if not adjusting distance
        close_preview_windows()
    return choice

def prompt_user_for_xml_file():
    """Prompt user to select an XML file using file dialog"""
    root = tk.Tk()
    root.withdraw()  # Hide the root window
    file_path = filedialog.askopenfilename(title="Select XML File", filetypes=[("XML Files", "*.xml")])
    return file_path

def prompt_user_for_excel_file():
    """Prompt user to select an Excel file using file dialog."""
    root = tk.Tk()
    root.withdraw()  # Hide the root window
    file_path = filedialog.askopenfilename(
        title="Select Excel File", 
        filetypes=[("Excel Files", "*.xlsx *.xls")]
    )
    return file_path

def write_projects_to_temp_file(projects):
    """Write project details to a temporary file and open it"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
        temp_file.write("=== Project Details ===\n\n")
        
        for project in projects:
            temp_file.write("-------------------\n")
            temp_file.write(f"Project Name: {project.get('name', 'N/A')}\n")
            temp_file.write(f"Project ID: {project.get('id', 'N/A')}\n")
            temp_file.write(f"Created At: {project.get('created_at', 'N/A')}\n")
            temp_file.write(f"Updated At: {project.get('updated_at', 'N/A')}\n")
            temp_file.write(f"Status: {project.get('status', 'N/A')}\n")
            temp_file.write(f"Address: {project.get('address', 'N/A')}\n\n")

    # Open the file with the default text editor
    if platform.system() == 'Darwin':       # macOS
        subprocess.run(['open', temp_file.name])
    elif platform.system() == 'Windows':    # Windows
        os.startfile(temp_file.name)
    else:                                   # Linux
        subprocess.run(['xdg-open', temp_file.name])

    return temp_file.name

def get_user_input(prompt, required=True, default=None):
    """Get user input with validation"""
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value if value else default
        print("This field is required. Please enter a value.")

def get_pasted_column_data(prompt=None):
    """Get multi-line pasted data from the terminal, typically from an Excel column.
    Specifically designed for Windows environment.
    
    This function allows users to paste a column of data and processes it into a list.
    Users can finish input by pressing Ctrl+Z followed by Enter on a new line.
    
    Args:
        prompt (str, optional): Custom prompt message. If None, uses default Windows-specific instructions.
        
    Returns:
        list: List of non-empty strings from the input, with whitespace stripped
    """
    if prompt is None:
        print("\nPaste your Excel column data below:")
        print("1. Copy your data from Excel")
        print("2. Right-click in this terminal to paste")
        print("3. Press Enter to ensure you're on a new line")
        print("4. Press Ctrl+Z and then Enter to finish")
        print("\nPaste your data here:")
    else:
        print(prompt)
    
    lines = []
    try:
        while True:
            try:
                line = input()
                if line.strip():  # Only add non-empty lines
                    lines.append(line.strip())
            except EOFError:  # Ctrl+Z in Windows
                break
    except KeyboardInterrupt:  # Ctrl+C
        print("\nInput cancelled by user")
        return []
    
    if not lines:
        print("No data was received. Make sure to paste your data and press Ctrl+Z followed by Enter when done.")
    else:
        print(f"\nReceived {len(lines)} items.")
        
    return lines

def get_project_id_input(project_service):
    """Prompt user for project ID or name and resolve to project ID.
    
    Args:
        project_service: Instance of ProjectService
        
    Returns:
        str: Resolved project ID
    """
    while True:
        input_value = get_user_input("Enter project UUID or name: ").strip()
        
        if not input_value:
            print("Input cannot be empty. Please try again.")
            continue
            
        project_id = project_service.get_project_id_from_name_or_id(input_value)
        
        if project_id:
            return project_id
        else:
            print("Project not found. Please try again with a valid project UUID or exact project name.")
