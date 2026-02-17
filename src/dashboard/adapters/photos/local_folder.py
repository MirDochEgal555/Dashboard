from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ...domain.models import PhotoItem
from .base import PhotosAdapterError


def _normalize_extensions(extensions: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for raw_extension in extensions:
        extension = raw_extension.strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = f".{extension}"
        normalized.add(extension)
    if not normalized:
        raise PhotosAdapterError("At least one photo extension must be configured")
    return normalized


def _caption_from_filename(file_path: Path) -> str | None:
    raw_caption = file_path.stem.replace("_", " ").replace("-", " ").strip()
    collapsed = " ".join(raw_caption.split())
    return collapsed or None


class LocalFolderPhotosAdapter:
    def __init__(self, *, folder: Path, extensions: Iterable[str]) -> None:
        self._folder = Path(folder)
        self._extensions = _normalize_extensions(extensions)

    def get_photos(self) -> list[PhotoItem]:
        if not self._folder.exists():
            return []
        if not self._folder.is_dir():
            raise PhotosAdapterError(f"Configured photos folder is not a directory: {self._folder}")

        photos: list[PhotoItem] = []
        for file_path in sorted(self._folder.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in self._extensions:
                continue
            relative_path = file_path.relative_to(self._folder).as_posix()
            photos.append(PhotoItem(path=relative_path, caption=_caption_from_filename(file_path)))
        return photos
