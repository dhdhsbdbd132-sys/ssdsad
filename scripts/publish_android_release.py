"""Publish only authenticated, checked Android build artifacts from this repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile


REPOSITORY = "dhdhsbdbd132-sys/ssdsad"
WORKFLOW = ".github/workflows/android.yml"
ARTIFACT = "todaygo-debug-apk"
VERSION = "1.2.0"
# Earlier successful builds contained incompatible desktop extension libraries.
MINIMUM_BUILD_SHA = "926dc494102111a0e13bed4f139ff7118ce72cbe"
MAX_BYTES = 250 * 1024 * 1024
METADATA = ".publication.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
APK_NAME = re.compile(r"todaygo-[A-Za-z0-9._-]+\.apk\Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class SafeStorageRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        validate_storage_url(new_url)
        return super().redirect_request(request, fp, code, message, headers, new_url)


def validate_storage_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    hostname = parsed.hostname or ""
    require(
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
        and any(
            hostname.endswith(suffix)
            for suffix in (
                ".blob.core.windows.net",
                ".actions.githubusercontent.com",
                ".githubusercontent.com",
            )
        ),
        "GitHub returned an unexpected artifact storage address",
    )


class GitHub:
    def __init__(self):
        require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "Unexpected repository context")
        token = os.environ.get("GITHUB_TOKEN", "")
        require(bool(token), "GITHUB_TOKEN is missing")
        self.headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "TodayGo-verified-Android-release",
        }
        self.opener = urllib.request.build_opener(NoRedirect())

    def response(self, path: str, *, method="GET", payload=None, data=None, content_type=None):
        url = "https://api.github.com" + path if path.startswith("/") else path
        parsed = urllib.parse.urlsplit(url)
        require(
            parsed.scheme == "https"
            and parsed.hostname in ("api.github.com", "uploads.github.com")
            and parsed.username is None
            and parsed.password is None,
            "Unexpected GitHub API address",
        )
        headers = self.headers.copy()
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        return self.opener.open(request, timeout=90)

    def api(self, path: str, *, missing=False, **kwargs):
        try:
            with self.response(path, **kwargs) as response:
                body = response.read(2 * 1024 * 1024 + 1)
                require(len(body) <= 2 * 1024 * 1024, "GitHub JSON response is too large")
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            raise RuntimeError(f"GitHub API request failed (HTTP {error.code})") from None

    def download_artifact(self, artifact_id: int, destination: Path) -> None:
        path = f"/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"
        response = None
        try:
            response = self.response(path)
        except urllib.error.HTTPError as error:
            require(
                error.code in (301, 302, 303, 307, 308),
                f"Artifact download failed (HTTP {error.code})",
            )
            location = error.headers.get("Location", "")
            validate_storage_url(location)
            # A separate request forwards no Authorization header to blob storage.
            external = urllib.request.build_opener(SafeStorageRedirect())
            response = external.open(location, timeout=90)
        with response, destination.open("xb") as output:
            written = 0
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                require(written <= MAX_BYTES, "Artifact download exceeds size limit")
                output.write(chunk)


def validate_run(api: GitHub, run_id: int) -> dict:
    run = api.api(f"/repos/{REPOSITORY}/actions/runs/{run_id}")
    workflow = api.api(f"/repos/{REPOSITORY}/actions/workflows/android.yml")
    require(run.get("id") == run_id, "Unexpected build run ID")
    for field in ("repository", "head_repository"):
        repository = run.get(field) or {}
        require(
            repository.get("full_name") == REPOSITORY and repository.get("fork") is False,
            "Fork build is not eligible for publication",
        )
    require(
        run.get("path") == WORKFLOW and workflow.get("path") == WORKFLOW,
        "Unexpected build workflow",
    )
    require(run.get("workflow_id") == workflow.get("id"), "Build workflow identity mismatch")
    require(
        run.get("head_branch") == "main" and run.get("event") == "workflow_dispatch",
        "Only manually dispatched main builds may be published",
    )
    require(
        run.get("status") == "completed" and run.get("conclusion") == "success",
        "Build run did not finish successfully",
    )
    sha = run.get("head_sha", "")
    require(bool(SHA.fullmatch(sha)), "Invalid source commit")
    comparison = api.api(f"/repos/{REPOSITORY}/compare/{sha}...main")
    require(
        comparison.get("status") in ("ahead", "identical")
        and comparison.get("base_commit", {}).get("sha") == sha,
        "Build commit is outside current main history",
    )
    fixed_build = api.api(f"/repos/{REPOSITORY}/compare/{MINIMUM_BUILD_SHA}...{sha}")
    require(
        fixed_build.get("status") in ("ahead", "identical")
        and fixed_build.get("base_commit", {}).get("sha") == MINIMUM_BUILD_SHA,
        "Build predates the Android dependency and ELF verification fix",
    )
    return run


def unpack_artifact(archive_path: Path, directory: Path) -> str:
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        require(
            len(entries) == 3, "Artifact must contain exactly one APK, BUILD.txt and SHA256SUMS.txt"
        )
        seen = set()
        apk_name = None
        for entry in entries:
            name = entry.filename
            require(name.lower() not in seen, "Duplicate artifact filename")
            seen.add(name.lower())
            require(
                len(name) <= 127
                and (name in ("BUILD.txt", "SHA256SUMS.txt") or APK_NAME.fullmatch(name)),
                "Unexpected or unsafe artifact path",
            )
            mode = (entry.external_attr >> 16) & 0xF000
            require(
                mode in (0, 0x8000)
                and not (entry.external_attr & 0x400)
                and not entry.is_dir()
                and not (entry.flag_bits & 1),
                "Artifact must contain ordinary, unencrypted files",
            )
            limit = MAX_BYTES if name.endswith(".apk") else 4096
            require(0 < entry.file_size <= limit, "Invalid artifact member size")
            if name.endswith(".apk"):
                require(apk_name is None, "Multiple APKs in artifact")
                apk_name = name
            with archive.open(entry) as source, (directory / name).open("xb") as output:
                copied = 0
                while chunk := source.read(min(1024 * 1024, limit - copied + 1)):
                    copied += len(chunk)
                    require(copied <= limit, "Artifact member exceeds size limit")
                    output.write(chunk)
                require(copied == entry.file_size, "Incomplete artifact member")
        require(
            apk_name is not None and {"build.txt", "sha256sums.txt"}.issubset(seen),
            "Missing artifact metadata",
        )
        return apk_name


def check_package(directory: Path, metadata: dict) -> None:
    require(
        metadata.get("repository") == REPOSITORY and metadata.get("tag") == "v" + VERSION,
        "Unexpected publication identity",
    )
    sha, apk_name = metadata.get("source_sha", ""), metadata.get("apk_name", "")
    require(
        bool(SHA.fullmatch(sha)) and bool(APK_NAME.fullmatch(apk_name)), "Invalid package metadata"
    )
    build = (directory / "BUILD.txt").read_text(encoding="utf-8")
    expected = f"Source commit: {sha}\nArchitecture: arm64-v8a\nVersion: {VERSION}\nBuild: debug\n"
    require(
        build == expected, "BUILD.txt does not match successful build source/version/architecture"
    )
    checksum = (directory / "SHA256SUMS.txt").read_text(encoding="ascii")
    match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+\.apk)\n?", checksum)
    require(match is not None and match[2] == apk_name, "Invalid SHA256SUMS.txt")
    actual = digest(directory / apk_name)
    require(actual == match[1] and actual == metadata.get("apk_sha256"), "APK checksum mismatch")


def save_metadata(directory: Path, metadata: dict) -> None:
    (directory / METADATA).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def load_metadata(directory: Path) -> dict:
    metadata = json.loads((directory / METADATA).read_text(encoding="utf-8"))
    check_package(directory, metadata)
    return metadata


def download(api: GitHub, run_id: int, tag: str, directory: Path) -> None:
    require(tag == "v" + VERSION, f"This publisher supports v{VERSION}")
    run = validate_run(api, run_id)
    listing = api.api(f"/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100")
    require(listing.get("total_count", 0) <= 100, "Unexpected number of build artifacts")
    artifacts = [item for item in listing.get("artifacts", []) if item.get("name") == ARTIFACT]
    require(len(artifacts) == 1, "Expected one todaygo-debug-apk artifact")
    artifact = artifacts[0]
    require(
        artifact.get("expired") is False and 0 < artifact.get("size_in_bytes", 0) <= MAX_BYTES,
        "Artifact is expired or has an invalid size",
    )
    provenance = artifact.get("workflow_run") or {}
    require(
        provenance.get("id") == run_id and provenance.get("head_sha") == run["head_sha"],
        "Artifact build source mismatch",
    )
    require(
        provenance.get("repository_id") == run["repository"]["id"]
        and provenance.get("head_repository_id") == run["head_repository"]["id"],
        "Artifact repository mismatch",
    )
    directory.mkdir(parents=True, exist_ok=False)
    archive = directory / ".artifact.zip"
    api.download_artifact(artifact["id"], archive)
    require(archive.stat().st_size == artifact["size_in_bytes"], "GitHub artifact size mismatch")
    archive_digest = artifact.get("digest")
    if archive_digest is not None:
        require(archive_digest == "sha256:" + digest(archive), "GitHub artifact digest mismatch")
    apk_name = unpack_artifact(archive, directory)
    archive.unlink()
    metadata = {
        "repository": REPOSITORY,
        "tag": tag,
        "run_id": run_id,
        "artifact_id": artifact["id"],
        "source_sha": run["head_sha"],
        "apk_name": apk_name,
        "apk_sha256": digest(directory / apk_name),
        "verified": False,
    }
    check_package(directory, metadata)
    save_metadata(directory, metadata)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"source_sha={run['head_sha']}\n")
    print(
        f"Authenticated successful build {run_id}, commit {run['head_sha']}, artifact {artifact['id']}"
    )


def verify(directory: Path, source: Path) -> None:
    metadata = load_metadata(directory)
    head = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    require(head == metadata["source_sha"], "Verifier checkout does not match APK source commit")
    verifier = source / "scripts/verify_android_apk.py"
    require(verifier.is_file(), "Source build verifier is missing")
    environment = os.environ.copy()
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        environment.pop(name, None)
    subprocess.run([sys.executable, str(verifier), str(directory)], env=environment, check=True)
    check_package(directory, metadata)
    metadata["verified"] = True
    metadata["verifier_source_sha"] = head
    save_metadata(directory, metadata)


def tag_commit(api: GitHub, tag: str) -> str | None:
    ref = api.api(f"/repos/{REPOSITORY}/git/ref/tags/{tag}", missing=True)
    if ref is None:
        return None
    target = ref["object"]
    for _ in range(5):
        if target.get("type") == "commit":
            require(bool(SHA.fullmatch(target.get("sha", ""))), "Invalid release tag target")
            return target["sha"]
        require(
            target.get("type") == "tag" and bool(SHA.fullmatch(target.get("sha", ""))),
            "Unexpected tag object",
        )
        target = api.api(f"/repos/{REPOSITORY}/git/tags/{target['sha']}")["object"]
    raise RuntimeError("Release tag indirection limit exceeded")


def release_notes(metadata: dict) -> str:
    apk = metadata["apk_name"]
    marker = f"<!-- todaygo-android run={metadata['run_id']} sha={metadata['source_sha']} apk={metadata['apk_sha256']} -->"
    return f"""Готовое приложение **«Сегодня идём»** для Android 7 и новее, ARM64.

[Скачать приложение APK](https://github.com/{REPOSITORY}/releases/download/{metadata["tag"]}/{apk})

Скачайте APK и откройте его на телефоне. Если Android попросит, разрешите установку этому браузеру. Это версия для учебного проекта с отладочной подписью.

Для входа, мероприятий и карты подключите приложение к серверу:

1. На Windows обновите проект и откройте `CONFIGURE_EMAIL_WINDOWS.bat`. Введите адрес Mail.ru и пароль приложения локально на компьютере.
2. Запустите `START_ANDROID_SERVER_WINDOWS.bat` и оставьте его окно открытым.
3. Подключите телефон и компьютер к одной сети Wi-Fi. В настройке сервера приложения введите адрес из окна запуска, включите «Сервер на моём ПК через Wi-Fi» и нажмите «Проверить и подключиться».

В приложении: анимированный фон Москвы, карта, мероприятия и подтверждение входа кодом на почту.

Вход через Google удалён. Установка и работа на физическом Android в этой среде ещё не проверялись.

Контрольная сумма и сведения о сборке приложены в `SHA256SUMS.txt` и `BUILD.txt`.

{marker}
"""


def publish(api: GitHub, directory: Path) -> None:
    metadata = load_metadata(directory)
    require(
        metadata.get("verified") is True
        and metadata.get("verifier_source_sha") == metadata["source_sha"],
        "APK has not passed the source build verifier",
    )
    run = validate_run(api, metadata["run_id"])
    require(run["head_sha"] == metadata["source_sha"], "Publication source changed")
    existing_tag = tag_commit(api, metadata["tag"])
    require(
        existing_tag in (None, metadata["source_sha"]),
        "Existing release tag points to another commit",
    )
    releases = api.api(f"/repos/{REPOSITORY}/releases?per_page=100")
    require(len(releases) < 100, "Release listing requires additional pagination")
    matching = [release for release in releases if release.get("tag_name") == metadata["tag"]]
    require(len(matching) <= 1, "Multiple matching releases")
    notes = release_notes(metadata)
    marker = notes.split("<!--", 1)[1]
    if matching:
        release = matching[0]
        require(
            marker in release.get("body", ""), "Existing release belongs to another publication"
        )
        require(
            release.get("target_commitish") == metadata["source_sha"],
            "Existing release source mismatch",
        )
    else:
        release = api.api(
            f"/repos/{REPOSITORY}/releases",
            method="POST",
            payload={
                "tag_name": metadata["tag"],
                "target_commitish": metadata["source_sha"],
                "name": f"Сегодня идём {VERSION} — Android",
                "body": notes,
                "draft": True,
                "prerelease": False,
            },
        )
    expected = [metadata["apk_name"], "SHA256SUMS.txt", "BUILD.txt"]
    assets = api.api(f"/repos/{REPOSITORY}/releases/{release['id']}/assets?per_page=100")
    require(
        len(assets) <= 3 and all(asset.get("name") in expected for asset in assets),
        "Release contains unexpected assets; nothing overwritten",
    )
    if not release.get("draft"):
        require(
            len(assets) == 3 and len({asset.get("name") for asset in assets}) == 3,
            "Published release is incomplete",
        )
        for asset in assets:
            path = directory / asset["name"]
            require(
                asset.get("state") == "uploaded"
                and asset.get("size") == path.stat().st_size
                and asset.get("digest") == "sha256:" + digest(path),
                "Published asset verification failed",
            )
        print("This verified release is already published: " + release["html_url"])
        return
    # Only assets in this helper's matching private draft may be replaced during retry.
    for asset in assets:
        api.api(f"/repos/{REPOSITORY}/releases/assets/{asset['id']}", method="DELETE")
    upload_base = release["upload_url"].split("{", 1)[0]
    for name in expected:
        path = directory / name
        payload = path.read_bytes()
        require(len(payload) <= MAX_BYTES, "Release asset exceeds size limit")
        content_type = (
            "application/vnd.android.package-archive" if name.endswith(".apk") else "text/plain"
        )
        asset = api.api(
            upload_base + "?" + urllib.parse.urlencode({"name": name}),
            method="POST",
            data=payload,
            content_type=content_type,
        )
        require(
            asset.get("name") == name
            and asset.get("state") == "uploaded"
            and asset.get("size") == len(payload),
            "GitHub did not complete asset upload; draft remains unpublished",
        )
        if asset.get("digest") is not None:
            require(
                asset["digest"] == "sha256:" + hashlib.sha256(payload).hexdigest(),
                "Uploaded asset checksum mismatch; draft remains unpublished",
            )
        print("Uploaded verified asset: " + name)
    require(
        tag_commit(api, metadata["tag"]) in (None, metadata["source_sha"]),
        "Release tag changed during upload; draft remains unpublished",
    )
    published = api.api(
        f"/repos/{REPOSITORY}/releases/{release['id']}", method="PATCH", payload={"draft": False}
    )
    require(published.get("draft") is False, "GitHub did not publish the release")
    require(
        tag_commit(api, metadata["tag"]) == metadata["source_sha"],
        "Published tag does not match verified source",
    )
    print("Published release: " + published["html_url"])
    print(
        f"Direct APK: https://github.com/{REPOSITORY}/releases/download/{metadata['tag']}/{metadata['apk_name']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("download", "verify", "publish"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--tag", default="v" + VERSION)
    parser.add_argument("--source-directory", type=Path)
    args = parser.parse_args()
    if args.command == "download":
        require(
            args.run_id is not None and re.fullmatch(r"[1-9][0-9]{0,19}", args.run_id) is not None,
            "Invalid build run ID",
        )
        download(GitHub(), int(args.run_id), args.tag, args.directory)
    elif args.command == "verify":
        require(args.source_directory is not None, "Source directory is required")
        verify(args.directory, args.source_directory)
    else:
        publish(GitHub(), args.directory)


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        ValueError,
        KeyError,
        OSError,
        zipfile.BadZipFile,
        subprocess.CalledProcessError,
    ) as error:
        # Signed storage URLs and tokens must never appear in failure logs.
        message = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print("Publication stopped: " + message, file=sys.stderr)
        raise SystemExit(1) from None
