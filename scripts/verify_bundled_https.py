"""Check live Moscow tile HTTPS using the CA file packaged in the APK."""

import io
from pathlib import Path
import ssl
import struct
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile


def verify(directory: Path) -> None:
    apks = list(directory.glob("*.apk"))
    if len(apks) != 1:
        raise RuntimeError("Expected exactly one previously verified Android APK")
    with zipfile.ZipFile(apks[0]) as archive:
        with tarfile.open(
            fileobj=io.BytesIO(archive.read("lib/arm64-v8a/libpybundle.so")), mode="r:*"
        ) as bundle:
            certificates = [
                member
                for member in bundle.getmembers()
                if member.isfile() and member.name.endswith("/certifi/cacert.pem")
            ]
            if len(certificates) != 1 or not 0 < certificates[0].size < 1024 * 1024:
                raise RuntimeError("APK must contain one bounded certifi CA file")
            with bundle.extractfile(certificates[0]) as source:
                pem = source.read()
    with tempfile.TemporaryDirectory(prefix="todaygo-ca-") as temporary:
        ca_file = Path(temporary) / "cacert.pem"
        ca_file.write_bytes(pem)
        context = ssl.create_default_context(cafile=str(ca_file))
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise RuntimeError("Certificate and hostname verification must stay enabled")
        for host, path in (
            ("tile.openstreetmap.org", "/10/619/320.png"),
            ("a.tile.openstreetmap.fr", "/hot/10/619/320.png"),
        ):
            request = urllib.request.Request(
                "https://" + host + path,
                headers={
                    "User-Agent": "TodayGo/1.0 (+https://github.com/dhdhsbdbd132-sys/ssdsad)",
                    "Accept": "image/png",
                },
            )
            try:
                with urllib.request.urlopen(request, context=context, timeout=15) as response:
                    data = response.read(2 * 1024 * 1024 + 1)
                    if (
                        response.status != 200
                        or not 24 <= len(data) <= 2 * 1024 * 1024
                        or data[:8] != b"\x89PNG\r\n\x1a\n"
                        or data[12:16] != b"IHDR"
                        or struct.unpack(">II", data[16:24]) != (256, 256)
                    ):
                        raise ValueError("Invalid Moscow map tile response")
                print(f"Verified HTTPS Moscow tile from {host} with the CA file from APK")
                return
            except (urllib.error.URLError, ValueError, TimeoutError) as error:
                print(f"Tile source {host} unavailable: {type(error).__name__}")
    raise RuntimeError("Neither map source passed verified HTTPS with the APK CA file")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
