"""Build Android without accidentally packaging Linux dependency wheels."""

import os
from pathlib import Path

from buildozer import Buildozer


def main():
    os.chdir(Path(__file__).resolve().parents[1] / "client")
    excluded = os.environ.get("PIP_NO_BINARY", "").split(",")
    if "charset-normalizer" not in excluded and ":all:" not in excluded:
        excluded.append("charset-normalizer")
    os.environ["PIP_NO_BINARY"] = ",".join(filter(None, excluded))
    # charset-normalizer provides a pure Python implementation for ARM64.
    os.environ["CHARSET_NORMALIZER_USE_MYPYC"] = "0"
    Buildozer().run_command(["android", "debug"])


if __name__ == "__main__":
    main()
