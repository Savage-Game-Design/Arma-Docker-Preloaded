import os
import shutil
import subprocess

from steam_downloader import *

class SteamCmd(SteamDownloader):
    def __init__(self, credentials: SteamCredentials, temp_dir: Path):
        self.credentials = credentials
        self.temp_dir = temp_dir

    def install(self, installable_app: Installable[App] | None, installable_workshop_items: InstallableWorkshopItems):
        try:
            app = installable_app and installable_app.item or None
            self.run_download(app, [w.item for w in installable_workshop_items])
            self.move_workshop_items_to_destinations(installable_workshop_items)
            if installable_app:
                self.cleanup_app_folder()
                self.move_app_to_destination(installable_app)
        finally:
            self.clear_steam_cache()
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run_download(self, app: App | None, workshop_items: Iterable[WorkshopItem]):
        self.temp_dir.mkdir(exist_ok=True, parents=True)
        command = [
            os.environ.get("STEAMCMD_PATH", "steamcmd"),
            "@ShutdownOnFailedCommand 1",
            "+force_install_dir",
            str(self.temp_dir.absolute()),
            "+login",
            self.credentials.username.value,
            self.credentials.password.value
        ]

        if app:
            command.extend([
                "+app_update",
                app.id
            ])

            if app.branch:
                command.extend([
                    "-beta",
                    app.branch.name,
                ])

                if app.branch.password:
                    command.extend([
                        "-betapassword",
                        app.branch.password.value,
                    ])

        for workshop_item in workshop_items:
            command.extend([
                "+workshop_download_item",
                workshop_item.app_id,
                workshop_item.id
            ])

        command.extend(["+quit"])

        result = subprocess.run(command, capture_output=False)

        if result.returncode != 0:
            raise BuildError(f"Steamcmd execution failed: exited with code {result.returncode}")

    def move_workshop_items_to_destinations(self, installable_workshop_items: InstallableWorkshopItems):
        for installable_workshop_item in installable_workshop_items:
            workshop_item = installable_workshop_item.item
            download_path = self.temp_dir / "steamapps" / "workshop" / "content" / workshop_item.app_id / workshop_item.id
            if not download_path.exists():
                raise missing_workshop_item(download_path)
            move_contents(download_path, installable_workshop_item.install_dir)

    def cleanup_app_folder(self):
        shutil.rmtree(self.temp_dir / "steamapps")

    def move_app_to_destination(self, installable_app: Installable[App]):
        download_path = self.temp_dir
        move_contents(download_path, installable_app.install_dir)

    @staticmethod
    def clear_steam_cache():
        cache_dir = (Path.home() / "Steam").absolute()
        if not cache_dir.exists():
            # Steamcmd may have failed before creating it; let that failure surface instead.
            print(f"Warning: Steam cache folder '{cache_dir}' not found, nothing to clear", flush=True)
            return
        shutil.rmtree(cache_dir)
