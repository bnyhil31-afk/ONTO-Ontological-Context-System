# ONTO Consent Ledger Specification 001
**Document ID:** CONSENT-LEDGER-SPEC-001
**Version:** 1.0
**Status:** LOCKED — Design precedes code.
**Authors:** Neo (bnyhil31-afk), Claude (Anthropic)
**Governs:** Phase 4 — Multi-User Consent Ledger
**Rule 1.09A:** Code, tests, and documentation must agree with every
               decision recorded here before any checklist item is
               marked complete.

---

## Why This Exists

Systems that enforce consent only at the collection UI account for the
majority of GDPR enforcement actions (€6.2B+ through mid-2025) and most
HIPAA OCR penalties. A consent banner that fires once at signup is not
a consent ledger. It is a legal liability wearing a compliance costume.

ONTO's consent ledger enforces consent at the data-access layer — every
graph read, every navigation, every federation share — not just at
collection time. This is the architecture lesson from a decade of
regulatory failures, distilled into a single design principle:

**Consent is checked where data moves, not where users click.**

This document locks every decision before a line is code is written.

---

## Part I — Governing Principles

### 1.1 The Four Non-Negotiable Decisions

These are the highest-impact architectural choices. They are locked here.
Reopening them requires a new spec version with documented justification.

**Decision 1: Enforce consent at the query layer.**
`graph.navigate()` is the enforcement point. Every graph traversal involving
another subject's data passes through a consent gate before execution.
The gate checks current consent status, purpose alignment, recipient
authorization, and classification ceiling. A traversal without a valid
consent record returns an empty result with a CONSENT_REQUIRED event in
the audit trail — it never raises an exception.

**Decision 2: ISO 27560 + W3C DPV as the record schema from day one.**
Consent records are authored using W3C Data Privacy Vocabulary (DPV)
concepts in JSON-LD. This provides semantic richness now and a native
upgrade path to W3C VC 2.0 without a breaking migration. The VC 2.0
envelope fields (`@context`, `type`, `issuer`, `credentialSubject`,
`proof`, `credentialStatus`) are present in every record from day one —
NULL until Phase 5 activates the VCService.

**Decision 3: Dual credential format from the start.**
Records are designed to be expressible in both W3C Data Integrity
(`eddsa-rdfc-2022`) and SD-JWT VC. EU Digital Identity Wallet
compliance (December 2027 deadline) requires SD-JWT VC for online
scenarios. Building for dual format now avoids a forced migration
in 18 months. The VCService interface (defined here, implemented
Phase 5) abstracts the credential format from the rest of the system.

**Decision 4: Operator-configurable friction, evidence-based defaults.**
Three regulatory profiles (team, healthcare, financial) select different
enforcement strictness, UI friction, retention periods, and revocation
mechanisms. The underlying record structure is identical across all three.
Only the enforcement and presentation layers differ.

### 1.2 What This Is Not

This is not a UI framework. It is not an OAuth server. It is not a
replacement for legal counsel. It is not a guarantee of regulatory
compliance for any specific deployment.

This is the infrastructure that makes compliance possible. Legal
compliance for any specific deployment requires independent legal review
(checklist item 4.01).

---

## Part II — Architecture Overview

### 2.1 Addon, Not Integration

Phase 4 follows the same governing principle as Phase 3:

**No file outside `api/consent/` is modified by Phase 4.**
The consent ledger is an addon to a complete, functioning system.
ONTO without the multi-user consent ledger is fully functional for
single-user deployments. Phase 4 adds capability for multi-user
and regulated contexts.

The one exception: `modules/graph.py` gains a consent gate at the
`navigate()` call site. This is a single function call behind a
feature flag — not a structural modification.

### 2.2 Package Structure

```
api/
  consent/
    __init__.py          — Package init; dep check; exposes ConsentAdapter
    adapter.py           — ConsentAdapter protocol (the single swap point)
    ledger.py            — ConsentLedger: record, check, revoke, history
    enforcement.py       — PDP/PEP gate; integrates with graph.navigate()
    profiles.py          — Regulatory profile definitions and selection
    vc_service.py        — VCService protocol (no implementation in Phase 4)
    schema.py            — ISO 27560 + DPV record schema; JSON-LD contexts
    config.py            — All consent env vars in one place
    status_list.py       — Bitstring Status List management (revocation)

modules/
  graph.py               — ONE addition: consent gate at navigate()
                           (feature-flagged, no structural change)

tests/
  test_consent.py        — Phase 4 test suite

docs/
  CONSENT-LEDGER-SPEC-001.md  — This document
  CONSENT-LEDGER.md           — Operator-facing documentation
```

### 2.3 The ConsentAdapter Protocol

Same pattern as FederationAdapter. The single swap point.
Any concern — regulatory change, new jurisdiction, VC format shift —
is addressed by wrapping or replacing the adapter.

```python
class ConsentAdapter(Protocol):
    def check(
        self,
        subject_id: str,
        requester_id: str,
        purpose: str,
        classification: int,
        operation: str,
    ) -> ConsentDecision: ...

    def grant(self, record: ConsentRecord) -> str: ...
    def revoke(self, consent_id: str, reason: str) -> bool: ...
    def history(self, subject_id: str) -> List[ConsentRecord]: ...
    def pending(self, subject_id: str) -> List[ConsentRequest]: ...
```

`ConsentDecision` is a dataclass:
```python
@dataclass
class ConsentDecision:
    allowed: bool
    consent_id: Optional[str]   # UUID of the authorizing record
    reason: str                  # always populated; explains the decision
    requires_checkpoint: bool    # True if human decision is needed
    audit_id: Optional[int]      # audit trail record ID
```

### 2.4 The PDP/PEP Pattern

**PDP (Policy Decision Point):** `enforcement.ConsentGate.decide()`
  Evaluates consent records against the request context.
  Returns a `ConsentDecision`. Pure function — no side effects.

**PEP (Policy Enforcement Point):** `modules/graph.navigate()` (one call)
  Calls `ConsentGate.decide()` before executing the traversal.
  On `allowed=False`: returns empty result + writes audit event.
  On `requires_checkpoint=True`: returns empty result + triggers
  `onto_checkpoint` (same pattern as everywhere else in ONTO).

This is the minimum viable enforcement point. As ONTO grows,
additional PEPs can be added at `graph.relate()`, MCP tool handlers,
and the federation boundary — all calling the same PDP.

---

## Part III — Record Schema

### 3.1 Unified Consent Record

Every consent record — regardless of deployment context or regulatory
profile — has the same structure. Regulatory differences are expressed
through field population, not through separate schemas.

```sql
CREATE TABLE IF NOT EXISTS consent_ledger (
    -- Identity
    consent_id          TEXT    PRIMARY KEY,   -- UUID v4
    schema_version      TEXT    NOT NULL DEFAULT '1.0',

    -- Parties (ISO 27560 §6.3.2)
    subject_id          TEXT    NOT NULL,      -- SHA-256(user identity)
    grantor_id          TEXT    NOT NULL,      -- who gave consent
    requester_id        TEXT    NOT NULL,      -- who receives access
    operator_node_did   TEXT,                  -- did:key of ONTO node

    -- Consent substance (ISO 27560 §6.3.3)
    purpose             TEXT    NOT NULL,      -- DPV purpose concept URI
    purpose_description TEXT    NOT NULL,      -- human-readable
    legal_basis         TEXT    NOT NULL,      -- GDPR Art 6 / HIPAA / GLBA
    operations          TEXT    NOT NULL,      -- JSON array: read/relate/navigate/export
    classification_max  INTEGER NOT NULL,      -- max data classification covered
    data_categories     TEXT,                  -- JSON array of DPV data category URIs
    geographic_scope    TEXT,                  -- ISO 3166-1 codes, comma-separated

    -- Temporal (ISO 27560 §6.3.4)
    granted_at          REAL    NOT NULL,
    valid_from          REAL    NOT NULL,
    valid_until         REAL,                  -- NULL = standing (see re-confirmation)
    last_reconfirmed    REAL,

    -- Consent state
    status              TEXT    NOT NULL DEFAULT 'active',
    revoked_at          REAL,
    revocation_reason   TEXT,
    revocation_type     TEXT,                  -- 'written' (HIPAA) | 'electronic' (GDPR)

    -- Regulatory profile fields (HIPAA §164.508 requirements)
    hipaa_phi_description TEXT,               -- specific PHI description
    hipaa_expiry_event    TEXT,               -- expiry by event (not just date)
    hipaa_conditioning    TEXT,               -- conditioning statement
    hipaa_redisclosure    TEXT,               -- redisclosure warning

    -- Delegation chain
    delegated_from      TEXT,                  -- parent consent_id if delegated
    delegation_depth    INTEGER NOT NULL DEFAULT 0,  -- max 3

    -- Audit
    chain_hash          TEXT,                  -- Merkle chain link to audit trail
    govern_event_id     INTEGER,               -- audit trail record of the GOVERN event

    -- W3C VC 2.0 fields (present from day one; NULL until Phase 5 activates VCService)
    vc_id               TEXT,                  -- VC @id
    vc_issuer           TEXT,                  -- did:key of issuing node
    vc_proof_type       TEXT,                  -- 'DataIntegrityProof' | 'SD-JWT'
    vc_cryptosuite      TEXT,                  -- 'eddsa-rdfc-2022'
    vc_proof            TEXT,                  -- base64url signature
    vc_status_list_id   TEXT,                  -- Bitstring Status List URL
    vc_status_list_idx  INTEGER,               -- index in status list
    sd_jwt_token        TEXT                   -- SD-JWT VC (EUDIW format, Phase 5)
);

CREATE INDEX IF NOT EXISTS idx_consent_subject
    ON consent_ledger(subject_id, status);
CREATE INDEX IF NOT EXISTS idx_consent_requester
    ON consent_ledger(requester_id, status);
CREATE INDEX IF NOT EXISTS idx_consent_purpose
    ON consent_ledger(purpose, valid_until);
```

### 3.2 DPV Purpose Vocabulary

Purposes are expressed as DPV concept URIs. This is what makes
consent records machine-readable and semantically interoperable.

Standard DPV purposes mapped to ONTO operations:

| DPV URI | Plain meaning | Default operations |
|---------|--------------|-------------------|
| `dpv:ServiceProvision` | Operating the system | read, navigate |
| `dpv:ResearchAndDevelopment` | Analytics, improvement | read |
| `dpv:LegalCompliance` | Audit, regulatory | read, export |
| `dpv:SharingWithThirdParty` | Federation sharing | navigate, export |
| `dpv:PersonalisedBenefit` | Personalisation | read, relate, navigate |
| `dpv:HealthcarePayment` | HIPAA treatment/operations | read, navigate |

Operators may define custom purpose URIs under their own namespace.
Custom purposes must include a plain-language `purpose_description`.

### 3.3 Legal Basis Vocabulary

| Value | Regulation | When to use |
|-------|-----------|-------------|
| `gdpr:consent-art6-1a` | GDPR | Explicit user consent |
| `gdpr:legitimate-interest-art6-1f` | GDPR | Legitimate interest assessment required |
| `gdpr:legal-obligation-art6-1c` | GDPR | SEC 17a-4, MiFID II retention |
| `hipaa:authorization-164-508` | HIPAA | Named PHI authorization |
| `hipaa:treatment` | HIPAA | Treatment — no authorization needed |
| `hipaa:operations` | HIPAA | Healthcare operations |
| `glba:opt-out` | GLBA | Financial data sharing (opt-out model) |
| `legitimate-use` | General | Non-regulated contexts |

The legal_basis field is critical for two reasons: (1) it determines
the revocation mechanism (electronic for GDPR, written for HIPAA),
and (2) it determines whether the MiFID II / SEC 17a-4 retention lock
applies — records with `legal-obligation` basis cannot be erased.

### 3.4 JSON-LD Context and DPV Mapping

Every consent record can be serialized as a DPV-conformant JSON-LD
document. The serialization is defined in `schema.py` and is the
foundation for VC 2.0 wrapping in Phase 5.

```jsonc
{
  "@context": [
    "https://www.w3.org/ns/dpv",
    "https://onto.example/consent/v1"
  ],
  "@type": "dpv:ConsentRecord",
  "dpv:hasConsentId": "<consent_id>",
  "dpv:hasDataSubject": {"@id": "onto:subject:<subject_id>"},
  "dpv:hasDataController": {"@id": "<operator_node_did>"},
  "dpv:hasPurpose": {"@id": "<purpose_uri>"},
  "dpv:hasLegalBasis": {"@id": "<legal_basis>"},
  "dpv:hasPermission": ["<operations_array>"],
  "dpv:hasExpiryDate": "<valid_until_iso8601>",
  "dpv:hasStatus": {"@id": "dpv:ConsentGiven"}
}
```

Phase 5 wraps this in a VC 2.0 envelope:
```jsonc
{
  "@context": [
    "https://www.w3.org/ns/credentials/v2",
    "https://www.w3.org/ns/dpv"
  ],
  "type": ["VerifiableCredential", "ONTOConsentCredential"],
  "issuer": "<operator_node_did>",
  "validFrom": "<granted_at_iso8601>",
  "validUntil": "<valid_until_iso8601>",
  "credentialSubject": { /* DPV record above */ },
  "credentialStatus": {
    "type": "BitstringStatusListEntry",
    "statusListCredential": "<status_list_url>",
    "statusListIndex": <vc_status_list_idx>,
    "statusPurpose": "revocation"
  },
  "proof": {
    "type": "DataIntegrityProof",
    "cryptosuite": "eddsa-rdfc-2022",
    "created": "<timestamp>",
    "verificationMethod": "<did_key_url>",
    "proofPurpose": "assertionMethod",
    "proofValue": "<base64url_signature>"
  }
}
```

---

## Part IV — Regulatory Profiles

### 4.1 Profile Selection

Selected via `ONTO_CONSENT_PROFILE` environment variable.
Valid values: `team`, `healthcare`, `financial`, `custom`.
Default: `team`.

Each profile sets defaults for:
- Consent granularity (per-session / per-purpose / per-authorization)
- Friction level (low / medium / high)
- Revocation mechanism (electronic / written)
- Retention period (operator-defined / 6-year / 7-year)
- Required record fields
- Re-confirmation interval
- Delegation depth limit

### 4.2 Team Profile

**Context:** 2-50 people, informal or low-regulation deployment.

| Setting | Value | Rationale |
|---------|-------|-----------|
| Granularity | Per-purpose | GDPR minimum; manageable friction |
| Friction | JIT on first access per purpose | ≤3 prompts/session |
| Revocation | Electronic | GDPR compliant |
| Retention | Operator-defined (default: indefinite) | No minimum unless EU |
| Re-confirmation | 90 days (standing consents) | Same as Phase 3 |
| Delegation depth | 2 | A → B → C |
| VC fields | NULL | Phase 5 |

`required_fields`: consent_id, subject_id, grantor_id, requester_id,
  purpose, legal_basis, operations, granted_at, valid_until

### 4.3 Healthcare Profile

**Context:** HIPAA-covered entities, clinical research, patient care.

| Setting | Value | Rationale |
|---------|-------|-----------|
| Granularity | Per-authorization (per PHI disclosure) | 45 CFR §164.508 |
| Friction | Explicit per-operation | HIPAA authorization required |
| Revocation | Written (signed statement required) | §164.508(b)(5) |
| Retention | 6 years from creation or last effective date | HIPAA §164.530(j) |
| Re-confirmation | Per-disclosure (not time-based) | Each use is a new authorization |
| Delegation depth | 1 | Named parties only |
| VC fields | Required when Phase 5 activates | Portable patient consent |

Additional required fields: `hipaa_phi_description`, `hipaa_expiry_event`,
  `hipaa_conditioning`, `hipaa_redisclosure`, named parties in
  grantor_id and requester_id (not hashed — HIPAA requires identification).

De-identification bypass: data with classification 0 (public) that has
  been formally de-identified via Safe Harbor or Expert Determination
  does not require consent. The consent gate checks for a
  `deidentification_record_id` before requiring a consent_id.

### 4.4 Financial Profile

**Context:** SEC-registered entities, GLBA-covered institutions,
  MiFID II-subject firms.

| Setting | Value | Rationale |
|---------|-------|-----------|
| Granularity | Per-purpose with opt-out option | GLBA opt-out model |
| Friction | Explicit opt-in for sharing; implicit for internal | GLBA §6802 |
| Revocation | Electronic | GLBA opt-out mechanism |
| Retention | 7 years (SEC 17a-4) or 5 years (MiFID II) | Regulatory minimum |
| Re-confirmation | Annual for standing consents | Regulation-neutral safe default |
| Delegation depth | 1 | Regulated context — minimize chain length |
| VC fields | Required when Phase 5 activates | SEC 17a-4 audit trail |
| Privilege tagging | Supported | Attorney-client privilege field |

**Retention lock:** Records with `legal_basis = gdpr:legal-obligation-art6-1c`
  are locked against erasure during their retention period. The
  cryptographic erasure pathway (Phase 5.01) will enforce this lock
  before executing key destruction.

**GLBA opt-out:** When `consent_record.legal_basis = glba:opt-out`, the
  system creates an opt-out record rather than an opt-in consent record.
  The consent gate inverts: data sharing is permitted until an opt-out
  record is found for the subject/purpose pair.

### 4.5 Custom Profile

Operators in regulated contexts not covered by the three standard
profiles can define a custom profile by subclassing `RegulatoryProfile`
in `profiles.py`. All fields of the standard record are available.
Custom profiles must pass all tests in `TestRegulatoryProfiles` before
deployment.

---

## Part V — Enforcement Model

### 5.1 The Consent Gate

`enforcement.ConsentGate` implements the PDP. It is stateless and
can be called from anywhere. It reads from the consent ledger and
the regulatory profile — it never writes.

```python
def decide(
    self,
    subject_id: str,
    requester_id: str,
    purpose: str,
    classification: int,
    operation: str,
    context: Optional[Dict] = None,
) -> ConsentDecision:
```

Decision logic (in order):

1. **Absolute barriers** (not configurable):
   - `classification >= 4`: always `allowed=False` (PHI/privileged)
   - `is_crisis`: always `allowed=False` (safety gate, same as federation)

2. **Self-access**: `subject_id == requester_id` → `allowed=True`
   (users always access their own data without a consent record)

3. **Active consent lookup**: find a valid, non-expired, non-revoked
   consent record matching (subject_id, requester_id, purpose).
   If found and `operation in record.operations`: `allowed=True`

4. **Pending consent**: if no active record exists and the regulatory
   profile requires explicit consent: `requires_checkpoint=True`
   (triggers onto_checkpoint — same pattern as everywhere in ONTO)

5. **GLBA opt-out check**: for financial profile, check for an active
   opt-out record. If found: `allowed=False`. If not found: permitted.

6. **Default deny**: `allowed=False, reason="no consent record found"`

### 5.2 Integration with graph.navigate()

```python
# modules/graph.py — the one addition in Phase 4
# Feature-flagged: no-op when ONTO_CONSENT_ENABLED=false (default)

def navigate(
    text: str,
    include_sensitive: bool = False,
    # Phase 4 additions (optional — backwards compatible)
    subject_id: Optional[str] = None,
    requester_id: Optional[str] = None,
    purpose: Optional[str] = None,
    consent_id: Optional[str] = None,
) -> List[Dict]:

    # Existing logic unchanged when consent not configured
    if not _CONSENT_ENABLED or subject_id is None:
        return _navigate_unchecked(text, include_sensitive)

    # Phase 4: consent gate before traversal
    from api.consent.enforcement import consent_gate
    decision = consent_gate.decide(
        subject_id=subject_id,
        requester_id=requester_id or subject_id,
        purpose=purpose or "dpv:ServiceProvision",
        classification=_get_context_classification(),
        operation="navigate",
    )

    if not decision.allowed:
        _memory.record(
            event_type="CONSENT_GATE_BLOCKED",
            notes=decision.reason,
            context={"subject_id": subject_id, "purpose": purpose},
        )
        if decision.requires_checkpoint:
            return [{"consent_required": True, "consent_id": None}]
        return []

    return _navigate_unchecked(text, include_sensitive)
```

### 5.3 Consent Request Flow

When `requires_checkpoint=True`:
1. Caller receives `[{"consent_required": True}]`
2. Caller surfaces to `onto_checkpoint` with context
3. Operator sees: "User [id] is requesting access to [subject]'s
   data for purpose [purpose]. Grant access?"
4. Decision `proceed` → `consent.grant()` creates a consent record
5. Subsequent `navigate()` call with `consent_id` proceeds normally

This is human sovereignty at the data layer, not just the UI.

---

## Part VI — VCService Protocol (Phase 5 Interface)

### 6.1 Why Define It Now

The VCService interface is defined in Phase 4 even though it has
no implementation. This is the watch movement principle: the interface
specification is done before the component exists, so the rest of the
system is built to the interface.

When Phase 5 activates (sidecar or native Python library), nothing
upstream changes. The consent ledger, the enforcement gate, the
regulatory profiles — none of them change. Only the VCService
implementation activates.

### 6.2 The Interface

```python
# api/consent/vc_service.py

class VCService(Protocol):
    """
    Cryptographic VC operations for consent records.
    Phase 4: not implemented. Returns None for all operations.
    Phase 5: either a native Python implementation (if a suitable
             library exists by then) or a sidecar HTTP API call.

    The sidecar is a small Rust or Go service that handles:
      - VC 2.0 issuance with DataIntegrity + eddsa-rdfc-2022
      - SD-JWT VC issuance for EUDIW compliance
      - Bitstring Status List management
      - DIF Presentation Exchange verification
    The sidecar exposes a simple JSON HTTP API.
    ONTO calls it. ONTO never knows whether it's Rust, Go, or Python.
    """

    def issue_vc(
        self,
        consent_record: Dict,
        format: str = "data-integrity",  # or "sd-jwt"
    ) -> Optional[Dict]:
        """
        Issue a W3C VC 2.0 for a consent record.
        format="data-integrity" → DataIntegrityProof + eddsa-rdfc-2022
        format="sd-jwt" → SD-JWT VC (EUDIW-compatible)
        Returns the signed VC dict, or None if Phase 5 not active.
        """
        ...

    def verify_vc(self, vc: Dict) -> Tuple[bool, str]:
        """
        Verify a VC's proof and check its revocation status.
        Returns (valid, reason).
        Returns (False, "vc_service_not_active") in Phase 4.
        """
        ...

    def revoke_vc(self, consent_id: str, status_list_index: int) -> bool:
        """
        Flip the revocation bit in the Bitstring Status List.
        Returns False in Phase 4 (status list not yet active).
        """
        ...

    def create_presentation_definition(
        self,
        required_purpose: str,
        required_operations: List[str],
    ) -> Dict:
        """
        Create a DIF Presentation Definition for consent verification.
        Used when ONTO acts as a verifier (Phase 5+).
        """
        ...


class NullVCService:
    """
    Phase 4 no-op implementation. All methods return None/False.
    Activated when ONTO_VC_SERVICE_ENABLED=false (default in Phase 4).
    """

    def issue_vc(self, *args, **kwargs) -> None:
        return None

    def verify_vc(self, *args, **kwargs) -> Tuple[bool, str]:
        return False, "vc_service_not_active"

    def revoke_vc(self, *args, **kwargs) -> bool:
        return False

    def create_presentation_definition(self, *args, **kwargs) -> Dict:
        return {}
```

### 6.3 Sidecar Architecture (Phase 5 Reference)

When Phase 5 activates, the sidecar:

```
ONTO Python process
       ↓ HTTP POST /vc/issue
VCService Sidecar (Rust/Go)
       ↓
Ed25519 signing (eddsa-rdfc-2022)
       ↓
Signed VC returned to ONTO
       ↓
Stored in consent_ledger.vc_proof
```

The sidecar API surface is minimal:
- `POST /vc/issue` — issue a VC from a consent record dict
- `POST /vc/verify` — verify a VC's proof
- `POST /vc/revoke` — update Bitstring Status List
- `GET  /vc/status/{consent_id}` — check revocation status

Environment variables for Phase 5:
```
ONTO_VC_SERVICE_ENABLED=false        # true when sidecar is running
ONTO_VC_SERVICE_URL=http://127.0.0.1:7800
ONTO_VC_SERVICE_TIMEOUT_SECS=5
ONTO_VC_STATUS_LIST_URL=             # public URL for Bitstring Status List
```

---

## Part VII — Bitstring Status List

### 7.1 Design

Every consent record gets a `vc_status_list_idx` (NULL in Phase 4).
When Phase 5 activates, the VCService manages a Bitstring Status List
following the W3C Recommendation (May 2025).

- Minimum size: 131,072 entries (16KB compressed) — covers all
  consent records ONTO is likely to issue in production
- Multi-bit entries: 2 bits per entry encode 4 states:
  - `00` = active
  - `01` = suspended (pending review)
  - `10` = revoked
  - `11` = expired
- `ttl`: 300 seconds for consent revocation (prompt propagation)
- Status list is a VC itself, signed by the node's did:key

### 7.2 Revocation Cascade

When `consent.revoke()` is called:
1. Local record updated to `status='revoked'` immediately
2. If Phase 5 active: `vc_service.revoke_vc()` flips status list bit
3. If federation: `adapter.recall()` sends retraction to peers
4. `CONSENT_REVOKED` audit event written
5. Within `ttl` seconds: all verifiers checking the status list
   will see the revocation

---

## Part VIII — Storage and Scaling

### 8.1 Phase 4 (SQLite)

```sql
-- Required pragmas for consent ledger table
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA cache_size = -32768;
```

All consent writes use `BEGIN IMMEDIATE` transactions.
Consent reads never block writers (WAL mode).
Expected scale: 2-50 users, hundreds of consent records,
thousands of consent checks per day — well within SQLite capacity.

### 8.2 Scaling Path

| Users | Writers/sec | Storage | Approach |
|-------|-------------|---------|---------|
| 2-50 | <10 | <100MB | SQLite WAL |
| 50-200 | <50 | <1GB | SQLite + Litestream |
| 200-1000 | <200 | <10GB | SQLite + LiteFS |
| 1000+ | Unlimited | Unlimited | PostgreSQL |

The ConsentAdapter interface is identical across all tiers.
The storage layer swaps underneath. Nothing upstream changes.

---

## Part IX — Configuration

```
# Master switch (default: false — single-user mode unchanged)
ONTO_CONSENT_ENABLED=false

# Regulatory profile
ONTO_CONSENT_PROFILE=team          # team | healthcare | financial | custom

# Feature flags
ONTO_CONSENT_GATE_ENFORCE=true     # false = log only (audit mode)
ONTO_CONSENT_JIT_ENABLED=true      # JIT consent prompting at navigate()
ONTO_CONSENT_DELEGATION_MAX_DEPTH=3

# Retention (overrides profile default)
ONTO_CONSENT_RETENTION_DAYS=       # empty = profile default

# Re-confirmation interval
ONTO_CONSENT_RECONFIRM_DAYS=90

# VCService (Phase 5)
ONTO_VC_SERVICE_ENABLED=false
ONTO_VC_SERVICE_URL=http://127.0.0.1:7800
ONTO_VC_STATUS_LIST_URL=

# Audit mode (log consent decisions without blocking)
# Use this during rollout to validate consent coverage before enforcing
ONTO_CONSENT_AUDIT_ONLY=false
```

**Important:** `ONTO_CONSENT_GATE_ENFORCE=false` puts the gate in
audit-only mode — it logs what *would* have been blocked but does not
block it. Use during rollout to validate coverage. Never ship to
production in this mode.

---

## Part X — Test Coverage Requirements

Safety-critical classes block deployment if they fail.

| Class | Coverage | Critical |
|-------|----------|---------|
| ⚠️ TestConsentAbsoluteBarriers | crisis=True → blocked; cls 4+ → blocked | Yes |
| ⚠️ TestConsentGate | self-access permitted; no-consent blocked; checkpoint triggered | Yes |
| TestConsentLedger | grant, revoke, history, delegation chain | No |
| TestRegulatoryProfiles | team/healthcare/financial required fields; retention locks | No |
| TestGLBAOptOut | opt-out inverts permit/deny; opt-out record creation | No |
| TestHIPAAFields | six required elements present; written revocation enforced | No |
| TestDelegationChain | max depth enforced; chain traced in audit | No |
| TestVCServiceInterface | NullVCService returns None/False; interface contract | No |
| TestSchemaJSON-LD | every record serializes to valid DPV JSON-LD | No |
| TestMigration | consent_ledger table created; existing schema unchanged | No |
| TestConsentGateIntegration | navigate() blocked without consent; audit event written | No |
| TestAuditMode | AUDIT_ONLY=true logs without blocking | No |

---

## Part XI — Open Questions (Answered Before Coding)

These are decided here. They are not reopened without a new spec version.

**Q1: Where is the enforcement point?**
`graph.navigate()` — the primary data access point. Additional PEPs
at `graph.relate()` and MCP tools are Phase 4+ additions.

**Q2: How is subject_id defined for multi-user?**
SHA-256(user_identity_string) — same pattern as session hashing.
For HIPAA profile: full named identity (not hashed) per §164.508.

**Q3: GLBA opt-out vs GDPR opt-in — same table?**
Yes. `legal_basis` field distinguishes them. Opt-out records have
`status='opt_out'` rather than `'active'`. Gate logic handles both.

**Q4: Delegation — what happens if the parent consent is revoked?**
Cascade revocation: revoking a parent consent_id automatically
revokes all records with `delegated_from = parent_consent_id`.
Written to audit trail as `CONSENT_CASCADE_REVOKED`.

**Q5: Can consent be granted for derived data / inferences?**
No automatic consent inheritance. If A's data produces an inference
about B, consent for A does not cover B. A new consent request for B
is required. This matches Colorado Privacy Act requirements and
protects against "consent decay" in AI systems.

**Q6: What happens to crisis content at the consent gate?**
Same absolute barrier as everywhere else in ONTO. Crisis content
is blocked before consent is checked. The consent gate never
sees crisis content. This is not configurable.

**Q7: HIPAA written revocation — how is "written" enforced technically?**
A consent record with `legal_basis = hipaa:authorization-164-508`
requires `revocation_type = 'written'`. The API requires a non-empty
`revocation_statement` field (the signed statement text or its hash).
The system cannot verify the signature is physically present, but it
creates an audit record that serves as evidence of the written process.
Legal counsel must verify the process is compliant for the deployment.

---

## Part XII — What Phase 4 Delivers

At the end of Phase 4, ONTO supports:

1. Multi-user deployments with consent enforced at the query layer
2. Three regulatory profiles (team, healthcare, financial)
3. ISO 27560 + DPV consent records, VC 2.0 upgrade-ready
4. GLBA opt-out model alongside GDPR opt-in
5. HIPAA §164.508 authorization elements
6. Consent delegation with cascade revocation
7. JIT consent prompting via onto_checkpoint
8. Audit-only mode for staged rollout
9. Full test suite with safety-critical gate tests

What Phase 4 does NOT deliver (reserved for Phase 5+):
- W3C VC 2.0 issuance and verification (VCService sidecar)
- SD-JWT VC for EUDIW compliance
- Bitstring Status List (revocation visible to external verifiers)
- DIF Presentation Exchange
- OAuth 2.1 + PKCE (Stage 2 upgrade to session management)
- Full RBAC (role-based access layered on consent — Stage 2)

---

*This document is part of the permanent record of ONTO.*
*Code follows design. Never the reverse.*
*Consent is not a feature. It is a commitment.*
*Let's explore together.*
