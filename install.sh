#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements.txt"
BIN_DIR="${BIN_DIR:-/opt/homebrew/bin}"
BIN_PATH="${BIN_DIR}/mano-cua"
SKIP_PIP_UPGRADE="${SKIP_PIP_UPGRADE:-0}"
SKIP_DEPENDENCY_INSTALL="${SKIP_DEPENDENCY_INSTALL:-0}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but was not found in PATH." >&2
  exit 1
fi

if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
  echo "Error: requirements.txt not found at ${REQUIREMENTS_FILE}." >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Creating virtual environment at ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
else
  echo "Using existing virtual environment at ${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"

if [[ "${SKIP_PIP_UPGRADE}" != "1" ]]; then
  echo "Upgrading pip"
  python -m pip install --upgrade pip
else
  echo "Skipping pip upgrade"
fi

if [[ "${SKIP_DEPENDENCY_INSTALL}" != "1" ]]; then
  echo "Installing dependencies from requirements.txt"
  python -m pip install -r "${REQUIREMENTS_FILE}"
else
  echo "Skipping dependency installation"
fi

mkdir -p "${BIN_DIR}"

PROJECT_ROOT_ESCAPED="${PROJECT_ROOT//\'/\'\\\'\'}"

cat > "${BIN_PATH}" <<EOF
#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT='${PROJECT_ROOT_ESCAPED}'
VENV_PYTHON="\${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "\${VENV_PYTHON}" ]]; then
  echo "Error: virtual environment python not found at \${VENV_PYTHON}. Re-run install.sh from the project directory." >&2
  exit 1
fi

cd "\${PROJECT_ROOT}"
exec "\${VENV_PYTHON}" -m visual.vla "\$@"
EOF

chmod +x "${BIN_PATH}"

cat <<EOF

Installation complete.
Activate the virtual environment with:
  source "${VENV_DIR}/bin/activate"

Command installed at:
  ${BIN_PATH}

If you move this project directory later, re-run ./install.sh to refresh the launcher path.
EOF
