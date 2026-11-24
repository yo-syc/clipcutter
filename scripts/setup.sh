
#!/usr/bin/env bash
# ClipCutter setup for macOS, Linux and Termux.
# Safe to run again.

set -euo pipefail
cd "$(dirname "$0")/.."

say() {
    printf "\n\033[1;32m==>\033[0m %s\n" "$1"
}

have() {
    command -v "$1" >/dev/null 2>&1
}

OS="$(uname -s)"

# Detect Termux
if [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *com.termux* ]]; then
    OS="Termux"
fi

if [ "$OS" = "Darwin" ]; then

    if ! have brew; then
        echo "Homebrew is required: https://brew.sh"
        exit 1
    fi

    say "Installing tools with Homebrew"

    for pkg in uv ffmpeg node fribidi; do
        brew list "$pkg" >/dev/null 2>&1 || brew install "$pkg"
    done

elif [ "$OS" = "Termux" ]; then

    say "Installing tools for Termux"

    pkg update -y
    pkg upgrade -y

    pkg install -y python uv ffmpeg nodejs git libfribidi

elif [ "$OS" = "Linux" ]; then

    if have apt-get; then
        say "Installing tools with apt"

        if have sudo; then
            SUDO="sudo"
        else
            SUDO=""
        fi

        $SUDO apt-get update -y

        $SUDO apt-get install -y \
            ffmpeg nodejs git \
            libfribidi0 \
            fonts-dejavu-core \
            fonts-noto-color-emoji \
            fonts-noto-core

    else
        echo "Please install ffmpeg, nodejs, git, fribidi and fonts using your package manager."
    fi

    if ! have uv; then
        say "Installing uv"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi

fi

# Verify required commands
say "Checking required tools"

for tool in uv ffmpeg node; do
    if ! have "$tool"; then
        echo "Missing required tool: $tool"
        exit 1
    fi
done

# Python dependencies
say "Installing Python packages"

if [ "$OS" = "Termux" ]; then
    uv sync --python "$(command -v python)"
else
    uv sync
fi

# Diagnostics
say "Checking everything"

uv run clipcutter doctor || true

printf "\nStart the app with:\n\n"
printf "    uv run clipcutter serve\n\n"
printf "Then open http://localhost:8787\n"
