"""Statistics tracking for OneDrive Manager (odman)."""

import threading
from datetime import datetime


class OperationStats:
    """Thread-safe statistics tracking for upload/download operations."""

    def __init__(self):
        self._lock = threading.Lock()
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

    def update(self, **kwargs):
        """Thread-safe method to update statistics."""
        with self._lock:
            for key, value in kwargs.items():
                if key in self.stats:
                    self.stats[key] += value

    def get_stats(self):
        """Get a copy of current statistics."""
        with self._lock:
            return self.stats.copy()

    def reset(self):
        """Reset all statistics."""
        with self._lock:
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

    def get_success_rate(self):
        """Calculate success rate as a percentage."""
        stats = self.get_stats()
        total_attempted = (
            stats["successful_uploads"]
            + stats["failed_uploads"]
            + stats["successful_downloads"]
            + stats["failed_downloads"]
        )

        if total_attempted == 0:
            return 0.0

        successful = stats["successful_uploads"] + stats["successful_downloads"]
        return (successful / total_attempted) * 100

    def get_duration(self):
        """Get operation duration."""
        stats = self.get_stats()
        return datetime.now() - stats["start_time"]

    def get_transfer_speed_mb_per_sec(self):
        """Calculate transfer speed in MB/s."""
        stats = self.get_stats()
        duration = self.get_duration()

        if duration.total_seconds() == 0:
            return 0.0

        total_bytes = stats["uploaded_size"] + stats["downloaded_size"]
        mb_transferred = total_bytes / 1024 / 1024
        return mb_transferred / duration.total_seconds()
