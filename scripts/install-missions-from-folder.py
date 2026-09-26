import argparse
import os
import shutil
from pathlib import Path

from utils import lowercase_all_files_at_path

def install_missions_from_folder(args):
    folder_path = Path(args.folder.strip())

    if not folder_path.is_dir():
        print(f"No missions folder at '{folder_path}', nothing to install")
        return

    mission_files = list(folder_path.rglob("*.pbo"))
    mission_names = [ p.name for p in mission_files ]

    if len(mission_files) == 0:
        print("No mission PBOs to install, exiting")
        return

    print(f"Installing missions: {', '.join(mission_names)}", flush=True)

    arma_dir = Path(os.environ["ARMA_INSTALL_PATH"])

    mission_folder = arma_dir / "mpmissions"
    mission_folder.mkdir(exist_ok=True, parents=True)

    for file in mission_files:
        dest = mission_folder / file.name.lower()
        shutil.copy(file, dest)

parser = argparse.ArgumentParser(description="Installs missions from a folder")
parser.add_argument('folder', help='folder to install missions from')

args = parser.parse_args()

install_missions_from_folder(args)