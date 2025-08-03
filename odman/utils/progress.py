"""Progress display utilities for OneDrive Manager (odman)."""

from odman.models.file import File
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
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def create_file_progress(filename, file_size):
    """Create a progress display for individual file operations with enhanced columns."""
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


def create_unified_progress():
    """Create a unified progress display for multiple file operations."""
    return Progress(
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


def display_operation_summary(stats_obj):
    """Display a comprehensive operation summary."""
    stats = stats_obj.get_stats()
    duration = stats_obj.get_duration()
    success_rate = stats_obj.get_success_rate()
    transfer_speed = stats_obj.get_transfer_speed_mb_per_sec()

    # Create summary table
    summary_table = Table(show_header=False, box=box.SIMPLE, pad_edge=False)
    summary_table.add_column("Metric", style="bold cyan", width=25, no_wrap=True)
    summary_table.add_column("Value", style="white", no_wrap=True)

    # Calculate total attempted operations
    total_attempted = (
        stats["successful_uploads"]
        + stats["failed_uploads"]
        + stats["successful_downloads"]
        + stats["failed_downloads"]
    )

    summary_table.add_row("📁 Total Files", f"[bold]{total_attempted}[/bold]")
    summary_table.add_row("")
    summary_table.add_row("[bold underline]📤 Uploads[/bold underline]", "")
    summary_table.add_row(
        "✅ Successful Uploads",
        f"[bold green]{stats['successful_uploads']}[/bold green]",
    )
    summary_table.add_row(
        "❌ Failed Uploads", f"[bold red]{stats['failed_uploads']}[/bold red]"
    )
    summary_table.add_row(
        "📤 Data Uploaded",
        f"[bold green]{stats['uploaded_size'] / 1024 / 1024:.2f} MB[/bold green]",
    )
    summary_table.add_row("")
    summary_table.add_row("[bold underline]📥 Downloads[/bold underline]", "")
    summary_table.add_row(
        "✅ Successful Downloads",
        f"[bold green]{stats['successful_downloads']}[/bold green]",
    )
    summary_table.add_row(
        "❌ Failed Downloads",
        f"[bold red]{stats['failed_downloads']}[/bold red]",
    )
    summary_table.add_row(
        "📥 Data Downloaded",
        f"[bold green]{stats['downloaded_size'] / 1024 / 1024:.2f} MB[/bold green]",
    )
    summary_table.add_row("")
    summary_table.add_row("[bold underline]📊 Performance[/bold underline]", "")
    summary_table.add_row("📊 Success Rate", f"[bold]{success_rate:.1f}%[/bold]")
    summary_table.add_row(
        "💾 Total Size",
        f"[bold]{stats['total_size'] / 1024 / 1024:.2f} MB[/bold]",
    )
    summary_table.add_row("⏱️  Duration", f"[bold]{str(duration).split('.')[0]}[/bold]")
    summary_table.add_row("🚀 Speed", f"[bold]{transfer_speed:.2f} MB/s[/bold]")

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
            title=f"[bold]{title_icon} Operation Summary[/bold]",
            border_style=panel_style,
            padding=(1, 2),
        )
    )


def display_file_list(files: list[File], folder_path="root"):
    """Display a list of files in a formatted table."""
    if not files:
        console.print(f"[yellow]No files found in {folder_path}[/yellow]")
        return

    # Create files table
    files_table = Table(show_header=True, box=box.SIMPLE)
    files_table.add_column("Name", style="cyan")
    files_table.add_column("Type", style="white")
    files_table.add_column("Size", style="yellow")
    files_table.add_column("Path", style="dim")

    for file_info in files:
        if file_info.type == "file":
            size_str = f"{file_info.size / 1024 / 1024:.2f} MB"
            type_str = "📄 File"
        else:
            size_str = "-"
            type_str = "📁 Folder"

        files_table.add_row(file_info.name, type_str, size_str, file_info.path)

    console.print(f"\n[bold]Files in {folder_path}:[/bold]")
    console.print(files_table)


def display_upload_plan(file_paths):
    """Display an upload plan showing what will be uploaded."""
    from odman.utils.helpers import get_file_size_mb, get_directory_size
    import os

    plan_table = Table(show_header=True, box=box.SIMPLE)
    plan_table.add_column("File/Directory", style="cyan")
    plan_table.add_column("Type", style="white")
    plan_table.add_column("Size", style="yellow")

    total_size = 0
    for file_path in file_paths:
        if os.path.isfile(file_path):
            size_mb = get_file_size_mb(file_path)
            total_size += size_mb
            plan_table.add_row(
                os.path.basename(file_path),
                "📄 File",
                f"{size_mb:.2f} MB",
            )
        elif os.path.isdir(file_path):
            dir_size_bytes, file_count = get_directory_size(file_path)
            dir_size_mb = dir_size_bytes / 1024 / 1024
            total_size += dir_size_mb
            plan_table.add_row(
                os.path.basename(file_path),
                f"📁 Directory ({file_count} files)",
                f"{dir_size_mb:.2f} MB",
            )

    plan_table.add_row("", "", "")
    plan_table.add_row("[bold]TOTAL", "", f"[bold]{total_size:.2f} MB")

    console.print("\n")
    console.print(
        Panel(
            plan_table,
            title="[bold green]📋 Upload Plan[/bold green]",
            border_style="green",
        )
    )
