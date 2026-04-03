"""
api/consent/schema.py

ISO 27560 + W3C DPV consent record schema for ONTO.

Responsibilities:
  - SQL DDL for the consent_ledger table
  - initialize() to create tables idempotently
  - DPV purpose and legal basis vocabularies
  - JSON-LD serialization of consent records

The schema is forward-compatible with W3C VC 2.0:
VC envelope fields (vc_id, vc_issuer, vc_proof, etc.) are present
in every record from day one — NULL until Phase 5 activates VCService.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from modules import memory as _memory


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_CONSENT_LEDGER = """
CREATE TABLE IF NOT EXISTS consent_ledger (
    -- Identity
    consent_id          TEXT    PRIMARY KEY,
    schema_version      TEXT    NOT NULL DEFAULT '1.0',

    -- Parties (ISO 27560 §6.3.2)
    subject_id          TEXT    NOT NULL,
    grantor_id          TEXT    NOT NULL,
    requester_id        TEXT    NOT NULL,
    operator_node_did   TEXT,

    -- Consent substance (ISO 27560 §6.3.3)
    purpose             TEXT    NOT NULL DEFAULT 'dpv:ServiceProvision',
    purpose_description TEXT    NOT NULL DEFAULT '',
    legal_basis         TEXT    NOT NULL DEFAULT 'legitimate-use',
    operations          TEXT    NOT NULL DEFAULT '["read","navigate"]',
    classification_max  INTEGER NOT NULL DEFAULT 2,
    data_categories     TEXT,
    geographic_scope    TEXT,

    -- Temporal (ISO 27560 §6.3.4)
    granted_at          REAL    NOT NULL,
    valid_from          REAL    NOT NULL,
    valid_until         REAL,
    last_reconfirmed    REAL,

    -- State
    status              TEXT    NOT NULL DEFAULT 'active',
    revoked_at          REAL,
    revocation_reason   TEXT,
    revocation_type     TEXT,

    -- HIPAA §164.508 required elements (healthcare profile)
    hipaa_phi_description TEXT,
    hipaa_expiry_event    TEXT,
    hipaa_conditioning    TEXT,
    hipaa_redisclosure    TEXT,

    -- Delegation chain
    delegated_from      TEXT    REFERENCES consent_ledger(consent_id),
    delegation_depth    INTEGER NOT NULL DEFAULT 0,

    -- Audit linkage
    chain_hash          TEXT,
    govern_event_id     INTEGER,

    -- W3C VC 2.0 fields (Phase 4: NULL; Phase 5: populated by VCService)
    vc_id               TEXT,
    vc_issuer           TEXT,
    vc_proof_type       TEXT,
    vc_cryptosuite      TEXT,
    vc_proof            TEXT,
    vc_status_list_id   TEXT,
    vc_status_list_idx  INTEGER,
    sd_jwt_token        TEXT
);
"""

_CREATE_CONSENT_REQUESTS = """
CREATE TABLE IF NOT EXISTS consent_requests (
    request_id      TEXT    PRIMARY KEY,
    subject_id      TEXT    NOT NULL,
    requester_id    TEXT    NOT NULL,
    purpose         TEXT    NOT NULL,
    purpose_description TEXT NOT NULL DEFAULT '',
    classification  INTEGER NOT NULL DEFAULT 0,
    operation       TEXT    NOT NULL,
    created_at      REAL    NOT NULL,
    expires_at      REAL,
    resolved_at     REAL,
    resolution      TEXT,   -- 'granted' | 'denied' | 'expired'
    context_json    TEXT
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_consent_subject
    ON consent_ledger(subject_id, status);

CREATE INDEX IF NOT EXISTS idx_consent_requester
    ON consent_ledger(requester_id, status);

CREATE INDEX IF NOT EXISTS idx_consent_purpose
    ON consent_ledger(purpose, valid_until);

CREATE INDEX IF NOT EXISTS idx_consent_delegation
    ON consent_ledger(delegated_from)
    WHERE delegated_from IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_consent_requests_subject
    ON consent_requests(subject_id, resolved_at);
"""


# ---------------------------------------------------------------------------
# INITIALIZE
# ---------------------------------------------------------------------------

def initialize() -> None:
    """
    Create all consent tables and indexes idempotently.
    Safe to call multiple times — CREATE IF NOT EXISTS throughout.
    Called by ConsentManager.start() before any operations.
    """
    conn = _get_conn()
    try:
        with conn:
            conn.execute(_CREATE_CONSENT_LEDGER)
            conn.execute(_CREATE_CONSENT_REQUESTS)
            for stmt in _CREATE_INDEXES.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
    finally:
        conn.close()


def _get_conn() -> sqlite3.Connection:
    """Return a WAL-mode connection to the ONTO database."""
    conn = sqlite3.connect(
        _memory.DB_PATH,
        check_same_thread=False,
        timeout=5,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA cache_size=-32768")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# DPV PURPOSE VOCABULARY
# ---------------------------------------------------------------------------

# Standard W3C Data Privacy Vocabulary purpose URIs mapped to
# their plain-language descriptions and default permitted operations.
DPV_PURPOSES: Dict[str, Dict[str, Any]] = {
    "dpv:ServiceProvision": {
        "description": "Operating the ONTO system for this session",
        "default_operations": ["read", "navigate"],
        "classification_ceiling": 2,
    },
    "dpv:ResearchAndDevelopment": {
        "description": "Analytics, improvement, and research",
        "default_operations": ["read"],
        "classification_ceiling": 1,
    },
    "dpv:LegalCompliance": {
        "description": "Audit, regulatory compliance, and legal obligations",
        "default_operations": ["read", "export"],
        "classification_ceiling": 3,
    },
    "dpv:SharingWithThirdParty": {
        "description": "Sharing context with federated ONTO nodes",
        "default_operations": ["navigate", "export"],
        "classification_ceiling": 2,
    },
    "dpv:PersonalisedBenefit": {
        "description": "Personalisation and contextual adaptation",
        "default_operations": ["read", "relate", "navigate"],
        "classification_ceiling": 2,
    },
    "dpv:HealthcarePayment": {
        "description": "Healthcare treatment, payment, or operations (HIPAA)",
        "default_operations": ["read", "navigate"],
        "classification_ceiling": 4,
    },
}

# ---------------------------------------------------------------------------
# LEGAL BASIS VOCABULARY
# ---------------------------------------------------------------------------

LEGAL_BASES: Dict[str, str] = {
    "gdpr:consent-art6-1a":           "GDPR Article 6(1)(a) — explicit consent",
    "gdpr:legitimate-interest-art6-1f":"GDPR Article 6(1)(f) — legitimate interest",
    "gdpr:legal-obligation-art6-1c":  "GDPR Article 6(1)(c) — legal obligation",
    "hipaa:authorization-164-508":    "HIPAA 45 CFR §164.508 — authorization",
    "hipaa:treatment":                "HIPAA — treatment (no authorization needed)",
    "hipaa:operations":               "HIPAA — healthcare operations",
    "hipaa:payment":                  "HIPAA — payment",
    "glba:opt-out":                   "GLBA §6802 — opt-out of data sharing",
    "legitimate-use":                 "Legitimate use (non-regulated context)",
}

# ---------------------------------------------------------------------------
# JSON-LD SERIALIZATION
# ---------------------------------------------------------------------------

_JSONLD_CONTEXT = [
    "https://www.w3.org/ns/dpv",
    "https://onto.example/consent/v1",
]


def to_jsonld(record: "ConsentRecord") -> Dict[str, Any]:  # type: ignore
    """
    Serialize a ConsentRecord as a DPV-conformant JSON-LD document.
    This is the Phase 4 format. Phase 5 wraps this in a VC 2.0 envelope.
    """
    import json as _json
    doc: Dict[str, Any] = {
        "@context": _JSONLD_CONTEXT,
        "@type": "dpv:ConsentRecord",
        "dpv:hasConsentId": record.consent_id,
        "dpv:hasDataSubject": {
            "@id": f"onto:subject:{record.subject_id}"
        },
        "dpv:hasDataController": {
            "@id": record.operator_node_did or "onto:node:local"
        },
        "dpv:hasPurpose": {
            "@id": record.purpose
        },
        "dpv:hasLegalBasis": {
            "@id": record.legal_basis
        },
        "dpv:hasPermission": record.operations,
        "dpv:hasStatus": {
            "@id": (
                "dpv:ConsentGiven"
                if record.status == "active"
                else "dpv:ConsentRefused"
            )
        },
    }
    if record.valid_until:
        from datetime import datetime, timezone
        doc["dpv:hasExpiryDate"] = datetime.fromtimestamp(
            record.valid_until, tz=timezone.utc
        ).isoformat()
    if record.data_categories:
        doc["dpv:hasDataCategory"] = [
            {"@id": c} for c in record.data_categories
        ]
    return doc


def to_vc_envelope(jsonld_record: Dict[str, Any], record: "ConsentRecord") -> Dict[str, Any]:  # type: ignore
    """
    Wrap a DPV JSON-LD record in a W3C VC 2.0 envelope.
    Phase 4: proof field is empty (VCService not active).
    Phase 5: VCService fills the proof field.
    """
    from datetime import datetime, timezone

    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    envelope: Dict[str, Any] = {
        "@context": [
            "https://www.w3.org/ns/credentials/v2",
            "https://www.w3.org/ns/dpv",
        ],
        "type": ["VerifiableCredential", "ONTOConsentCredential"],
        "id": record.vc_id or f"urn:uuid:{record.consent_id}",
        "issuer": record.vc_issuer or record.operator_node_did or "onto:node:local",
        "validFrom": _iso(record.valid_from),
        "credentialSubject": jsonld_record,
    }
    if record.valid_until:
        envelope["validUntil"] = _iso(record.valid_until)
    if record.vc_status_list_id and record.vc_status_list_idx is not None:
        envelope["credentialStatus"] = {
            "type": "BitstringStatusListEntry",
            "statusListCredential": record.vc_status_list_id,
            "statusListIndex": record.vc_status_list_idx,
            "statusPurpose": "revocation",
        }
    # Proof: empty in Phase 4; populated by VCService in Phase 5
    if record.vc_proof:
        envelope["proof"] = {
            "type": "DataIntegrityProof",
            "cryptosuite": record.vc_cryptosuite or "eddsa-rdfc-2022",
            "proofValue": record.vc_proof,
        }
    return envelope
