#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export TODAYGO_DEMO=1
export KIVY_HOME="${KIVY_HOME:-$PWD/.data/kivy}"
export MESA_SHADER_CACHE_DIR="${MESA_SHADER_CACHE_DIR:-$PWD/.data/mesa}"
exec .client-venv/bin/python client/main.py
