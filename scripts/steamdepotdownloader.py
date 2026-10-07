import os
import shutil
import subprocess
from steam_downloader import *

class SteamDepotDownloader(SteamDownloader):
    def __init__(self, credentials: SteamCredentials, temp_dir: Path):
        self.credentials = credentials
        self.temp_dir = temp_dir

    def install(self, installable_app: Installable[App] | None, installable_workshop_items: InstallableWorkshopItems):
        if installable_app:
            self.install_app(installable_app)
        for item in installable_workshop_items:
            self.install_workshop_item(item)

    def install_app(self, installable_app: Installable[App]):
        self._prepare_temp_dir()
        app = installable_app.item
        command = self._get_base_steam_depot_downloader_command()
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

        self._cleanup_install()
        move_contents(self.temp_dir, installable_app.install_dir)


    def install_workshop_item(self, installable_workshop_item: Installable[WorkshopItem]):
        self._prepare_temp_dir()
        workshop_item = installable_workshop_item.item
        command = self._get_base_steam_depot_downloader_command()
        command.extend([
            "-app", workshop_item.app_id,
            "-pubfile", workshop_item.id
        ])

        self._execute_command(command, what=f"workshop item {workshop_item.id}")
        self._cleanup_install()
        move_contents(self.temp_dir, installable_workshop_item.install_dir)

    def _execute_command(self, command, what: str):
        result = subprocess.run(command, capture_output=False)
        if result.returncode != 0:
            raise BuildError(f"Steam Depot Downloader execution failed: downloading {what} exited with code {result.returncode}")

    def _prepare_temp_dir(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _cleanup_install(self):
        shutil.rmtree(self.temp_dir / ".DepotDownloader", ignore_errors=True)

    def _get_base_steam_depot_downloader_command(self):
        return [
            os.environ.get("STEAMDEPOTDOWNLOADER_PATH", "DepotDownloader"),
            "-max-downloads", "16",
            "-dir",
            str(self.temp_dir.absolute()),
            "-username",
            self.credentials.username.value,
            "-password",
            self.credentials.password.value,
        ]
