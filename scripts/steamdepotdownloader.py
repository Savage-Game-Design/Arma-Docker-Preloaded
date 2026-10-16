import os
import shutil
import subprocess
from steam_downloader import *

# DepotDownloader keeps its manifest state here. It lets a second run verify the existing files and fetch only changed chunks.
# Needs to be on a cache volume across builds to avoid full re-downloads.
STATE_FOLDER = ".DepotDownloader"


class SteamDepotDownloader(SteamDownloader):
    def __init__(self, credentials: SteamCredentials, cache_dir: Path):
        """
        cache_dir: workshop items are downloaded into "<cache_dir>/<app_id>/<item_id>" and copied to
                   their install location. This enables it to be cached across builds.
                   Apps are downloaded straight into their install location and do not use it.
        """
        self.credentials = credentials
        self.cache_dir = cache_dir

    def install(self, installable_app: Installable[App] | None, installable_workshop_items: InstallableWorkshopItems):
        if installable_app:
            self.install_app(installable_app)
        for item in installable_workshop_items:
            self.install_workshop_item(item)

    def install_app(self, installable_app: Installable[App]):
        app = installable_app.item
        install_dir = installable_app.install_dir
        install_dir.mkdir(exist_ok=True, parents=True)
        command = self._get_base_steam_depot_downloader_command(install_dir)
        command.extend([
            "-app", installable_app.item.id
        ])

        if app.branch:
            command.extend([
                "-branch",
                app.branch.name,
            ])

            if app.branch.password:
                command.extend([
                    "-branchpassword",
                    app.branch.password.value,
                ])

        if app.depots:
            for depot in app.depots:
                depot_command = command + [
                    '-depot',
                    depot
                ]
                self._execute_command(depot_command, what=f"app {app.id} depot {depot}")
        else:
            self._execute_command(command, what=f"app {app.id}")

        # Nothing caches the app, so its state would only add to the image.
        shutil.rmtree(install_dir / STATE_FOLDER, ignore_errors=True)

    def install_workshop_item(self, installable_workshop_item: Installable[WorkshopItem]):
        workshop_item = installable_workshop_item.item
        download_dir = self.cache_dir / workshop_item.app_id / workshop_item.id
        download_dir.mkdir(exist_ok=True, parents=True)
        if (download_dir / STATE_FOLDER).is_dir():
            print(f"Workshop item {workshop_item.id}: found in the download cache", flush=True)

        command = self._get_base_steam_depot_downloader_command(download_dir)
        command.extend([
            "-app", workshop_item.app_id,
            "-pubfile", workshop_item.id
        ])
        self._execute_command(command, what=f"workshop item {workshop_item.id}")

        # Copied rather than moved so the cache keeps it across builds.
        shutil.copytree(download_dir, installable_workshop_item.install_dir, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(STATE_FOLDER))

    def _execute_command(self, command, what: str):
        result = subprocess.run(command, capture_output=False)
        if result.returncode != 0:
            raise BuildError(f"Steam Depot Downloader execution failed: downloading {what} exited with code {result.returncode}")

    def _get_base_steam_depot_downloader_command(self, download_dir: Path):
        return [
            os.environ.get("STEAMDEPOTDOWNLOADER_PATH", "DepotDownloader"),
            "-max-downloads", "16",
            "-dir",
            str(download_dir.absolute()),
            "-username",
            self.credentials.username.value,
            "-password",
            self.credentials.password.value,
        ]
