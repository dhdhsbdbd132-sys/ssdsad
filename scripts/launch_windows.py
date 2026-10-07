"""Local desktop supervisor used by START_WINDOWS.bat; also testable on Linux."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".data"
VENV = ROOT / ".windows-venv"
REQUIREMENTS = (ROOT / "backend/requirements.txt", ROOT / "client/requirements.lock.txt")


@contextmanager
def launch_lock():
    DATA.mkdir(parents=True, exist_ok=True)
    # OS releases the lock even if the launcher is interrupted or crashes.
    with (DATA / "windows-launch.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                "Приложение уже запускается или работает. Проверьте открытые окна."
            ) from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def command(args, *, env=None):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, env=env, check=False)
    if result.returncode:
        raise RuntimeError(
            f"Команда завершилась с ошибкой {result.returncode}. Подробности показаны выше."
        )


def prepare():
    if sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        raise RuntimeError("Требуется Python 3.12, 64-bit.")
    python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if VENV.exists() and not (VENV / "pyvenv.cfg").is_file():
        raise RuntimeError(
            "Папка .windows-venv уже существует и не является виртуальным окружением. Её содержимое сохранено."
        )
    if not python.is_file():
        print("Создаём отдельное окружение приложения…", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV)
    digest = hashlib.sha256()
    digest.update(str(sys.version_info[:3]).encode())
    for requirements in REQUIREMENTS:
        digest.update(requirements.read_bytes())
    stamp = VENV / "todaygo-dependencies.sha256"
    current = digest.hexdigest()
    if not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != current:
        print("Устанавливаем зависимости. Первый запуск может занять несколько минут…", flush=True)
        command(
            [
                python,
                "-X",
                "utf8",
                "-m",
                "pip",
                "install",
                "--no-input",
                "--disable-pip-version-check",
                "-r",
                REQUIREMENTS[0],
                "-r",
                REQUIREMENTS[1],
            ]
        )
        stamp.write_text(current, encoding="utf-8")
    else:
        print("Зависимости уже установлены.", flush=True)
    return python


def port_for_api():
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 8000))
            return 8000
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


def stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def request_json(url):
    # Never send localhost health checks through an unrelated corporate proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=1) as response:
        return json.load(response)


def run(smoke=False):
    with launch_lock():
        python = prepare()
        api_env = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
        # -X utf8 keeps file mail and Cyrillic data consistent across Windows locales.
        environment = subprocess.check_output(
            [
                str(python),
                "-X",
                "utf8",
                "-c",
                "from app.core.config import Settings; print(Settings().environment)",
            ],
            cwd=ROOT,
            env=api_env,
            text=True,
            encoding="utf-8",
        ).strip()
        if environment != "development":
            raise RuntimeError(
                "Этот файл предназначен для локальной разработки. Текущая .env сохранена; для другого режима используйте инструкции README."
            )
        print("Подготавливаем базу данных и мероприятия Москвы…", flush=True)
        command(
            [
                python,
                "-X",
                "utf8",
                "-m",
                "alembic",
                "-c",
                ROOT / "backend/alembic.ini",
                "upgrade",
                "head",
            ],
            env=api_env,
        )
        command([python, "-X", "utf8", "-m", "app.cli", "seed"], env=api_env)
        port = port_for_api()
        if port != 8000:
            print(
                f"Порт 8000 занят: приложение использует {port}. Для внешнего OAuth адрес callback должен соответствовать этому порту.",
                flush=True,
            )
        url = f"http://127.0.0.1:{port}"
        log_file = DATA / f"windows-api-{time.time_ns()}.log"
        api, client = None, None
        with log_file.open("w", encoding="utf-8") as log:
            try:
                api = subprocess.Popen(
                    [
                        str(python),
                        "-X",
                        "utf8",
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--app-dir",
                        str(ROOT / "backend"),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                        "--no-proxy-headers",
                    ],
                    cwd=ROOT,
                    env=api_env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if api.poll() is not None:
                        raise RuntimeError(f"Сервер завершился при запуске. Лог: {log_file}")
                    try:
                        if request_json(url + "/api/health") == {"status": "ok"}:
                            page = request_json(url + "/api/events")
                            if isinstance(page.get("items"), list):
                                break
                    except (urllib.error.URLError, OSError, ValueError):
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError(f"Сервер не запустился за 30 секунд. Лог: {log_file}")
                print("Сервер готов. Открываем приложение.", flush=True)
                print(
                    "Для кода регистрации откройте READ_CODE_WINDOWS.bat. При настроенном SMTP проверьте свою почту.",
                    flush=True,
                )
                client_env = {
                    **os.environ,
                    "TODAYGO_API_URL": url,
                    "KIVY_HOME": str(DATA / "kivy"),
                    "MESA_SHADER_CACHE_DIR": str(DATA / "mesa"),
                }
                no_proxy = ",".join(
                    [
                        client_env.get("NO_PROXY", ""),
                        client_env.get("no_proxy", ""),
                        "127.0.0.1",
                        "localhost",
                    ]
                )
                client_env["NO_PROXY"] = client_env["no_proxy"] = no_proxy
                if smoke:
                    client_env["TODAYGO_MAP_MODE"] = "offline"
                    # Actual Kivy/OpenGL window and HTTP load; no mock application.
                    code = """from kivy.clock import Clock
from todaygo.application import TodayGoApp
app=TodayGoApp()
def check(_):
    assert not app.busy and len(app.events)>=6, 'Kivy did not load Moscow events'
    app.root.export_to_png('.data/windows-launch-smoke.png')
    app.stop()
Clock.schedule_once(check,4)
app.run()
"""
                    client_env["PYTHONPATH"] = str(ROOT / "client")
                    args = [str(python), "-X", "utf8", "-c", code]
                else:
                    args = [str(python), "-X", "utf8", str(ROOT / "client/main.py")]
                client = subprocess.Popen(args, cwd=ROOT, env=client_env)
                if client.wait() != 0:
                    raise RuntimeError("Клиент завершился с ошибкой. Подробности показаны выше.")
                print("Приложение закрыто. Останавливаем его сервер.", flush=True)
            finally:
                stop(client)
                stop(api)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Сегодня идём — запуск для компьютера")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Проверить реальный запуск Kivy и API, затем закрыть",
    )
    options = parser.parse_args()
    try:
        run(smoke=options.smoke_test)
    except KeyboardInterrupt:
        print("\nЗапуск остановлен.")
        sys.exit(130)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        sys.exit(1)
