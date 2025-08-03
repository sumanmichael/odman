"""Upload operations for OneDrive Manager (odman)."""

import os
import requests
from concurrent.futures import ThreadPoolExecutor
from rich.console import Console

from .config import CHUNK_SIZE, SMALL_FILE_THRESHOLD
from .progress import create_file_progress, create_unified_progress
from .utils import truncate_path

console = Console()


class OneDriveUploader:
    """Handles file upload operations to OneDrive."""

    def __init__(self, client):
        """Initialize with an OneDriveClient instance."""
        self.client = client

    def upload_small_file(
        self, user_id, file_path, destination_path, progress_callback=None
    ):
        """Uploads a file smaller than 4MB using a single PUT request."""
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        api_base_url = self.client.get_api_base_url(user_id)
        sanitized_path = requests.utils.quote(destination_path)
        upload_url = f"{api_base_url}/root:/{sanitized_path}:/content"

        try:
            with open(file_path, "rb") as f:
                file_data = f.read()

            def upload_request():
                headers = self.client.auth.get_headers().copy()
                headers["Content-Type"] = "application/octet-stream"
                return requests.put(
                    upload_url, headers=headers, data=file_data
                )

            response = self.client.retry_request(upload_request)
            response.raise_for_status()

            if progress_callback:
                progress_callback(file_size)

            self.client.stats.update(successful_uploads=1, uploaded_size=file_size)

        except requests.exceptions.RequestException as e:
            console.print(f"[red]Failed to upload {filename}: {str(e)}[/red]")
            self.client.stats.update(failed_uploads=1)

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

        api_base_url = self.client.get_api_base_url(user_id)
        sanitized_path = requests.utils.quote(destination_path)
        session_url = f"{api_base_url}/root:/{sanitized_path}:/createUploadSession"
        session_body = {"item": {"@microsoft.graph.conflictBehavior": "replace"}}

        try:
            # Create upload session
            def create_session():
                headers = self.client.auth.get_headers()
                headers["Content-Type"] = "application/json"
                return requests.post(session_url, headers=headers, json=session_body)

            session_response = self.client.retry_request(create_session)
            session_response.raise_for_status()
            upload_session = session_response.json()
            upload_url = upload_session["uploadUrl"]

            # Upload file in chunks
            with open(file_path, "rb") as f:
                uploaded_bytes = 0
                upload_response = None

                while uploaded_bytes < file_size:
                    chunk_data = f.read(chunk_size)
                    chunk_size_actual = len(chunk_data)

                    if chunk_size_actual == 0:
                        break

                    range_start = uploaded_bytes
                    range_end = uploaded_bytes + chunk_size_actual - 1

                    chunk_headers = {
                        "Content-Length": str(chunk_size_actual),
                        "Content-Range": f"bytes {range_start}-{range_end}/{file_size}",
                    }

                    def upload_chunk():
                        return requests.put(
                            upload_url, headers=chunk_headers, data=chunk_data
                        )

                    upload_response = self.client.retry_request(upload_chunk)
                    upload_response.raise_for_status()

                    uploaded_bytes += chunk_size_actual

                    if progress_callback:
                        progress_callback(chunk_size_actual)

            if upload_response and upload_response.status_code in [200, 201]:
                self.client.stats.update(successful_uploads=1, uploaded_size=file_size)
            else:
                self.client.stats.update(failed_uploads=1)

        except requests.exceptions.RequestException as e:
            console.print(f"[red]Failed to upload {filename}: {str(e)}[/red]")
            self.client.stats.update(failed_uploads=1)

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
            self.client.stats.update(failed_uploads=1)
            return

        if os.path.isdir(file_path):
            console.print(
                f"[yellow]Skipping directory: {file_path} (use upload_directory instead)[/yellow]"
            )
            return

        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        self.client.stats.update(total_files=1, total_size=file_size)

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
            self.client.stats.update(failed_uploads=1)

    def upload_single_file_with_progress(
        self, user_id, file_path, destination_folder=None, chunk_size=CHUNK_SIZE
    ):
        """Upload a single file with enhanced progress display."""
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            console.print(f"[red]File not found: {file_path}[/red]")
            return False

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        progress = create_file_progress(filename, file_size)

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
                file_size = os.path.getsize(local_path)
                file_name = os.path.basename(local_path)

                if destination_folder:
                    clean_folder = destination_folder.strip("/")
                    destination_path = f"{clean_folder}/{file_name}"
                    remote_folder = clean_folder
                else:
                    destination_path = file_name
                    remote_folder = None

                all_files.append(
                    {
                        "local_path": local_path,
                        "destination_path": destination_path,
                        "remote_folder": remote_folder,
                        "size": file_size,
                        "display_name": file_name,
                    }
                )

            elif os.path.isdir(local_path):
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
                        current_remote_folder = f"{remote_root_folder}/{relative_path}"

                    for filename in files:
                        local_file_path = os.path.join(root, filename)
                        file_size = os.path.getsize(local_file_path)
                        destination_path = f"{current_remote_folder}/{filename}"

                        all_files.append(
                            {
                                "local_path": local_file_path,
                                "destination_path": destination_path,
                                "remote_folder": current_remote_folder,
                                "size": file_size,
                                "display_name": truncate_path(destination_path, 35),
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
            f"[cyan]🚀 Starting upload of {len(all_files)} files ({total_size / 1024 / 1024:.1f} MB) with {self.client.max_workers} workers...[/cyan]"
        )

        # Create folders first (sequentially to avoid conflicts)
        folders_created = set()
        for file_info in all_files:
            if "remote_folder" in file_info and file_info["remote_folder"]:
                if file_info["remote_folder"] not in folders_created:
                    self.client.ensure_remote_folder_exists(
                        user_id, file_info["remote_folder"]
                    )
                    folders_created.add(file_info["remote_folder"])

        # Upload files
        if show_progress:
            progress = create_unified_progress()

            with progress:
                overall_task = progress.add_task(
                    "📦 Overall Progress", total=total_size
                )
                file_tasks = {}

                # Create individual file tasks
                for file_info in all_files:
                    task_id = progress.add_task(
                        f"📄 {file_info['display_name']}", total=file_info["size"]
                    )
                    file_tasks[file_info["local_path"]] = task_id

                def upload_with_progress(file_info):
                    """Upload a single file with progress callback."""
                    task_id = file_tasks[file_info["local_path"]]

                    def progress_callback(bytes_uploaded):
                        progress.update(task_id, advance=bytes_uploaded)
                        progress.update(overall_task, advance=bytes_uploaded)

                    self.upload_any_file(
                        user_id,
                        file_info["local_path"],
                        file_info["destination_path"],
                        chunk_size,
                        progress_callback,
                    )

                # Upload files in parallel
                with ThreadPoolExecutor(
                    max_workers=self.client.max_workers
                ) as executor:
                    futures = []
                    for file_info in all_files:
                        future = executor.submit(upload_with_progress, file_info)
                        futures.append(future)

                    # Wait for all uploads to complete
                    for future in futures:
                        try:
                            future.result()
                        except Exception as e:
                            console.print(f"[red]Upload error: {e}[/red]")
        else:
            # No progress display - upload without visual feedback
            with ThreadPoolExecutor(max_workers=self.client.max_workers) as executor:
                futures = []
                for file_info in all_files:
                    future = executor.submit(
                        self.upload_any_file,
                        user_id,
                        file_info["local_path"],
                        None,
                        chunk_size,
                        None,
                    )
                    futures.append((future, file_info))

                # Process completed uploads
                for future, file_info in futures:
                    try:
                        future.result()
                        console.print(f"[green]✅ {file_info['display_name']}[/green]")
                    except Exception as e:
                        console.print(f"[red]❌ {file_info['display_name']}: {e}[/red]")
