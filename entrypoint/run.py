import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess

from server_config_generator.generate_server_config import generate_all, ConfigError, DEFAULT_DEFAULTS_FILE

PROFILES_ROOT = Path.home() / ".local/share/Arma 3 - Other Profiles"
# Written into the Arma install directory, which is also the server's working directory.
GENERATED_CONFIG_NAME = "server.cfg"
# Written by scripts/install_content.py into the Arma install directory at build time.
INSTALLED_CONTENT_MANIFEST = "installed_content.json"

DOCKER_USER = "arma"
DOCKER_GROUP = "arma"

class PermissionsFailure(Exception):
    def __init__(self, path):
        super().__init__(f"Couldn't write to '${path}' or update permissions")

def check_dir_writable(path: Path) -> bool:
    file = path / "write_test"
    try:
        file.touch()
        file.unlink()
        return True
    except OSError:
        pass

    return False

def set_permissions(path: Path):
    try:
        for current_dir, dir_names, filenames in os.walk(path):
            shutil.chown(current_dir, DOCKER_USER, DOCKER_GROUP)
            for file in filenames:
                shutil.chown(current_dir / file, DOCKER_USER, DOCKER_GROUP)
    except OSError as e:
        raise PermissionsFailure(path) from e

def check_critical_paths():
    paths = [
        Path.home() / ".local/share/Arma 3",
        Path.home() / ".local/share/Arma 3 - Other Profiles"
    ]

    for path in paths:
        path.mkdir(exist_ok=True, parents=True)
        is_writable = check_dir_writable(path)
        if not is_writable:
            set_permissions(path)

def get_arma_argument(arma_parameters: list, name: str) -> str | None:
    """Returns the value of an Arma argument given as -name=value, or None if absent.

    Argument names are matched case-insensitively, as Arma does.
    """
    prefix = f"-{name}=".lower()
    for param in arma_parameters:
        if param.lower().startswith(prefix):
            return param[len(prefix):]
    return None

def with_default_config(arma_parameters: list) -> list:
    """Adds -config= pointing at the generated server.cfg, unless the caller passed their own."""
    config = get_arma_argument(arma_parameters, "config")
    if config is None:
        return [*arma_parameters, f"-config={GENERATED_CONFIG_NAME}"]
    if config != GENERATED_CONFIG_NAME:
        print(f"-config={config} was passed, so Arma will load that file instead of the generated "
              f"{GENERATED_CONFIG_NAME}. ARMA_CFG_* variables will have no effect.", flush=True)
    return list(arma_parameters)

def write_generated_file(path: Path, content: str, source: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"Generated {path} from {source} variables:\n{content}", flush=True)

def generate_server_config(arma_root: Path, arma_parameters: list):
    """Writes server.cfg from ARMA_CFG_* variables on every start, replacing any existing file.

    When any ARMA_DIFFICULTY_* variable is set, also writes <name>.Arma3Profile for the profile
    selected by -name=. The neighbouring <name>.vars.Arma3Profile (persistence) is never touched.
    """
    try:
        generated = generate_all(dict(os.environ), DEFAULT_DEFAULTS_FILE)
    except ConfigError as e:
        print(f"config generation failed: {e}", flush=True)
        raise SystemExit(1) from e

    write_generated_file(arma_root / GENERATED_CONFIG_NAME, generated.server_cfg, "ARMA_CFG_*")

    if generated.profile is None:
        return

    profile_name = get_arma_argument(arma_parameters, "name")
    if profile_name is None:
        print("config generation failed: ARMA_DIFFICULTY_* variables are set but no -name= argument was given, "
              "so the profile to write is unknown", flush=True)
        raise SystemExit(1)
    if get_arma_argument(arma_parameters, "profiles") is not None:
        print("config generation failed: ARMA_DIFFICULTY_* variables are set but -profiles= is not supported, "
              "the profile would be written where Arma does not read it", flush=True)
        raise SystemExit(1)

    profile_path = PROFILES_ROOT / profile_name / f"{profile_name}.Arma3Profile"
    write_generated_file(profile_path, generated.profile, "ARMA_DIFFICULTY_*")

def print_installed_content(arma_root: Path):
    """Prints the manifest written by install_content.py at build time, if there is one."""
    manifest_path = arma_root / INSTALLED_CONTENT_MANIFEST
    if not manifest_path.exists():
        print("No installed-content manifest found", flush=True)
        return
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        rows = [[str(entry.get(column, "")) for column in ("kind", "name", "origin", "load")] for entry in entries]
    except (OSError, ValueError, TypeError, AttributeError) as e:
        print(f"Couldn't read installed-content manifest '{manifest_path}': {e}", flush=True)
        return
    if not rows:
        print("Installed content: none", flush=True)
        return
    headers = ["KIND", "NAME", "ORIGIN", "LOAD WITH"]
    widths = [max(len(row[i]) for row in [headers, *rows]) for i in range(len(headers))]
    lines = ["  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in [headers, *rows]]
    print("Installed content:\n" + "\n".join(lines), flush=True)

def run(args):
    arma_root = Path(os.environ["ARMA_INSTALL_PATH"])
    arma_executable = arma_root / os.environ.get("ARMA_EXECUTABLE", "arma3server_x64")

    arma_parameters = with_default_config(args.arma_parameters)

    check_critical_paths()
    generate_server_config(arma_root, arma_parameters)

    print_installed_content(arma_root)

    command = [
        arma_executable,
        *arma_parameters,
    ]

    print(f"Running Arma 3: {[str(param) for param in command]}", flush=True)
    subprocess.run([str(param) for param in command], cwd=arma_root)


parser = argparse.ArgumentParser(description="Runs Arma 3")
parser.add_argument("arma_parameters", action="store", nargs="*")

run(parser.parse_args())
