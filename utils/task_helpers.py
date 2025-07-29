"""Task helper functions for Fieldwire API."""

def compare_openings_with_tasks(openings, tasks):
    """Compare openings with tasks to find unmatched ones."""
    task_names = [task['name'] for task in tasks]
    unmatched_openings = [opening for opening in openings if opening["Number"] not in task_names]
    return unmatched_openings 