# CCPA Compliance Review

**File:** `docs/PRIVACY_CCPA.md`  
**Project:** ONTO — Ontological Context System  
**Version:** Draft 1.0  
**Status:** Pending legal review (checklist item 4.01)  
**Last updated:** 2026

> **Notice:** This is a working draft. It has not been reviewed by legal
> counsel. CCPA compliance for any specific deployment must be assessed
> by a qualified California data protection lawyer. This document
> describes the architectural design — not a legal guarantee of compliance.

---

## Does CCPA apply to your ONTO deployment?

The California Consumer Privacy Act (CCPA), as amended by the California
Privacy Rights Act (CPRA), applies to for-profit businesses that:

- Do business in California, **and**
- Meet one or more of these thresholds:
  - Annual gross revenue exceeds $25 million
  - Buy, sell, or share personal information of 100,000+ consumers annually
  - Derive 50%+ of annual revenue from selling or sharing personal information

**For most ONTO Stage 1 deployments** (personal use, small research, single-device),
CCPA does not apply — the thresholds are not met and there is no commercial
data processing.

**For operators building commercial services on ONTO** — CCPA likely applies
if you serve California residents. Consult legal counsel.

---

## California consumer rights under CCPA/CPRA

| Right | Description | ONTO's current position |
|---|---|---|
| Right to know | What personal information is collected and how it is used | ✅ Full audit trail is readable at any time |
| Right to delete | Request deletion of personal information | ✅ Stage 1: delete database. Stage 2+: cryptographic erasure per subject |
| Right to correct | Request correction of inaccurate personal information | ⚠️ Records are immutable — correction records can be appended |
| Right to opt-out | Opt out of sale or sharing of personal information | ✅ ONTO does not sell or share data in Stage 1 |
| Right to limit use | Limit use of sensitive personal information | ⚠️ Requires consent ledger — Stage 2 feature |
| Right to non-discrimination | Not be discriminated against for exercising rights | ✅ By design — no differential treatment |
| Right to data portability | Receive personal data in a portable format | ✅ SQLite is a portable, open format |

---

## Personal information under CCPA

CCPA defines "personal information" broadly. ONTO's classification
system maps to CCPA categories:

| CCPA category | ONTO classification | Examples |
|---|---|---|
| Identifiers | Level 2 (personal) | Name, email, phone, address |
| Personal records | Level 2–3 | Financial, medical, employment records |
| Protected characteristics | Level 3 (sensitive) | Age, race, religion, health conditions |
| Commercial information | Level 2–3 | Transaction records, purchasing history |
| Biometric data | Level 3 (sensitive) | Fingerprints, facial recognition |
| Internet/network activity | Level 0–2 | Usage patterns |
| Geolocation | Level 2–3 | Precise location data |
| Sensitive personal information | Level 3–4 | SSN, financial account numbers, health data |

---

## What ONTO does NOT do

ONTO does not:
- Sell personal information to third parties
- Share personal information with third parties for cross-context
  behavioral advertising
- Use personal information for purposes beyond what the user
  directly provides it for
- Send data to any external server (Stage 1)
- Profile users for advertising or commercial targeting

These are architectural properties, not just policies. In Stage 1,
there is no network connection for data to leave through.

---

## Sensitive personal information (CPRA)

CPRA added special protections for "sensitive personal information,"
including Social Security numbers, financial account details, precise
geolocation, racial/ethnic origin, religious beliefs, health and
sexual orientation data, and biometric data.

ONTO classifies these at level 3 (sensitive) or above at intake.
Classification level 3+ data:
- Is logged when read (READ_ACCESS events in the audit trail)
- Cannot be classified down — only up
- Will be subject to cryptographic erasure in Stage 2+

---

## For operators: CCPA compliance obligations

If CCPA applies to your deployment:

1. **Privacy notice** — provide a clear privacy notice to California
   residents at or before the point of collection. Update
   `docs/PRIVACY_POLICY.md` with deployment-specific information.

2. **Privacy policy** — publish a comprehensive privacy policy that
   includes all CCPA-required disclosures.

3. **Consumer request process** — establish a process to receive and
   respond to consumer rights requests (know, delete, correct, opt-out)
   within 45 days.

4. **No sale or sharing** — if you do not sell or share personal
   information, include a statement to that effect.

5. **Data minimization** — ONTO's minimum-necessary architecture
   supports this requirement by design.

6. **Security** — implement reasonable security measures appropriate
   to the nature of the information. ONTO's encryption, authentication,
   and audit trail support this.

7. **Contracts** — if you share data with service providers or
   contractors, execute CCPA-compliant contracts.

---

## What still needs legal review

- [ ] Threshold assessment — does CCPA apply to your specific
  deployment and business?
- [ ] Consumer request process design and implementation
- [ ] Privacy notice content and placement
- [ ] Service provider contract templates
- [ ] Assessment of whether any data sharing constitutes "sale"
  under CCPA's broad definition
- [ ] Annual privacy policy review process

---

*This document is a working draft and has not been reviewed by legal counsel.*  
*CCPA compliance for any specific deployment must be independently assessed.*
