"""Status service for Fieldwire API."""

from core.auth import AuthManager
from utils.decorators import paginate_response

class StatusService(AuthManager):
    """Service for status operations."""

    @paginate_response()
    def get_statuses_for_project_id(self, project_id):
        """Get all statuses in a project with pagination support."""
        url = f"{self.project_base_url}/projects/{project_id}/statuses"
        return url 