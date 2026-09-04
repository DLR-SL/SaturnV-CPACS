#!/usr/bin/env bash
# Builds TiGL (python-internal bindings + pythonOCC) from source -- no Docker
# image and no container registry required.
#
# The script is idempotent: if a previous run (or a restored CI cache) already
# left a working environment behind, the expensive configure/install steps are
# skipped. That is what makes the GitHub Actions cache worthwhile.
#
# Configuration via environment:
#   TIGL_REF   git ref of DLR-SC/tigl to build          (default: main)
#   TIGL_DIR   where to clone and build TiGL            (default: $HOME/tigl)
#   PIXI_ENV   pixi environment to use                  (default: python-internal)
set -euo pipefail

TIGL_REF="${TIGL_REF:-main}"
TIGL_DIR="${TIGL_DIR:-${HOME}/tigl}"
PIXI_ENV="${PIXI_ENV:-python-internal}"

# GitLab ran this as root inside a container; GitHub-hosted runners are an
# unprivileged user with passwordless sudo. Handle both.
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

$SUDO apt-get update -qq
$SUDO apt-get install -y -qq --no-install-recommends \
    curl ca-certificates git build-essential cmake ninja-build

if ! [ -x "${HOME}/.pixi/bin/pixi" ]; then
    curl -fsSL https://pixi.sh/install.sh | bash
fi
export PATH="${HOME}/.pixi/bin:${PATH}"

if [ ! -d "${TIGL_DIR}/.git" ]; then
    git clone --branch "${TIGL_REF}" --depth 1 \
        https://github.com/DLR-SC/tigl.git "${TIGL_DIR}"
fi
cd "${TIGL_DIR}"

# The bindings are what the export script actually imports, so importing them
# is the honest check for "already built" -- more reliable than probing for
# build artefacts on disk.
if pixi run -e "${PIXI_ENV}" python -c "import tigl3.tigl3wrapper" >/dev/null 2>&1; then
    echo "TiGL already installed in ${TIGL_DIR} -- skipping build."
    exit 0
fi

pixi run -e "${PIXI_ENV}" configure
pixi run -e "${PIXI_ENV}" install
pixi add -e "${PIXI_ENV}" pythonocc-core lxml

# The export-models job invokes the export script through "pixi run", so pixi
# handles the full environment activation (PATH, LD_LIBRARY_PATH for the
# compiled OCCT/TiGL libraries) instead of us rebuilding it by hand.
