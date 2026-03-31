# Privacy Policy

**Project:** ONTO — Ontological Context System  
**Version:** Draft 1.0  
**Status:** Pending legal review (checklist item 4.01)  
**Last updated:** 2026

> **Notice:** This is a working draft. It has not been reviewed by legal
> counsel. It must not be used as a final privacy policy for any deployment
> handling real user data without professional legal review.
> See checklist item 4.01.

---

## Plain language summary

- All data stays on your device. Nothing is sent anywhere.
- Everything you input is recorded permanently in a local database.
- You can read everything the system has ever recorded about you.
- You cannot delete records from the audit trail — this is by design.
- The system detects and responds to crisis signals for your safety.
- No advertising. No tracking. No third parties.

---

## 1. Who this policy covers

This policy applies to anyone who installs and uses ONTO on their own
device (a personal computer, laptop, Raspberry Pi, or similar hardware).

It also applies to operators — people who deploy ONTO for others to use.
Operators have additional responsibilities described in Section 8.

---

## 2. What data ONTO collects

ONTO records everything that passes through the system. This is not a
bug — it is the core design. The audit trail is what makes the system
trustworthy.

**What is recorded:**
- Every input you provide, after sanitization
- The system's assessment of each input (complexity, classification,
  safety signals if any)
- The system's response (the surface output)
- Every decision made at the checkpoint
- Session start and end times
- System boot and shutdown events
- Any access to sensitive records (classification level 2 and above)

**What is NOT recorded:**
- Your passphrase (only a hash is stored — the passphrase itself is
  never written anywhere)
- Session tokens (stored in memory only, never written to disk)
- Any data from outside the system — ONTO does not read your files,
  contacts, browser history, or any other application data

---

## 3. How ONTO classifies your data

Every input is automatically classified at the point of entry:

| Level | Label | Examples |
|---|---|---|
| 0 | Public | General questions, casual conversation |
| 2 | Personal | Name, email, phone, address, age |
| 3 | Sensitive | Health, financial, legal, biometric information |
| 4 | Privileged | Attorney-client, clinical, or clergy communications |
| 5 | Critical | Set explicitly by the operator only |

Classification is automatic and best-effort. It is heuristic — it may
not catch everything. If you share sensitive information, assume it will
be classified at the appropriate level and recorded accordingly.

Classification can only increase — it never decreases once assigned.

---

## 4. Where your data is stored

All data is stored in `data/memory.db` on the device running ONTO.
This is a standard SQLite database file.

**No data is transmitted** to any external server, cloud service, or
third party. ONTO has no network functionality in Stage 1. There are
no analytics, no telemetry, and no remote logging of any kind.

---

## 5. How long your data is kept

The audit trail is permanent by design. Records are never automatically
deleted. This permanence is what makes the audit trail trustworthy —
a record that can be deleted can be manipulated.

**Your options:**
- Read the full audit trail at any time (see the README)
- Delete the entire database file (`data/memory.db`) to start fresh —
  this erases all history
- Export the database to another location before deleting

Individual record deletion is not supported. This is an intentional
architectural decision, not a technical limitation.

**GDPR right to erasure:** If you are subject to GDPR and need a
compliant data erasure process, see `docs/PRIVACY_GDPR.md` for the
current GDPR architecture. Legal counsel should review this before
any EU deployment. See checklist item 5.01.

---

## 6. Safety and crisis detection

ONTO monitors all inputs for signals that may indicate someone is in
distress. This cannot be turned off.

When a crisis signal is detected:
- The system pauses all other processing
- Crisis resources are displayed immediately
- The human operator at the checkpoint reviews the input
- No automated response is sent — a human must decide what to do

This monitoring is pattern-based. It is not comprehensive and may
produce false positives or miss indirect expressions of distress.
It is a safety layer, not a diagnostic tool.

The resources displayed by default are:
- 988 Suicide & Crisis Lifeline (US): call or text 988
- Crisis Text Line: text HOME to 741741
- International resources: findahelpline.com

These can be changed by the operator for localization. They cannot
be removed entirely.

---

## 7. Your rights

You have the right to:
- **Read** everything recorded about you (the full audit trail)
- **Verify** that the system's principles have not been changed
- **Delete** the entire database if you choose to start fresh
- **Understand** how the system made every decision (the audit trail
  records the reasoning, not just the outcome)
- **Stop** using the system at any time

You do not have the right to:
- Delete individual records from the audit trail (by design)
- Prevent the system from recording your inputs (recording is required
  for the system to function)

---

## 8. Operator responsibilities

If you deploy ONTO for others to use, you are the operator and you
take on additional responsibilities:

- You must provide users with a privacy policy before they use the system
- You must not use ONTO to collect data beyond what users consent to
- You must secure the device and database appropriately for your
  deployment context
- You must comply with applicable data protection laws in your jurisdiction
- You must not remove or weaken the crisis detection and response layer
- You must ensure users can access and delete their data as described
  in this policy

Operators deploying in the EU should review GDPR requirements carefully.
Operators in California should review CCPA requirements. Legal counsel
is strongly recommended before any significant deployment.

---

## 9. Security

ONTO is designed with security in mind:

- The audit trail is cryptographically chained (Merkle chain) —
  tampering is detectable
- Authentication uses Argon2id password hashing (where enabled)
- Session tokens are 256-bit random values with idle and absolute timeouts
- The database can be encrypted (see `core/config.py`)
- No secrets are ever stored in the codebase

No system is perfectly secure. Physical security of the device is
your responsibility. See `docs/Setup_RaspberryPi.md` for Pi-specific
security guidance.

---

## 10. Changes to this policy

This policy will be updated as the project evolves. Changes will be
documented in `CHANGELOG.md`. The version and date at the top of this
document reflect the current state.

---

## 11. Contact

Questions about this policy: open an issue at the repository.

For security vulnerabilities: use GitHub's private security advisory
feature. Do not open a public issue for security concerns.

---

## 12. Legal status of this document

This privacy policy is a draft produced for an open-source project
with no legal entity, no employed staff, and no revenue. It reflects
the privacy architecture of the system honestly.

It has not been reviewed by legal counsel. It may not satisfy the
legal requirements of your jurisdiction. Before deploying ONTO in
any context where users' personal data is processed, consult a
qualified data protection lawyer.

---

*This document is part of the permanent record of ONTO.*  
*It is updated as the project and its legal understanding evolves.*  
*It is honest about what it does not yet know.*
