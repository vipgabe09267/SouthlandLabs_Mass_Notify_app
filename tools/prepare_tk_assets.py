"""Make the pinned runtime's embedded Tcl/Tk libraries explicit build assets."""
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    destination = ROOT / "build" / "tk-data"
    total = 0
    for dll, prefix in (("tcl90.dll", "tcl_library"), ("tcl9tk90.dll", "tk_library")):
        with zipfile.ZipFile(Path(sys.base_prefix) / "DLLs" / dll) as archive:
            for entry in archive.infolist():
                path = PurePosixPath(entry.filename)
                if (not path.parts or path.parts[0] != prefix or path.is_absolute()
                        or any(part in {"", ".", ".."} or ":" in part or "\\" in part for part in path.parts)):
                    raise ValueError("Unsafe embedded Tcl/Tk library path")
                if entry.is_dir():
                    continue
                total += entry.file_size
                if entry.file_size > 8 * 1024 * 1024 or total > 64 * 1024 * 1024:
                    raise ValueError("Embedded Tcl/Tk library exceeds its size limit")
                target = destination.joinpath(*path.parts)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError("Embedded library escapes its build directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry))
    if not (destination / "tcl_library" / "init.tcl").is_file() or not (destination / "tk_library" / "tk.tcl").is_file():
        raise ValueError("The runtime is missing Tcl/Tk initialization scripts")
    print("Prepared explicit Tcl/Tk script libraries from the checked Python runtime.")


if __name__ == "__main__":
    main()
