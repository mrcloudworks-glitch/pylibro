#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if pkill -f "\.venv/bin/python app\.py"; then
    echo "PyLibro server stopped."
else
    echo "No PyLibro server was running."
fi
