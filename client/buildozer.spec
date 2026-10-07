[app]
title = Сегодня идём
package.name = todaygo
package.domain = ru.todaygo
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,json,txt
source.exclude_dirs = tests,.buildozer,bin,__pycache__
version = 1.0.0
requirements = python3,kivy==2.3.1,kivy_garden.mapview==1.0.6,requests==2.32.5,certifi,openssl,pyjnius
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 35
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.enable_androidx = True
# Remote API uses HTTPS. Emulator localhost (10.0.2.2) can use HTTP in a debug build.
android.extra_manifest_application_arguments = android-application-arguments.xml
p4a.commit = 957a3e5f8c270f7aa648ba185e5a68c1077a798d
[buildozer]
log_level = 2
warn_on_root = 1
