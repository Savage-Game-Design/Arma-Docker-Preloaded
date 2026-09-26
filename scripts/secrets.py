import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Secret:
    value: str

    def __str__(self):
            return "!!SECRET!!"

    def __repr__(self):
        return "!!SECRET!!"

class SecretNotDefinedError(Exception):
    def __init__(self, location):
        super().__init__(f"Secret not defined at {location}")

def read_secret_from_env_var(name: str):
    return Secret(os.environ[name].strip())

def read_secret_from_file(path: Path) -> Secret:
    with open(path, "r") as secret_file:
        return Secret(secret_file.read().strip())

def read_docker_secret(name: str) -> Secret:
    path = Path("/run/secrets/") / name
    if not path.exists():
        raise SecretNotDefinedError(path)
    return read_secret_from_file(path)

def expand_secrets(command: list[Any]) -> list[str]:
    return [
        str(param.value) if isinstance(param, Secret) else str(param)
        for param in command
    ]