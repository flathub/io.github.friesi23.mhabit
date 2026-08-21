#!/usr/bin/env python3

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml


ARCHITECTURES = {
    "x86_64": "x64",
    "aarch64": "arm64",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update sqlite3 offline sources in foreign.json.",
    )
    parser.add_argument("--manifest", type=Path, default=Path("flatpak-flutter.yml"))
    parser.add_argument("--foreign", type=Path, default=Path("foreign.json"))
    parser.add_argument(
        "--pubspec-lock",
        type=Path,
        help="Read sqlite3 version from a local pubspec.lock instead of the app source.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with status 1 instead of updating a stale foreign.json.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Download and verify assets even if foreign.json is already current.",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def find_app_source(manifest: dict) -> dict:
    for module in manifest.get("modules", []):
        if module.get("name") != "mhabit":
            continue
        for source in module.get("sources", []):
            if source.get("type") == "git" and source.get("url", "").endswith(
                "/mhabit.git"
            ):
                return source
    raise ValueError("Could not find the mhabit git source in the manifest")


def raw_pubspec_lock_url(source: dict) -> str:
    repository = source["url"]
    commit = source.get("commit")
    if not commit:
        raise ValueError("The mhabit source must have a pinned commit")

    parsed = urllib.parse.urlparse(repository)
    if parsed.hostname != "github.com":
        raise ValueError("Automatic pubspec.lock download currently requires GitHub")

    repository_path = parsed.path.removesuffix(".git").strip("/")
    return f"https://raw.githubusercontent.com/{repository_path}/{commit}/pubspec.lock"


def load_pubspec_lock(args: argparse.Namespace, manifest: dict) -> dict:
    if args.pubspec_lock:
        return load_yaml(args.pubspec_lock)

    source = find_app_source(manifest)
    url = raw_pubspec_lock_url(source)
    with urllib.request.urlopen(url) as response:
        return yaml.safe_load(response.read())


def sqlite3_version(pubspec_lock: dict) -> str:
    try:
        package = pubspec_lock["packages"]["sqlite3"]
        version = package["version"]
    except (KeyError, TypeError) as error:
        raise ValueError("Could not find sqlite3 in pubspec.lock") from error

    if package.get("source") != "hosted":
        raise ValueError("Only hosted sqlite3 packages are supported")
    return str(version)


def sha256_url(url: str) -> str:
    digest = hashlib.sha256()
    with urllib.request.urlopen(url) as response:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def generate_sources(version: str) -> list[dict]:
    release = f"sqlite3-{version}"
    base_url = (
        "https://github.com/simolus3/sqlite3.dart/releases/download/" f"{release}"
    )
    sources = []

    for flatpak_arch, sqlite_arch in ARCHITECTURES.items():
        filename = f"libsqlite3.{sqlite_arch}.linux.so"
        url = f"{base_url}/{filename}"
        digest = sha256_url(url)
        sources.append(
            {
                "type": "file",
                "only-arches": [flatpak_arch],
                "url": url,
                "sha256": digest,
                "dest": (
                    "$APP/.dart_tool/hooks_runner/shared/sqlite3/build/"
                    f"download-{digest[:8]}"
                ),
                "dest-filename": "libsqlite3.so",
            }
        )

    return sources


def load_foreign(path: Path) -> dict:
    if path.exists():
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    return {}


def sources_match_version(foreign: dict, version: str) -> bool:
    try:
        sources = foreign["sqlite3"]["manifest"]["sources"]
    except (KeyError, TypeError):
        return False

    if len(sources) != len(ARCHITECTURES):
        return False

    release_url = (
        "https://github.com/simolus3/sqlite3.dart/releases/download/"
        f"sqlite3-{version}"
    )
    by_arch = {source["only-arches"][0]: source for source in sources}
    for flatpak_arch, sqlite_arch in ARCHITECTURES.items():
        source = by_arch.get(flatpak_arch, {})
        digest = source.get("sha256", "")
        if source.get("url") != (
            f"{release_url}/libsqlite3.{sqlite_arch}.linux.so"
        ):
            return False
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            return False
        if not source.get("dest", "").endswith(f"/download-{digest[:8]}"):
            return False
        if source.get("dest-filename") != "libsqlite3.so":
            return False
    return True


def rendered_foreign(foreign: dict, sources: list[dict]) -> str:

    sqlite3 = foreign.setdefault("sqlite3", {})
    sqlite3["manifest"] = {"sources": sources}
    return json.dumps(foreign, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    args = parse_args()
    try:
        manifest = load_yaml(args.manifest)
        version = sqlite3_version(load_pubspec_lock(args, manifest))
        foreign = load_foreign(args.foreign)

        if not args.refresh and sources_match_version(foreign, version):
            print(f"foreign.json already matches sqlite3 {version}")
            return 0
        if args.check and not args.refresh:
            print(f"foreign.json does not match sqlite3 {version}", file=sys.stderr)
            return 1

        sources = generate_sources(version)
        rendered = rendered_foreign(foreign, sources)
        current = args.foreign.read_text(encoding="utf-8") if args.foreign.exists() else ""

        if rendered == current:
            print(f"foreign.json already matches sqlite3 {version}")
            return 0
        if args.check:
            print(f"foreign.json does not match sqlite3 {version}", file=sys.stderr)
            return 1

        args.foreign.write_text(rendered, encoding="utf-8")
        print(f"Updated foreign.json for sqlite3 {version}")
        return 0
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
