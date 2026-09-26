"""Replace a file's text through a temporary sibling so readers never see a partial write."""

import os
from pathlib import Path
import secrets


def write_text_atomically(
    path: Path,
    content: str,
    *,
    mode: int,
    apply_umask: bool,
    fsync_file: bool,
    fsync_directory: bool,
    encoding: str | None,
) -> None:
    """Publish complete text at ``path`` with one rename over the previous file.

    The text is first written to a new file next to ``path``. Renaming within one
    directory is atomic, so a reader sees either the previous file or the complete new
    one, never a partly written file.

    Parameters
    ----------
    path : Path
        Destination file. Its directory must already exist.
    content : str
        Complete text of the new file.
    mode : int
        Permission bits of the new file.
    apply_umask : bool
        When true, the process umask narrows ``mode`` exactly as it does for ``open``.
        When false, the file gets exactly ``mode`` whatever the umask is.
    fsync_file : bool
        Flush the written text to stable storage before the rename, so a crash cannot
        leave the new name pointing at incomplete data.
    fsync_directory : bool
        Flush the directory after the rename, so the replacement itself survives a crash.
    encoding : str | None
        Text encoding. ``None`` selects the same default encoding that ``open`` uses.

    Raises
    ------
    OSError
        If the temporary file cannot be created or written, or cannot replace ``path``.

    Notes
    -----
    If anything fails before the rename, the temporary file is removed and an existing
    destination keeps its previous bytes.
    """
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    # O_EXCL refuses a name that already exists, so an unrelated file or symlink that
    # happens to use this name is never written through.
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding) as stream:
            if not apply_umask:
                # fchmod is not filtered by the umask, unlike the mode given to os.open.
                os.fchmod(stream.fileno(), mode)
            stream.write(content)
            if fsync_file:
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    if fsync_directory:
        _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """Flush a directory so a rename inside it is durable, not only its file contents.

    Parameters
    ----------
    directory : Path
        Directory whose entries changed.
    """
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
