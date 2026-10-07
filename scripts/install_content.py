"""Installs mods and missions from workshop ids, https URLs and paths in a local content folder.

--mods and --missions are ";"-separated mixes of Steam workshop ids and https URLs to .zip or .pbo
files. They only choose the image layer: each installs everything its sources contain, mods or
missions. See sources.py for the entry grammar, scanner.py for how a folder is read and
installer.py for where things land.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

from errors import BuildError
from installer import Installer
from sources import LocalSource, WorkshopSource, parse_entries, parse_local_entries
from steam_downloader import get_steam_credentials_env
from steamcmd import SteamCmd
from steamdepotdownloader import SteamDepotDownloader

STAGING_FOLDER = ".staging"

# Failures that are the build's inputs or environment rather than a bug: reported in one line.
EXPECTED_ERRORS = (BuildError,)

EPILOG = """\
Each argument installs everything its sources contain: a workshop item or zip listed under
--mods that holds a mission installs the mission, and the other way round. The arguments only
decide which image layer the content lands in.

environment:
  ARMA_INSTALL_PATH               Arma server folder to install into. Required.
  STEAM_USERNAME, STEAM_PASSWORD  Steam credentials. Required only for workshop ids.
  STEAM_API_BASE_URL              Steam Web API base, for workshop mission titles.
                                  Default https://api.steampowered.com
  ARMA_MAX_DOWNLOAD_BYTES         Largest URL download allowed. Default 20 GiB.
  ARMA_MINIMUM_DOWNLOAD_SPEED     MB/s. With the byte cap this bounds a download's total time. Default 10.
  ARMA_DOWNLOAD_TIMEOUT_SECONDS   Longest wait for the connection or for any single read. Default 60.
  ARMA_MAX_EXTRACT_BYTES          Largest total size a zip may extract to. Default 25 GiB.

example:
  ARMA_INSTALL_PATH=/arma/server python3 install_content.py \\
    --mods "450814997;https://example.com/my_mods.zip" \\
    --missions "2345678901=coop_town.altis;https://example.com/coop.altis.pbo"
  ARMA_INSTALL_PATH=/arma/server python3 install_content.py \
    --local "@my_mod;missions/coop.altis.pbo;packs" --local-root ./content
"""


def make_downloader(arma_dir: Path, use_steamcmd: bool):
    try:
        credentials = get_steam_credentials_env()
    except KeyError as e:
        raise BuildError("Workshop ids were given but STEAM_USERNAME and STEAM_PASSWORD are not set. "
                         "Pass them as build secrets, or use only URL sources.") from e
    if use_steamcmd:
        return SteamCmd(credentials=credentials, temp_dir=arma_dir / "steamcmd_mods_temp")
    return SteamDepotDownloader(credentials=credentials, temp_dir=arma_dir / "steamdepotdownloader_mods_temp")


def run(args):
    install_path = os.environ.get("ARMA_INSTALL_PATH")
    if not install_path:
        raise BuildError("ARMA_INSTALL_PATH is not set")
    arma_dir = Path(install_path)

    # Parse everything first, so a bad entry fails before any download starts.
    mod_items, mod_urls = parse_entries(args.mods, argument="ARMA_MODS", allow_override=False,
                                        legacy_modlist=args.legacy_modlist)
    mission_items, mission_urls = parse_entries(args.missions, argument="ARMA_MISSIONS", allow_override=True)
    workshop_items = [*mod_items, *mission_items]
    local_entries = parse_local_entries(args.local)

    if not workshop_items and not mod_urls and not mission_urls and not local_entries:
        print("No mods or missions to install, exiting", flush=True)
        return

    # Only touch Steam credentials when something actually needs them.
    steam = make_downloader(arma_dir, args.steamcmd) if workshop_items else None
    sources = []
    if steam is not None:
        sources.append(WorkshopSource(workshop_items, steam))
    sources.extend(mod_urls)
    sources.extend(mission_urls)
    if local_entries:
        sources.append(LocalSource(Path(args.local_root), local_entries))

    staging = arma_dir / STAGING_FOLDER
    shutil.rmtree(staging, ignore_errors=True)
    installer = Installer(arma_dir)
    try:
        for source in sources:
            for content in source.fetch(staging):
                installer.install(content)
        installer.write_manifest()
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if steam is not None:
            # Removed so nothing empty is left in the image layer.
            shutil.rmtree(steam.temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Installs mods and missions from workshop ids, URLs and build-context paths",
                                     epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mods", default="", help="';'-separated workshop ids and/or https .zip or .pbo URLs")
    parser.add_argument("--missions", default="",
                        help="';'-separated workshop ids, '<id>=<name>.<map>' overrides, and/or https .zip or .pbo URLs")
    parser.add_argument("--legacy-modlist", default="", help="deprecated MODLIST value, merged into --mods")
    parser.add_argument("--local", default="",
                        help="';'-separated paths, relative to --local-root, to mod folders, .pbo files, or folders of either")
    parser.add_argument("--local-root", metavar="DIR", default="/local",
                        help="folder the --local paths are relative to (default: /local, the mounted 'local' build context)")
    parser.add_argument("--steamcmd", action="store_true", help="use Steamcmd instead of Steam Depot Downloader")
    args = parser.parse_args()

    try:
        run(args)
    except EXPECTED_ERRORS as e:
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
