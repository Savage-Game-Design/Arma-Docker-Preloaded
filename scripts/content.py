"""The record passed from a content source to the installer.

A source fetches content and decides its final name. The installer places it in the Arma
folder and knows nothing about where it came from.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Kind(Enum):
    MOD = "mod"
    MISSION = "mission"


@dataclass
class Content:
    kind: Kind
    name: str          # final "@folder" (lower-cased) for a mod, "name.map.pbo" (lower-cased) for a mission
    path: Path         # where the content is now: a mod folder or a .pbo file
    origin: str        # "workshop:450814997", "url:https://...", "local:@foo"
    disposable: bool   # the installer may move it instead of copying (staging that will be deleted)
    overlay: bool      # merging onto an already installed item of the same name is allowed (local only)

    @property
    def load_hint(self) -> str:
        if self.kind is Kind.MOD:
            return f"-mod={self.name}"
        return f"ARMA_CFG_MISSION_N_TEMPLATE={self.name[:-len('.pbo')]}"


@dataclass
class ManifestEntry:
    kind: str
    name: str
    title: str         # meta.cpp name for a mod that has one, otherwise the same as name
    origin: str
    path: str
    load: str
    keys: list = field(default_factory=list)


MANIFEST_FILENAME = "installed_content.json"


def get_keys_folder(mod_root: Path) -> Path | None:
    """The folder holding a mod's .bikey files, or None if the mod has none.

    Installed mods are lower-cased, but CDLC folders and mods given by absolute path keep
    their own casing, so both spellings are checked. Used by the installer for the manifest
    and by the entrypoint to build -keysFolder for the mods a server loads.
    """
    for candidate in (mod_root / "keys", mod_root / "Keys"):
        if candidate.is_dir():
            return candidate
    return None


def list_key_files(mod_root: Path) -> list[Path]:
    folder = get_keys_folder(mod_root)
    return sorted(folder.glob("*.bikey")) if folder is not None else []
