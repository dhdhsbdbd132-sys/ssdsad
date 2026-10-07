"""Record the real Kivy auth/background animation without starting an API.

Run with the client Python environment; Pillow is needed only for this capture:
    pip install Pillow
    python scripts/capture_motion.py

For a headless Linux environment, set SDL_VIDEODRIVER=offscreen. The recording
uses temporary settings and never submits forms, calls an API or shows a map.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
os.environ.setdefault("KIVY_HOME", str(ROOT / ".data/kivy-motion"))
os.environ["TODAYGO_MAP_MODE"] = "offline"
os.environ["TODAYGO_REDUCED_MOTION"] = "0"

from kivy.clock import Clock
from todaygo.application import TodayGoApp
from todaygo.theme import Action, BG, CYAN, INK, LIME, MUTED, STROKE, SURFACE, SURFACE_HIGH, VIOLET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/animated-design.gif")
    parser.add_argument("--fps", type=int, choices=range(1, 25), default=8)
    parser.add_argument("--width", type=int, choices=range(180, 481), default=360)
    args = parser.parse_args()
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "Install the capture-only dependency: python -m pip install Pillow"
        ) from exc

    data = ROOT / ".data"
    data.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="capture-motion-", dir=data) as temporary:
        folder = Path(temporary)
        settings = folder / "settings"
        settings.mkdir()
        screenshots = []

        class MotionPreview(TodayGoApp):
            @property
            def user_data_dir(self):
                return str(settings)

            def build(self):
                root = super().build()
                self._start_event.cancel()
                self._capture_event = None
                self._timeline = []
                self.go_auth()
                return root

            def run_api(self, fn, callback):
                raise RuntimeError("The motion capture must not call the API")

            def on_start(self):
                def focus_email(_):
                    self.screens["auth"].fields["email"].focus = True

                def blur_email(_):
                    self.screens["auth"].fields["email"].focus = False

                def register(_):
                    button = next(
                        widget
                        for widget in self.screens["auth"].walk()
                        if isinstance(widget, Action) and widget.text == "Нет аккаунта? Регистрация"
                    )
                    button.trigger_action(duration=0.18)

                for delay, action in (
                    (1.0, focus_email),
                    (1.7, blur_email),
                    (2.1, register),
                    (4.3, lambda _: self.go_connect()),
                    (5.8, lambda _: self.go_auth()),
                ):
                    self._timeline.append(Clock.schedule_once(action, delay))
                self._capture_event = Clock.schedule_interval(self._capture, 1 / args.fps)

            def _capture(self, _):
                target = folder / f"frame-{len(screenshots):03d}.png"
                self.root.export_to_png(str(target))
                screenshots.append(target)
                if len(screenshots) >= 7 * args.fps:
                    self.stop()
                    return False

            def on_stop(self):
                if self._capture_event is not None:
                    self._capture_event.cancel()
                for event in self._timeline:
                    event.cancel()
                super().on_stop()

        MotionPreview().run()
        if len(screenshots) != 7 * args.fps:
            raise RuntimeError("Capture stopped before all seven seconds were recorded")

        frames = []
        for filename in screenshots:
            with Image.open(filename) as source:
                height = round(source.height * args.width / source.width)
                frames.append(
                    source.convert("RGB").resize((args.width, height), Image.Resampling.LANCZOS)
                )
        # One palette for all frames prevents the gradients and text from flashing.
        sw, sh = 96, round(frames[0].height * 96 / args.width)
        atlas = Image.new("RGB", (sw * len(frames), sh))
        for index, frame in enumerate(frames):
            atlas.paste(frame.resize((sw, sh), Image.Resampling.LANCZOS), (index * sw, 0))
        palette = atlas.quantize(
            colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        )
        # Small white labels must stay white even when the gradients dominate the
        # sampled image. Reserve the exact UI colours and a few anti-alias greys.
        reserved = [BG, SURFACE, SURFACE_HIGH, STROKE, INK, MUTED, LIME, CYAN, VIOLET, (1, 1, 1, 1)]
        for fraction in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9):
            reserved.append(
                tuple(start + (end - start) * fraction for start, end in zip(SURFACE, INK))
            )
        colours = palette.getpalette()
        for index, colour in enumerate(reserved, start=240):
            colours[index * 3 : index * 3 + 3] = [round(channel * 255) for channel in colour[:3]]
        palette.putpalette(colours)
        paletted = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
        # GIF durations have 10 ms precision, so alternate 120/130 ms at 8 fps.
        durations = [
            (round((i + 1) * 100 / args.fps) - round(i * 100 / args.fps)) * 10
            for i in range(len(frames))
        ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        paletted[0].save(
            args.output,
            save_all=True,
            append_images=paletted[1:],
            loop=0,
            duration=durations,
            disposal=2,
            optimize=True,
        )
        print(f"Captured {len(frames)} real Kivy frames: {args.output}")


if __name__ == "__main__":
    main()
