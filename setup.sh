#!/bin/bash
# setup.sh
#
# One command to prepare ONTO on any device.
# Works on Raspberry Pi, Mac, Linux, Windows (via WSL).
# Requires only Python 3.7+ — nothing else.
#
# Run with:  bash setup.sh

set -e

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ONTO — Setup"
echo "════════════════════════════════════════════════════════════"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  [ERROR] Python 3 is required but not found."
    echo "  Install it from https://www.python.org or via:"
    echo "    sudo apt install python3   (Raspberry Pi / Linux)"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_VERSION" -lt 7 ]; then
    echo "  [ERROR] Python 3.7 or higher is required."
    exit 1
fi

echo "  [✓] Python 3 found."

# Create data directory
mkdir -p data
echo "  [✓] Data directory ready."

# Seal the principles — the most important step
echo ""
echo "  Sealing the principles..."
python3 -c "
import sys
sys.path.insert(0, '.')
from core.verify import seal_principles
record = seal_principles()
print()
print('  ┌─────────────────────────────────────────────────────────┐')
print('  │  PRINCIPLES SEALED                                      │')
print('  │                                                         │')
print(f'  │  Hash: {record[\"hash\"][:48]}  │')
print('  │                                                         │')
print('  │  Publish this hash publicly so anyone can verify it.   │')
print('  │  Once sealed, the principles cannot be changed.         │')
print('  └─────────────────────────────────────────────────────────┘')
"

echo ""
echo "  Setup complete."
echo ""
echo "  TO START THE SYSTEM:"
echo "    python3 main.py"
echo ""
echo "  TO VERIFY PRINCIPLES AT ANY TIME:"
echo "    python3 -m core.verify"
echo ""
echo "════════════════════════════════════════════════════════════"
echo ""
