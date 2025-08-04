"""Download operations for OneDrive Manager (odman)."""

import os
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from rich.console import Console

from odman.core.config import CHUNK_SIZE
from odman.utils.progress import create_file_progress, create_unified_progress
from odman.utils.helpers import truncate_path

console = Console()


class OneDriveDownloader:
    """Handles file download operations from OneDrive."""

    def __init__(self, client):
        """Initialize with an OneDriveClient instance."""
        self.client = client

    def download_file(
        self, user_id, remote_file_path, local_file_path, progress_callback=None
    ):
        """Download a single file from OneDrive."""
        api_base_url = self.client.get_api_base_url(user_id)
        sanitized_path = quote(remote_file_path)
        download_url = f"{api_base_url}/root:/{sanitized_path}:/content"

        try:

            def download_request():
                return requests.get(
                    download_url, headers=self.client.auth.get_headers(), stream=True
                )

            response = self.client.retry_request(download_request)
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

            self.client.stats.update(successful_downloads=1, downloaded_size=file_size)
            return True

        except requests.exceptions.RequestException as e:
            console.print(f"[red]Failed to download {remote_file_path}: {str(e)}[/red]")
            self.client.stats.update(failed_downloads=1)
            return False

    def download_single_file_with_progress(
        self, user_id, remote_file_path, local_file_path
    ):
        """Download a single file with enhanced progress display."""
        # Get file info first
        api_base_url = self.client.get_api_base_url(user_id)
        sanitized_path = quote(remote_file_path)
        info_url = f"{api_base_url}/root:/{sanitized_path}"

        try:

            def info_request():
                return requests.get(info_url, headers=self.client.auth.get_headers())

            response = self.client.retry_request(info_request)
            response.raise_for_status()
            file_info = response.json()

            filename = file_info["name"]
            file_size = file_info["size"]

            progress = create_file_progress(filename, file_size)

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

    def download_folder(
        self, user_id, remote_folder_path, local_folder_path, show_progress=True
    ):
        """Download all files from a OneDrive folder."""
        # List all files in the folder recursively
        files = self.client.list_files(user_id, remote_folder_path, recursive=True)

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
            f"[cyan]📥 Starting download of {len(files_to_download)} files ({total_size / 1024 / 1024:.1f} MB) with {self.client.max_workers} workers...[/cyan]"
        )

        if show_progress:
            progress = create_unified_progress()

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
                    task_id = file_tasks[file_info["path"]]
                    rel_path = os.path.relpath(file_info["path"], remote_folder_path)
                    local_path = os.path.join(local_folder_path, rel_path)

                    def progress_callback(bytes_downloaded):
                        progress.update(task_id, advance=bytes_downloaded)
                        progress.update(overall_task, advance=bytes_downloaded)

                    return self.download_file(
                        user_id, file_info["path"], local_path, progress_callback
                    )

                # Download files in parallel
                with ThreadPoolExecutor(
                    max_workers=self.client.max_workers
                ) as executor:
                    futures = []
                    for file_info in files_to_download:
                        future = executor.submit(download_with_progress, file_info)
                        futures.append((future, file_info))

                    # Process completed downloads
                    for future, file_info in futures:
                        try:
                            future.result()
                        except Exception as e:
                            console.print(
                                f"[red]Download error for {file_info['path']}: {e}[/red]"
                            )
        else:
            # No progress display
            with ThreadPoolExecutor(max_workers=self.client.max_workers) as executor:
                futures = []
                for file_info in files_to_download:
                    relative_path = file_info["path"].lstrip("/")
                    local_path = os.path.join(local_folder_path, relative_path)
                    future = executor.submit(
                        self.download_file, user_id, file_info["path"], local_path, None
                    )
                    futures.append((future, file_info))

                # Process completed downloads
                for future, file_info in futures:
                    try:
                        future.result()
                        console.print(
                            f"[green]✅ {truncate_path(file_info['path'], 50)}[/green]"
                        )
                    except Exception as e:
                        console.print(
                            f"[red]❌ {truncate_path(file_info['path'], 50)}: {e}[/red]"
                        )

    def download_unified(
        self, user_id, remote_paths, local_base_path, show_progress=True
    ):
        """Download files and folders in a single unified progress display."""
        all_files = self._collect_files_to_download(
            user_id, remote_paths, local_base_path
        )

        if not all_files:
            console.print("[yellow]No files found to download.[/yellow]")
            return

        total_size = sum(f["size"] for f in all_files)
        console.print(
            f"[cyan]📥 Starting download of {len(all_files)} files ({total_size / 1024 / 1024:.1f} MB) with {self.client.max_workers} workers...[/cyan]"
        )

        if show_progress:
            self._download_with_progress(user_id, all_files, total_size)
        else:
            self._download_without_progress(user_id, all_files)

    def _collect_files_to_download(self, user_id, remote_paths, local_base_path):
        """Collect all files to download from remote paths."""
        all_files = []

        # Collect all files from the remote paths
        for remote_path in remote_paths:
            # Check if it's a file or folder
            api_base_url = self.client.get_api_base_url(user_id)
            sanitized_path = quote(remote_path)
            info_url = f"{api_base_url}/root:/{sanitized_path}"

            try:

                def info_request():
                    return requests.get(
                        info_url, headers=self.client.auth.get_headers()
                    )

                response = self.client.retry_request(info_request)
                response.raise_for_status()
                item_info = response.json()

                if "folder" in item_info:
                    # It's a folder, get all files recursively
                    folder_files = self.client.list_files(
                        user_id, remote_path, recursive=True
                    )
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

        return all_files

    def _download_with_progress(self, user_id, all_files, total_size):
        """Download files with progress display."""
        progress = create_unified_progress()

        with progress:
            overall_task = progress.add_task("📦 Overall Progress", total=total_size)
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
            with ThreadPoolExecutor(max_workers=self.client.max_workers) as executor:
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

    def _download_without_progress(self, user_id, all_files):
        """Download files without progress display."""
        with ThreadPoolExecutor(max_workers=self.client.max_workers) as executor:
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
