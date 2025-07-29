"""Main entry point for Fieldwire API CLI."""

from cli.cli import run_cli
from core.auth import AuthManager
from services.project import ProjectService

def main():
    print("     __( )_")
    print("    (      (o____")
    print("     |          |")
    print("     |      (__/")
    print("       \     /   ___")
    print("       /     \  \___/")
    print("     /    ^    /     \ ")
    print("    |   |  |__|_TOKEN |")
    print("    |    \______)____/")
    print("     \         /")
    print("       \     /_")
    print("        |  ( __)")
    print("        (____)")

    bearer_token = input("Enter your Fieldwire Bearer Token: ")
    api = AuthManager(bearer_token)
    
    # Initialize project cache
    print("\nInitializing application...")
    project_service = ProjectService(api)
    if not project_service.initialize_project_cache():
        print("Warning: Failed to initialize project cache. Project name lookup will not be available.")
    
    run_cli(api, project_service)

if __name__ == "__main__":
    main()
                               