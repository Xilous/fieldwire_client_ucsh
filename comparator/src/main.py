import typer
from typing import Optional
from src.parser import XMLParser
from src.comparator import Comparator
from src.ui import UI
from src.exporter import Exporter

app = typer.Typer()

@app.command()
def compare(
    old_file: Optional[str] = typer.Argument(None),
    new_file: Optional[str] = typer.Argument(None),
    export_file: Optional[str] = typer.Option(None, "--export", "-e")
):
    """Compare two door hardware schedule XML files."""
    ui = UI()
    
    # Get file paths if not provided
    if not old_file or not new_file:
        old_file, new_file = ui.prompt_for_files()
    
    try:
        # Parse XML files
        parser = XMLParser()
        old_openings = parser.parse_file(old_file)
        new_openings = parser.parse_file(new_file)
        
        # Compare openings
        comparator = Comparator()
        summary = comparator.compare(old_openings, new_openings)
        
        # Show summary
        ui.show_summary(summary)
        
        # Interactive opening details view
        while True:
            selected_change = ui.show_changed_openings_list(summary.changes)
            if not selected_change:
                break
            
            ui.show_opening_details(selected_change)
        
        # Export if requested
        if export_file or (export_path := ui.export_prompt()):
            Exporter.export_to_json(
                summary,
                old_file,
                new_file,
                export_file or export_path
            )
    
    except Exception as e:
        typer.echo(f"Error: {str(e)}", err=True)
        raise typer.Exit(1)

def main():
    """Entry point for direct execution."""
    app()

if __name__ == "__main__":
    main() 