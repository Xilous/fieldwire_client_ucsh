from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt
from typing import List, Optional, Tuple
from src.models import ComparisonSummary, OpeningChange
import tkinter as tk
from tkinter import filedialog

class UI:
    """User interface for displaying comparison results."""
    
    def __init__(self):
        self.console = Console()
        # Initialize root window but keep it hidden
        self.root = tk.Tk()
        self.root.withdraw()
    
    def show_summary(self, summary: ComparisonSummary):
        """Display comparison summary."""
        self.console.print("\n[bold blue]Door Hardware Schedule Comparison Summary[/bold blue]")
        
        # Create summary table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="dim")
        table.add_column("Count", justify="right")
        
        table.add_row(
            "Total Changed Openings",
            str(summary.total_changed_openings)
        )
        table.add_row(
            "Openings with Door Info Changes",
            str(summary.openings_with_door_info_changes)
        )
        table.add_row(
            "Openings with Hardware Changes",
            str(summary.openings_with_hardware_changes)
        )
        
        self.console.print(table)
    
    def show_changed_openings_list(
        self,
        changes: List[OpeningChange]
    ) -> Optional[OpeningChange]:
        """
        Display list of changed openings and let user select one for details.
        Returns selected opening change or None if user chooses to exit.
        """
        self.console.print("\n[bold blue]Changed Openings[/bold blue]")
        
        # Create openings table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim")
        table.add_column("Opening Number")
        table.add_column("Door Info Changes")
        table.add_column("Hardware Changes")
        
        for idx, change in enumerate(changes, 1):
            table.add_row(
                str(idx),
                change.number,
                str(len(change.door_info_changes)),
                str(len(change.hardware_changes))
            )
        
        self.console.print(table)
        
        # Get user selection
        choice = Prompt.ask(
            "\nEnter opening number to view details (or 'q' to quit)",
            choices=[str(i) for i in range(1, len(changes) + 1)] + ['q']
        )
        
        if choice == 'q':
            return None
        
        return changes[int(choice) - 1]
    
    def show_opening_details(self, change: OpeningChange):
        """Display detailed changes for a specific opening."""
        self.console.print(f"\n[bold blue]Details for Opening {change.number}[/bold blue]")
        
        # Show door info changes
        if change.door_info_changes:
            door_panel = Table(show_header=True, header_style="bold cyan")
            door_panel.add_column("Field")
            door_panel.add_column("Old Value")
            door_panel.add_column("New Value")
            
            for info_change in change.door_info_changes:
                door_panel.add_row(
                    info_change.field,
                    info_change.old_value,
                    info_change.new_value
                )
            
            self.console.print(Panel(
                door_panel,
                title="Door Information Changes",
                border_style="cyan"
            ))
        
        # Show hardware changes
        if change.hardware_changes:
            # Group changes by type
            added = [c for c in change.hardware_changes if c.type == 'added']
            deleted = [c for c in change.hardware_changes if c.type == 'deleted']
            modified = [c for c in change.hardware_changes if c.type == 'modified']
            
            if added:
                self._show_hardware_group(added, "Added Hardware", "green")
            
            if deleted:
                self._show_hardware_group(deleted, "Deleted Hardware", "red")
            
            if modified:
                self._show_modified_hardware(modified)
    
    def _show_hardware_group(self, changes, title: str, color: str):
        """Display a group of hardware changes."""
        table = Table(show_header=True, header_style=f"bold {color}")
        table.add_column("Short Code")
        table.add_column("Product Code")
        table.add_column("Sub Category")
        table.add_column("Quantity")
        table.add_column("Handing")
        table.add_column("Finish")
        
        for change in changes:
            table.add_row(
                change.item.short_code,
                change.item.product_code,
                change.item.sub_category,
                str(change.item.quantity_active),
                str(change.item.handing),
                str(change.item.finish_ansi)
            )
        
        self.console.print(Panel(table, title=title, border_style=color))
    
    def _show_modified_hardware(self, changes):
        """Display modified hardware items."""
        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("Hardware")
        table.add_column("Field")
        table.add_column("Old Value")
        table.add_column("New Value")
        
        for change in changes:
            hardware_id = (
                f"{change.item.short_code} - "
                f"{change.item.product_code} - "
                f"{change.item.sub_category}"
            )
            
            for field, values in change.modifications.items():
                table.add_row(
                    hardware_id,
                    field,
                    values['old'],
                    values['new']
                )
        
        self.console.print(Panel(
            table,
            title="Modified Hardware",
            border_style="yellow"
        ))
    
    def prompt_for_files(self) -> Tuple[str, str]:
        """Prompt user for old and new file paths using file dialog."""
        self.console.print("\n[bold blue]Select the OLD version XML file[/bold blue]")
        old_file = filedialog.askopenfilename(
            title="Select OLD version XML file",
            filetypes=[("XML files", "*.xml")]
        )
        
        if not old_file:
            raise ValueError("No file selected for OLD version")
            
        self.console.print("\n[bold blue]Select the NEW version XML file[/bold blue]")
        new_file = filedialog.askopenfilename(
            title="Select NEW version XML file",
            filetypes=[("XML files", "*.xml")]
        )
        
        if not new_file:
            raise ValueError("No file selected for NEW version")
            
        return old_file, new_file
    
    def export_prompt(self) -> Optional[str]:
        """Prompt user for export file path."""
        if Prompt.ask(
            "Would you like to export the changes report?",
            choices=["y", "n"]
        ) == "y":
            return filedialog.asksaveasfilename(
                title="Save JSON Report",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json")]
            )
        return None 