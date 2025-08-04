"""Configuration constants for OneDrive Manager (odman)."""

# Microsoft Graph API constants
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]  # Scope for confidential client flow

# File size constants
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB
SMALL_FILE_THRESHOLD = 4 * 1024 * 1024  # 4 MiB

# Environment variable names
ENV_CLIENT_ID = "ONEDRIVE_CLIENT_ID"
ENV_TENANT_ID = "ONEDRIVE_TENANT_ID"
ENV_CLIENT_SECRET = "ONEDRIVE_CLIENT_SECRET"
ENV_USER_ID = "ONEDRIVE_USER_ID"

# Worker limits
MIN_WORKERS = 1
MAX_WORKERS = 10
DEFAULT_WORKERS = 3
