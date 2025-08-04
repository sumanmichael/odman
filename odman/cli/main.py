"""Command Line Interface for OneDrive Manager (odman)."""

import os
import sys
import socket
import argparse
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from odman.core.config import CHUNK_SIZE, DEFAULT_WORKERS, MIN_WORKERS, MAX_WORKERS
from odman.core.auth import OneDriveAuth
from odman.core.client import OneDriveClient
from odman.services.upload import OneDriveUploader
from odman.services.download import OneDriveDownloader
from odman.utils.progress import (
    display_operation_summary,
    display_file_list,
    display_upload_plan,
)
from odman.utils.helpers import validate_path_exists, get_directory_size

console = Console()


def display_header():
    """Display the application header."""
    console.print("\n")
    console.print(
        Panel(
            "[bold blue]OneDrive Manager (odman)[/bold blue]\n"
            "[dim]Professional CLI tool for OneDrive file operations via app-only authentication[/dim]",
            border_style="blue",
            padding=(1, 2),
        )
    )


def run_preflight_checks(args):
    """Run pre-flight system checks."""
    console.print("\n")
    console.print("[bold cyan]🔍 Running Pre-flight Checks...[/bold cyan]")

    checks_table = Table(show_header=False, box=box.SIMPLE)
    checks_table.add_column("Check", style="white", width=40)
    checks_table.add_column("Status", style="white", width=15)

    # Environment Variable Check
    env_vars_ok = OneDriveAuth.validate_environment()
    checks_table.add_row(
        "Environment Variables",
        "✅ [green]PASS[/green]" if env_vars_ok else "❌ [red]FAIL[/red]",
    )

    # File existence checks (only for upload)
    if args.command == "upload":
        files_exist = True
        total_size = 0
        for file_path in args.local_file_paths:
            path_type = validate_path_exists(file_path)
            if not path_type:
                files_exist = False
                break
            if path_type == "file":
                total_size += os.path.getsize(file_path)
            elif path_type == "directory":
                dir_size, _ = get_directory_size(file_path)
                total_size += dir_size

        checks_table.add_row(
            "File/Directory Paths",
            "✅ [green]PASS[/green]" if files_exist else "❌ [red]FAIL[/red]",
        )
    else:
        files_exist = True
        total_size = 0

    # Network connectivity (basic check)
    try:
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
            "\n❌ [bold red]ERROR: Missing one or more required environment variables."
        )
        console.print(
            "[red]Please set the required environment variables before running odman."
        )
        sys.exit(1)

    if args.command == "upload" and not files_exist:
        for file_path in args.local_file_paths:
            if not validate_path_exists(file_path):
                console.print(
                    f"\n❌ [bold red]ERROR: The path '{file_path}' does not exist."
                )
        sys.exit(1)

    if not network_ok:
        console.print("\n❌ [bold red]ERROR: Cannot connect to Microsoft Graph API.")
        console.print("[red]Please check your internet connection.")
        sys.exit(1)


def handle_upload_command(args, client):
    """Handle the upload command."""
    user_id = OneDriveAuth.get_user_id()
    uploader = OneDriveUploader(client)

    # Display upload plan
    display_upload_plan(args.local_file_paths)

    # Filter out invalid paths
    valid_paths = []
    for local_path in args.local_file_paths:
        path_type = validate_path_exists(local_path)
        if path_type in ["file", "directory"]:
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

    display_operation_summary(client.stats)


def handle_download_command(args, client):
    """Handle the download command."""
    user_id = OneDriveAuth.get_user_id()
    downloader = OneDriveDownloader(client)

    # Create local folder if it doesn't exist
    os.makedirs(args.local_folder, exist_ok=True)

    # Download all files and directories
    downloader.download_unified(
        user_id=user_id,
        remote_paths=args.remote_file_paths,
        local_base_path=args.local_folder,
        show_progress=not args.no_progress,
    )

    display_operation_summary(client.stats)


def handle_list_command(args, client: OneDriveClient):
    """Handle the list command."""
    user_id = OneDriveAuth.get_user_id()

    files = client.list_files(user_id, args.remote_folder_path, args.recursive)
    display_file_list(files, args.remote_folder_path or "root")


def create_argument_parser():
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="OneDrive Manager (odman) - Upload, download, and manage files in OneDrive using app-only authentication.",
        epilog="""
        This tool uses confidential client authentication. Ensure that the required
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
        help="The local paths to the files or directories to upload.",
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
        default=DEFAULT_WORKERS,
        help=f"Maximum number of concurrent upload workers. Default is {DEFAULT_WORKERS}. Range: {MIN_WORKERS}-{MAX_WORKERS}.",
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
        default=DEFAULT_WORKERS,
        help=f"Maximum number of concurrent download workers. Default is {DEFAULT_WORKERS}. Range: {MIN_WORKERS}-{MAX_WORKERS}.",
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

    return parser


def main():
    """Main function to handle command-line arguments and execute commands."""
    # Display header
    display_header()

    # Parse arguments
    parser = create_argument_parser()
    args = parser.parse_args()

    # If no command is specified, show help
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Validate max_workers argument for upload/download
    if hasattr(args, "max_workers") and (
        args.max_workers < MIN_WORKERS or args.max_workers > MAX_WORKERS
    ):
        console.print(
            f"[red]❌ Error: max-workers must be between {MIN_WORKERS} and {MAX_WORKERS}.[/red]"
        )
        sys.exit(1)

    # Run pre-flight checks
    run_preflight_checks(args)

    # Execute command
    try:
        max_workers = getattr(args, "max_workers", DEFAULT_WORKERS)
        client = OneDriveClient(max_workers=max_workers)

        if args.command == "upload":
            handle_upload_command(args, client)
        elif args.command == "download":
            handle_download_command(args, client)
        elif args.command == "list":
            handle_list_command(args, client)

    except Exception as e:
        console.print(f"\n❌ [bold red]An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
