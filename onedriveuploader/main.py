import os
import sys
import argparse
import msal
import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    FileSizeColumn,
    TotalFileSizeColumn,
    DownloadColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich import box
from datetime import datetime

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

# Initialize Rich console
console = Console()


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

        # Upload statistics
        self.stats = {
            "total_files": 0,
            "successful_uploads": 0,
            "failed_uploads": 0,
            "total_size": 0,
            "uploaded_size": 0,
            "start_time": datetime.now(),
        }

    def _get_access_token(self):
        """
        Acquires an app-only access token using the client credentials flow.
        There is no user interaction and no token cache.
        """
        app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            authority=self.authority,
            client_credential=self.client_secret,
        )

        # The acquire_token_for_client method will automatically cache the token
        # in memory and refresh it when it expires.
        result = app.acquire_token_for_client(scopes=SCOPES)

        if "access_token" in result:
            return result["access_token"]
        else:
            console.print("❌ [bold red]ERROR: Failed to acquire access token.")
            console.print(f"[red]Error: {result.get('error')}")
            console.print(f"[red]Description: {result.get('error_description')}")
            console.print(
                "[yellow]Please check your credentials and ensure admin consent has been granted for Application Permissions in Azure."
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
                    pass  # Folder created successfully
                else:
                    response.raise_for_status()
            except requests.exceptions.RequestException as e:
                if e.response is not None and e.response.status_code == 409:
                    pass  # Folder already exists
                else:
                    # Re-raise for actual errors
                    raise

            if current_path_for_api:
                current_path_for_api = f"{current_path_for_api}/{part}"
            else:
                current_path_for_api = part

    def upload_directory(
        self,
        user_id,
        local_dir_path,
        destination_folder=None,
        chunk_size=CHUNK_SIZE,
        show_progress=True,
    ):
        """Uploads all files in a local directory to a OneDrive folder."""
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
                self.upload_any_file(
                    user_id,
                    local_file_path,
                    current_remote_folder,
                    chunk_size,
                    show_progress,
                )

    def upload_small_file(self, user_id, file_path, destination_path):
        """Uploads a file smaller than 4MB using a single PUT request."""
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        # Show progress bar for small files
        progress = Progress(
            TextColumn(f"[cyan]{filename}"),
            BarColumn(),
            TaskProgressColumn(),
            "•",
            FileSizeColumn(),
            "/",
            TotalFileSizeColumn(),
            console=console,
        )

        with progress:
            task = progress.add_task("", total=file_size)

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
                progress.update(task, advance=file_size)

                self.stats["successful_uploads"] += 1
                self.stats["uploaded_size"] += file_size

            except requests.exceptions.RequestException:
                self.stats["failed_uploads"] += 1
                # Silent error handling - just update stats

    def upload_large_file(
        self,
        user_id,
        file_path,
        destination_path,
        chunk_size=CHUNK_SIZE,
        show_progress=True,
    ):
        """Uploads a file of any size using a resumable upload session."""
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

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

            if show_progress:
                progress = Progress(
                    TextColumn(f"[cyan]{filename}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    "•",
                    DownloadColumn(),
                    "•",
                    TransferSpeedColumn(),
                    "•",
                    TimeElapsedColumn(),
                    "•",
                    TimeRemainingColumn(),
                    console=console,
                )

                with progress:
                    task = progress.add_task("", total=file_size)

                    with open(file_path, "rb") as f:
                        start_byte = 0
                        upload_response = None
                        while start_byte < file_size:
                            chunk = f.read(chunk_size)
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
                            progress.update(task, advance=chunk_len)
                            start_byte += chunk_len
            else:
                with open(file_path, "rb") as f:
                    start_byte = 0
                    upload_response = None
                    while start_byte < file_size:
                        chunk = f.read(chunk_size)
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
                        start_byte += chunk_len

            if upload_response and upload_response.status_code in [200, 201]:
                self.stats["successful_uploads"] += 1
                self.stats["uploaded_size"] += file_size

        except requests.exceptions.RequestException:
            self.stats["failed_uploads"] += 1
            # Silent error handling - just update stats

    def upload_any_file(
        self,
        user_id,
        file_path,
        destination_folder=None,
        chunk_size=CHUNK_SIZE,
        show_progress=True,
    ):
        """Determines the correct upload method and executes it."""
        if not os.path.exists(file_path):
            self.stats["failed_uploads"] += 1
            return

        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        self.stats["total_files"] += 1
        self.stats["total_size"] += file_size

        if destination_folder:
            clean_folder = destination_folder.strip("/")
            destination_path = f"{clean_folder}/{file_name}"
        else:
            destination_path = file_name

        if os.path.isdir(file_path):
            self.upload_directory(
                user_id, file_path, destination_folder, chunk_size, show_progress
            )
            return

        if file_size < SMALL_FILE_THRESHOLD:
            self.upload_small_file(user_id, file_path, destination_path)
        else:
            self.upload_large_file(
                user_id, file_path, destination_path, chunk_size, show_progress
            )

    def display_summary(self):
        """Display a comprehensive upload summary."""
        end_time = datetime.now()
        duration = end_time - self.stats["start_time"]

        # Create summary table
        summary_table = Table(show_header=False, box=box.SIMPLE)
        summary_table.add_column("Metric", style="cyan", width=20)
        summary_table.add_column("Value", style="white")

        # Calculate success rate
        total_attempted = (
            self.stats["successful_uploads"] + self.stats["failed_uploads"]
        )
        success_rate = (
            (self.stats["successful_uploads"] / total_attempted * 100)
            if total_attempted > 0
            else 0
        )

        # Calculate upload speed
        upload_speed_mb = (
            (self.stats["uploaded_size"] / 1024 / 1024) / duration.total_seconds()
            if duration.total_seconds() > 0
            else 0
        )

        summary_table.add_row(
            "📁 Total Files", f"[bold]{self.stats['total_files']}[/bold]"
        )
        summary_table.add_row(
            "✅ Successful",
            f"[bold green]{self.stats['successful_uploads']}[/bold green]",
        )
        summary_table.add_row(
            "❌ Failed", f"[bold red]{self.stats['failed_uploads']}[/bold red]"
        )
        summary_table.add_row("📊 Success Rate", f"[bold]{success_rate:.1f}%[/bold]")
        summary_table.add_row(
            "💾 Total Size",
            f"[bold]{self.stats['total_size'] / 1024 / 1024:.2f} MB[/bold]",
        )
        summary_table.add_row(
            "📤 Uploaded",
            f"[bold green]{self.stats['uploaded_size'] / 1024 / 1024:.2f} MB[/bold green]",
        )
        summary_table.add_row(
            "⏱️ Duration", f"[bold]{str(duration).split('.')[0]}[/bold]"
        )
        summary_table.add_row("🚀 Speed", f"[bold]{upload_speed_mb:.2f} MB/s[/bold]")

        # Determine panel color based on success rate
        if success_rate == 100:
            panel_style = "green"
            title_icon = "🎉"
        elif success_rate >= 80:
            panel_style = "yellow"
            title_icon = "⚠️"
        else:
            panel_style = "red"
            title_icon = "❌"

        console.print("\n")
        console.print(
            Panel(
                summary_table,
                title=f"[bold]{title_icon} Upload Summary[/bold]",
                border_style=panel_style,
                padding=(1, 2),
            )
        )


def main():
    """
    Main function to handle command-line arguments and initiate the upload.
    """
    # Display header
    console.print("\n")
    console.print(
        Panel(
            "[bold blue]OneDrive Uploader[/bold blue]\n"
            "[dim]Professional file upload tool for Microsoft OneDrive[/dim]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Upload one or more files to a user's OneDrive using app-only authentication.",
        epilog="""
        This script uses confidential client authentication. Ensure that the required
        environment variables (ONEDRIVE_CLIENT_ID, ONEDRIVE_TENANT_ID,
        ONEDRIVE_CLIENT_SECRET, ONEDRIVE_USER_ID) are set before running.
        The application must be granted the 'Files.ReadWrite.All' Application Permission
        in Azure AD and have received admin consent.
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "local_file_paths",
        nargs="+",
        help="The local paths to the files to upload.",
    )
    parser.add_argument(
        "-r",
        "--remote-folder",
        default="",
        help="The destination folder in OneDrive. If not specified, uploads to the root.",
    )
    parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"The chunk size for large file uploads in bytes. Default is {CHUNK_SIZE} bytes.",
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable the progress bar."
    )

    args = parser.parse_args()

    # --- Pre-flight Checks ---
    console.print("\n")
    console.print("[bold cyan]🔍 Running Pre-flight Checks...[/bold cyan]")

    checks_table = Table(show_header=False, box=box.SIMPLE)
    checks_table.add_column("Check", style="white", width=40)
    checks_table.add_column("Status", style="white", width=15)

    # Environment Variable Check
    client_id = os.getenv("ONEDRIVE_CLIENT_ID")
    tenant_id = os.getenv("ONEDRIVE_TENANT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
    user_id = os.getenv("ONEDRIVE_USER_ID")

    env_vars_ok = all([client_id, tenant_id, client_secret, user_id])
    checks_table.add_row(
        "Environment Variables",
        "✅ [green]PASS[/green]" if env_vars_ok else "❌ [red]FAIL[/red]",
    )

    # File existence checks
    files_exist = True
    total_size = 0
    for file_path in args.local_file_paths:
        if not os.path.exists(file_path):
            files_exist = False
            break
        if os.path.isfile(file_path):
            total_size += os.path.getsize(file_path)
        elif os.path.isdir(file_path):
            for root, _, files in os.walk(file_path):
                for file in files:
                    total_size += os.path.getsize(os.path.join(root, file))

    checks_table.add_row(
        "File/Directory Paths",
        "✅ [green]PASS[/green]" if files_exist else "❌ [red]FAIL[/red]",
    )

    # Network connectivity (basic check)
    try:
        import socket

        socket.create_connection(("graph.microsoft.com", 443), timeout=5)
        network_ok = True
    except Exception:
        network_ok = False

    checks_table.add_row(
        "Network Connectivity",
        "✅ [green]PASS[/green]" if network_ok else "❌ [red]FAIL[/red]",
    )

    # Display checks
    console.print(
        Panel(checks_table, title="[bold]🔧 System Checks[/bold]", border_style="cyan")
    )

    # Exit if checks failed
    if not env_vars_ok:
        console.print(
            "\n❌ [bold red]ERROR: Missing one or more required environment variables:"
        )
        console.print(
            "[red]ONEDRIVE_CLIENT_ID, ONEDRIVE_TENANT_ID, ONEDRIVE_CLIENT_SECRET, ONEDRIVE_USER_ID"
        )
        sys.exit(1)

    if not files_exist:
        for file_path in args.local_file_paths:
            if not os.path.exists(file_path):
                console.print(
                    f"\n❌ [bold red]ERROR: The file '{file_path}' does not exist."
                )
        sys.exit(1)

    # Display upload plan
    plan_table = Table(show_header=True, box=box.SIMPLE)
    plan_table.add_column("File/Directory", style="cyan")
    plan_table.add_column("Type", style="white")
    plan_table.add_column("Size", style="yellow")

    for file_path in args.local_file_paths:
        if os.path.isfile(file_path):
            size = os.path.getsize(file_path)
            plan_table.add_row(
                os.path.basename(file_path), "📄 File", f"{size / 1024 / 1024:.2f} MB"
            )
        elif os.path.isdir(file_path):
            file_count = sum(len(files) for _, _, files in os.walk(file_path))
            dir_size = sum(
                os.path.getsize(os.path.join(root, file))
                for root, _, files in os.walk(file_path)
                for file in files
            )
            plan_table.add_row(
                os.path.basename(file_path),
                f"📁 Directory ({file_count} files)",
                f"{dir_size / 1024 / 1024:.2f} MB",
            )

    plan_table.add_row("", "", "")
    plan_table.add_row("[bold]TOTAL", "", f"[bold]{total_size / 1024 / 1024:.2f} MB")

    console.print("\n")
    console.print(
        Panel(
            plan_table,
            title="[bold green]📋 Upload Plan[/bold green]",
            border_style="green",
        )
    )

    # --- Upload Process ---

    try:
        uploader = OneDriveUploader(client_id, client_secret, tenant_id)

        for local_path in args.local_file_paths:
            if os.path.isdir(local_path):
                uploader.upload_directory(
                    user_id=user_id,
                    local_dir_path=local_path,
                    destination_folder=args.remote_folder,
                    chunk_size=args.chunk_size,
                    show_progress=not args.no_progress,
                )
            elif os.path.isfile(local_path):
                uploader.upload_any_file(
                    user_id=user_id,
                    file_path=local_path,
                    destination_folder=args.remote_folder,
                    chunk_size=args.chunk_size,
                    show_progress=not args.no_progress,
                )
            else:
                console.print(
                    f"⚠️ [yellow]WARNING: Path '{local_path}' is not a file or directory, skipping."
                )
                continue

        # Display final summary
        uploader.display_summary()

    except Exception as e:
        console.print(
            f"\n❌ [bold red]An unexpected error occurred during the upload process: {e}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
