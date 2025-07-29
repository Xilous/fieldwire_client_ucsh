"""Export utilities for Fieldwire API data."""

import pandas as pd
import tkinter as tk
from tkinter import filedialog
import os

def get_export_file_path(default_name, file_extension):
    """Prompt user to select a file path for export using file dialog.
    
    Args:
        default_name (str): Default filename without extension
        file_extension (str): File extension (e.g., 'xlsx', 'csv')
    
    Returns:
        str: Selected file path or None if cancelled
    """
    root = tk.Tk()
    root.withdraw()  # Hide the root window
    
    # Set up file types based on extension
    if file_extension.lower() == 'xlsx':
        filetypes = [("Excel Files", "*.xlsx"), ("All Files", "*.*")]
    elif file_extension.lower() == 'csv':
        filetypes = [("CSV Files", "*.csv"), ("All Files", "*.*")]
    else:
        filetypes = [("All Files", "*.*")]
    
    # Ensure default name has the correct extension
    if not default_name.endswith(f'.{file_extension}'):
        default_name += f'.{file_extension}'
    
    file_path = filedialog.asksaveasfilename(
        title=f"Save {file_extension.upper()} File",
        defaultextension=f'.{file_extension}',
        filetypes=filetypes,
        initialfile=default_name
    )
    
    root.destroy()  # Clean up the tkinter root
    return file_path if file_path else None

def export_projects_to_csv(projects, filename):
    """Export project data to CSV file."""
    df = pd.DataFrame(projects)
    df.to_csv(filename, index=False)
    print(f"Projects exported to {filename}")

def export_tasks_to_csv(tasks, filename):
    """Export task data to CSV file."""
    df = pd.DataFrame(tasks)
    df.to_csv(filename, index=False)
    print(f"Tasks exported to {filename}")

def format_data(data):
    """Format data for export."""
    # future implementation for any specific formatting required
    formatted_data = data  
    return formatted_data 