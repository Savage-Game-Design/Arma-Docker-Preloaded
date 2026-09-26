from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Iterable, TypeVar, Generic

from secrets import Secret, read_secret_from_env_var


@dataclass
class SteamCredentials:
    username: Secret
    password: Secret

@dataclass
class Branch:
    name: str
    password: Secret | None = None

@dataclass
class App:
    id: str
    branch: Branch | None = None
    depots: list[str] = field(default_factory=list)

@dataclass
class WorkshopItem:
    id: str
    app_id: str

I = TypeVar('I')
@dataclass
class Installable(Generic[I]):
    item: I
    install_dir: Path

InstallableWorkshopItems = Iterable[Installable[WorkshopItem]]


class SteamDownloader(Protocol):
    def install(self, app: Installable[App] | None, workshop_items: InstallableWorkshopItems):
        pass

def get_steam_credentials_env() -> SteamCredentials:
    return SteamCredentials(
        username=read_secret_from_env_var("STEAM_USERNAME"),
        password=read_secret_from_env_var("STEAM_PASSWORD"),
    )

def move_contents(src: Path, dest: Path):
    dest.mkdir(exist_ok=True, parents=True)
    for path in src.iterdir():
        path.rename(dest / path.name)

class MissingWorkshopItemError(Exception):
    def __init__(self, path: str):
        super().__init__(f"Downloaded workshop item not found at '{path}'")

