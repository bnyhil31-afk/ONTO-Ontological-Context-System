# GOVERNANCE

**Project:** ONTO — Ontological Context System  
**Protocol:** CRE — Contextual Reasoning Engine  
**Version:** 1.0  
**Status:** Active  
**Repository:** https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System

---

## Why this document exists

Open source projects without explicit governance documentation face documented
risks: values drift under growth pressure, contributor burnout from unclear
authority, and capture by well-resourced actors who fork the project and
remove its values while keeping its name.

This document defines how ONTO and CRE are governed, how decisions are made,
and how the values embedded in the architecture are protected in perpetuity.

The governance model evolves with the project. This document will be updated.
Every change to this document is recorded in the audit trail of the project's
history.

---

## The values are non-negotiable

The 13 principles sealed in `principles.txt` are the invariant core of this
project. The crossover contract (`docs/CROSSOVER_CONTRACT_v1.0.md`) defines
the shared architectural foundation.

No governance decision — at any stage, by any party — may:
- Remove or weaken the human sovereignty checkpoint (GOVERN function)
- Remove or weaken the audit trail (REMEMBER function)
- Remove or weaken the bias monitor
- Remove or weaken the consent ledger
- Override the principle that human wellbeing is the highest priority

Changes to the values require the process described in the
**Values Changes** section below. There are no exceptions.

---

## Current stage: Founder-leader

ONTO is currently in the founder-leader stage. This is appropriate for
a project with a single primary contributor. Lines of authority are clear.

**What this means in practice:**
- The founder (Neo, @bnyhil31-afk) makes all final decisions
- All changes go through pull requests (branch protection is enabled)
- No breaking changes are made without documentation in CHANGELOG.md
- The founder is bound by the principles before anyone else

**When this changes:**  
When ONTO has two or more active external contributors making regular
contributions, the project transitions to the Self-Appointing Council
model described below. This transition is not optional — it is a
commitment made in this document.

---

## Transition: Self-Appointing Council

At the defined threshold, a Steering Committee is established:

**Composition:** 3–7 members, including:
- The founder (permanent seat until voluntarily relinquished)
- Active contributors elected by contribution history
- At minimum one seat reserved for a non-technical stakeholder
  (user, affected community member, domain expert)

**Decisions requiring committee vote:**
- Any change to the crossover contract
- Any new external dependency
- Any breaking change to the CRE protocol
- Any change to the regulatory profile framework
- Any change to this governance document

**Decision method:** Consensus preferred. If consensus cannot be reached,
simple majority vote among committee members. Votes are recorded publicly.

---

## Values changes

Changes to the 13 principles or the crossover contract values require:

1. **Written proposal** — submitted as a GitHub issue with full rationale
2. **90-day public comment period** — anyone may comment
3. **Supermajority** — 2/3 of committee members must approve
4. **Independent review** — for security-related changes, independent
   security review before ratification
5. **New seal** — principles hash re-computed and published to the
   public Gist if principles.txt is changed

A change that weakens any of the values enumerated above cannot pass
regardless of votes. The architecture enforces what governance cannot.

---

## Protocol fork policy

CRE is a public protocol. Anyone may fork it. However:

**A fork may NOT represent itself as CRE-compliant if it:**
- Removes the sovereignty checkpoint (GOVERN function)
- Removes or makes optional the audit trail (REMEMBER function)
- Removes the bias monitor
- Removes the consent ledger
- Removes the wellbeing gradient
- Removes the minimum necessary principle from NAVIGATE
- Claims human wellbeing is not the highest priority

The term "CRE-compliant" is reserved for implementations that satisfy
all values-bearing requirements in CRE-SPEC-001. A fork that removes
these components must not use the CRE name or claim compatibility.

This policy will be backed by trademark registration when legal
foundations are established (item 4.01 on the pre-launch checklist).

---

## Anti-concentration commitment

The CRE network must remain diverse. No single node or cluster of nodes
should accumulate disproportionate influence.

As a protocol-level commitment:
- The protocol monitors concentration signals
- Routing rules prefer underutilized nodes when multiple paths exist
- Concentration above defined thresholds triggers a governance event
- Any single entity controlling more than 33% of network routing
  triggers mandatory governance review

---

## Security vulnerability disclosure

If you discover a security vulnerability:

1. **Do not open a public issue**
2. Contact the project maintainer directly through GitHub's private
   security advisory feature
3. Provide a clear description of the vulnerability and its potential impact
4. Allow reasonable time for a fix before public disclosure
5. Your name will be credited in the fix unless you prefer otherwise

Responsible disclosure is honored. Public disclosure before a fix is
available harms users — please do not do it.

---

## Contribution guidelines

All contributions are welcome. Before contributing:

1. Read the 13 principles in `principles.txt`. They bind contributors
   before anyone else.
2. Read `CONTRIBUTING.md` for the technical process.
3. Read the crossover contract (`docs/CROSSOVER_CONTRACT_v1.0.md`) for
   architectural constraints.
4. Open an issue before starting significant work — coordination saves
   everyone time.

All contributions are made under the MIT license. By contributing, you
agree that your contribution may be used under the project's license.

---

## Cooperative evolution path

This project aspires to eventually operate as a cooperative — with
joint ownership and democratic governance among active contributors
and affected communities.

This is a direction, not a current state. The path:
- Stage 1: Founder-leader (now)
- Stage 2: Self-Appointing Council (with 2+ regular contributors)
- Stage 3: Elected Steering Committee (with significant adoption)
- Stage 4: Cooperative or foundation structure (with the community)

No timeline is imposed. The transition happens when the community
is ready, not on a calendar.

---

## Sustainability

This project is currently volunteer-maintained. If you find it valuable,
consider contributing your time, expertise, or code.

Commercial deployments that build on ONTO and CRE are welcome and
encouraged under the MIT license. We ask — but do not require — that
commercial users contribute improvements back to the project.

---

## Questions

Open an issue. All questions are welcome. Every question is a contribution
to making the project more understandable.

---

*This governance document is part of the permanent record of ONTO.*  
*It is updated as the project evolves.*  
*It is honest about what authority exists and where it lies.*  
*That is the only way trust is built.*
