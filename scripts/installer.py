"""Places content records into the Arma server directory, with one conflict policy for every source.

A mod gets:
  - an "@<name>" folder under the server root, lower-cased throughout, which Arma on Linux needs
  - an "@<meta.cpp name>" symlink, when meta.cpp declares a name, sanitised like folder names
  - its *.bikey files left in place; the entrypoint passes loaded mods' keys/ folders via -keysFolder
A mission is placed in mpmissions/.

Everything installed is recorded in installed_content.json, which the entrypoint prints at startup.
"""

import json
import os
import shutil
from pathlib import Path

from content import MANIFEST_FILENAME, Content, Kind, ManifestEntry, list_key_files
from errors import BuildError
from scanner import sanitise_mod_name


def parse_meta(path) -> dict[str, str]:
    result = {}
    # utf-8-sig drops a BOM, which some tools write and which would otherwise corrupt the first key.
    with open(path, "r", encoding="utf-8-sig", errors="replace") as meta_file:
        for line in meta_file.readlines():
            cleaned_line = line.strip()
            if not cleaned_line or cleaned_line.startswith("//"):
                continue
            if cleaned_line[-1] == ";":
                cleaned_line = cleaned_line[:-1]

            # Split on the first "=" only, so values containing "=" survive.
            kv_pair = [component.strip() for component in cleaned_line.split("=", 1)]

            if len(kv_pair) != 2:
                print(f"Meta.cpp parser error - couldn't interpret: {line}", flush=True)
                continue

            key = kv_pair[0]
            value = kv_pair[1]

            if len(value) >= 2 and value[0] == "\"" and value[-1] == "\"":
                value = value[1:-1]

            result[key] = value

    return result


def read_meta_name(mod_dir: Path) -> str | None:
    """The mod's name from its meta.cpp, or None if it has no meta.cpp or no name in it."""
    meta_path = mod_dir / "meta.cpp"
    if not meta_path.exists():
        return None
    return parse_meta(meta_path).get("name", "").strip() or None


def lowercase_all_files_at_path(path: Path):
    # Bottom-up, so a folder is renamed only after everything inside it has been.
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files + dirs:
            lowered = name.lower()
            if lowered != name:
                os.rename(os.path.join(root, name), os.path.join(root, lowered))


def describe_existing(path: Path) -> str:
    if path.is_symlink():
        try:
            return f"a symlink to '{os.readlink(path)}'"
        except OSError:
            return "an unreadable symlink"
    return "a folder" if path.is_dir() else "a file"


def merge_copy(src: Path, dest: Path):
    """Copies src into dest file by file, lower-casing every relative path, so differently-cased
    folders (Addons/ and addons/) overlay each other instead of colliding."""
    for root, _, files in os.walk(src):
        rel_parts = [part.lower() for part in Path(root).relative_to(src).parts]
        target_dir = dest.joinpath(*rel_parts)
        target_dir.mkdir(parents=True, exist_ok=True)
        for file_name in files:
            shutil.copy2(Path(root) / file_name, target_dir / file_name.lower())


def read_manifest(arma_dir: Path) -> list[dict]:
    """Returns the manifest's entries, or an empty list if it is missing or unreadable."""
    path = arma_dir / MANIFEST_FILENAME
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            raise ValueError("expected a list")
        return entries
    except (OSError, ValueError) as e:
        print(f"Warning: ignoring unreadable manifest '{path}': {e}", flush=True)
        return []


class Installer:
    def __init__(self, arma_dir: Path):
        self.arma_dir = arma_dir
        self.installed: dict[tuple[str, str], Content] = {}
        self.entries: list[ManifestEntry] = []

    def install(self, content: Content) -> Path:
        key = (content.kind.value, content.name)
        earlier = self.installed.get(key)
        if earlier is not None:
            raise BuildError(f"{content.kind.value} {content.name} from {content.origin} has the same name "
                                f"as the one from {earlier.origin}")

        if content.kind is Kind.MOD:
            dest, keys, title = self.install_mod(content)
        else:
            dest, keys, title = self.install_mission(content)

        self.installed[key] = content
        self.entries.append(ManifestEntry(kind=content.kind.value, name=content.name, title=title or content.name,
                                          origin=content.origin, path=dest.relative_to(self.arma_dir).as_posix(),
                                          load=content.load_hint, keys=keys))
        return dest

    # ----------------------------------------------------------------------- mods

    def install_mod(self, content: Content) -> tuple[Path, list[str], str | None]:
        dest = self.arma_dir / content.name

        if dest.exists() or dest.is_symlink():
            message = f"Cannot install mod {content.name} from {content.origin}: {describe_existing(dest)} already exists at that location"
            if not dest.is_dir():
                raise BuildError(message + ".")
            if not content.overlay:
                raise BuildError(message + " and the mod does not allow overlaying an existing folder.")
            # Broken symlink - dest.exists() is always False
            if not dest.exists():
                raise BuildError(message + " and is broken.")
            print(f"Overlaying {content.origin} onto existing mod {content.name}", flush=True)
            real_dest = Path(dest).resolve()
            merge_copy(content.path, real_dest)
        elif content.disposable:
            shutil.move(str(content.path), str(dest))
        else:
            shutil.copytree(content.path, dest)

        # Do a renaming pass to prevent errors in Arma. Everything must be lower case.
        lowercase_all_files_at_path(dest)
        meta_name = read_meta_name(dest)
        if meta_name:
            self.link_meta_name(dest, meta_name, content)
        keys = self.list_keys(dest)
        print(f"Installed {content.name} from {content.origin}, load with -mod={content.name}", flush=True)
        return dest, keys, meta_name

    def link_meta_name(self, mod_dir: Path, name: str, content: Content):
        # Same rules as folder names: lower-cased, whitespace to underscores, unsafe characters dropped.
        link_name = sanitise_mod_name(name)
        if link_name == "@":
            print(f"Warning: skipping name symlink for {mod_dir.name}: meta.cpp name '{name}' has no usable characters",
                  flush=True)
            return

        link = self.arma_dir / link_name
        if link.is_symlink() or link.exists():
            try:
                if link.resolve() == mod_dir.resolve():
                    return
            except (OSError, RuntimeError):
                pass
            detail = (f"cannot create name link '{link.name}' for mod {mod_dir.name}, "
                      f"it already exists as {describe_existing(link)}")
            if content.overlay:
                # Local overlays may legitimately share a meta.cpp name with a mod from another source.
                print(f"Warning: {detail}. Skipping the name link.", flush=True)
                return
            raise BuildError(f"Mod name conflict at '{link}': {detail}")
        link.symlink_to(mod_dir, target_is_directory=True)
        print(f"Linked {link.name} -> {mod_dir.name}, mod can also be loaded with -mod={link.name}", flush=True)

    def list_keys(self, mod_dir: Path) -> list[str]:
        """Names of the mod's *.bikey files, for the manifest.

        Keys are not copied anywhere at build time. At startup the entrypoint passes the keys/
        folder of every mod named in -mod= and -servermod= to Arma via -keysFolder, so only the
        mods a server actually loads have their signatures accepted.
        """
        key_files = list_key_files(mod_dir)
        if not key_files:
            print(f"Info: Mod {mod_dir.name} ships no .bikey files", flush=True)
        return [key_file.name for key_file in key_files]

    # ----------------------------------------------------------------------- missions

    def install_mission(self, content: Content) -> tuple[Path, list[str], str | None]:
        mission_folder = self.arma_dir / "mpmissions"
        mission_folder.mkdir(exist_ok=True, parents=True)
        dest = mission_folder / content.name

        if dest.exists():
            if not content.overlay:
                raise BuildError(f"Cannot install mission {content.name} from {content.origin}, "
                                    f"it was already installed by an earlier source")
            print(f"Replacing existing mission {content.name} with the one from {content.origin}", flush=True)

        if content.disposable:
            shutil.move(str(content.path), str(dest))
        else:
            shutil.copy2(content.path, dest)
        print(f"Installed mission {content.name} from {content.origin}, "
              f"load with ARMA_CFG_MISSION_N_TEMPLATE={content.name[:-len('.pbo')]}", flush=True)
        return dest, [], None

    # ----------------------------------------------------------------------- manifest

    def write_manifest(self):
        """Merges this run's entries into the manifest. Call only after the whole run succeeded."""
        if not self.entries:
            return
        path = self.arma_dir / MANIFEST_FILENAME
        replaced = {(e.kind, e.name) for e in self.entries}
        entries = [e for e in read_manifest(self.arma_dir)
                   if not (isinstance(e, dict) and (e.get("kind"), e.get("name")) in replaced)]
        entries.extend(vars(e) for e in self.entries)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(entries, f, indent=2)
            f.write("\n")
        print(f"Recorded {len(self.entries)} installed item(s) in {path}", flush=True)
