"""Local desktop or Android API supervisor; also testable on Linux."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
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
                "Приложение или сервер Android уже запускается или работает. Проверьте открытые окна."
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


def prepare(android_server=False):
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
    requirements_files = REQUIREMENTS[:1] if android_server else REQUIREMENTS
    for requirements in requirements_files:
        digest.update(requirements.read_bytes())
    stamp = VENV / (
        "todaygo-api-dependencies.sha256" if android_server else "todaygo-dependencies.sha256"
    )
    current = digest.hexdigest()
    if not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != current:
        print("Устанавливаем зависимости. Первый запуск может занять несколько минут…", flush=True)
        arguments = [
            python,
            "-X",
            "utf8",
            "-m",
            "pip",
            "install",
            "--no-input",
            "--disable-pip-version-check",
        ]
        for requirements in requirements_files:
            arguments.extend(("-r", requirements))
        command(arguments)
        stamp.write_text(current, encoding="utf-8")
    else:
        print("Зависимости уже установлены.", flush=True)
    return python


def port_for_api(host="127.0.0.1"):
    with socket.socket() as sock:
        for port in (8000, 8080, 0):
            try:
                sock.bind((host, port))
            except OSError:
                if port == 0:
                    raise
            else:
                return sock.getsockname()[1]


def lan_ipv4_addresses():
    """Read local RFC1918 addresses without contacting an Internet service."""
    candidates = set()
    try:
        for address in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.add(address[4][0])
    except OSError:
        pass
    # UDP connect selects an interface from the local routing table; no packet is sent.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            try:
                sock.connect(("192.0.2.1", 9))
            except BlockingIOError:
                pass
            candidates.add(sock.getsockname()[0])
    except OSError:
        pass
    if os.name == "nt":
        try:
            result = subprocess.run(["ipconfig"], capture_output=True, timeout=5, check=False)
            if result.returncode == 0:
                # IPv4 and digits survive both Russian and English OEM encodings.
                output = result.stdout.decode("utf-8", errors="replace")
                candidates.update(re.findall(r"IPv4[^:\r\n]*:\s*([\d.]+)", output))
        except (OSError, subprocess.SubprocessError):
            pass
    private_networks = tuple(
        ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )
    addresses = []
    for value in candidates:
        try:
            address = ipaddress.IPv4Address(value)
        except ipaddress.AddressValueError:
            continue
        if any(address in network for network in private_networks):
            try:
                # A hostname can have a stale DNS record; require an address owned by this PC.
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                    probe.bind((str(address), 0))
            except OSError:
                continue
            addresses.append(address)
    return [str(address) for address in sorted(addresses)]


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


def run(smoke=False, android_server=False):
    with launch_lock():
        python = prepare(android_server=android_server)
        api_env = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
        # -X utf8 keeps file mail and Cyrillic data consistent across Windows locales.
        settings = json.loads(
            subprocess.check_output(
                [
                    str(python),
                    "-X",
                    "utf8",
                    "-c",
                    "import json; from app.core.config import Settings; s=Settings(); "
                    "print(json.dumps({'environment': s.environment, 'mail_backend': s.mail_backend}))",
                ],
                cwd=ROOT,
                env=api_env,
                text=True,
                encoding="utf-8",
            ).strip()
        )
        if settings["environment"] != "development":
            raise RuntimeError(
                "Этот файл предназначен для локальной разработки. Текущая .env сохранена; для другого режима используйте инструкции README."
            )
        addresses = lan_ipv4_addresses() if android_server else []
        if android_server and not addresses:
            raise RuntimeError(
                "Не удалось найти локальный IPv4-адрес компьютера. Подключите компьютер и телефон "
                "к одной сети Wi-Fi и запустите START_ANDROID_SERVER_WINDOWS.bat ещё раз. "
                "Проверьте, что подключение к Wi-Fi активно."
            )
        host = "0.0.0.0" if android_server else "127.0.0.1"
        if android_server:
            # Only hosts belonging to this PC are accepted; no wildcard or public address.
            api_env["ALLOWED_HOSTS"] = ",".join(["localhost", "127.0.0.1", *addresses])
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
        port = port_for_api(host)
        if port != 8000:
            print(
                f"Порт 8000 занят: сервер использует порт {port}. Используйте адрес с этим портом.",
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
                        host,
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
                if settings["mail_backend"] == "file":
                    print(
                        "Режим разработки: письма не отправляются. Для кода откройте "
                        "READ_CODE_WINDOWS.bat. Для отправки писем запустите CONFIGURE_EMAIL_WINDOWS.bat.",
                        flush=True,
                    )
                else:
                    print(
                        "Настроен SMTP: код подтверждения ищите в своей почте и папке «Спам».",
                        flush=True,
                    )
                if android_server:
                    print("Компьютер и телефон должны быть в одной сети Wi-Fi.", flush=True)
                    for address in addresses:
                        print(f"Адрес сервера для телефона: http://{address}:{port}", flush=True)
                    print(
                        "Сервер Android готов. Оставьте это окно открытым. Для остановки нажмите Ctrl+C.",
                        flush=True,
                    )
                    while api.poll() is None:
                        time.sleep(0.25)
                    raise RuntimeError(f"Сервер Android завершился. Лог: {log_file}")
                print("Сервер готов. Открываем приложение.", flush=True)
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
    parser = argparse.ArgumentParser(description="Сегодня идём — приложение или сервер Android")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Проверить реальный запуск Kivy и API, затем закрыть",
    )
    parser.add_argument(
        "--android-server",
        action="store_true",
        help="Запустить только API для телефона в локальной сети, без Kivy",
    )
    options = parser.parse_args()
    if options.smoke_test and options.android_server:
        parser.error("--smoke-test и --android-server используются отдельно")
    try:
        run(smoke=options.smoke_test, android_server=options.android_server)
    except KeyboardInterrupt:
        print("\nЗапуск остановлен.")
        sys.exit(130)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        sys.exit(1)
