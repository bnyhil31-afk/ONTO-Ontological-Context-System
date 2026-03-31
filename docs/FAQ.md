# Frequently Asked Questions

**Project:** ONTO — Ontological Context System

---

## General

**What is ONTO?**

ONTO is a system that helps you make sense of information by building
context around it. You give it any input — a question, a statement, a
problem. It places that input in the context of everything it has seen
before, tells you what it sees and how certain it is, and then asks
you what to do next.

Everything it does is recorded permanently. Anyone can check it.

---

**Do I need technical knowledge to use it?**

No. If you can run a terminal and type, you can use ONTO.
The setup guides walk through every step for Windows, Mac, Linux,
and Raspberry Pi.

---

**Does it need the internet?**

No. ONTO runs entirely on your device. No data ever leaves your machine
unless you choose to move it. It works offline completely.

---

**Is it free?**

Yes. MIT license. Free to use, free to modify, free to distribute.
Forever.

---

**Who built this?**

Neo (@bnyhil31-afk). It is open source — anyone can contribute.

---

## Installation

**What do I need to install?**

Python 3.7 or higher. That is all. ONTO has no required external
dependencies beyond Python's standard library.

---

**It says Python is not found. What do I do?**

On Linux or Raspberry Pi:
```bash
sudo apt install python3
```

On Mac, download from https://www.python.org/downloads/

On Windows, see `docs/Setup_Windows.md`.

---

**setup.sh failed. What do I do?**

Try:
```bash
chmod +x setup.sh
bash setup.sh
```

If it still fails, open an issue with the error message. All questions
are welcome.

---

**Can I run it on a Raspberry Pi Zero?**

Yes, but the original Pi Zero W (single-core, 512MB) is slow.
The Pi Zero 2W (quad-core) works well. The Pi 3, 4, and 5 are all
fully supported. See `docs/Setup_RaspberryPi.md` for details.

---

## Principles and Trust

**What are the 13 principles?**

They are in `principles.txt` in the repository root. They are short
and written in plain language. Read them.

They cover: purpose, life first, freedom, truth, do no harm, openness,
memory, integrity, humility, growth, dignity, consent, and accountability.

---

**Can the principles be changed?**

No. They are sealed with a cryptographic hash. If anyone changes
`principles.txt`, the system detects it and refuses to run.

The hash is published at:
https://gist.github.com/bnyhil31-afk/6436e717a619b9a4d685f5b8709a53c8

Anyone can verify the principles have not changed:
```bash
sha256sum principles.txt
```

---

**How do I verify the principles are intact?**

```bash
python3 -m core.verify
```

Or manually:
```bash
sha256sum principles.txt
```

Compare the output to the hash in the README. If they match — the
principles are intact. If they do not — something is wrong.

---

**Can I trust a fork of ONTO?**

Only if the fork:
- Keeps the 13 principles intact and verified
- Does not remove the human sovereignty checkpoint
- Does not remove the audit trail
- Does not remove the bias monitor or consent mechanisms

A fork that removes these components is not ONTO, regardless of what
it calls itself. See `GOVERNANCE.md` for the full fork policy.

---

## Data and Privacy

**Where is my data stored?**

In `data/memory.db` on your device. Nowhere else.
It is a standard SQLite file. You can open it with any SQLite viewer.

---

**Can I delete my data?**

The audit trail is append-only — records cannot be deleted. This is by
design: the permanence of the record is what makes it trustworthy.

If you want to start fresh, you can delete the `data/memory.db` file
and the system will create a new one on next run. The history will be
gone.

For deployments that need a formal right-to-erasure process (GDPR),
see the compliance documentation in `docs/` and the legal section of
the CRE specification.

---

**Does the system send my data anywhere?**

No. ONTO has no network functionality in Stage 1. Nothing leaves
your device. No telemetry, no analytics, no cloud sync.

---

**What classification levels mean:**

| Level | Label | Examples |
|---|---|---|
| 0 | public | General questions, casual conversation |
| 1 | internal | Organizational information |
| 2 | personal | Your name, email, phone, address |
| 3 | sensitive | Health, financial, legal information |
| 4 | privileged | Attorney-client, clinical, clergy communications |
| 5 | critical | Existential risk if exposed — set explicitly |

Classification is auto-detected at intake and can only increase,
never decrease.

---

**What happens when it detects a crisis signal?**

The system stops immediately. It displays crisis resources before
anything else happens. The human operator at the checkpoint must
review the input before any other action is taken.

The crisis response is designed to connect people with support —
not to diagnose or assess. Detection is indicative, not comprehensive.
Human judgment at the checkpoint is essential.

Crisis resources displayed by default:
- 988 Suicide & Crisis Lifeline (US): call or text 988
- Crisis Text Line: text HOME to 741741
- International: findahelpline.com

This cannot be turned off. It can be localized — see `core/config.py`.

---

## The Audit Trail

**What is the audit trail?**

Everything ONTO does is recorded in `data/memory.db`. Every input,
every decision, every session start and end. The record is permanent
and tamper-evident.

---

**How do I read the audit trail?**

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from modules import memory
memory.initialize()
memory.print_readable(memory.read_all())
"
```

Or open `data/memory.db` with any SQLite viewer.
DB Browser for SQLite (https://sqlitebrowser.org/) is free and works well.

---

**What is the Merkle chain?**

Every record in the audit trail stores a SHA-256 hash of the record
before it. This creates a cryptographic chain — if any record is
deleted or modified, the chain breaks and the gap is detectable.

To verify the chain is intact:
```python
from modules import memory
memory.initialize()
result = memory.verify_chain()
print(result["intact"])   # True if unbroken
print(result["total"])    # Total records checked
```

---

**Can records be deleted or modified?**

No. The database enforces this with triggers. Any attempt to delete
or modify a record raises an error. This is tested in the test suite.

---

## Sessions

**What is a session?**

A session tracks your interaction with the system from login to logout.
Sessions expire after 30 minutes of inactivity (configurable) and
have a maximum lifetime of 8 hours (configurable).

---

**What happens when a session expires?**

The session is recorded as expired in the audit trail. You will need
to start a new session. Data is never lost — only the session token
is invalidated.

---

## Configuration

**How do I change settings?**

Copy `.env.example` to `.env` and edit the values. Or set environment
variables before running:

```bash
ONTO_RATE_LIMIT_PER_MINUTE=30 python3 main.py
```

See `core/config.py` or `docs/API.md` for a full list of settings.

---

**How do I set a passphrase?**

Generate the hash of your passphrase:
```bash
python3 -c "import hashlib; print(hashlib.sha256(b'your-passphrase-here').hexdigest())"
```

Set the environment variable:
```bash
ONTO_AUTH_PASSPHRASE_HASH=<hash> python3 main.py
```

Or add it to your `.env` file. Never put the passphrase itself in `.env`
— only the hash.

---

## Contributing

**How do I contribute?**

Read `CONTRIBUTING.md`. Read the 13 principles. Open an issue before
starting significant work.

All contributions are welcome. The principles bind contributors
before anyone else.

---

**Can I use ONTO in a commercial product?**

Yes. MIT license. No restrictions. We ask — but do not require — that
commercial users contribute improvements back to the project.

---

**I found a security vulnerability. What do I do?**

Do not open a public issue. Use GitHub's private security advisory
feature to contact the maintainer. See `GOVERNANCE.md` for the full
responsible disclosure process.

---

**I have a question that is not answered here.**

Open an issue. All questions are welcome. Every question is a
contribution to making the project more understandable.

---

*This document will be updated as the project evolves.*  
*If something here is wrong or unclear, open an issue.*
