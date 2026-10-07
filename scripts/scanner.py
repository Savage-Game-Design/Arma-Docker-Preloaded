"""Finds mods and missions in an extracted zip or a local folder.

Rules:
  1. __MACOSX entries are dropped everywhere. If the root holds exactly one directory, no files,
     and that directory has no mod markers, it is a wrapper (e.g. a GitHub archive's "repo-main/"):
     descend into it, up to MAX_WRAPPER_DEPTH levels. The wrapper's name becomes the fallback name.
  2. If the root itself has mod markers (addons/, mod.cpp, meta.cpp), it is one mod named from the
     fallback name. It is an error if no name can be derived.
  3. Otherwise each top-level directory with mod markers is a mod named after the folder. An
     "@"-prefixed directory whose children have markers is a wrapper such as "@Mods/": those
     children are the mods. There is no deeper nesting: a mod inside a mod is part of the outer mod.
  4. Missions are .pbo files (any case) at the root, or anywhere inside top-level directories that
     are not mods. PBOs inside mod folders are never missions.
  5. Everything else is logged and ignored. Finding nothing is an error.
"""

import re
from pathlib import Path

from content import Content, Kind
from errors import BuildError

MOD_MARKER_DIRS = ("addons",)
MOD_MARKER_FILES = ("mod.cpp", "meta.cpp")
MAX_WRAPPER_DEPTH = 5
IGNORED_NAMES = ("__MACOSX",)


def scan_error(origin: str, reason: str) -> BuildError:
    return BuildError(f"{origin}: {reason}")


def has_mod_markers(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    for child in folder.iterdir():
        lowered = child.name.lower()
        if child.is_dir() and lowered in MOD_MARKER_DIRS:
            return True
        if child.is_file() and lowered in MOD_MARKER_FILES:
            return True
    return False


def sanitise_mod_name(name: str) -> str:
    """Folder-safe "@name". Returns "@" alone if nothing usable survives."""
    name = name.lower()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^a-z0-9_@.-]", "", name)
    name = re.sub(r"_+", "_", name)
    name = name.lstrip("@.")
    return "@" + name


def is_pbo(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pbo"


def _children(folder: Path) -> list[Path]:
    return sorted((c for c in folder.iterdir() if c.name not in IGNORED_NAMES), key=lambda p: p.name)


def _mod_name(folder: Path, origin: str) -> str:
    name = sanitise_mod_name(folder.name)
    if name == "@":
        raise scan_error(origin,f"cannot derive a mod name from folder '{folder.name}'")
    return name


def _collect_missions(folder: Path, root: Path, missions: list[Path], ignored: list[str]):
    """Recursively finds PBOs under a non-mod folder. Nested mod folders are skipped, not mods."""
    for child in _children(folder):
        rel = child.relative_to(root).as_posix()
        if child.is_dir():
            if has_mod_markers(child):
                ignored.append(f"{rel}/ (mod folder nested too deep)")
                continue
            _collect_missions(child, root, missions, ignored)
        elif is_pbo(child):
            missions.append(child)
        else:
            ignored.append(rel)


def scan_tree(root: Path, origin: str, *, fallback_name: str, disposable: bool, overlay: bool) -> list[Content]:
    fallback = sanitise_mod_name(fallback_name) if fallback_name else "@"

    for _ in range(MAX_WRAPPER_DEPTH):
        if has_mod_markers(root):
            break
        children = _children(root)
        dirs = [c for c in children if c.is_dir()]
        if len(dirs) != 1 or len(children) != 1 or has_mod_markers(dirs[0]):
            break
        root = dirs[0]
        wrapper_name = sanitise_mod_name(root.name)
        if wrapper_name != "@":
            fallback = wrapper_name

    def make(kind: Kind, name: str, path: Path) -> Content:
        return Content(kind=kind, name=name, path=path, origin=origin, disposable=disposable, overlay=overlay)

    if has_mod_markers(root):
        if fallback == "@":
            raise scan_error(origin,"the top level is a mod folder, but no mod name could be derived for it")
        return [make(Kind.MOD, fallback, root)]

    mods: list[tuple[str, Path]] = []
    missions: list[Path] = []
    ignored: list[str] = []

    for child in _children(root):
        rel = child.relative_to(root).as_posix()
        if child.is_dir():
            if has_mod_markers(child):
                mods.append((_mod_name(child, origin), child))
            elif child.name.startswith("@") and any(has_mod_markers(c) for c in _children(child)):
                for inner in _children(child):
                    inner_rel = inner.relative_to(root).as_posix()
                    if inner.is_dir() and has_mod_markers(inner):
                        mods.append((_mod_name(inner, origin), inner))
                    elif inner.is_dir():
                        _collect_missions(inner, root, missions, ignored)
                    elif is_pbo(inner):
                        missions.append(inner)
                    else:
                        ignored.append(inner_rel)
            else:
                _collect_missions(child, root, missions, ignored)
        elif is_pbo(child):
            missions.append(child)
        else:
            ignored.append(rel)

    if ignored:
        print(f"Ignoring entries in '{origin}' that are not mods or missions: {ignored}", flush=True)

    results = [make(Kind.MOD, name, path) for name, path in sorted(mods, key=lambda m: m[0])]
    results += [make(Kind.MISSION, pbo.name.lower(), pbo)
                for pbo in sorted(missions, key=lambda p: (p.name.lower(), p.as_posix()))]

    if not results:
        raise scan_error(origin,"no mods or missions found. Expected folders containing addons/, mod.cpp or meta.cpp, or .pbo files")

    seen: dict[str, Path] = {}
    for item in results:
        if item.name in seen:
            raise scan_error(origin,f"'{seen[item.name].relative_to(root).as_posix()}' and "
                                    f"'{item.path.relative_to(root).as_posix()}' would both install as '{item.name}'")
        seen[item.name] = item.path
    return results
