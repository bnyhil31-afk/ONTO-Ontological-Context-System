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

### Step 4 — Set up

ONTO's `setup.sh` is a bash script and will not run natively in PowerShell.
Run these equivalent steps instead:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If there is no `requirements.txt`, skip the pip install — ONTO has no
required dependencies beyond Python's standard library.

Create the data directory:

```powershell
mkdir data -ErrorAction SilentlyContinue
```

### Step 5 — Run

```powershell
python main.py
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
Run `python -m pip` instead of `pip`.

**Permission errors**  
Run PowerShell as Administrator.

**Something else**  
Open an issue at the repository. All questions are welcome.

---

*If something in this guide is wrong or unclear, please open an issue.*  
*Every correction makes this better for the next person.*
