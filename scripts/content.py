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
    origin: str
    path: str
    load: str
    keys: list = field(default_factory=list)


MANIFEST_FILENAME = "installed_content.json"
