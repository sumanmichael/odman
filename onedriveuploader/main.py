import os
import sys
import argparse
import msal
import requests
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
    FileSizeColumn,
    TotalFileSizeColumn,
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


def truncate_path(path, max_length=40):
    """Truncate a file path with ellipses if it's too long."""
    if len(path) <= max_length:
        return path

    # Try to keep the filename and some parent directory info
    filename = os.path.basename(path)
    if len(filename) >= max_length - 3:
        return f"...{filename[-(max_length-3):]}"

    # Calculate how much space we have for the directory part
    remaining_space = max_length - len(filename) - 3  # 3 for "..."
    if remaining_space > 0:
        dir_part = os.path.dirname(path)
        if len(dir_part) > remaining_space:
            dir_part = dir_part[:remaining_space]
        return f"...{dir_part}/{filename}"
    else:
        return f"...{filename}"


class OneDriveUploader:
    """
    Handles file uploads to a specific user's OneDrive using a confidential
    client application flow (app-only authentication).
    """

    def __init__(self, client_id, client_secret, tenant_id, max_workers=3):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authority = f"https://login.microsoftonline.com/{tenant_id}"

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

        self.access_token = self._get_access_token()

        # Upload statistics (thread-safe)
        self._stats_lock = threading.Lock()
        self.stats = {
            "total_files": 0,
            "successful_uploads": 0,
            "failed_uploads": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "total_size": 0,
            "uploaded_size": 0,
            "downloaded_size": 0,
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

    def _update_stats(self, **kwargs):
        """Thread-safe method to update upload statistics."""
        with self._stats_lock:
            for key, value in kwargs.items():
                if key in self.stats:
                    self.stats[key] += value

    def _retry_request(self, func, max_retries=3, delay=1):
        """Retry a function with exponential backoff."""
        for attempt in range(max_retries):
            try:
                return func()
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise
                if hasattr(e, "response") and e.response is not None:
                    if e.response.status_code == 429:  # Rate limited
                        retry_after = int(e.response.headers.get("Retry-After", delay))
                        time.sleep(retry_after)
                    elif e.response.status_code >= 500:  # Server error
                        time.sleep(delay * (2**attempt))
                    else:
                        raise  # Don't retry for client errors
                else:
                    time.sleep(delay * (2**attempt))

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
        """Uploads all files in a local directory to a OneDrive folder using parallel processing."""
        local_dir_name = os.path.basename(os.path.abspath(local_dir_path))

        if destination_folder:
            remote_root_folder = f"{destination_folder.strip('/')}/{local_dir_name}"
        else:
            remote_root_folder = local_dir_name

        # Collect all files to upload
        upload_tasks = []
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

            # Ensure the folder exists first
            self._ensure_remote_folder_exists(user_id, current_remote_folder)

            for filename in files:
                local_file_path = os.path.join(root, filename)
                upload_tasks.append(
                    (
                        user_id,
                        local_file_path,
                        current_remote_folder,
                        chunk_size,
                        None,  # progress_callback - will be set during upload
                    )
                )

        # Upload files in parallel
        if upload_tasks:
            console.print(
                f"[cyan]📁 Uploading {len(upload_tasks)} files from directory with {self.max_workers} workers...[/cyan]"
            )

            # Create progress tracker if needed
            if show_progress:
                progress = Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    "•",
                    FileSizeColumn(),
                    "/",
                    TotalFileSizeColumn(),
                    "•",
                    TransferSpeedColumn(),
                    "•",
                    TimeElapsedColumn(),
                    "•",
                    TimeRemainingColumn(),
                    console=console,
                )

                # Calculate total size for overall progress
                total_size = sum(
                    os.path.getsize(task[1])
                    for task in upload_tasks
                    if os.path.isfile(task[1])
                )

                with progress:
                    overall_task = progress.add_task(
                        "Directory Progress", total=total_size
                    )
                    file_tasks = {}

                    for task in upload_tasks:
                        file_path = task[1]
                        if os.path.isfile(file_path):
                            filename = os.path.basename(file_path)
                            file_size = os.path.getsize(file_path)
                            task_id = progress.add_task(
                                f"📄 {filename}", total=file_size
                            )
                            file_tasks[file_path] = task_id

                    def upload_with_progress(task):
                        """Upload a single file with progress callback."""
                        user_id, file_path, destination_folder, chunk_size, _ = task

                        def progress_callback(bytes_uploaded):
                            if file_path in file_tasks:
                                progress.update(
                                    file_tasks[file_path], advance=bytes_uploaded
                                )
                            progress.update(overall_task, advance=bytes_uploaded)

                        return self.upload_any_file(
                            user_id=user_id,
                            file_path=file_path,
                            destination_folder=destination_folder,
                            chunk_size=chunk_size,
                            progress_callback=progress_callback,
                        )

                    with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                        futures = []
                        for task in upload_tasks:
                            future = executor.submit(upload_with_progress, task)
                            futures.append((future, task[1]))  # Keep track of file path

                        # Process completed uploads
                        completed = 0
                        for future, file_path in zip(
                            futures, [task[1] for task in upload_tasks]
                        ):
                            try:
                                future.result()  # This will raise any exceptions that occurred
                                completed += 1
                            except Exception as e:
                                console.print(
                                    f"[red]❌ Failed {os.path.basename(file_path)}: {e}[/red]"
                                )
                                self._update_stats(failed_uploads=1)
            else:
                # No progress display
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = []
                    for task in upload_tasks:
                        future = executor.submit(self.upload_any_file, *task)
                        futures.append((future, task[1]))  # Keep track of file path

                    # Process completed uploads
                    completed = 0
                    for future, file_path in zip(
                        futures, [task[1] for task in upload_tasks]
                    ):
                        try:
                            future.result()  # This will raise any exceptions that occurred
                            completed += 1
                            console.print(
                                f"[green]✅ Completed {completed}/{len(upload_tasks)}: {os.path.basename(file_path)}[/green]"
                            )
                        except Exception as e:
                            console.print(
                                f"[red]❌ Failed {os.path.basename(file_path)}: {e}[/red]"
                            )
                            self._update_stats(failed_uploads=1)
        else:
            console.print("[yellow]No files found in directory to upload.[/yellow]")

    def _create_file_progress(self, filename, file_size):
        """Create a progress display for individual file uploads with enhanced columns."""
        return Progress(
            TextColumn(f"[cyan]{filename}"),
            BarColumn(),
            TaskProgressColumn(),
            "•",
            FileSizeColumn(),
            "/",
            TotalFileSizeColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeElapsedColumn(),
            "•",
            TimeRemainingColumn(),
            console=console,
        )

    def upload_small_file(
        self, user_id, file_path, destination_path, progress_callback=None
    ):
        """Uploads a file smaller than 4MB using a single PUT request."""
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        api_base_url = self._get_api_base_url(user_id)
        sanitized_path = requests.utils.quote(destination_path)
        upload_url = f"{api_base_url}/root:/{sanitized_path}:/content"

        try:
            with open(file_path, "rb") as f:
                file_content = f.read()

            def upload_request():
                headers = self._get_headers()
                headers["Content-Type"] = "application/octet-stream"
                response = requests.put(upload_url, headers=headers, data=file_content)
                response.raise_for_status()
                return response

            self._retry_request(upload_request)

            if progress_callback:
                progress_callback(file_size)

            self._update_stats(successful_uploads=1, uploaded_size=file_size)

        except requests.exceptions.RequestException as e:
            console.print(f"[red]Failed to upload {filename}: {str(e)}[/red]")
            self._update_stats(failed_uploads=1)

    def upload_large_file(
        self,
        user_id,
        file_path,
        destination_path,
        chunk_size=CHUNK_SIZE,
        progress_callback=None,
    ):
        """Uploads a file of any size using a resumable upload session."""
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        api_base_url = self._get_api_base_url(user_id)
        sanitized_path = requests.utils.quote(destination_path)
        session_url = f"{api_base_url}/root:/{sanitized_path}:/createUploadSession"
        session_body = {"item": {"@microsoft.graph.conflictBehavior": "replace"}}

        try:

            def create_session():
                return requests.post(
                    session_url, headers=self._get_headers(), json=session_body
                )

            session_response = self._retry_request(create_session)
            session_response.raise_for_status()
            upload_session = session_response.json()
            upload_url = upload_session["uploadUrl"]

            with open(file_path, "rb") as f:
                start_byte = 0
                upload_response = None
                while start_byte < file_size:
                    # Read chunk and calculate range
                    chunk = f.read(chunk_size)
                    chunk_len = len(chunk)
                    end_byte = start_byte + chunk_len - 1

                    def upload_chunk():
                        chunk_headers = {
                            "Content-Length": str(chunk_len),
                            "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
                        }
                        return requests.put(
                            upload_url, headers=chunk_headers, data=chunk
                        )

                    upload_response = self._retry_request(upload_chunk)
                    upload_response.raise_for_status()

                    if progress_callback:
                        progress_callback(chunk_len)

                    start_byte += chunk_len

            if upload_response and upload_response.status_code in [200, 201]:
                self._update_stats(successful_uploads=1, uploaded_size=file_size)

        except requests.exceptions.RequestException as e:
            console.print(f"[red]Failed to upload {filename}: {str(e)}[/red]")
            self._update_stats(failed_uploads=1)

    def upload_any_file(
        self,
        user_id,
        file_path,
        destination_folder=None,
        chunk_size=CHUNK_SIZE,
        progress_callback=None,
    ):
        """Determines the correct upload method and executes it."""
        if not os.path.exists(file_path):
            console.print(f"[red]File not found: {file_path}[/red]")
            self._update_stats(failed_uploads=1)
            return

        if os.path.isdir(file_path):
            console.print(
                f"[yellow]Skipping directory: {file_path} (use upload_directory instead)[/yellow]"
            )
            return

        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        self._update_stats(total_files=1, total_size=file_size)

        if destination_folder:
            clean_folder = destination_folder.strip("/")
            destination_path = f"{clean_folder}/{file_name}"
        else:
            destination_path = file_name

        try:
            if file_size < SMALL_FILE_THRESHOLD:
                self.upload_small_file(
                    user_id, file_path, destination_path, progress_callback
                )
            else:
                self.upload_large_file(
                    user_id, file_path, destination_path, chunk_size, progress_callback
                )
        except Exception as e:
            console.print(
                f"[red]Unexpected error uploading {file_name}: {str(e)}[/red]"
            )
            self._update_stats(failed_uploads=1)

    def upload_single_file_with_progress(
        self,
        user_id,
        file_path,
        destination_folder=None,
        chunk_size=CHUNK_SIZE,
    ):
        """Upload a single file with enhanced progress display."""
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            console.print(f"[red]File not found: {file_path}[/red]")
            return False

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        progress = self._create_file_progress(filename, file_size)

        with progress:
            task = progress.add_task("", total=file_size)

            def progress_callback(bytes_uploaded):
                progress.update(task, advance=bytes_uploaded)

            try:
                self.upload_any_file(
                    user_id,
                    file_path,
                    destination_folder,
                    chunk_size,
                    progress_callback,
                )
                return True
            except Exception as e:
                console.print(f"[red]Failed to upload {filename}: {str(e)}[/red]")
                return False

    def collect_all_files(self, local_paths, destination_folder=None):
        """Collect all files from directories and individual files into a unified list."""
        all_files = []

        for local_path in local_paths:
            if os.path.isfile(local_path):
                # Individual file
                if destination_folder:
                    clean_folder = destination_folder.strip("/")
                    dest_path = f"{clean_folder}/{os.path.basename(local_path)}"
                else:
                    dest_path = os.path.basename(local_path)

                all_files.append(
                    {
                        "local_path": local_path,
                        "destination_path": dest_path,
                        "display_path": local_path,
                        "size": os.path.getsize(local_path),
                    }
                )

            elif os.path.isdir(local_path):
                # Directory - collect all files recursively
                local_dir_name = os.path.basename(os.path.abspath(local_path))

                if destination_folder:
                    remote_root_folder = (
                        f"{destination_folder.strip('/')}/{local_dir_name}"
                    )
                else:
                    remote_root_folder = local_dir_name

                for root, _, files in os.walk(local_path):
                    if not files:
                        continue

                    relative_path = os.path.relpath(root, local_path)
                    if relative_path == ".":
                        current_remote_folder = remote_root_folder
                    else:
                        current_remote_folder = os.path.join(
                            remote_root_folder, relative_path
                        ).replace("\\", "/")

                    # Ensure the remote folder exists
                    # Note: We'll need to call this in the upload method

                    for filename in files:
                        local_file_path = os.path.join(root, filename)
                        dest_path = f"{current_remote_folder}/{filename}"

                        # Create a relative display path from the original directory
                        rel_file_path = os.path.relpath(
                            local_file_path, os.path.dirname(local_path)
                        )

                        all_files.append(
                            {
                                "local_path": local_file_path,
                                "destination_path": dest_path,
                                "display_path": rel_file_path,
                                "size": os.path.getsize(local_file_path),
                                "remote_folder": current_remote_folder,
                            }
                        )

        return all_files

    def upload_unified(
        self,
        user_id,
        local_paths,
        destination_folder=None,
        chunk_size=CHUNK_SIZE,
        show_progress=True,
    ):
        """Upload files and directories in a single unified progress display."""
        # Collect all files from directories and individual files
        all_files = self.collect_all_files(local_paths, destination_folder)

        if not all_files:
            console.print("[yellow]No files found to upload.[/yellow]")
            return

        total_size = sum(f["size"] for f in all_files)
        console.print(
            f"[cyan]🚀 Starting upload of {len(all_files)} files ({total_size / 1024 / 1024:.1f} MB) with {self.max_workers} workers...[/cyan]"
        )

        # Create folders first (sequentially to avoid conflicts)
        folders_created = set()
        for file_info in all_files:
            if "remote_folder" in file_info:
                folder_path = file_info["remote_folder"]
                if folder_path not in folders_created:
                    self._ensure_remote_folder_exists(user_id, folder_path)
                    folders_created.add(folder_path)

        # Create unified progress display
        if show_progress:
            progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                "•",
                FileSizeColumn(),
                "/",
                TotalFileSizeColumn(),
                "•",
                TransferSpeedColumn(),
                "•",
                TimeElapsedColumn(),
                "•",
                TimeRemainingColumn(),
                console=console,
            )

            with progress:
                overall_task = progress.add_task(
                    "📦 Overall Progress", total=total_size
                )
                file_tasks = {}

                # Create individual file tasks with truncated paths
                for file_info in all_files:
                    display_name = truncate_path(file_info["display_path"], 35)
                    task_id = progress.add_task(
                        f"📄 {display_name}", total=file_info["size"]
                    )
                    file_tasks[file_info["local_path"]] = task_id

                def upload_with_progress(file_info):
                    """Upload a single file with progress callback."""
                    local_path = file_info["local_path"]

                    def progress_callback(bytes_uploaded):
                        if local_path in file_tasks:
                            progress.update(
                                file_tasks[local_path], advance=bytes_uploaded
                            )
                        progress.update(overall_task, advance=bytes_uploaded)

                    return self.upload_any_file(
                        user_id=user_id,
                        file_path=local_path,
                        destination_folder=os.path.dirname(
                            file_info["destination_path"]
                        )
                        if "/" in file_info["destination_path"]
                        else None,
                        chunk_size=chunk_size,
                        progress_callback=progress_callback,
                    )

                # Upload files in parallel
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = []
                    for file_info in all_files:
                        future = executor.submit(upload_with_progress, file_info)
                        futures.append((future, file_info))

                    # Process completed uploads
                    for future, file_info in futures:
                        try:
                            future.result()
                        except Exception as e:
                            display_name = truncate_path(file_info["display_path"], 35)
                            console.print(f"[red]❌ Failed {display_name}: {e}[/red]")
        else:
            # No progress display - upload without visual feedback
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                for file_info in all_files:
                    future = executor.submit(
                        self.upload_any_file,
                        user_id,
                        file_info["local_path"],
                        os.path.dirname(file_info["destination_path"])
                        if "/" in file_info["destination_path"]
                        else None,
                        chunk_size,
                        None,
                    )
                    futures.append((future, file_info))

                # Process completed uploads
                for future, file_info in futures:
                    try:
                        future.result()
                        console.print(
                            f"[green]✅ {truncate_path(file_info['display_path'], 50)}[/green]"
                        )
                    except Exception as e:
                        console.print(
                            f"[red]❌ {truncate_path(file_info['display_path'], 50)}: {e}[/red]"
                        )

    def upload_files_parallel(
        self,
        user_id,
        file_paths,
        destination_folder=None,
        chunk_size=CHUNK_SIZE,
        show_progress=True,
    ):
        """Upload multiple files in parallel with unified progress tracking."""
        if not file_paths:
            return

        console.print(
            f"[cyan]🚀 Starting parallel upload of {len(file_paths)} files with {self.max_workers} workers...[/cyan]"
        )

        # Create a unified progress tracker for all files
        if show_progress:
            progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                "•",
                FileSizeColumn(),
                "/",
                TotalFileSizeColumn(),
                "•",
                TransferSpeedColumn(),
                "•",
                TimeElapsedColumn(),
                "•",
                TimeRemainingColumn(),
                console=console,
            )
        else:
            progress = None

        # Calculate total size for overall progress
        total_size = sum(os.path.getsize(fp) for fp in file_paths if os.path.isfile(fp))

        with progress if progress else threading.Lock():
            if progress:
                overall_task = progress.add_task("Overall Progress", total=total_size)
                file_tasks = {}
                for file_path in file_paths:
                    if os.path.isfile(file_path):
                        filename = os.path.basename(file_path)
                        file_size = os.path.getsize(file_path)
                        task_id = progress.add_task(f"📄 {filename}", total=file_size)
                        file_tasks[file_path] = task_id

            def upload_with_progress(file_path):
                """Upload a single file with progress callback."""

                def progress_callback(bytes_uploaded):
                    if progress:
                        if file_path in file_tasks:
                            progress.update(
                                file_tasks[file_path], advance=bytes_uploaded
                            )
                        progress.update(overall_task, advance=bytes_uploaded)

                return self.upload_any_file(
                    user_id,
                    file_path,
                    destination_folder,
                    chunk_size,
                    progress_callback,
                )

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                for file_path in file_paths:
                    if os.path.isfile(file_path):
                        future = executor.submit(upload_with_progress, file_path)
                        futures.append(future)

                # Process completed uploads
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        console.print(f"[red]Upload error: {e}[/red]")

    def display_summary(self):
        """Display a comprehensive upload summary."""
        end_time = datetime.now()
        duration = end_time - self.stats["start_time"]

        # Create summary table
        summary_table = Table(show_header=False, box=box.SIMPLE, pad_edge=False)
        summary_table.add_column("Metric", style="bold cyan", width=25, no_wrap=True)
        summary_table.add_column("Value", style="white", no_wrap=True)

        # Calculate success rate
        total_attempted = (
            self.stats["successful_uploads"]
            + self.stats["failed_uploads"]
            + self.stats["successful_downloads"]
            + self.stats["failed_downloads"]
        )
        success_rate = (
            (
                (
                    self.stats["successful_uploads"] + self.stats["successful_downloads"]
                ) / total_attempted * 100
            )
            if total_attempted > 0
            else 0
        )

        # Calculate upload speed
        upload_speed_mb = (
            (
                (self.stats["uploaded_size"] + self.stats["downloaded_size"])
                / 1024
                / 1024
            )
            / duration.total_seconds()
            if duration.total_seconds() > 0
            else 0
        )

        summary_table.add_row("📁 Total Files", f"[bold]{total_attempted}[/bold]")
        summary_table.add_row("")
        summary_table.add_row("[bold underline]📤 Uploads[/bold underline]", "")
        summary_table.add_row(
            "✅ Successful Uploads",
            f"[bold green]{self.stats['successful_uploads']}[/bold green]",
        )
        summary_table.add_row(
            "❌ Failed Uploads", f"[bold red]{self.stats['failed_uploads']}[/bold red]"
        )
        summary_table.add_row(
            "📤 Data Uploaded",
            f"[bold green]{self.stats['uploaded_size'] / 1024 / 1024:.2f} MB[/bold green]",
        )
        summary_table.add_row("")
        summary_table.add_row("[bold underline]📥 Downloads[/bold underline]", "")
        summary_table.add_row(
            "✅ Successful downloads",
            f"[bold green]{self.stats['successful_downloads']}[/bold green]",
        )
        summary_table.add_row(
            "❌ Failed downloads",
            f"[bold red]{self.stats['failed_downloads']}[/bold red]",
        )
        summary_table.add_row(
            "📥 Data Downloaded",
            f"[bold green]{self.stats['downloaded_size'] / 1024 / 1024:.2f} MB[/bold green]",
        )
        summary_table.add_row("")
        summary_table.add_row("[bold underline]📊 Performance[/bold underline]", "")
        summary_table.add_row("📊 Success Rate", f"[bold]{success_rate:.1f}%[/bold]")
        summary_table.add_row(
            "💾 Total Size",
            f"[bold]{self.stats['total_size'] / 1024 / 1024:.2f} MB[/bold]",
        )
        summary_table.add_row(
            "⏱️  Duration", f"[bold]{str(duration).split('.')[0]}[/bold]"
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

    def list_files(self, user_id, folder_path="", recursive=False):
        """List files and folders in a OneDrive directory."""
        api_base_url = self._get_api_base_url(user_id)

        if folder_path:
            sanitized_path = requests.utils.quote(folder_path)
            list_url = f"{api_base_url}/root:/{sanitized_path}:/children"
        else:
            list_url = f"{api_base_url}/root/children"

        try:

            def list_request():
                return requests.get(list_url, headers=self._get_headers())

            response = self._retry_request(list_request)
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
                    "download_url": item.get("@microsoft.graph.downloadUrl"),
                    "id": item["id"],
                }
                items.append(item_info)

                # If recursive and it's a folder, get its contents
                if recursive and item_info["type"] == "folder":
                    subfolder_items = self.list_files(
                        user_id, item_info["path"], recursive=True
                    )
                    items.extend(subfolder_items)

            return items

        except requests.exceptions.RequestException as e:
            console.print(
                f"[red]Failed to list files in {folder_path or 'root'}: {str(e)}[/red]"
            )
            return []

    def download_file(
        self, user_id, remote_file_path, local_file_path, progress_callback=None
    ):
        """Download a single file from OneDrive."""
        api_base_url = self._get_api_base_url(user_id)
        sanitized_path = requests.utils.quote(remote_file_path)
        download_url = f"{api_base_url}/root:/{sanitized_path}:/content"

        try:

            def download_request():
                return requests.get(
                    download_url, headers=self._get_headers(), stream=True
                )

            response = self._retry_request(download_request)
            response.raise_for_status()

            # Create directory if it doesn't exist
            dir_name = os.path.dirname(local_file_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            # Get file size from headers
            file_size = int(response.headers.get("content-length", 0))

            with open(local_file_path, "wb") as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(len(chunk))

            self._update_stats(successful_downloads=1, downloaded_size=file_size)
            return True

        except requests.exceptions.RequestException as e:
            console.print(f"[red]Failed to download {remote_file_path}: {str(e)}[/red]")
            self._update_stats(failed_downloads=1)
            return False

    def download_folder(
        self, user_id, remote_folder_path, local_folder_path, show_progress=True
    ):
        """Download all files from a OneDrive folder."""
        # List all files in the folder recursively
        files = self.list_files(user_id, remote_folder_path, recursive=True)

        if not files:
            console.print(
                f"[yellow]No files found in {remote_folder_path or 'root'}[/yellow]"
            )
            return

        # Filter only files (not folders)
        files_to_download = [f for f in files if f["type"] == "file"]

        if not files_to_download:
            console.print(
                f"[yellow]No files found in {remote_folder_path or 'root'}[/yellow]"
            )
            return

        total_size = sum(f["size"] for f in files_to_download)
        console.print(
            f"[cyan]📥 Starting download of {len(files_to_download)} files ({total_size / 1024 / 1024:.1f} MB) with {self.max_workers} workers...[/cyan]"
        )

        if show_progress:
            progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                "•",
                FileSizeColumn(),
                "/",
                TotalFileSizeColumn(),
                "•",
                TransferSpeedColumn(),
                "•",
                TimeElapsedColumn(),
                "•",
                TimeRemainingColumn(),
                console=console,
            )

            with progress:
                overall_task = progress.add_task(
                    "📦 Overall Progress", total=total_size
                )
                file_tasks = {}

                # Create individual file tasks
                for file_info in files_to_download:
                    display_name = truncate_path(file_info["path"], 35)
                    task_id = progress.add_task(
                        f"📄 {display_name}", total=file_info["size"]
                    )
                    file_tasks[file_info["path"]] = task_id

                def download_with_progress(file_info):
                    """Download a single file with progress callback."""
                    remote_path = file_info["path"]

                    # Calculate local path
                    if remote_folder_path:
                        # Remove the remote folder path from the beginning
                        relative_path = remote_path[
                            len(remote_folder_path.strip("/")) + 1 :
                        ]
                    else:
                        relative_path = remote_path

                    local_path = os.path.join(local_folder_path, relative_path)

                    def progress_callback(bytes_downloaded):
                        if remote_path in file_tasks:
                            progress.update(
                                file_tasks[remote_path], advance=bytes_downloaded
                            )
                        progress.update(overall_task, advance=bytes_downloaded)

                    return self.download_file(
                        user_id, remote_path, local_path, progress_callback
                    )

                # Download files in parallel
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = []
                    for file_info in files_to_download:
                        future = executor.submit(download_with_progress, file_info)
                        futures.append((future, file_info))

                    # Process completed downloads
                    for future, file_info in futures:
                        try:
                            future.result()
                        except Exception as e:
                            display_name = truncate_path(file_info["path"], 35)
                            console.print(f"[red]❌ Failed {display_name}: {e}[/red]")
        else:
            # No progress display
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                for file_info in files_to_download:
                    # Calculate local path
                    if remote_folder_path:
                        relative_path = file_info["path"][
                            len(remote_folder_path.strip("/")) + 1 :
                        ]
                    else:
                        relative_path = file_info["path"]

                    local_path = os.path.join(local_folder_path, relative_path)

                    future = executor.submit(
                        self.download_file, user_id, file_info["path"], local_path, None
                    )
                    futures.append((future, file_info))

                # Process completed downloads
                completed = 0
                for future, file_info in futures:
                    try:
                        future.result()
                        completed += 1
                        console.print(
                            f"[green]✅ Downloaded {completed}/{len(files_to_download)}: {os.path.basename(file_info['path'])}[/green]"
                        )
                    except Exception as e:
                        console.print(
                            f"[red]❌ Failed {os.path.basename(file_info['path'])}: {e}[/red]"
                        )

    def download_single_file_with_progress(
        self, user_id, remote_file_path, local_file_path
    ):
        """Download a single file with enhanced progress display."""
        # Get file info first
        api_base_url = self._get_api_base_url(user_id)
        sanitized_path = requests.utils.quote(remote_file_path)
        info_url = f"{api_base_url}/root:/{sanitized_path}"

        try:

            def info_request():
                return requests.get(info_url, headers=self._get_headers())

            response = self._retry_request(info_request)
            response.raise_for_status()
            file_info = response.json()

            filename = file_info["name"]
            file_size = file_info["size"]

            progress = self._create_file_progress(filename, file_size)

            with progress:
                task = progress.add_task("", total=file_size)

                def progress_callback(bytes_downloaded):
                    progress.update(task, advance=bytes_downloaded)

                return self.download_file(
                    user_id, remote_file_path, local_file_path, progress_callback
                )

        except requests.exceptions.RequestException as e:
            console.print(
                f"[red]Failed to get file info for {remote_file_path}: {str(e)}[/red]"
            )
            return False

    def download_unified(
        self, user_id, remote_paths, local_base_path, show_progress=True
    ):
        """Download files and folders in a single unified progress display."""
        all_files = []

        # Collect all files from the remote paths
        for remote_path in remote_paths:
            # Check if it's a file or folder
            api_base_url = self._get_api_base_url(user_id)
            sanitized_path = requests.utils.quote(remote_path)
            info_url = f"{api_base_url}/root:/{sanitized_path}"

            try:

                def info_request():
                    return requests.get(info_url, headers=self._get_headers())

                response = self._retry_request(info_request)
                response.raise_for_status()
                item_info = response.json()

                if "folder" in item_info:
                    # It's a folder, get all files recursively
                    folder_files = self.list_files(user_id, remote_path, recursive=True)
                    for file_info in folder_files:
                        if file_info["type"] == "file":
                            # Calculate local path
                            relative_path = file_info["path"][
                                len(remote_path.strip("/")) + 1 :
                            ]
                            local_path = os.path.join(
                                local_base_path,
                                os.path.basename(remote_path),
                                relative_path,
                            )

                            all_files.append(
                                {
                                    "remote_path": file_info["path"],
                                    "local_path": local_path,
                                    "display_path": file_info["path"],
                                    "size": file_info["size"],
                                }
                            )
                else:
                    # It's a file
                    local_path = os.path.join(local_base_path, item_info["name"])
                    all_files.append(
                        {
                            "remote_path": remote_path,
                            "local_path": local_path,
                            "display_path": remote_path,
                            "size": item_info["size"],
                        }
                    )

            except requests.exceptions.RequestException as e:
                console.print(
                    f"[red]Failed to get info for {remote_path}: {str(e)}[/red]"
                )
                continue

        if not all_files:
            console.print("[yellow]No files found to download.[/yellow]")
            return

        total_size = sum(f["size"] for f in all_files)
        console.print(
            f"[cyan]📥 Starting download of {len(all_files)} files ({total_size / 1024 / 1024:.1f} MB) with {self.max_workers} workers...[/cyan]"
        )

        if show_progress:
            progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                "•",
                FileSizeColumn(),
                "/",
                TotalFileSizeColumn(),
                "•",
                TransferSpeedColumn(),
                "•",
                TimeElapsedColumn(),
                "•",
                TimeRemainingColumn(),
                console=console,
            )

            with progress:
                overall_task = progress.add_task(
                    "📦 Overall Progress", total=total_size
                )
                file_tasks = {}

                # Create individual file tasks
                for file_info in all_files:
                    display_name = truncate_path(file_info["display_path"], 35)
                    task_id = progress.add_task(
                        f"📄 {display_name}", total=file_info["size"]
                    )
                    file_tasks[file_info["remote_path"]] = task_id

                def download_with_progress(file_info):
                    """Download a single file with progress callback."""

                    def progress_callback(bytes_downloaded):
                        if file_info["remote_path"] in file_tasks:
                            progress.update(
                                file_tasks[file_info["remote_path"]],
                                advance=bytes_downloaded,
                            )
                        progress.update(overall_task, advance=bytes_downloaded)

                    return self.download_file(
                        user_id,
                        file_info["remote_path"],
                        file_info["local_path"],
                        progress_callback,
                    )

                # Download files in parallel
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = []
                    for file_info in all_files:
                        future = executor.submit(download_with_progress, file_info)
                        futures.append((future, file_info))

                    # Process completed downloads
                    for future, file_info in futures:
                        try:
                            future.result()
                        except Exception as e:
                            display_name = truncate_path(file_info["display_path"], 35)
                            console.print(f"[red]❌ Failed {display_name}: {e}[/red]")
        else:
            # No progress display
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                for file_info in all_files:
                    future = executor.submit(
                        self.download_file,
                        user_id,
                        file_info["remote_path"],
                        file_info["local_path"],
                        None,
                    )
                    futures.append((future, file_info))

                # Process completed downloads
                for future, file_info in futures:
                    try:
                        future.result()
                        console.print(
                            f"[green]✅ {truncate_path(file_info['display_path'], 50)}[/green]"
                        )
                    except Exception as e:
                        console.print(
                            f"[red]❌ {truncate_path(file_info['display_path'], 50)}: {e}[/red]"
                        )


def main():
    """
    Main function to handle command-line arguments and initiate upload/download.
    """
    # Display header
    console.print("\n")
    console.print(
        Panel(
            "[bold blue]OneDrive Uploader/Downloader[/bold blue]\n"
            "[dim]Professional file upload/download tool for Microsoft OneDrive[/dim]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Upload or download files to/from a user's OneDrive using app-only authentication.",
        epilog="""
        This script uses confidential client authentication. Ensure that the required
        environment variables (ONEDRIVE_CLIENT_ID, ONEDRIVE_TENANT_ID,
        ONEDRIVE_CLIENT_SECRET, ONEDRIVE_USER_ID) are set before running.
        The application must be granted the 'Files.ReadWrite.All' Application Permission
        in Azure AD and have received admin consent.
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Add subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Upload command
    upload_parser = subparsers.add_parser("upload", help="Upload files to OneDrive")
    upload_parser.add_argument(
        "local_file_paths",
        nargs="+",
        help="The local paths to the files to upload.",
    )
    upload_parser.add_argument(
        "-r",
        "--remote-folder",
        default="",
        help="The destination folder in OneDrive. If not specified, uploads to the root.",
    )
    upload_parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"The chunk size for large file uploads in bytes. Default is {CHUNK_SIZE} bytes.",
    )
    upload_parser.add_argument(
        "--no-progress", action="store_true", help="Disable the progress bar."
    )
    upload_parser.add_argument(
        "-w",
        "--max-workers",
        type=int,
        default=3,
        help="Maximum number of concurrent upload workers. Default is 3. Range: 1-10.",
    )

    # Download command
    download_parser = subparsers.add_parser(
        "download", help="Download files from OneDrive"
    )
    download_parser.add_argument(
        "remote_file_paths",
        nargs="+",
        help="The remote paths in OneDrive to download.",
    )
    download_parser.add_argument(
        "-l",
        "--local-folder",
        default="./downloads",
        help="The local folder to download files to. Default is './downloads'.",
    )
    download_parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"The chunk size for downloads in bytes. Default is {CHUNK_SIZE} bytes.",
    )
    download_parser.add_argument(
        "--no-progress", action="store_true", help="Disable the progress bar."
    )
    download_parser.add_argument(
        "-w",
        "--max-workers",
        type=int,
        default=3,
        help="Maximum number of concurrent download workers. Default is 3. Range: 1-10.",
    )

    # List command
    list_parser = subparsers.add_parser("list", help="List files in OneDrive")
    list_parser.add_argument(
        "remote_folder_path",
        nargs="?",
        default="",
        help="The remote folder path to list. Default is root.",
    )
    list_parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="List files recursively.",
    )

    args = parser.parse_args()

    # If no command is specified, show help
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Validate max_workers argument for upload/download
    if hasattr(args, "max_workers") and (args.max_workers < 1 or args.max_workers > 20):
        console.print("[red]❌ Error: max-workers must be between 1 and 20.[/red]")
        sys.exit(1)

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

    # File existence checks (only for upload)
    if args.command == "upload":
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
    else:
        files_exist = True
        total_size = 0

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

    if args.command == "upload" and not files_exist:
        for file_path in args.local_file_paths:
            if not os.path.exists(file_path):
                console.print(
                    f"\n❌ [bold red]ERROR: The file '{file_path}' does not exist."
                )
        sys.exit(1)

    # --- Execute Command ---
    try:
        max_workers = getattr(args, "max_workers", 3)
        uploader = OneDriveUploader(client_id, client_secret, tenant_id, max_workers)

        if args.command == "upload":
            # Display upload plan
            plan_table = Table(show_header=True, box=box.SIMPLE)
            plan_table.add_column("File/Directory", style="cyan")
            plan_table.add_column("Type", style="white")
            plan_table.add_column("Size", style="yellow")

            for file_path in args.local_file_paths:
                if os.path.isfile(file_path):
                    size = os.path.getsize(file_path)
                    plan_table.add_row(
                        os.path.basename(file_path),
                        "📄 File",
                        f"{size / 1024 / 1024:.2f} MB",
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
            plan_table.add_row(
                "[bold]TOTAL", "", f"[bold]{total_size / 1024 / 1024:.2f} MB"
            )

            console.print("\n")
            console.print(
                Panel(
                    plan_table,
                    title="[bold green]📋 Upload Plan[/bold green]",
                    border_style="green",
                )
            )

            # Filter out invalid paths
            valid_paths = []
            for local_path in args.local_file_paths:
                if os.path.isdir(local_path) or os.path.isfile(local_path):
                    valid_paths.append(local_path)
                else:
                    console.print(
                        f"⚠️ [yellow]WARNING: Path '{local_path}' is not a file or directory, skipping."
                    )

            if not valid_paths:
                console.print("[red]❌ No valid files or directories to upload.[/red]")
                sys.exit(1)

            # Upload all files and directories
            uploader.upload_unified(
                user_id=user_id,
                local_paths=valid_paths,
                destination_folder=args.remote_folder,
                chunk_size=args.chunk_size,
                show_progress=not args.no_progress,
            )
            uploader.display_summary()

        elif args.command == "download":
            # Create local folder if it doesn't exist
            os.makedirs(args.local_folder, exist_ok=True)

            # Download all files and directories
            uploader.download_unified(
                user_id=user_id,
                remote_paths=args.remote_file_paths,
                local_base_path=args.local_folder,
                show_progress=not args.no_progress,
            )
            uploader.display_summary()

        elif args.command == "list":
            # List files in the specified folder
            files = uploader.list_files(
                user_id, args.remote_folder_path, args.recursive
            )

            if not files:
                console.print(
                    f"[yellow]No files found in {args.remote_folder_path or 'root'}[/yellow]"
                )
            else:
                # Display files in a table
                files_table = Table(show_header=True, box=box.SIMPLE)
                files_table.add_column("Name", style="cyan")
                files_table.add_column("Type", style="white")
                files_table.add_column("Size", style="yellow")
                files_table.add_column("Path", style="dim")

                for file_info in files:
                    if file_info["type"] == "file":
                        size_str = f"{file_info['size'] / 1024 / 1024:.2f} MB"
                        type_str = "📄 File"
                    else:
                        size_str = "-"
                        type_str = "📁 Folder"

                    files_table.add_row(
                        file_info["name"], type_str, size_str, file_info["path"]
                    )

                console.print(
                    f"\n[bold]Files in {args.remote_folder_path or 'root'}:[/bold]"
                )
                console.print(files_table)

    except Exception as e:
        console.print(f"\n❌ [bold red]An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
