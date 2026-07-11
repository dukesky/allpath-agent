#!/bin/sh

set -eu

REPOSITORY_URL="https://github.com/dukesky/allpath-agent.git"
ALLPATH_HOME="${ALLPATH_HOME:-$HOME/.allpath-agent}"
INSTALL_DIR=""
BIN_DIR="${ALLPATH_BIN_DIR:-$HOME/.local/bin}"
SOURCE_DIR=""
PYTHON_COMMAND=""
LOCAL_INSTALL=false
SKIP_LAUNCH=false
UPDATE_PATH=true

log() {
    printf '%s\n' "→ $1"
}

success() {
    printf '%s\n' "✓ $1"
}

fail() {
    printf '%s\n' "Error: $1" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Allpath Agent installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/dukesky/allpath-agent/main/scripts/install.sh | sh
  ./scripts/install.sh --local

Options:
  --local                 Install the current checkout for local testing
  --source PATH           Install a specific local checkout
  --home PATH             Data and managed-runtime directory
  --install-dir PATH      Managed application directory
  --bin-dir PATH          Command directory (default: ~/.local/bin)
  --python PATH           Python 3.11+ interpreter
  --skip-launch           Install without starting the first conversation
  --no-path-update        Do not modify the shell PATH configuration
  -h, --help              Show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --local)
            LOCAL_INSTALL=true
            shift
            ;;
        --source)
            [ "$#" -ge 2 ] || fail "--source requires a path"
            LOCAL_INSTALL=true
            SOURCE_DIR=$2
            shift 2
            ;;
        --home)
            [ "$#" -ge 2 ] || fail "--home requires a path"
            ALLPATH_HOME=$2
            shift 2
            ;;
        --install-dir)
            [ "$#" -ge 2 ] || fail "--install-dir requires a path"
            INSTALL_DIR=$2
            shift 2
            ;;
        --bin-dir)
            [ "$#" -ge 2 ] || fail "--bin-dir requires a path"
            BIN_DIR=$2
            shift 2
            ;;
        --python)
            [ "$#" -ge 2 ] || fail "--python requires a path"
            PYTHON_COMMAND=$2
            shift 2
            ;;
        --skip-launch)
            SKIP_LAUNCH=true
            shift
            ;;
        --no-path-update)
            UPDATE_PATH=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

ALLPATH_HOME=$(mkdir -p "$ALLPATH_HOME" && cd "$ALLPATH_HOME" && pwd)
INSTALL_DIR=${INSTALL_DIR:-"$ALLPATH_HOME/runtime"}
mkdir -p "$INSTALL_DIR" "$BIN_DIR"
INSTALL_DIR=$(cd "$INSTALL_DIR" && pwd)
BIN_DIR=$(cd "$BIN_DIR" && pwd)
VENV_DIR="$INSTALL_DIR/venv"

python_is_supported() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    if [ -n "$PYTHON_COMMAND" ]; then
        python_is_supported "$PYTHON_COMMAND" || fail "--python must be Python 3.11 or newer"
        return
    fi
    for candidate in python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1 \
            && python_is_supported "$(command -v "$candidate")"; then
            PYTHON_COMMAND=$(command -v "$candidate")
            return
        fi
    done

    UV_COMMAND="$ALLPATH_HOME/bin/uv"
    if [ ! -x "$UV_COMMAND" ]; then
        command -v curl >/dev/null 2>&1 || fail "curl is required to install managed Python"
        log "Installing managed uv"
        mkdir -p "$ALLPATH_HOME/bin"
        curl -LsSf https://astral.sh/uv/install.sh \
            | env UV_INSTALL_DIR="$ALLPATH_HOME/bin" UV_NO_MODIFY_PATH=1 sh
    fi
    log "Installing managed Python 3.11"
    "$UV_COMMAND" python install 3.11
    PYTHON_COMMAND=$("$UV_COMMAND" python find 3.11)
}

find_python
success "Using $($PYTHON_COMMAND --version 2>&1)"

if [ "$LOCAL_INSTALL" = true ]; then
    if [ -z "$SOURCE_DIR" ]; then
        SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
        SOURCE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
    else
        SOURCE_DIR=$(cd "$SOURCE_DIR" && pwd)
    fi
    [ -f "$SOURCE_DIR/pyproject.toml" ] || fail "local source is not an Allpath checkout"
else
    SOURCE_DIR="$INSTALL_DIR/source"
    command -v git >/dev/null 2>&1 || fail "git is required for remote installation"
    if [ -d "$SOURCE_DIR/.git" ]; then
        log "Updating Allpath Agent"
        git -C "$SOURCE_DIR" pull --ff-only
    elif [ -e "$SOURCE_DIR" ]; then
        fail "$SOURCE_DIR exists but is not an Allpath git checkout"
    else
        log "Downloading Allpath Agent"
        git clone --depth 1 "$REPOSITORY_URL" "$SOURCE_DIR"
    fi
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "Creating isolated Python environment"
    "$PYTHON_COMMAND" -m venv "$VENV_DIR"
fi

if [ "$LOCAL_INSTALL" = true ]; then
    SITE_PACKAGES=$("$VENV_DIR/bin/python" -c \
        'import sysconfig; print(sysconfig.get_paths()["purelib"])')
    printf '%s\n' "$SOURCE_DIR/src" > "$SITE_PACKAGES/allpath_agent_local.pth"
    success "Linked local checkout $SOURCE_DIR"
else
    log "Installing Allpath Agent package"
    "$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -e "$SOURCE_DIR"
fi

COMMAND_PATH="$BIN_DIR/allpath-agent"
quote_shell() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\''/g")"
}
{
    printf '%s\n' '#!/bin/sh'
    printf 'export ALLPATH_HOME=%s\n' "$(quote_shell "$ALLPATH_HOME")"
    printf 'exec %s -m allpath_agent.cli.main "$@"\n' \
        "$(quote_shell "$VENV_DIR/bin/python")"
} > "$COMMAND_PATH"
chmod +x "$COMMAND_PATH"
success "Installed command $COMMAND_PATH"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        if [ "$UPDATE_PATH" = true ]; then
            case "${SHELL:-}" in
                */zsh) SHELL_RC="$HOME/.zshrc" ;;
                *) SHELL_RC="$HOME/.bashrc" ;;
            esac
            PATH_LINE="export PATH=\"$BIN_DIR:\$PATH\""
            if ! grep -F "$PATH_LINE" "$SHELL_RC" >/dev/null 2>&1; then
                printf '\n%s\n' "$PATH_LINE" >> "$SHELL_RC"
                success "Added Allpath Agent to PATH in $SHELL_RC"
            fi
        fi
        ;;
esac

printf '\nAllpath Agent is ready.\n'
printf 'Command: %s\n' "$COMMAND_PATH"

if [ "$SKIP_LAUNCH" = false ] && [ -r /dev/tty ]; then
    printf '\nStarting your first conversation...\n\n'
    "$COMMAND_PATH" < /dev/tty
else
    printf 'Start with: %s\n' "$COMMAND_PATH"
fi
