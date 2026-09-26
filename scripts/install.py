import argparse
import os
from pathlib import Path

from cdlcs import CDLC, CDLCId, CDLCsById
from steam_downloader import App, Branch, Installable, WorkshopItem, get_steam_credentials_env
from steamcmd import SteamCmd
from steamdepotdownloader import SteamDepotDownloader


def make_arma_server_app(branch: Branch | None, cdlcs: list[CDLC]):
    branch = Branch(name='creatordlc') if cdlcs and not branch else branch

    depots = []
    if cdlcs:
        base_arma_depots = [
            "233781",
            "233783",
        ]

        cdlc_depots = [cdlc.depot for cdlc in cdlcs]
        depots = base_arma_depots + cdlc_depots

    return App(
        id="233780",
        branch=branch,
        depots=depots
    )

def install(args):
    branch_name = args.branch.strip() if args.branch else ""
    branch = None if len(branch_name) == 0 else Branch(
        name=branch_name,
    )

    cdlcIds = [CDLCId(idStr) for idStr in args.cdlcs.split(",") if len(idStr)]
    cdlcs = [CDLCsById[cdlcId.value] for cdlcId in cdlcIds]
    app = make_arma_server_app(branch, cdlcs)

    install_dir = Path(os.environ["ARMA_INSTALL_PATH"])

    cdlc_names = [cdlc.name for cdlc in cdlcs]
    install_desc = [
        "Installing Arma 3 server",
        f"- Branch: {branch.name}" if branch else "",
        f"- CDLCs: {', '.join(cdlc_names)}" if cdlc_names else "",
        f"- Install directory: {install_dir.absolute()}",
        "\n"
    ]
    for line in install_desc:
        if line:
            print(line, flush=True)

    steam = SteamDepotDownloader(
        credentials=get_steam_credentials_env(),
        temp_dir=install_dir / "steamdepotdownloader_temp",
    )

    if args.steamcmd:
        steam = SteamCmd(
            credentials=get_steam_credentials_env(),
            temp_dir=install_dir / "steamcmd_temp"
        )

    steam.install(Installable(app, install_dir), [])

    os.chmod(install_dir / "arma3server", 0o755)
    os.chmod(install_dir / "arma3server_x64", 0o755)

    return 0


parser = argparse.ArgumentParser(description="Install the Arma 3 dedicated server")
parser.add_argument("--branch", help="Arma 3 server branch to install", nargs="?")
parser.add_argument("--steamcmd", help="Use Steamcmd instead of Steam Depot Downloader", action="store_true")
parser.add_argument("--cdlcs", help="Comma separated list of CDLC ids to install", action="store", nargs="?", default="")
args = parser.parse_args()

# Allows --cdlcs to be specified with no arguments, and still be stored as a string
args.cdlcs = args.cdlcs or ""

install(args)