#!/bin/bash
# Web UI Startup Script

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "======================================"
echo " Starting Sato Clone Web UI (Streamlit)"
echo "======================================"

# Install dependencies if needed
echo "Checking dependencies..."
python3 -m pip install -r "$DIR/infrastructure/requirements-ui.txt" || {
    echo "Failed to install dependencies."
    exit 1
}

# Run the UI
echo "Launching Streamlit..."
python3 -m streamlit run "$DIR/infrastructure/web_ui.py" --server.address=0.0.0.0
