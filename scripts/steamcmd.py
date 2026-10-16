import os
import shutil
import subprocess

from steam_downloader import *

# Folder for all workshop downloads (force_install_dir), storing the per-app workshop state to enable build caching.
WORKSHOP_FOLDER = "steamcmd"


class SteamCmd(SteamDownloader):
    def __init__(self, credentials: SteamCredentials, cache_dir: Path):
        """
        cache_dir: workshop items are downloaded under "<cache_dir>/steamcmd" and copied to their
                   install location. The downloads are kept to enable caching across builds.
                   Apps are downloaded straight into their install location and do not use it.
        """
        self.credentials = credentials
        self.cache_dir = cache_dir

    def install(self, installable_app: Installable[App] | None, installable_workshop_items: InstallableWorkshopItems):
        installable_workshop_items = list(installable_workshop_items)
        try:
            if installable_app:
                self.install_app(installable_app)
            if installable_workshop_items:
                self.install_workshop_items(installable_workshop_items)
        finally:
            self.clear_steam_cache()

    def install_app(self, installable_app: Installable[App]):
        app = installable_app.item
        install_dir = installable_app.install_dir
        install_dir.mkdir(exist_ok=True, parents=True)
        command = self._base_command(install_dir)
        command.extend(["+app_update", app.id])
        if app.branch:
            command.extend(["-beta", app.branch.name])
            if app.branch.password:
                command.extend(["-betapassword", app.branch.password.value])
        self._run(command)
        # Nothing caches the app, so its steamapps state would only add to the image.
        shutil.rmtree(install_dir / "steamapps", ignore_errors=True)

    def install_workshop_items(self, installable_workshop_items: list[Installable[WorkshopItem]]):
        workshop_root = self.cache_dir / WORKSHOP_FOLDER
        workshop_root.mkdir(exist_ok=True, parents=True)
        command = self._base_command(workshop_root)
        for installable in installable_workshop_items:
            item = installable.item
            if self._download_path(workshop_root, item).is_dir():
                print(f"Workshop item {item.id}: found in the download cache", flush=True)
            command.extend(["+workshop_download_item", item.app_id, item.id])
        self._run(command)

        for installable in installable_workshop_items:
            download_path = self._download_path(workshop_root, installable.item)
            if not download_path.exists():
                raise missing_workshop_item(download_path)
            # Copied rather than moved so the cache keeps it.
            shutil.copytree(download_path, installable.install_dir, dirs_exist_ok=True)

    @staticmethod
    def _download_path(workshop_root: Path, item: WorkshopItem) -> Path:
        return workshop_root / "steamapps" / "workshop" / "content" / item.app_id / item.id

    def _base_command(self, install_dir: Path) -> list[str]:
        return [
            os.environ.get("STEAMCMD_PATH", "steamcmd"),
            "@ShutdownOnFailedCommand 1",
            "+force_install_dir",
            str(install_dir.absolute()),
            "+login",
            self.credentials.username.value,
            self.credentials.password.value,
        ]

    @staticmethod
    def _run(command: list[str]):
        result = subprocess.run(command + ["+quit"], capture_output=False)
        if result.returncode != 0:
            raise BuildError(f"Steamcmd execution failed: exited with code {result.returncode}")

    @staticmethod
    def clear_steam_cache():
        """Removes steamcmd's own folder (depot chunks, logs); it is outside the cache and would bloat the image."""
        cache_dir = (Path.home() / "Steam").absolute()
        if not cache_dir.exists():
            # Steamcmd may have failed before creating it; let that failure surface instead.
            print(f"Warning: Steam cache folder '{cache_dir}' not found, nothing to clear", flush=True)
            return
        shutil.rmtree(cache_dir)
