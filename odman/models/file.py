"""File model for OneDrive Manager (odman)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass
class File:
    """Represents a file or folder in OneDrive."""

    name: str
    type: str  # "file" or "folder"
    size: int
    path: str
    id: Optional[str] = None
    created_datetime: Optional[datetime] = None
    modified_datetime: Optional[datetime] = None
    mime_type: Optional[str] = None
    web_url: Optional[str] = None

    @classmethod
    def from_api_response(cls, item: Dict[str, Any], folder_path: str = "") -> "File":
        """Create a File object from OneDrive API response data."""
        item_path = f"{folder_path}/{item['name']}" if folder_path else item["name"]

        # Parse datetime fields if present
        created_datetime = None
        if "createdDateTime" in item:
            try:
                created_datetime = datetime.fromisoformat(
                    item["createdDateTime"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        modified_datetime = None
        if "lastModifiedDateTime" in item:
            try:
                modified_datetime = datetime.fromisoformat(
                    item["lastModifiedDateTime"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        return cls(
            name=item["name"],
            type="folder" if "folder" in item else "file",
            size=item.get("size", 0),
            path=item_path,
            id=item.get("id"),
            created_datetime=created_datetime,
            modified_datetime=modified_datetime,
            mime_type=item.get("file", {}).get("mimeType") if "file" in item else None,
            web_url=item.get("webUrl"),
        )
