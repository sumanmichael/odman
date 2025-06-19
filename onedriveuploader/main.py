import os
import sys
import argparse
import json
import msal
import requests
from tqdm import tqdm

# --- CONFIGURATION ---
# This script reads credentials from environment variables for security.
# Set these in your environment before running:
#
# 1. ONEDRIVE_CLIENT_ID: Your Application (client) ID.
# 2. ONEDRIVE_TENANT_ID: Your Directory (tenant) ID.
# 3. ONEDRIVE_CLIENT_SECRET: Your Client Secret value.
# 4. ONEDRIVE_USER_ID: The User ID or User Principal Name (email) of the target OneDrive account.
#
# Example (Linux/macOS):
# export ONEDRIVE_CLIENT_ID="your-client-id"
# export ONEDRIVE_TENANT_ID="your-tenant-id"
# export ONEDRIVE_CLIENT_SECRET="your-client-secret"
# export ONEDRIVE_USER_ID="user@example.com"
#
# Example (Windows PowerShell):
# $env:ONEDRIVE_CLIENT_ID="your-client-id"
# $env:ONEDRIVE_TENANT_ID="your-tenant-id"
# $env:ONEDRIVE_CLIENT_SECRET="your-client-secret"
# $env:ONEDRIVE_USER_ID="user@example.com"

# Microsoft Graph API constants
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]  # Scope for confidential client flow

# File size constants
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB
SMALL_FILE_THRESHOLD = 4 * 1024 * 1024  # 4 MiB


class OneDriveUploader:
    """
    Handles file uploads to a specific user's OneDrive using a confidential
    client application flow (app-only authentication).
    """

    def __init__(self, client_id, client_secret, tenant_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authority = f"https://login.microsoftonline.com/{tenant_id}"
        self.access_token = self._get_access_token()

    def _get_access_token(self):
        """
        Acquires an app-only access token using the client credentials flow.
        There is no user interaction and no token cache.
        """
        print("Attempting to acquire app-only access token...")
        app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            authority=self.authority,
            client_credential=self.client_secret,
        )

        # The acquire_token_for_client method will automatically cache the token
        # in memory and refresh it when it expires.
        result = app.acquire_token_for_client(scopes=SCOPES)

        if "access_token" in result:
            print("Successfully acquired app-only access token.")
            return result["access_token"]
        else:
            print("ERROR: Failed to acquire access token.")
            print(f"Error: {result.get('error')}")
            print(f"Description: {result.get('error_description')}")
            print(
                "Please check your credentials and ensure admin consent has been granted for Application Permissions in Azure."
            )
            sys.exit(1)

    def _get_headers(self):
        """Constructs the default headers for API requests."""
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get_api_base_url(self, user_id):
        """
        Constructs the base URL for Graph API calls, targeting a specific user.
        """
        return f"{GRAPH_API_ENDPOINT}/users/{user_id}/drive"

    def _ensure_remote_folder_exists(self, user_id, remote_folder_path):
        if not remote_folder_path:
            return

        print(f"Ensuring remote directory '{remote_folder_path}' exists...")
        api_base_url = self._get_api_base_url(user_id)
        headers = self._get_headers()
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
                response = requests.post(
                    create_folder_url, headers=headers, json=folder_body
                )
                if response.status_code == 201:
                    print(
                        f"Created folder '{part}' in '{current_path_for_api or 'root'}'"
                    )
                else:
                    response.raise_for_status()
            except requests.exceptions.RequestException as e:
                if e.response is not None and e.response.status_code == 409:
                    print(
                        f"Folder '{part}' already exists in '{current_path_for_api or 'root'}'"
                    )
                else:
                    print(f"ERROR: Error creating folder '{part}': {e}")
                    if e.response is not None:
                        print(f"Response Body: {e.response.text}")
                    raise

            if current_path_for_api:
                current_path_for_api = f"{current_path_for_api}/{part}"
            else:
                current_path_for_api = part

    def upload_directory(self, user_id, local_dir_path, destination_folder=None):
        """Uploads all files in a local directory to a OneDrive folder."""
        print(f"\nUploading directory '{local_dir_path}'...")

        local_dir_name = os.path.basename(os.path.abspath(local_dir_path))

        if destination_folder:
            remote_root_folder = f"{destination_folder.strip('/')}/{local_dir_name}"
        else:
            remote_root_folder = local_dir_name

        for root, _, files in os.walk(local_dir_path):
            if not files:
                continue

            relative_path = os.path.relpath(root, local_dir_path)
            if relative_path == ".":
                current_remote_folder = remote_root_folder
            else:
                current_remote_folder = os.path.join(
                    remote_root_folder, relative_path
                ).replace("\\", "/")

            self._ensure_remote_folder_exists(user_id, current_remote_folder)

            for filename in files:
                local_file_path = os.path.join(root, filename)
                self.upload_any_file(user_id, local_file_path, current_remote_folder)

    def upload_small_file(self, user_id, file_path, destination_path):
        """Uploads a file smaller than 4MB using a single PUT request."""
        print(f"Performing small file upload for '{os.path.basename(file_path)}'...")
        api_base_url = self._get_api_base_url(user_id)
        sanitized_path = requests.utils.quote(destination_path)
        upload_url = f"{api_base_url}/root:/{sanitized_path}:/content"

        try:
            with open(file_path, "rb") as f:
                file_content = f.read()
            headers = self._get_headers()
            headers["Content-Type"] = "application/octet-stream"
            response = requests.put(upload_url, headers=headers, data=file_content)
            response.raise_for_status()
            print("Small file uploaded successfully!")
            print(json.dumps(response.json(), indent=2))
        except requests.exceptions.RequestException as e:
            print(f"Error during small file upload: {e}")
            if e.response is not None:
                print(f"Response Body: {e.response.text}")

    def upload_large_file(self, user_id, file_path, destination_path):
        """Uploads a file of any size using a resumable upload session."""
        print(f"Performing large file upload for '{os.path.basename(file_path)}'...")
        api_base_url = self._get_api_base_url(user_id)
        sanitized_path = requests.utils.quote(destination_path)
        session_url = f"{api_base_url}/root:/{sanitized_path}:/createUploadSession"
        session_body = {"item": {"@microsoft.graph.conflictBehavior": "replace"}}

        try:
            session_response = requests.post(
                session_url, headers=self._get_headers(), json=session_body
            )
            session_response.raise_for_status()
            upload_session = session_response.json()
            upload_url = upload_session["uploadUrl"]
            print("Upload session created.")

            file_size = os.path.getsize(file_path)
            with open(file_path, "rb") as f:
                with tqdm(
                    total=file_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=f"Uploading {os.path.basename(file_path)}",
                ) as pbar:
                    start_byte = 0
                    upload_response = None
                    while start_byte < file_size:
                        chunk = f.read(CHUNK_SIZE)
                        chunk_len = len(chunk)
                        end_byte = start_byte + chunk_len - 1
                        chunk_headers = {
                            "Content-Length": str(chunk_len),
                            "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
                        }

                        upload_response = requests.put(
                            upload_url, headers=chunk_headers, data=chunk
                        )
                        upload_response.raise_for_status()
                        pbar.update(chunk_len)
                        start_byte += chunk_len

            if upload_response and upload_response.status_code in [200, 201]:
                print("\nLarge file uploaded successfully!")
                print(json.dumps(upload_response.json(), indent=2))

        except requests.exceptions.RequestException as e:
            print(f"Error during large file upload: {e}")
            if e.response is not None:
                print(f"Response Body: {e.response.text}")

    def upload_any_file(self, user_id, file_path, destination_folder=None):
        """Determines the correct upload method and executes it."""
        if not os.path.exists(file_path):
            print(f"Error: Source file not found at '{file_path}'")
            return

        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)

        if destination_folder:
            clean_folder = destination_folder.strip("/")
            destination_path = f"{clean_folder}/{file_name}"
        else:
            destination_path = file_name

        print(f"\nSource: '{file_path}' ({file_size / 1024 / 1024:.2f} MB)")
        print(f"Target User ID: {user_id}")
        print(f"Destination: OneDrive Root:/{destination_path}")

        if file_size < SMALL_FILE_THRESHOLD:
            self.upload_small_file(user_id, file_path, destination_path)
        else:
            self.upload_large_file(user_id, file_path, destination_path)


def main():
    """Main function to parse arguments and run the uploader."""
    # --- CLI Parser ---
    parser = argparse.ArgumentParser(
        description="Upload files or directories to a specific user's OneDrive using app-only authentication.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Environment Variables:
  This script requires the following environment variables to be set for authentication:

  1. ONEDRIVE_CLIENT_ID: Your Application (client) ID.
  2. ONEDRIVE_TENANT_ID: Your Directory (tenant) ID.
  3. ONEDRIVE_CLIENT_SECRET: Your Client Secret value.
  4. ONEDRIVE_USER_ID: The User ID or User Principal Name (email) of the target OneDrive account.
""",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="The full local path of the file or directory to upload.",
    )
    parser.add_argument(
        "-d",
        "--destination",
        dest="destination_folder",
        help="The destination folder in the user's OneDrive root (e.g., 'Shared/Reports').",
        default=None,
    )

    args = parser.parse_args()

    if not args.path:
        parser.print_help()
        sys.exit(0)

    # --- Load Configuration from Environment ---
    client_id = os.getenv("ONEDRIVE_CLIENT_ID")
    tenant_id = os.getenv("ONEDRIVE_TENANT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
    user_id = os.getenv("ONEDRIVE_USER_ID")

    if not all([client_id, tenant_id, client_secret, user_id]):
        print("ERROR: One or more environment variables are not set.")
        print(
            "Please set ONEDRIVE_CLIENT_ID, ONEDRIVE_TENANT_ID, ONEDRIVE_CLIENT_SECRET, and ONEDRIVE_USER_ID."
        )
        sys.exit(1)

    # --- Execute Upload ---
    try:
        uploader = OneDriveUploader(client_id, client_secret, tenant_id)
        if os.path.isdir(args.path):
            uploader.upload_directory(user_id, args.path, args.destination_folder)
        elif os.path.isfile(args.path):
            uploader.upload_any_file(user_id, args.path, args.destination_folder)
        else:
            print(f"ERROR: Path not found or is not a file/directory: {args.path}")
            sys.exit(1)
    except Exception as e:
        print(f"\nA critical error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
