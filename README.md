# ONTO
## An Ontological Context System
### Version 1.0 — MVP

Built by Neo

---

## What is this?

ONTO is a system that helps you make sense of information.

You give it any input — a question, a statement, a problem.
It understands it in context. It tells you what it sees and how sure it is.
Then it asks you what to do next.

Everything it does is recorded permanently. Anyone can check it.

---

## Who is this for?

Anyone. Everyone.

You do not need technical knowledge to use it.
You do not need an account, a subscription, or internet access.
It runs on a Raspberry Pi. It runs on your laptop. It runs anywhere Python runs.

---

## The Principles

This system is built on 13 principles. They are in `principles.txt`.

They cannot be changed. If they are tampered with, the system refuses to run.

Read them. They are short and written in plain language.

### Verified Principles Hash

```
b1d3054f646c5f3abaffd3a275683949aef426d135cf823e7b3665fb06a03ba5
```

Anyone can verify the principles have not been changed:

```bash
sha256sum principles.txt
```

If the output matches the hash above — the principles are intact.

---

## What it does — step by step

```
You type something
       ↓
INTAKE — the system receives and classifies it
       ↓
CONTEXTUALIZE — the system places it in the field of everything it knows
       ↓
SURFACE — the system tells you what it sees, honestly
       ↓
CHECKPOINT — the system asks you what to do next
       ↓
MEMORY — your decision is recorded permanently
       ↓
Repeat
```

---

## How to install

You need Python 3.7 or higher. That is all.

**On Raspberry Pi or Linux:**
```bash
sudo apt update
sudo apt install python3
git clone https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System.git
cd ONTO-Ontological-Context-System
bash setup.sh
```

**On Mac:**
```bash
git clone https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System.git
cd ONTO-Ontological-Context-System
bash setup.sh
```

**On Windows:**
Use WSL (Windows Subsystem for Linux) and follow the Linux instructions.

---

## How to run

```bash
python3 main.py
```

Type anything. Press Enter. Follow the prompts.

---

## What the files do

```
ONTO-Ontological-Context-System/
│
├── principles.txt          The foundation. Read this first.
│
├── main.py                 Start here. Runs the system.
├── setup.sh                Run once to prepare the system.
│
├── core/
│   ├── verify.py           Guards the principles. Runs on every boot.
│   └── principles.hash     The sealed fingerprint of the principles.
│
├── modules/
│   ├── intake.py           Receives any input. Checks for safety.
│   ├── contextualize.py    Builds understanding. Finds connections.
│   ├── surface.py          Presents findings in plain language.
│   ├── checkpoint.py       Asks the human. Records the decision.
│   └── memory.py           Permanent, append-only audit trail.
│
└── data/
    └── memory.db           The permanent record. Never deleted.
```

---

## How to verify the principles

Anyone, anywhere, can verify that the principles have not been changed:

```bash
python3 -m core.verify
```

Or compute the hash yourself:
```bash
sha256sum principles.txt
```

Compare the result to the published hash above.

If they match — the principles are intact.
If they don't — something is wrong.

---

## How to read the memory

Everything the system has ever done is in `data/memory.db`.

To read it:
```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from modules import memory
memory.initialize()
memory.print_readable(memory.read_all())
"
```

Or open it with any SQLite viewer. It is a standard, open format.

---

## The three governing forces

Every input is weighed by:

- **Distance** — how new or familiar is this?
- **Complexity** — how simple or involved is this?
- **Size** — how much is here to process?

These three things together determine how much attention the system
gives to any input — and how carefully it proceeds before acting.

---

## Safety

If the system detects that someone may be in danger, it stops
everything and provides crisis resources before anything else.

This cannot be turned off.

---

## Contributing

This project is open source. Everyone is welcome.

The principles apply to contributors too.
Read them before you submit anything.

---

## License

MIT — Open. Free. For everyone. Always.

---

## Repository

https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System

## Verified Principles Hash

Public record: https://gist.github.com/bnyhil31-afk/6436e717a619b9a4d685f5b8709a53c8

---

*Built on the belief that technology should serve people —
not the other way around.*
