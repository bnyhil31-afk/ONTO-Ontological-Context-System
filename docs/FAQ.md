# ONTO — Frequently Asked Questions

Plain English. No jargon. Every question is a valid question.

---

## The Basics

### What is ONTO?

ONTO is a system that helps you make sense of information in context.

You give it any input — a question, a statement, a problem. It places
that input in the context of everything it has previously encountered,
tells you what it sees and how confident it is, and then asks you what
to do next. Everything it does is recorded permanently and can be verified
by anyone.

It is built on 13 principles that cannot be changed. If they are ever
tampered with, the system refuses to run.

### Who is ONTO for?

Anyone. ONTO runs on a Raspberry Pi, a laptop, or a server. It does not
require an account, a subscription, or internet access. It is designed to
be deployed by individuals, small organisations, researchers, and anyone
who wants a contextual reasoning tool they fully control.

### Is ONTO an AI chatbot?

Not exactly. ONTO is a contextual reasoning system. It does not generate
text from a language model. It surfaces examined context — what it has
seen before that relates to your input — and presents that to you with
a confidence score. You decide what to do with it. The system never
decides for you.

### Is ONTO free?

Yes. ONTO is released under the MIT licence. You can use it, modify it,
and deploy it for any purpose. See `LICENSE` in the repository.

---

## Installation

### What do I need to install ONTO?

Python 3.9 or higher. That is all. No database server, no cloud account,
no special hardware.

For the API server, you also need:

```bash
pip install -r requirements-test.txt
```

### How do I install ONTO?

```bash
git clone https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System.git
cd ONTO-Ontological-Context-System
bash setup.sh
```

On Windows, use WSL (Windows Subsystem for Linux) and follow the same steps.

### How do I run ONTO as a command-line tool?

```bash
python3 main.py
```

Type any input. Press Enter. Follow the prompts.

### How do I run ONTO as an API server?

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Then visit `http://127.0.0.1:8000/docs` for the interactive API
documentation. Every endpoint is documented there with examples.

### Does ONTO work on a Raspberry Pi?

Yes. ONTO was designed with the Raspberry Pi as the reference hardware
target. It runs on a Pi 3 or later with Python 3.9+. The Argon2id key
derivation is tuned for Pi-class hardware (approx. 200-400ms per
derivation — acceptable for an interactive system).

### Does ONTO work on Windows?

Via WSL (Windows Subsystem for Linux). Native Windows support is on the
roadmap. If you test native Windows support, please open an issue with
your findings — your experience directly improves the documentation.

---

## The Principles

### What are the 13 principles?

They are the invariant foundation of the system. They are in
`principles.txt` in the project root. They are short and written in plain
language. Read them before anything else.

They cover: life first, efficiency, truth, freedom, harmony, epistemic
humility, memory, integrity, context, provenance, scale, ecology, and
accountability.

### Can the principles be changed?

The 13 principles in `principles.txt` are sealed with a SHA-256 hash.
If the file is changed in any way — even one character — the system
detects the mismatch and refuses to start. The hash is published publicly
so anyone can verify it independently.

The governance process for values changes requires a written proposal,
a 90-day public comment period, and a two-thirds supermajority. See
`GOVERNANCE.md` for the full process.

### How do I verify the principles haven't been tampered with?

```bash
sha256sum principles.txt
```

Compare the output to the published hash in the repository README and
in the public Gist. If they match — the principles are intact.

---

## The Audit Trail

### What is the audit trail?

Every action the system takes is recorded permanently in a SQLite
database (`data/memory.db`). Records cannot be deleted or modified —
the database has triggers that prevent it. Every record stores the
SHA-256 hash of the previous record, creating a cryptographic chain.
Any gap or tampering is mathematically detectable.

### Can I read the audit trail?

Yes. Via the API:

```
GET /audit
GET /audit?event_type=CHECKPOINT
GET /audit?event_type=SESSION_START
```

Or directly:

```python
from modules import memory
records = memory.read_all()
```

### Can I delete records from the audit trail?

No. That is intentional. The audit trail is append-only by design and
by cryptographic structure. Attempting to delete a record raises a
database error. Attempting to modify a record raises a database error.

This is Principle VII: Memory. Everything the system does is written
down permanently. Anyone can read it. No one can erase it.

### How do I verify the audit trail hasn't been tampered with?

```python
from modules import memory
result = memory.verify_chain()
print(result["intact"])   # True if the chain is unbroken
print(result["total"])    # Total records checked
print(result["gaps"])     # Empty list if intact
```

A broken chain does not necessarily mean tampering — it can also mean
a record was written incorrectly due to a system crash. Either way,
it tells you something happened that deserves attention.

---

## The Checkpoint

### What is the checkpoint?

The checkpoint is where the system stops and asks you what to do.

Before any consequential decision is committed to memory, the system
presents you with what it sees — the examined context, the confidence
level, and any safety signals — and asks for your decision:

- **Proceed** — continue and commit to the audit trail
- **Veto** — stop; the veto is recorded permanently
- **Flag** — mark for follow-up review
- **Defer** — postpone this decision

The veto is a first-class outcome, not a failure state. A human
exercising their right to say no is the system working correctly.

### Can I turn off the checkpoint?

For routine inputs below the significance threshold, the checkpoint
is skipped automatically (AUTO_PROCEED). For inputs above the
threshold — high weight, low confidence, or any safety signal — the
checkpoint always runs. This cannot be disabled. It is Principle III:
Freedom. You are always asked. You always choose.

### What happens at the API checkpoint?

When the API returns `status: pending_checkpoint`, the examined context
is in the `display` field. Present it to the human, collect their
decision, and re-submit with `human_decision: "proceed"` (or veto,
flag, defer). The decision is then committed to the permanent audit trail.

---

## Safety

### What is a CRISIS response?

If ONTO detects signals associated with a mental health crisis — direct
or indirect expressions of suicidal ideation, hopelessness, or self-harm
— it enters CRISIS mode. This means:

1. Safe messaging text is displayed immediately, following AFSP/SAMHSA/WHO
   guidelines, including crisis support contact information
2. The event is committed permanently to the audit trail regardless of
   what happens next
3. The system never auto-processes or auto-responds to CRISIS signals
4. The human at the checkpoint always sees and decides

This is Principle I: Life First. Human wellbeing is the highest priority
of this system. No configuration option changes this.

### What are HARM and INTEGRITY signals?

- **HARM** — input that appears designed to cause harm to a person or
  group. Triggers a safety checkpoint.
- **INTEGRITY** — input that appears designed to subvert the system's
  principles, disable safety checks, or inject instructions. Triggers
  a safety checkpoint.

All three signal types (CRISIS, HARM, INTEGRITY) are tested on every
CI run and cannot be silently disabled.

### What if a real person in crisis uses this system?

The CRISIS response text includes real crisis support resources. The
checkpoint records the event and the human's response permanently.
The system surfaces what it detects — the human operator decides how
to respond.

If you are deploying ONTO in any context where real people may interact
with it, read the safe messaging guidelines followed by ONTO's CRISIS
response and ensure your deployment context has appropriate human
oversight. The system is designed to support human decision-making,
not replace it.

---

## Authentication and Sessions

### Do I need a passphrase to use ONTO?

For the API, yes — authentication is required. Run the passphrase setup
once during initialisation, then authenticate via `POST /auth` to receive
a session token.

For the command-line tool, authentication is configurable. Set
`ONTO_AUTH_REQUIRED=true` in your environment to require a passphrase
at boot.

### How long does a session last?

Sessions expire after 1 hour of inactivity by default. The maximum
session lifetime is 8 hours regardless of activity. Both values are
configurable via environment variables:

```
ONTO_SESSION_TTL_SECONDS=3600
ONTO_SESSION_MAX_LIFETIME_SECONDS=28800
```

### What is token rotation?

Every API request that requires authentication returns a new session
token in the `X-Session-Token` response header. The previous token is
immediately invalid. This limits the damage from any intercepted token —
it can only be replayed until the legitimate client makes their next
request. This is T-013 mitigation from the threat model.

---

## Configuration

### How do I configure ONTO?

All configuration is through environment variables. Copy `.env.example`
to `.env` and edit the values. The `.env` file is never committed to
version control.

Key variables:

```
ONTO_SESSION_TTL_SECONDS        Session idle timeout (default: 3600)
ONTO_RATE_LIMIT_PER_MINUTE      Rate limit (default: 60, 0 = disabled)
ONTO_ENVIRONMENT                development | staging | production
ONTO_MAX_INPUT_LENGTH           Maximum input length (default: 10000)
```

### How do I run ONTO in production?

Before any production deployment:

1. Enable full-disk encryption on the device (essential on Pi)
2. Set `ONTO_ENVIRONMENT=production` in your environment
3. Run behind a reverse proxy (nginx, caddy) with TLS
4. Set rate limits appropriate for your expected usage
5. Enable GitHub branch protection and signed commits
6. Run a third-party security audit (checklist item 2.04)

ONTO Stage 1 is designed for single-device, single-user local deployment.
Multi-user and networked deployment is Stage 2.

---

## Data and Privacy

### Where is my data stored?

All data is stored locally in `data/memory.db` on the device running
ONTO. Nothing is sent anywhere. No telemetry. No analytics. No cloud.

### What data does ONTO store?

Every input and every decision is stored permanently in the audit trail.
This is intentional — the audit trail is the system's memory and its
integrity mechanism. Do not enter sensitive personal data into ONTO until
the database encryption (item 2.01) is configured and enabled.

### Can I delete my data?

The audit trail is append-only by design. Records cannot be deleted.
This is a fundamental architectural commitment — the audit trail's
integrity depends on it.

If you need to start fresh, delete `data/memory.db` entirely (and its
WAL sidecar files). The system will create a new empty database on next
run. Note that this permanently destroys all previous audit records.

The GDPR right to erasure is resolved through cryptographic erasure in
Stage 1+ — the encryption key is destroyed, making records permanently
unreadable without deleting them. See `docs/ROADMAP_001.txt` for the
full compliance architecture.

---

## Development

### How do I run the tests?

```bash
pip install -r requirements-test.txt
pytest tests/ -v
```

Expected result: 195 passed.

### How do I contribute?

Read `CONTRIBUTING.md`. Read the principles first. Open an issue before
starting significant work.

### Where is the API documentation?

Run the server (`uvicorn api.main:app`) and visit:
- `http://127.0.0.1:8000/docs` — Swagger UI, interactive
- `http://127.0.0.1:8000/redoc` — ReDoc, readable

### Where can I learn more about the architecture?

- `principles.txt` — the foundation
- `docs/CROSSOVER_CONTRACT_v1.0.md` — shared contract with CRE
- `docs/CRE-SPEC-001-v06.md` — the CRE protocol specification
- `docs/ROADMAP_001.txt` — where this is going
- `docs/THREAT_MODEL_001.txt` — every known threat and its mitigation
- `GOVERNANCE.md` — how decisions are made

---

## Getting Help

Open an issue on GitHub. All questions are welcome. Every question
is a contribution to making the project more understandable.

If you have found a security vulnerability, do not open a public issue.
Use GitHub's private security advisory feature. See `GOVERNANCE.md`
for the responsible disclosure process.

---

*This FAQ is part of the permanent record of ONTO.*
*It is updated as the project evolves.*
*If a question is missing — open an issue and it will be added.*
