"""File model for OneDrive Manager (odman)."""

from pydantic import BaseModel


class File(BaseModel):
    """Represents a file or folder in OneDrive."""

    name: str
    type: str
    size: int
    path: str