"""Content sources and the parser for the ARMA_MODS / ARMA_MISSIONS build arguments.

Entries are separated by ";" only, because URLs may contain commas. Each entry is one of:
  - a Steam workshop id (all digits)
  - an https URL to a .zip or a .pbo file
  - for ARMA_MISSIONS only, "<id>=<name>.<map>", an explicit filename for a workshop mission.
    The name may contain dots; the last dot separates the name from the map.

Each source fetches its content into a staging folder and reports what it found as Content
records. The installer places them; a source installs everything it yields, whichever argument
listed it.
"""

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import web
from content import Content, Kind
from errors import BuildError
from scanner import has_mod_markers, is_pbo, sanitise_mod_name, scan_tree
from steam_downloader import Installable, WorkshopItem, missing_workshop_item

ENTRY_SEPARATOR = ";"
ARMA_APP_ID = "107410"
# The name is greedy so it may contain dots; the map (after the last dot) may not.
OVERRIDE_PATTERN = re.compile(r"^(\d+)=([^;/\\=]+)\.([^.;/\\=]+)$")
MISSION_FILENAME_PATTERN = re.compile(r"^(.+)\.([^.]+)\.pbo$", re.IGNORECASE)
OVERRIDE_HINT = "Use '<id>=<name>.<map>' in ARMA_MISSIONS to name it explicitly."


def invalid_entry(argument: str, entry: str, reason: str) -> BuildError:
    return BuildError(f"Invalid {argument} entry '{entry}': {reason}")


def workshop_error(item_id: str, reason: str) -> BuildError:
    return BuildError(f"Workshop item {item_id}: {reason}")


class Source(Protocol):
    def fetch(self, staging: Path) -> list[Content]:
        ...


@dataclass
class WorkshopItemSpec:
    id: str
    override: str | None = None   # "<name>.<map>" lower-cased, without .pbo


def _listing(folder: Path) -> str:
    names = sorted(child.name + ("/" if child.is_dir() else "") for child in folder.iterdir())
    return str(names) if names else "nothing"


class WorkshopSource:
    """All workshop items of one layer, downloaded in a single steam.install call."""

    def __init__(self, items: list[WorkshopItemSpec], steam):
        self.items = items
        self.steam = steam

    def fetch(self, staging: Path) -> list[Content]:
        if not self.items:
            return []

        overrides: dict[str, str | None] = {}
        for spec in self.items:
            if spec.id in overrides and overrides[spec.id] != spec.override:
                raise workshop_error(spec.id, "is listed more than once with different names")
            overrides[spec.id] = spec.override
        item_ids = list(overrides)

        # Steam lookups first, before the (large) downloads. The kind is not known until the item
        # has been downloaded, and only a mission needs its title, so a failed lookup is kept and
        # raised only if the item turns out to be a mission without an override.
        details: dict[str, web.PublishedFileDetails] = {}
        lookup_errors: dict[str, BuildError] = {}
        for item_id in item_ids:
            if overrides[item_id]:
                continue
            try:
                details[item_id] = web.get_published_file_details(item_id)
            except BuildError as e:
                print(f"Workshop item {item_id}: Steam lookup failed, only a problem if it is a mission ({e})", flush=True)
                lookup_errors[item_id] = workshop_error(item_id, f"{e}. {OVERRIDE_HINT}")
                continue
            print(f"Workshop item {item_id} is titled '{details[item_id].title}'", flush=True)

        workshop_dir = staging / "workshop"
        workshop_dir.mkdir(parents=True, exist_ok=True)
        installables = [Installable(WorkshopItem(item_id, ARMA_APP_ID), workshop_dir / item_id) for item_id in item_ids]
        self.steam.install(None, installables)

        return [self._detect(item_id, workshop_dir / item_id, overrides[item_id], details.get(item_id),
                             lookup_errors.get(item_id))
                for item_id in item_ids]

    @staticmethod
    def _detect(item_id: str, item_dir: Path, override: str | None, details: "web.PublishedFileDetails | None",
                lookup_error: BuildError | None = None) -> Content:
        if not item_dir.is_dir():
            raise missing_workshop_item(item_dir)

        origin = f"workshop:{item_id}"

        if has_mod_markers(item_dir):
            print(f"Workshop item {item_id} detected as mod", flush=True)
            if override:
                print(f"Workshop item {item_id} is a mod, ignoring the name override '{override}'", flush=True)
            return Content(kind=Kind.MOD, name=f"@{item_id}", path=item_dir, origin=origin,
                           disposable=True, overlay=False)

        # A mission is a single file. DepotDownloader keeps Steam's recorded filename, which ends in
        # ".<map>.pbo"; steamcmd saves the same bytes as "<id>_legacy.bin", so the extension is not
        # checked here and the map is taken from Steam's record when the local name lacks it.
        files = sorted((p for p in item_dir.rglob("*") if p.is_file()), key=lambda p: p.as_posix())
        if len(files) == 1:
            pbo = files[0]
            print(f"Workshop item {item_id} detected as mission ({pbo.name})", flush=True)
            if override:
                name = f"{override}.pbo"
            else:
                if lookup_error is not None:
                    raise lookup_error
                world = _map_from_filename(pbo.name) or _map_from_filename(details.filename if details else "")
                if not world:
                    raise workshop_error(item_id, f"neither the downloaded file '{pbo.name}' nor Steam's recorded "
                                                 f"filename '{details.filename if details else ''}' ends in '.<map>.pbo', "
                                                 f"so the map cannot be determined. {OVERRIDE_HINT}")
                base = web.sanitise_title(details.title if details else "") or f"workshop_{item_id}"
                name = f"{base}.{world}.pbo"
            return Content(kind=Kind.MISSION, name=name, path=pbo, origin=origin, disposable=True, overlay=False)

        if not files:
            raise workshop_error(item_id, f"download contains no mod folder and no file "
                                         f"(is this a workshop item at all?). Found: {_listing(item_dir)}")
        raise workshop_error(item_id, f"download contains several files and no mod folder, so it is neither "
                                     f"a mod nor a single mission: {[p.relative_to(item_dir).as_posix() for p in files]}")


def _map_from_filename(filename: str) -> str | None:
    """The lower-cased <map> from a '<anything>.<map>.pbo' filename, else None."""
    match = MISSION_FILENAME_PATTERN.match(filename or "")
    return match.group(2).lower() if match else None


class UrlSource:
    """An https URL to a zip (scanned for mods and missions) or to a single .pbo mission."""

    def __init__(self, url: str):
        self.url = url

    def __repr__(self) -> str:
        return f"UrlSource({self.url!r})"

    def fetch(self, staging: Path) -> list[Content]:
        url = self.url
        origin = f"url:{url}"
        work = staging / "url" / hashlib.sha1(url.encode()).hexdigest()[:12]
        path = web.download_file(url, work / "download")

        if zipfile.is_zipfile(path):
            extracted = web.extract_zip(path, work / "extracted", url)
            return scan_tree(extracted, origin, fallback_name=web.url_filename_stem(url),
                             disposable=True, overlay=False)

        filename = re.split(r"[/\\]", web.url_filename(url))[-1].lower()
        if filename.endswith(".pbo"):
            if filename == ".pbo":
                raise web.download_error(url, "the URL's filename has no mission name before '.pbo'")
            if not MISSION_FILENAME_PATTERN.match(filename):
                print(f"Warning: mission file '{filename}' from {url} does not look like '<name>.<map>.pbo'", flush=True)
            dest = path.with_name(filename)
            path.rename(dest)
            print(f"Downloaded mission {filename}", flush=True)
            return [Content(kind=Kind.MISSION, name=filename, path=dest, origin=origin,
                            disposable=True, overlay=False)]

        raise web.download_error(url, "response is neither a zip nor a .pbo")


class LocalSource:
    """Paths in the "local" build context, listed in ARMA_LOCAL, overlaid onto whatever earlier layers installed.

    Each path is relative to that context's root and may be a mod folder, a .pbo file, or a folder
    holding either, which is scanned with the same rules as a zip. A missing path is an error.
    """

    def __init__(self, root: Path, entries: list[str]):
        self.root = root
        self.entries = entries

    def fetch(self, staging: Path) -> list[Content]:
        found: list[Content] = []
        for entry in self.entries:
            found.extend(self._fetch_one(entry))
        return found

    def _fetch_one(self, entry: str) -> list[Content]:
        origin = f"local:{entry}"
        relative = Path(entry.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise invalid_entry("ARMA_LOCAL", entry, "paths must be relative to the local content folder and may not contain '..'")
        path = self.root / relative
        if not path.exists():
            raise invalid_entry("ARMA_LOCAL", entry, f"no such file or folder in the local content folder ('{path}')")

        if path.is_file():
            if not is_pbo(path):
                raise invalid_entry("ARMA_LOCAL", entry, "a file must be a .pbo mission")
            return [Content(kind=Kind.MISSION, name=path.name.lower(), path=path, origin=origin,
                            disposable=False, overlay=True)]

        if has_mod_markers(path):
            name = sanitise_mod_name(path.name)
            if name == "@":
                raise invalid_entry("ARMA_LOCAL", entry, f"cannot derive a mod name from folder '{path.name}'")
            return [Content(kind=Kind.MOD, name=name, path=path, origin=origin, disposable=False, overlay=True)]

        return scan_tree(path, origin, fallback_name="", disposable=False, overlay=True)


def parse_local_entries(raw: str) -> list[str]:
    entries: list[str] = []
    for entry in split_entries(raw):
        if entry in entries:
            print(f"Ignoring duplicate ARMA_LOCAL entry '{entry}'", flush=True)
            continue
        entries.append(entry)
    return entries


def split_entries(raw: str) -> list[str]:
    return [entry.strip() for entry in (raw or "").split(ENTRY_SEPARATOR) if entry.strip()]


def split_legacy_modlist(raw: str) -> list[str]:
    """MODLIST historically accepted commas as well as semicolons."""
    return [entry.strip() for entry in re.split(r"[;,]", raw or "") if entry.strip()]


def is_https_url(entry: str) -> bool:
    parsed = urlparse(entry)
    return parsed.scheme == "https" and bool(parsed.netloc)


def is_http_url(entry: str) -> bool:
    parsed = urlparse(entry)
    return parsed.scheme == "http" and bool(parsed.netloc)


def match_override(entry: str) -> tuple[str, str, str] | None:
    """Returns (id, name, map) for a well-formed "<id>=<name>.<map>", else None."""
    match = OVERRIDE_PATTERN.match(entry)
    if not match:
        return None
    item_id, name, world = match.groups()
    if not name.strip(".").strip() or not world.strip():
        return None
    return item_id, name, world


def _parse_entry(entry: str, argument: str, allow_override: bool) -> WorkshopItemSpec | UrlSource:
    if entry.isdigit():
        return WorkshopItemSpec(id=entry)
    if is_https_url(entry):
        return UrlSource(entry)
    if is_http_url(entry):
        raise invalid_entry(argument, entry, "only https URLs are accepted")
    if "=" in entry and not allow_override:
        raise invalid_entry(argument, entry, "name overrides are only valid in ARMA_MISSIONS")
    match = match_override(entry)
    if match:
        item_id, name, world = match
        return WorkshopItemSpec(id=item_id, override=f"{name}.{world}".lower())
    if "=" in entry:
        raise invalid_entry(argument, entry, "override must look like <id>=<name>.<map>")
    if allow_override:
        raise invalid_entry(argument, entry, "expected a workshop id, <id>=<name>.<map>, or an https URL to a .zip or .pbo")
    raise invalid_entry(argument, entry, "expected a workshop id or an https URL to a .zip or .pbo")


def parse_entries(raw: str, *, argument: str, allow_override: bool,
                  legacy_modlist: str = "") -> tuple[list[WorkshopItemSpec], list[UrlSource]]:
    entries = [(entry, argument, allow_override) for entry in split_entries(raw)]

    legacy_entries = split_legacy_modlist(legacy_modlist)
    if legacy_entries:
        print(f"MODLIST is deprecated, use ARMA_MODS instead. Merging MODLIST entries: {legacy_entries}", flush=True)
        entries.extend((entry, "MODLIST", False) for entry in legacy_entries)

    items: list[WorkshopItemSpec] = []
    urls: list[UrlSource] = []
    seen = set()
    for entry, entry_argument, entry_allow_override in entries:
        parsed = _parse_entry(entry, entry_argument, entry_allow_override)
        key = ("url", parsed.url) if isinstance(parsed, UrlSource) else ("workshop", parsed.id, parsed.override)
        if key in seen:
            print(f"Ignoring duplicate {entry_argument} entry '{entry}'", flush=True)
            continue
        seen.add(key)
        if isinstance(parsed, UrlSource):
            urls.append(parsed)
        else:
            items.append(parsed)
    return items, urls
