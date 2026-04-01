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
4f7b303395e4b38fd3bc290c529c3b0ec7f717bf9c89764e215c4f7a9596527d
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
See `docs/Setup_Windows.md` for full instructions (WSL or native Python).

**On Raspberry Pi (detailed):**
See `docs/Setup_RaspberryPi.md` for hardware-specific guidance and
physical security recommendations.

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
│   ├── principles.hash     The sealed fingerprint of the principles.
│   ├── config.py           All configuration. Loads from environment.
│   ├── auth.py             Passphrase authentication. Swappable.
│   ├── encryption.py       AES-256-GCM database encryption.
│   ├── ratelimit.py        Sliding window rate limiter.
│   └── session.py          Session management and token lifecycle.
│
├── modules/
│   ├── intake.py           Receives any input. Classifies. Checks safety.
│   ├── contextualize.py    Builds understanding. Finds connections.
│   ├── surface.py          Presents findings in plain language.
│   ├── checkpoint.py       Asks the human. Records the decision.
│   └── memory.py           Permanent, append-only, Merkle-chained audit trail.
│
├── tests/
│   ├── test_onto.py        Core system tests (108 tests)
│   ├── test_conformance.py Crossover contract conformance (16 tests)
│   ├── test_security.py    Security hardening tests (28 tests)
│   ├── test_memory_chain.py Merkle chain and audit integrity (19 tests)
│   ├── test_classification_and_config.py Classification and safe messaging (16 tests)
│   └── test_session.py     Session management tests (17 tests)
│
├── docs/
│   ├── API.md              Full API reference for all modules
│   ├── FAQ.md              Frequently asked questions
│   ├── Setup_Windows.md    Windows installation guide
│   ├── Setup_RaspberryPi.md Raspberry Pi installation and security guide
│   ├── PRIVACY_POLICY.md   Privacy policy
│   ├── TERMS_OF_USE.md     Terms of use
│   ├── PRIVACY_GDPR.md     GDPR architecture and right to erasure
│   ├── PRIVACY_CCPA.md     CCPA compliance review
│   ├── DATA_RETENTION.md   Data retention policy
│   ├── CONSENT_MANAGEMENT.md Consent management framework
│   ├── CROSSOVER_CONTRACT_v1.0.md Shared contract with CRE protocol
│   ├── CRE-SPEC-001-v06.md CRE protocol specification v0.6
│   ├── ROADMAP_001.txt     POC to enterprise deployment roadmap
│   ├── THREAT_MODEL_001.txt 28 threats across 9 categories
│   └── REVIEW_001.txt      Architecture review across 12 domains
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

## How to verify the audit trail is intact

The audit trail is cryptographically chained. Every record links to
the one before it. Tampering is detectable.

```python
from modules import memory
memory.initialize()
result = memory.verify_chain()
print(result["intact"])  # True if unbroken
```

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

## Tests

188 tests. All passing. Across Python 3.8–3.12.

```bash
pytest tests/ -v
```

See `tests/README.md` for the full guide.

---

## Documentation

| Document | What it covers |
|---|---|
| `docs/API.md` | Full API reference |
| `docs/FAQ.md` | Common questions answered |
| `docs/Setup_Windows.md` | Windows installation |
| `docs/Setup_RaspberryPi.md` | Raspberry Pi installation |
| `GOVERNANCE.md` | How the project is governed |
| `CONTRIBUTING.md` | How to contribute |

---

## Contributing

This project is open source. Everyone is welcome.

The principles apply to contributors too.
Read them before you submit anything.

---

## License

LGPL-2.1 — Open core. Free to use. Modifications to the library must remain open.

---

## Repository

https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System

## Verified Principles Hash

Public record: https://gist.github.com/bnyhil31-afk/6436e717a619b9a4d685f5b8709a53c8

---

*Built on the belief that technology should serve people —
not the other way around.*
