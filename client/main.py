"""Desktop: python client/main.py. Android entry point: main.py."""

import os
from pathlib import Path
from kivy.utils import platform

if platform != "android":
    os.environ.setdefault("KIVY_HOME", str(Path(__file__).resolve().parents[1] / ".data/kivy"))
from todaygo.application import TodayGoApp

if __name__ == "__main__":
    TodayGoApp().run()
