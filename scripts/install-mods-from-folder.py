import argparse
import os
import shutil
from pathlib import Path

from utils import lowercase_all_files_at_path

def install_mods_from_folder(args):
    folder_path = Path(args.folder.strip())

    if not folder_path.is_dir():
        print(f"No mod folder at '{folder_path}', nothing to install")
        return

    mod_folders = [child for child in folder_path.iterdir() if child.is_dir()]

    if len(mod_folders) == 0:
        print("No mod folders to install, exiting")
        return

    mod_names = [ p.name for p in mod_folders ]

    print(f"Installing mods: {', '.join(mod_names)}", flush=True)

    arma_dir = Path(os.environ["ARMA_INSTALL_PATH"])

    for mod_folder in mod_folders:
        name = mod_folder.name if mod_folder.name.startswith("@") else f"@{mod_folder.name}"
        dest = arma_dir / name.lower()
        shutil.copytree(mod_folder, dest, dirs_exist_ok=True)

        # Do a renaming pass to prevent errors in Arma. Everything must be lower case.
        lowercase_all_files_at_path(dest)


parser = argparse.ArgumentParser(description="Installs mods from a folder")
parser.add_argument('folder', help='folder to install mods from')

args = parser.parse_args()

install_mods_from_folder(args)