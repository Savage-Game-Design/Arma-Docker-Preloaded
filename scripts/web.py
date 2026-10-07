"""Standard-library helpers for downloading zips and querying Steam's public workshop API."""

import http.client
import json
import os
import re
import shutil
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from errors import BuildError

USER_AGENT = "arma-docker-preloaded/1.0"
DEFAULT_STEAM_API_BASE_URL = "https://api.steampowered.com"
DOWNLOAD_FILENAME = "downloaded_file"
CHUNK_SIZE = 1024 * 1024
PROGRESS_INTERVAL_SECONDS = 10
DEFAULT_MAX_DOWNLOAD_BYTES = 20 * (1024 ** 3)
DEFAULT_MINIMUM_DOWNLOAD_SPEED = 10      # MB/s; with the byte cap this bounds a download's total time
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 60    # per socket operation: connect, headers, and each read
DEFAULT_MAX_EXTRACT_BYTES = 25 * (1024 ** 3)
MAX_ZIP_ENTRIES = 200000

# Content-Type of the most recent download_file response, for extract_zip's not-a-zip message.
last_content_type: str | None = None


def download_error(url: str, reason: str) -> BuildError:
    return BuildError(f"Download of '{url}' failed: {reason}")


def steam_api_error(item_id: str, reason: str) -> BuildError:
    return BuildError(f"Steam API lookup for workshop item {item_id} failed: {reason}")


class HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise download_error(req.full_url, f"redirect to non-https URL refused: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_download_opener = urllib.request.build_opener(HttpsOnlyRedirectHandler)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f}"


def url_filename(url: str) -> str:
    return urllib.parse.unquote(PurePosixPath(urllib.parse.urlparse(url).path).name)


def url_filename_stem(url: str) -> str:
    """Folder-safe name from the URL's filename, with a trailing .zip removed. May be empty."""
    name = re.sub(r"\.zip$", "", url_filename(url), flags=re.IGNORECASE)
    name = name.lower()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^a-z0-9_@.-]", "", name)
    while ".." in name:
        name = name.replace("..", "")
    return name.lstrip(".")


def download_file(url: str, dest_dir: Path) -> Path:
    """Streams url to dest_dir/downloaded_file. The save path never depends on the URL."""
    global last_content_type
    last_content_type = None
    max_bytes = _env_int("ARMA_MAX_DOWNLOAD_BYTES", DEFAULT_MAX_DOWNLOAD_BYTES)
    download_speed = _env_int("ARMA_MINIMUM_DOWNLOAD_SPEED", DEFAULT_MINIMUM_DOWNLOAD_SPEED)
    deadline_seconds = max_bytes / (download_speed * 1024 ** 2)
    timeout = _env_int("ARMA_DOWNLOAD_TIMEOUT_SECONDS", DEFAULT_DOWNLOAD_TIMEOUT_SECONDS)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / DOWNLOAD_FILENAME
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.monotonic()
    received = 0
    try:
        with _download_opener.open(request, timeout=timeout) as response, open(dest, "wb") as out:
            last_content_type = response.headers.get("Content-Type")
            length_header = response.headers.get("Content-Length")
            expected = int(length_header) if length_header and length_header.strip().isdigit() else None
            size_text = f"{_mb(expected)} MB" if expected is not None else "unknown size"
            print(f"Downloading {url} ({size_text})", flush=True)
            if expected is not None and expected > max_bytes:
                raise download_error(url, f"size {expected} bytes exceeds ARMA_MAX_DOWNLOAD_BYTES ({max_bytes})")

            last_progress = start
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes:
                    raise download_error(url, f"exceeded ARMA_MAX_DOWNLOAD_BYTES ({max_bytes} bytes)")
                out.write(chunk)
                now = time.monotonic()
                if now - start > deadline_seconds:
                    raise download_error(url, f"exceeded allowed download time ({deadline_seconds}s) - ARMA_MAX_DOWNLOAD_BYTES ({max_bytes} bytes) at ARMA_MINIMUM_DOWNLOAD_SPEED ({download_speed} MB/s)")
                if now - last_progress >= PROGRESS_INTERVAL_SECONDS:
                    last_progress = now
                    if expected:
                        print(f"  {_mb(received)}/{_mb(expected)} MB {received * 100 // expected}%", flush=True)
                    else:
                        print(f"  {_mb(received)} MB", flush=True)

            if expected is not None and received != expected:
                raise download_error(url, f"truncated: got {received} of {expected} bytes")
    except BuildError:
        dest.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as e:
        dest.unlink(missing_ok=True)
        raise download_error(url, f"HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        dest.unlink(missing_ok=True)
        raise download_error(url, str(e.reason)) from e
    except http.client.IncompleteRead as e:
        dest.unlink(missing_ok=True)
        raise download_error(url, f"truncated: got {received + len(e.partial)} bytes, connection closed early") from e
    except (http.client.HTTPException, OSError) as e:
        dest.unlink(missing_ok=True)
        raise download_error(url, f"{type(e).__name__}: {e}") from e

    print(f"Downloaded {_mb(received)} MB in {time.monotonic() - start:.1f}s", flush=True)
    return dest


def _not_a_zip_reason(zip_path: Path) -> str:
    size = zip_path.stat().st_size
    with open(zip_path, "rb") as f:
        head = f.read(16)
    reason = f"response is not a zip file ({size} bytes, starts with {head!r}"
    if last_content_type:
        reason += f", Content-Type {last_content_type}"
    return f"{reason})."


def _check_entries(infos: list[zipfile.ZipInfo], url: str) -> None:
    max_bytes = _env_int("ARMA_MAX_EXTRACT_BYTES", DEFAULT_MAX_EXTRACT_BYTES)
    if len(infos) > MAX_ZIP_ENTRIES:
        raise download_error(url, f"zip has {len(infos)} entries, more than the limit of {MAX_ZIP_ENTRIES}")
    total = 0
    for info in infos:
        name = info.filename
        if "\0" in name:
            raise download_error(url, f"zip entry name contains NUL: {name!r}")
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
            raise download_error(url, f"zip entry has an absolute path: {name!r}")
        if ".." in name.split("/"):
            raise download_error(url, f"zip entry contains a '..' component: {name!r}")
        total += info.file_size
        if total > max_bytes:
            raise download_error(url, f"zip uncompressed size exceeds ARMA_MAX_EXTRACT_BYTES ({max_bytes} bytes)")


def extract_zip(zip_path: Path, dest_dir: Path, url: str) -> Path:
    if not zipfile.is_zipfile(zip_path):
        raise download_error(url, _not_a_zip_reason(zip_path))
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            for info in infos:
                # Windows Compress-Archive writes "\" separators, which Linux would keep in filenames.
                info.filename = info.filename.replace("\\", "/")
            _check_entries(infos, url)
            # Pass the ZipInfo objects themselves: NameToInfo is still keyed by the original names.
            archive.extractall(dest_dir, members=infos)
    except zipfile.BadZipFile as e:
        raise download_error(url, f"corrupt zip: {e}") from e

    for macosx in sorted(dest_dir.rglob("__MACOSX"), key=lambda p: len(p.parts), reverse=True):
        if macosx.is_dir():
            shutil.rmtree(macosx)
    zip_path.unlink()
    return dest_dir


def steam_api_base_url() -> str:
    return os.environ.get("STEAM_API_BASE_URL", DEFAULT_STEAM_API_BASE_URL).rstrip("/")


@dataclass
class PublishedFileDetails:
    title: str
    filename: str   # the uploaded file's name as Steam records it, may be ""


def get_published_file_title(item_id: str, timeout: int = 60) -> str:
    return get_published_file_details(item_id, timeout).title


def get_published_file_details(item_id: str, timeout: int = 60) -> PublishedFileDetails:
    """Returns the workshop item's title and recorded filename via the public GetPublishedFileDetails endpoint."""
    url = f"{steam_api_base_url()}/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    body = urllib.parse.urlencode({"itemcount": 1, "publishedfileids[0]": item_id}).encode()
    request = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as e:
        raise steam_api_error(item_id, f"HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise steam_api_error(item_id, str(e.reason)) from e
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise steam_api_error(item_id, str(e)) from e

    try:
        details = payload["response"]["publishedfiledetails"][0]
    except (KeyError, IndexError, TypeError) as e:
        raise steam_api_error(item_id, "unexpected response shape") from e

    if details.get("result") != 1:
        raise steam_api_error(item_id, f"result code {details.get('result')} (item missing, private, or not a workshop file)")
    title = details.get("title")
    if not isinstance(title, str) or not title.strip():
        raise steam_api_error(item_id, "response has no title")
    filename = details.get("filename")
    return PublishedFileDetails(title=title, filename=filename if isinstance(filename, str) else "")


def sanitise_title(title: str) -> str:
    """ASCII-transliterate, lowercase, spaces to underscores, strip everything but [a-z0-9_], collapse underscores."""
    name = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")
