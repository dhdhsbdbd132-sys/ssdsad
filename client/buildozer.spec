[app]
title = Сегодня идём
package.name = todaygo
package.domain = ru.todaygo
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,json,txt
source.exclude_dirs = tests,android-recipes,.buildozer,bin,__pycache__
version = 1.2.0
android.numeric_version = 120
requirements = python3==3.12.14,hostpython3==3.12.14,kivy==2.3.1,kivy_garden.mapview==1.0.6,requests==2.32.5,certifi,openssl,pyjnius
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 35
android.minapi = 24
android.ndk = 28c
android.archs = arm64-v8a
android.accept_sdk_license = True
android.enable_androidx = True
# Debug APK supports an explicitly selected private LAN API and the emulator.
# A signed production release must use HTTPS and usesCleartextTraffic=false.
android.extra_manifest_application_arguments = android-application-arguments.xml
# python-for-android v2026.05.09, with Python 3.12 pinned for Kivy 2.3.1.
p4a.commit = 58d21141f17c889bf8585f5665921d72028f8831
p4a.local_recipes = android-recipes
[buildozer]
log_level = 2
warn_on_root = 1
