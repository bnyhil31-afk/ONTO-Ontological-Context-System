# Setting up ONTO on Windows

You have two options. Both work. Pick the one that suits you.

**Option A — WSL (recommended)**  
Windows Subsystem for Linux gives you a full Linux environment inside Windows.
This is the easiest path and is what the main README assumes.

**Option B — Native Windows**  
Run ONTO directly in PowerShell with no Linux layer.
A few extra steps, but no WSL required.

---

## Option A — WSL (recommended)

### Step 1 — Install WSL

Open PowerShell as Administrator and run:

```powershell
wsl --install
```

Restart your computer when prompted.

When it restarts, a Ubuntu terminal will open and ask you to create
a username and password. Choose anything — this is just for WSL.

### Step 2 — Install Python and Git inside WSL

In the Ubuntu terminal:

```bash
sudo apt update
sudo apt install python3 git -y
```

### Step 3 — Clone and set up ONTO

```bash
git clone https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System.git
cd ONTO-Ontological-Context-System
bash setup.sh
```

### Step 4 — Run

```bash
python3 main.py
```

That is it. Everything else works exactly as described in the main README.

---

## Option B — Native Windows (PowerShell)

### Step 1 — Install Python

Go to https://www.python.org/downloads/ and download the latest Python 3.x installer.

Run the installer. **Important:** check the box that says
**"Add Python to PATH"** before clicking Install.

Verify the installation in PowerShell:

```powershell
python --version
```

You should see something like `Python 3.12.x`.

### Step 2 — Install Git

Go to https://git-scm.com/download/win and download Git for Windows.

Run the installer with default settings.

Verify:

```powershell
git --version
```

### Step 3 — Clone ONTO

In PowerShell:

```powershell
git clone https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System.git
cd ONTO-Ontological-Context-System
```

### Step 4 — Run immediately (no install required)

ONTO's core runs on Python's standard library. No packages are required
to start the system. You can run it right now:

```powershell
python main.py
```

You should see the boot sequence and a `You:` prompt. Type anything to begin.

### Step 5 — Install optional packages (recommended)

For full functionality (encryption, authentication, graph analytics,
MCP interface), install the optional packages:

```powershell
pip install -r requirements.txt
```

What each group adds:

| Package | Adds |
|---------|------|
| `cryptography` + `argon2-cffi` | Database encryption and passphrase auth |
| `fastapi` + `uvicorn` | HTTP API server (`api/main.py`) |
| `fast-pagerank` + `scipy` | Personalized PageRank on large graphs |
| `fastmcp` | MCP interface for AI systems (Python 3.10+ only) |
| `zeroconf` + `grpcio` | Federation between ONTO nodes |

None of these are required for the core loop. Install what you need.

### Step 6 — Create the data directory (if it wasn't created automatically)

```powershell
mkdir data -ErrorAction SilentlyContinue
```

---

## Verifying the principles on Windows

**WSL or Git Bash:**
```bash
sha256sum principles.txt
```

**PowerShell:**
```powershell
Get-FileHash principles.txt -Algorithm SHA256 | Select-Object Hash
```

Compare the output to the hash in the README. If it matches — the principles
are intact.

---

## Reading the memory on Windows

**WSL or Git Bash:**
```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from modules import memory
memory.initialize()
memory.print_readable(memory.read_all())
"
```

**PowerShell:**
```powershell
python -c "import sys; sys.path.insert(0,'.'); from modules import memory; memory.initialize(); memory.print_readable(memory.read_all())"
```

You can also open `data/memory.db` directly with any SQLite viewer.
DB Browser for SQLite (https://sqlitebrowser.org/) is free and works well.

---

## Troubleshooting

**`python` not found**  
Try `python3` instead. If neither works, Python was not added to PATH.
Reinstall Python and check the "Add to PATH" box.

**`pip` not found**  
Run `python -m pip install -r requirements.txt` instead.

**Characters display as boxes (▯) instead of checkmarks**  
PowerShell on older Windows versions may not render unicode correctly.
This is cosmetic only — the system is working. To fix it, switch to
Windows Terminal (available free from the Microsoft Store), which
supports unicode by default.

**Permission errors**  
Run PowerShell as Administrator.

**Something else**  
Open an issue at the repository. All questions are welcome.

---

*If something in this guide is wrong or unclear, please open an issue.*  
*Every correction makes this better for the next person.*
