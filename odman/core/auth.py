"""Authentication module for OneDrive Manager (odman)."""

import os
import sys
import msal
from rich.console import Console

from odman.core.config import SCOPES, ENV_CLIENT_ID, ENV_TENANT_ID, ENV_CLIENT_SECRET, ENV_USER_ID

console = Console()


class OneDriveAuth:
    """Handles OneDrive authentication using Microsoft Graph API."""

    def __init__(self, client_id=None, client_secret=None, tenant_id=None):
        """Initialize authentication with credentials."""
        self.client_id = client_id or os.getenv(ENV_CLIENT_ID)
        self.client_secret = client_secret or os.getenv(ENV_CLIENT_SECRET)
        self.tenant_id = tenant_id or os.getenv(ENV_TENANT_ID)

        if not all([self.client_id, self.client_secret, self.tenant_id]):
            console.print(
                "❌ [bold red]ERROR: Missing required authentication credentials."
            )
            console.print(
                f"[red]Required environment variables: {ENV_CLIENT_ID}, {ENV_TENANT_ID}, {ENV_CLIENT_SECRET}"
            )
            sys.exit(1)

        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.access_token = None

    def get_access_token(self):
        """
        Acquires an app-only access token using the client credentials flow.
        There is no user interaction and no token cache.
        """
        if self.access_token:
            return self.access_token

        app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            authority=self.authority,
            client_credential=self.client_secret,
        )

        # The acquire_token_for_client method will automatically cache the token
        # in memory and refresh it when it expires.
        result = app.acquire_token_for_client(scopes=SCOPES)

        if "access_token" in result:
            self.access_token = result["access_token"]
            return self.access_token
        else:
            console.print("❌ [bold red]ERROR: Failed to acquire access token.")
            console.print(f"[red]Error: {result.get('error')}")
            console.print(f"[red]Description: {result.get('error_description')}")
            console.print(
                "[yellow]Please check your credentials and ensure admin consent has been granted for Application Permissions in Azure."
            )
            sys.exit(1)

    def get_headers(self):
        """Constructs the default headers for API requests."""
        token = self.get_access_token()
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def get_user_id():
        """Get the target user ID from environment variables."""
        user_id = os.getenv(ENV_USER_ID)
        if not user_id:
            console.print(
                f"❌ [bold red]ERROR: Missing required environment variable: {ENV_USER_ID}"
            )
            sys.exit(1)
        return user_id

    @staticmethod
    def validate_environment():
        """Validate that all required environment variables are set."""
        required_vars = [ENV_CLIENT_ID, ENV_TENANT_ID, ENV_CLIENT_SECRET, ENV_USER_ID]
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            console.print("❌ [bold red]ERROR: Missing required environment variables:")
            for var in missing_vars:
                console.print(f"[red]  - {var}")
            console.print(
                "\n[yellow]Please set these environment variables before running odman."
            )
            return False

        return True
