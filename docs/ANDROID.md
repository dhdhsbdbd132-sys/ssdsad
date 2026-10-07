# Сборка Android

Клиент написан на Kivy 2.3.1. Подготовлен `buildozer.spec` для ARM64 и ARMv7, Android 7+ (min API 24), target API 35. `python-for-android` зафиксирован на tag v2024.01.21 (точный commit в spec). Это **конфигурация для сборки**, не подтверждение готового APK или публикации в Google Play.

## Вручную: Ubuntu 22.04 / WSL2

Нужны Python 3.11, OpenJDK 17 и инструменты компиляции. Backend можно запускать отдельно на Python 3.12.

```bash
sudo apt-get update
sudo apt-get install -y git zip unzip openjdk-17-jdk autoconf automake libtool \
  pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake \
  libffi-dev libssl-dev
python3.11 -m venv .android-venv
.android-venv/bin/pip install buildozer==1.5.0 Cython==0.29.36 setuptools==69.5.1
cd client
../.android-venv/bin/buildozer android debug
```

SDK/NDK скачиваются при первой сборке: нужны несколько GB диска, интернет и принятие лицензий Android SDK. APK появится в `client/bin/`. Исходники не содержат серверных секретов или OAuth Client Secret. При ошибках обновления SDK/NDK не отключайте TLS/проверку артефактов; изучите лог Buildozer и совместимость выбранного toolchain.

## Через GitHub Actions

После размещения проекта в вашем GitHub-репозитории откройте Actions → **Android debug APK** → **Run workflow**. Артефакт `todaygo-debug-apk` содержит APK при успешной сборке. Workflow не был запущен из этой сессии; код не отправлялся в GitHub.

## Подключение

В «Профиль» задайте HTTPS-адрес доступного API. Для эмулятора Android на той же машине: `http://10.0.2.2:8000`, API запускается с `API_HOST=0.0.0.0`. Для телефона `localhost` не является компьютером с backend.

Клиент допускает HTTP только для loopback и адреса Android Emulator. Для release сборки установите `android:usesCleartextTraffic="false"` в `client/android-application-arguments.xml` и используйте HTTPS. Сборку release нужно подписать вашим ключом; ключи и keystore не хранятся в репозитории.

Все операции проходят через API. Токены остаются в памяти; отдельного разрешения на файловое хранилище или местоположение нет. Точка события выбирается вручную на карте. Картографические тайлы используют HTTPS, сохраняются в приватном кэше приложения и имеют видимую атрибуцию. Карта центрируется на Москве; запасной режим — авторская приблизительная схема центра города.

## Ограничения проверки

Desktop-клиент запускался с реальной отрисовкой OpenGL и HTTP API; экраны и сценарии проверены автоматически. Android-компиляция, установка APK на устройство, аппаратная клавиатура/возврат из браузера OAuth на устройстве и release-подпись здесь не проверялись. Для сдачи в виде APK выполните приведённую сборку и smoke-проверку на эмуляторе или телефоне.
