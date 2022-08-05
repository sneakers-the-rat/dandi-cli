"""
.. versionadded:: 0.36.0

`dandi.files` defines functionality for working with local files & directories
(as opposed to remote resources on a DANDI Archive server) that are of interest
to DANDI.  The classes for such files & directories all inherit from
`DandiFile`, which has two immediate subclasses: `DandisetMetadataFile`, for
representing :file:`dandiset.yaml` files, and `LocalAsset`, for representing
files that can be uploaded as assets to DANDI Archive.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
import weakref

from dandi import get_logger
from dandi.consts import (
    BIDS_DATASET_DESCRIPTION,
    VIDEO_FILE_EXTENSIONS,
    ZARR_EXTENSIONS,
    dandiset_metadata_file,
)
from dandi.exceptions import UnknownAssetError

from .bases import (
    DandiFile,
    DandisetMetadataFile,
    GenericAsset,
    LocalAsset,
    LocalDirectoryAsset,
    LocalFileAsset,
    NWBAsset,
    VideoAsset,
)
from .bids import (
    BIDSAsset,
    BIDSDatasetDescriptionAsset,
    GenericBIDSAsset,
    NWBBIDSAsset,
    ZarrBIDSAsset,
)
from .zarr import LocalZarrEntry, ZarrAsset, ZarrStat

__all__ = [
    "BIDSAsset",
    "BIDSDatasetDescriptionAsset",
    "DandiFile",
    "DandisetMetadataFile",
    "GenericAsset",
    "GenericBIDSAsset",
    "LocalAsset",
    "LocalDirectoryAsset",
    "LocalFileAsset",
    "LocalZarrEntry",
    "NWBAsset",
    "NWBBIDSAsset",
    "VideoAsset",
    "ZarrAsset",
    "ZarrBIDSAsset",
    "ZarrStat",
    "dandi_file",
    "find_dandi_files",
    "find_bids_dataset_description",
]

lgr = get_logger()


def find_dandi_files(
    *paths: str | Path,
    dandiset_path: Optional[str | Path] = None,
    allow_all: bool = False,
    include_metadata: bool = False,
) -> Iterator[DandiFile]:
    """
    Yield all DANDI files at or under the paths in ``paths`` (which may be
    either files or directories).  Files & directories whose names start with a
    period are ignored.  Directories are only included in the return value if
    they are of a type represented by a `LocalDirectoryAsset` subclass, in
    which case they are not recursed into.

    :param dandiset_path:
        The path to the root of the Dandiset in which the paths are located.
        All paths in ``paths`` must be equal to or subpaths of
        ``dandiset_path``.  If `None`, then the Dandiset path for each asset
        found is implicitly set to the parent directory.
    :param allow_all:
        If true, unrecognized assets and the Dandiset's :file:`dandiset.yaml`
        file are returned as `GenericAsset` and `DandisetMetadataFile`
        instances, respectively.  If false, they are not returned at all.
    :param include_metadata:
        If true, the Dandiset's :file:`dandiset.yaml` file is returned as a
        `DandisetMetadataFile` instance.  If false, it is not returned at all
        (unless ``allow_all`` is true).
    """

    # A pair of each file or directory being considered plus the most recent
    # BIDS dataset_description.json file at the path (if a directory) or in a
    # parent path
    path_queue: deque[tuple[Path, Optional[BIDSDatasetDescriptionAsset]]] = deque()
    for p in map(Path, paths):
        if dandiset_path is not None:
            try:
                p.relative_to(dandiset_path)
            except ValueError:
                raise ValueError(
                    "Path {str(p)!r} is not inside Dandiset path {str(dandiset_path)!r}"
                )
        path_queue.append((p, None))
    while path_queue:
        p, bidsdd = path_queue.popleft()
        if p.name.startswith("."):
            continue
        if p.is_dir():
            if p.is_symlink():
                lgr.warning("%s: Ignoring unsupported symbolic link to directory", p)
            elif dandiset_path is not None and p == Path(dandiset_path):
                if (p / BIDS_DATASET_DESCRIPTION).exists():
                    bids2 = dandi_file(p / BIDS_DATASET_DESCRIPTION, dandiset_path)
                    assert isinstance(bids2, BIDSDatasetDescriptionAsset)
                    bidsdd = bids2
                path_queue.extend((q, bidsdd) for q in p.iterdir())
            elif any(p.iterdir()):
                try:
                    df = dandi_file(p, dandiset_path, bids_dataset_description=bidsdd)
                except UnknownAssetError:
                    # The directory does not have a recognized file extension
                    # (ie., it's not a Zarr or any other directory asset type
                    # we may add later), so traverse through it as a regular
                    # directory.
                    if (p / BIDS_DATASET_DESCRIPTION).exists():
                        bids2 = dandi_file(p / BIDS_DATASET_DESCRIPTION, dandiset_path)
                        assert isinstance(bids2, BIDSDatasetDescriptionAsset)
                        bidsdd = bids2
                    path_queue.extend((q, bidsdd) for q in p.iterdir())
                else:
                    yield df
        else:
            df = dandi_file(p, dandiset_path, bids_dataset_description=bidsdd)
            # Don't use isinstance() here, as GenericBIDSAsset's should still
            # be returned
            if type(df) is GenericAsset and not allow_all:
                pass
            elif isinstance(df, DandisetMetadataFile) and not (
                allow_all or include_metadata
            ):
                pass
            else:
                yield df


def dandi_file(
    filepath: str | Path,
    dandiset_path: Optional[str | Path] = None,
    bids_dataset_description: Optional[BIDSDatasetDescriptionAsset] = None,
) -> DandiFile:
    """
    Return a `DandiFile` instance of the appropriate type for the file at
    ``filepath`` inside the Dandiset rooted at ``dandiset_path``.  If
    ``dandiset_path`` is not set, it will default to ``filepath``'s parent
    directory.

    If ``bids_dataset_description`` is set, the file will be assumed to lie
    within the BIDS dataset with the given :file:`dataset_description.json`
    file at its root, resulting in a `BIDSAsset`.

    If ``filepath`` is a directory, it must be of a type represented by a
    `LocalDirectoryAsset` subclass; otherwise, an `UnknownAssetError` exception
    will be raised.

    A regular file named :file:`dandiset.yaml` will only be represented by a
    `DandisetMetadataFile` instance if it is at the root of the Dandiset.

    A regular file that is not of a known type will be represented by a
    `GenericAsset` instance.
    """
    filepath = Path(filepath)
    if dandiset_path is not None:
        path = filepath.relative_to(dandiset_path).as_posix()
        if path == ".":
            raise ValueError("Dandi file path cannot equal Dandiset path")
    else:
        path = filepath.name
    if filepath.is_file() and path == dandiset_metadata_file:
        return DandisetMetadataFile(filepath=filepath)
    if bids_dataset_description is None:
        factory = DandiFileFactory()
    else:
        factory = BIDSFileFactory(bids_dataset_description)
    return factory(filepath, path)


class DandiFileType(Enum):
    """:meta private:"""

    NWB = 1
    ZARR = 2
    VIDEO = 3
    GENERIC = 4
    BIDS_DATASET_DESCRIPTION = 5

    @staticmethod
    def classify(path: Path) -> DandiFileType:
        if path.is_dir():
            if not any(path.iterdir()):
                raise UnknownAssetError("Empty directories cannot be assets")
            if path.suffix in ZARR_EXTENSIONS:
                return DandiFileType.ZARR
            raise UnknownAssetError(
                f"Directory has unrecognized suffix {path.suffix!r}"
            )
        elif path.name == BIDS_DATASET_DESCRIPTION:
            return DandiFileType.BIDS_DATASET_DESCRIPTION
        elif path.suffix == ".nwb":
            return DandiFileType.NWB
        elif path.suffix in VIDEO_FILE_EXTENSIONS:
            return DandiFileType.VIDEO
        else:
            return DandiFileType.GENERIC


class DandiFileFactory:
    """:meta private:"""

    CLASSES: dict[DandiFileType, type[LocalAsset]] = {
        DandiFileType.NWB: NWBAsset,
        DandiFileType.ZARR: ZarrAsset,
        DandiFileType.VIDEO: VideoAsset,
        DandiFileType.GENERIC: GenericAsset,
        DandiFileType.BIDS_DATASET_DESCRIPTION: BIDSDatasetDescriptionAsset,
    }

    def __call__(self, filepath: Path, path: str) -> DandiFile:
        return self.CLASSES[DandiFileType.classify(filepath)](
            filepath=filepath, path=path
        )


@dataclass
class BIDSFileFactory(DandiFileFactory):
    bids_dataset_description: BIDSDatasetDescriptionAsset

    CLASSES = {
        DandiFileType.NWB: NWBBIDSAsset,
        DandiFileType.ZARR: ZarrBIDSAsset,
        DandiFileType.VIDEO: GenericBIDSAsset,
        DandiFileType.GENERIC: GenericBIDSAsset,
    }

    def __call__(self, filepath: Path, path: str) -> DandiFile:
        ftype = DandiFileType.classify(filepath)
        if ftype is DandiFileType.BIDS_DATASET_DESCRIPTION:
            if filepath == self.bids_dataset_description.filepath:
                return self.bids_dataset_description
            else:
                return BIDSDatasetDescriptionAsset(filepath=filepath, path=path)
        df = self.CLASSES[ftype](
            filepath=filepath,
            path=path,
            bids_dataset_description_ref=weakref.ref(self.bids_dataset_description),
        )
        self.bids_dataset_description.dataset_files.append(df)
        return df


def find_bids_dataset_description(
    dirpath: str | Path, dandiset_path: Optional[str | Path] = None
) -> Optional[BIDSDatasetDescriptionAsset]:
    """
    Look for a :file:`dataset_description.json` file in the directory
    ``dirpath`` and each of its parents, stopping when a :file:`dandiset.yaml`
    file is found or ``dandiset_path`` is reached.
    """
    dirpath = Path(dirpath)
    for d in (dirpath, *dirpath.parents):
        bids_marker = d / BIDS_DATASET_DESCRIPTION
        dandi_end = d / dandiset_metadata_file
        if bids_marker.is_file() or bids_marker.is_symlink():
            f = dandi_file(bids_marker, dandiset_path)
            assert isinstance(f, BIDSDatasetDescriptionAsset)
            return f
        elif dandi_end.is_file() or dandi_end.is_symlink():
            return None
        elif dandiset_path is not None and d == Path(dandiset_path):
            return None
    return None
