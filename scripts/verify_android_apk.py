"""Check the built debug APK before offering it for installation."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
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
    native_count = 0
    readelf = shutil.which("readelf")
    if not readelf:
        raise RuntimeError("Install binutils/readelf to verify Android library dependencies")

    def check_elf(name: str, data: bytes):
        nonlocal native_count
        if (
            data[:6] != b"\x7fELF\x02\x01"
            or len(data) < 20
            or struct.unpack("<H", data[18:20])[0] != 183
        ):
            raise RuntimeError(f"Expected ARM64 ELF library, found another architecture: {name}")
        with tempfile.TemporaryDirectory(prefix="todaygo-elf-") as temporary:
            library = Path(temporary) / "library.so"
            library.write_bytes(data)
            metadata = subprocess.run(
                [readelf, "--wide", "--dynamic", "--version-info", str(library)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        forbidden = {
            "libc.so.6",
            "libm.so.6",
            "libdl.so.2",
            "libpthread.so.0",
            "librt.so.1",
            "libresolv.so.2",
            "libutil.so.1",
            "libstdc++.so.6",
            "libgcc_s.so.1",
            "ld-linux-aarch64.so.1",
            "ld-linux-x86-64.so.2",
        }
        needed = re.findall(r"\(NEEDED\).*?\[(.*?)\]", metadata)
        if forbidden.intersection(needed) or "GLIBC_" in metadata or "GLIBCXX_" in metadata:
            raise RuntimeError(f"GNU/Linux library cannot run on Android: {name}")
        native_count += 1

    with zipfile.ZipFile(apk) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"Damaged APK member: {bad_member}")
        names = set(archive.namelist())
        if "AndroidManifest.xml" not in names:
            raise RuntimeError("APK manifest is missing")
        if "lib/arm64-v8a/libmain.so" not in names:
            raise RuntimeError("ARM64 application library is missing")
        bundle_name = "lib/arm64-v8a/libpybundle.so"
        for name in names:
            if name.endswith(".so") and name != bundle_name:
                with archive.open(name) as library:
                    check_elf(name, library.read())
        if bundle_name not in names:
            raise RuntimeError("Python dependency bundle is missing")
        with tarfile.open(fileobj=io.BytesIO(archive.read(bundle_name)), mode="r:*") as bundle:
            bundled = bundle.getmembers()
            for member in bundled:
                if member.isfile() and member.name.endswith(".so"):
                    with bundle.extractfile(member) as library:
                        check_elf(member.name, library.read())
            dependency_names = [member.name for member in bundled]
            for dependency in ("certifi/cacert.pem", "requests/", "kivy_garden/mapview/"):
                if not any(dependency in name for name in dependency_names):
                    raise RuntimeError(f"Required Android dependency is missing: {dependency}")
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
    print(f"Verified architecture of {native_count} native libraries and extensions")
    print(f"SHA256: {hashlib.sha256(apk.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "client/bin")
    apks = sorted(directory.glob("*.apk"))
    if not apks:
        raise SystemExit(f"No APK files in {directory}")
    for artifact in apks:
        verify(artifact)
