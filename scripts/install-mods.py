import argparse
import os
import re
from pathlib import Path
import shutil

from steam_downloader import WorkshopItem, Installable, get_steam_credentials_env, MissingWorkshopItemError
from steamdepotdownloader import SteamDepotDownloader
from steamcmd import SteamCmd
from utils import parse_meta, lowercase_all_files_at_path

def install_mods(args):
    # Semicolons match the separator Arma uses for -mod=. Commas are still accepted, since
    # earlier versions of this script used them and existing build configs may rely on that.
    mod_ids = [value.strip() for value in re.split(r"[;,]", args.modlist) if len(value.strip()) > 0]
    mods = [WorkshopItem(id=mod_id, app_id="107410") for mod_id in mod_ids]

    if len(mods) == 0:
        print("No mods to install, exiting")
        return

    print(f"Installing mods: {mod_ids}", flush=True)

    arma_dir = Path(os.environ["ARMA_INSTALL_PATH"])

    steam = SteamDepotDownloader(
        credentials=get_steam_credentials_env(),
        temp_dir=arma_dir / "steamdepotdownloader_mods_temp",
    )

    if args.steamcmd:
        steam = SteamCmd(
            credentials=get_steam_credentials_env(),
            temp_dir=arma_dir / "steamcmd_mods_temp"
        )

    installable_mods = [
        Installable(item=mod, install_dir=arma_dir / f"@{mod.id}")
        for mod in mods
    ]

    steam.install(None, installable_mods)

    for installable_mod in installable_mods:
        mod_dir = installable_mod.install_dir
        if not mod_dir.exists():
            raise MissingWorkshopItemError(str(installable_mod.install_dir))

        meta_path = mod_dir / "meta.cpp"
        if meta_path.exists():
            metadata = parse_meta(meta_path)
            name = metadata.get("name", None)
            if name:
                (arma_dir / f"@{name}").symlink_to(mod_dir, target_is_directory=True)

        keys_folders = [mod_dir / "keys", mod_dir / "Keys"]
        for keys_folder in keys_folders:
            if keys_folder.exists():
                for key_file in keys_folder.glob("*.bikey"):
                    shutil.copy(key_file, arma_dir / "keys")

        # Do a renaming pass to prevent errors in Arma. Everything must be lower case.
        lowercase_all_files_at_path(mod_dir)


parser = argparse.ArgumentParser(description="Installs a list of mods")
parser.add_argument('modlist', default="", nargs="?", help='list of semicolon separated workshop ids')
parser.add_argument("--steamcmd", help="Use Steamcmd instead of Steam Depot Downloader", action="store_true")

args = parser.parse_args()

install_mods(args)
