"""Utility functions for OneDrive Manager (odman)."""

import os


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


def get_file_size_mb(file_path):
    """Get file size in MB."""
    size_bytes = os.path.getsize(file_path)
    return size_bytes / 1024 / 1024


def get_directory_size(directory_path):
    """Calculate the total size of all files in a directory."""
    total_size = 0
    file_count = 0

    for root, _, files in os.walk(directory_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                total_size += os.path.getsize(file_path)
                file_count += 1
            except OSError:
                # Skip files we can't access
                continue

    return total_size, file_count


def validate_path_exists(path):
    """Check if a path exists and return its type."""
    if not os.path.exists(path):
        return None
    elif os.path.isfile(path):
        return "file"
    elif os.path.isdir(path):
        return "directory"
    else:
        return "other"
