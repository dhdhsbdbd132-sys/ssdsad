"""Verified HTTPS tiles with an atomic, reusable cache.

Mapview's stock downloader silently leaves failed tiles in ``loading`` forever.
This transport reports failures to the map and never caches HTML error pages.
"""

import os
import struct
import tempfile
import time
import zlib
from pathlib import Path

import requests

USER_AGENT = "TodayGo/1.0 (+https://github.com/dhdhsbdbd132-sys/ssdsad)"
MAX_TILE_BYTES = 2 * 1024 * 1024
CACHE_TTL = 7 * 24 * 60 * 60
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate_png(data, tile_size=256):
    """Reject damaged, oversized, or non-image responses before caching them."""
    if len(data) > MAX_TILE_BYTES or not data.startswith(PNG_SIGNATURE):
        raise ValueError("Tile response is not a PNG image")
    offset, compressed, first, ended = 8, bytearray(), True, False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        if length > MAX_TILE_BYTES or offset + length + 12 > len(data):
            raise ValueError("Truncated PNG tile")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        expected = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected:
            raise ValueError("Damaged PNG tile")
        if first:
            if kind != b"IHDR" or length != 13:
                raise ValueError("Missing PNG header")
            width, height = struct.unpack_from(">II", payload)
            if (width, height) != (tile_size, tile_size):
                raise ValueError("Unexpected tile dimensions")
            first = False
        if kind == b"IDAT":
            compressed.extend(payload)
        offset += length + 12
        if kind == b"IEND":
            ended = True
            break
    if not ended or offset != len(data) or not compressed:
        raise ValueError("Incomplete PNG tile")
    decoder = zlib.decompressobj()
    decoder.decompress(bytes(compressed), tile_size * tile_size * 8 + tile_size + 1)
    if not decoder.eof or decoder.unused_data:
        raise ValueError("Invalid PNG image data")


def load_tile(url, cache_path, tile_size=256):
    """Return a validated cache path; HTTPS certificate checks stay enabled."""
    path = Path(cache_path)
    stale = False
    if path.exists():
        try:
            data = path.read_bytes() if path.stat().st_size <= MAX_TILE_BYTES else b""
            validate_png(data, tile_size)
            if time.time() - path.stat().st_mtime < CACHE_TTL:
                return str(path)
            stale = True
        except (OSError, ValueError, zlib.error):
            path.unlink(missing_ok=True)
    if not url.startswith("https://"):
        raise ValueError("Map tiles require HTTPS")
    try:
        with requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "image/png"},
            timeout=(3, 7),
            verify=True,
            stream=True,
        ) as response:
            response.raise_for_status()
            data = bytearray()
            for block in response.iter_content(chunk_size=65536):
                data.extend(block)
                if len(data) > MAX_TILE_BYTES:
                    raise ValueError("Map tile exceeds the size limit")
            validate_png(bytes(data), tile_size)
    except (requests.RequestException, ValueError, zlib.error):
        if stale:
            return str(path)
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tile-", delete=False) as out:
            temporary = out.name
            out.write(data)
        os.replace(temporary, path)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
    return str(path)
