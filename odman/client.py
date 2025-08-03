"""Core OneDrive client for OneDrive Manager (odman)."""

import requests
import time
from rich.console import Console

from .config import GRAPH_API_ENDPOINT
from .auth import OneDriveAuth
from .stats import OperationStats

console = Console()


class OneDriveClient:
    """Core OneDrive client that handles basic API operations."""

    def __init__(
        self, client_id=None, client_secret=None, tenant_id=None, max_workers=3
    ):
        """Initialize the OneDrive client."""
        self.auth = OneDriveAuth(client_id, client_secret, tenant_id)
        self.stats = OperationStats()

        # Validate and set max_workers
        if max_workers < 1:
            console.print(
                "[yellow]⚠️ Warning: max_workers must be at least 1. Setting to 1.[/yellow]"
            )
            self.max_workers = 1
        elif max_workers > 10:
            console.print(
                "[yellow]⚠️ Warning: max_workers > 10 may cause API rate limiting. Setting to 10.[/yellow]"
            )
            self.max_workers = 10
        else:
            self.max_workers = max_workers

    def get_api_base_url(self, user_id):
        """Constructs the base URL for Graph API calls, targeting a specific user."""
        return f"{GRAPH_API_ENDPOINT}/users/{user_id}/drive"

    def retry_request(self, func, max_retries=3, delay=1):
        """Retry a function with exponential backoff."""
        for attempt in range(max_retries):
            try:
                return func()
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise e
                console.print(
                    f"[yellow]Request failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                time.sleep(delay * (2**attempt))  # Exponential backoff

    def ensure_remote_folder_exists(self, user_id, remote_folder_path):
        """Ensure that a remote folder path exists, creating it if necessary."""
        if not remote_folder_path:
            return

        api_base_url = self.get_api_base_url(user_id)
        headers = self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        path_parts = remote_folder_path.strip("/").split("/")
        current_path_for_api = ""

        for part in path_parts:
            if not part:
                continue

            parent_path_for_url = (
                "root" if not current_path_for_api else f"root:/{current_path_for_api}:"
            )
            create_folder_url = f"{api_base_url}/{parent_path_for_url}/children"

            folder_body = {
                "name": part,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            }

            try:

                def create_folder_request():
                    return requests.post(
                        create_folder_url, headers=headers, json=folder_body
                    )

                response = self.retry_request(create_folder_request)
                if response.status_code not in [201, 409]:  # 409 = already exists
                    response.raise_for_status()

            except requests.exceptions.RequestException as e:
                if "already exists" not in str(e).lower():
                    console.print(
                        f"[yellow]Warning: Could not create folder '{part}': {e}"
                    )

            if current_path_for_api:
                current_path_for_api += f"/{part}"
            else:
                current_path_for_api = part

    def list_files(self, user_id, folder_path="", recursive=False):
        """List files and folders in a OneDrive directory."""
        api_base_url = self.get_api_base_url(user_id)

        if folder_path:
            sanitized_path = requests.utils.quote(folder_path)
            list_url = f"{api_base_url}/root:/{sanitized_path}:/children"
        else:
            list_url = f"{api_base_url}/root/children"

        try:

            def list_request():
                return requests.get(list_url, headers=self.auth.get_headers())

            response = self.retry_request(list_request)
            response.raise_for_status()
            data = response.json()

            items = []
            for item in data.get("value", []):
                item_info = {
                    "name": item["name"],
                    "type": "folder" if "folder" in item else "file",
                    "size": item.get("size", 0),
                    "path": f"{folder_path}/{item['name']}"
                    if folder_path
                    else item["name"],
                }

                items.append(item_info)

                # If recursive and it's a folder, get its contents
                if recursive and item_info["type"] == "folder":
                    subfolder_path = item_info["path"]
                    subitems = self.list_files(user_id, subfolder_path, recursive=True)
                    items.extend(subitems)

            return items

        except requests.exceptions.RequestException as e:
            console.print(
                f"[red]Failed to list files in {folder_path or 'root'}: {str(e)}[/red]"
            )
            return []
