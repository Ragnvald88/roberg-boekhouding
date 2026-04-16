#!/bin/bash
# Resolve to local CloudStorage path — SQLite cannot use WAL on SMB/network mounts
PROJECT_DIR="$HOME/Library/CloudStorage/SynologyDrive-Main/06_Development/roberg-boekhouding"
cd "$PROJECT_DIR"
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
