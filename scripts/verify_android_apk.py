"""Check the built debug APK before offering it for installation."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile


def find_android_tool(name: str) -> Path:
    roots = [Path.home() / ".buildozer/android/platform/android-sdk"]
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]))
    candidates = [
        tool
        for root in roots
        for tool in (root / "build-tools").glob(f"*/{name}")
        if tool.is_file()
    ]
    if not candidates:
        raise RuntimeError(f"Android build tool {name} is missing")
    return max(candidates, key=lambda p: tuple(int(x) for x in re.findall(r"\d+", p.parent.name)))


def verify(apk: Path) -> None:
    with zipfile.ZipFile(apk) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"Damaged APK member: {bad_member}")
        names = set(archive.namelist())
        if "AndroidManifest.xml" not in names:
            raise RuntimeError("APK manifest is missing")
        if "lib/arm64-v8a/libmain.so" not in names:
            raise RuntimeError("ARM64 application library is missing")
        if "assets/private.tar" not in names:
            raise RuntimeError("Application package is missing")
        with tarfile.open(
            fileobj=io.BytesIO(archive.read("assets/private.tar")), mode="r:*"
        ) as private:
            packaged = {member.name.removeprefix("./") for member in private.getmembers()}
        for stem in ("main", "todaygo/application", "todaygo/ambient", "todaygo/api"):
            if not any(f"{stem}.{ext}" in packaged for ext in ("py", "pyc")):
                raise RuntimeError(f"Application module is missing: {stem}")
        if "assets/DejaVuSans.ttf" not in packaged:
            raise RuntimeError("Russian UI font is missing")

    subprocess.run(
        [str(find_android_tool("apksigner")), "verify", "--verbose", str(apk)], check=True
    )
    metadata = subprocess.run(
        [str(find_android_tool("aapt")), "dump", "badging", str(apk)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if "name='ru.todaygo.todaygo'" not in metadata:
        raise RuntimeError("Unexpected Android package name")
    if "versionName='1.2.0'" not in metadata:
        raise RuntimeError("Unexpected application version")
    for declaration in ("sdkVersion:'24'", "targetSdkVersion:'35'", "android.permission.INTERNET"):
        if declaration not in metadata:
            raise RuntimeError(f"Required APK metadata is missing: {declaration}")
    print(f"Verified {apk.name}: ARM64, Android 7+, target API 35, valid debug signature")
    print(f"SHA256: {hashlib.sha256(apk.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "client/bin")
    apks = sorted(directory.glob("*.apk"))
    if not apks:
        raise SystemExit(f"No APK files in {directory}")
    for artifact in apks:
        verify(artifact)
