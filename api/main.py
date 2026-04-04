"""
api/main.py

ONTO HTTP API — Stage 1

Wraps the ONTO five-step processing loop in a secure, documented HTTP server.
Designed for local single-device deployment — the same device that runs ONTO.

Endpoints
─────────
  GET    /health       Public liveness check
  POST   /auth         Authenticate and receive a session token
  POST   /process      Run the ONTO five-step loop on any input
  GET    /audit        Read the permanent audit trail
  DELETE /session      Explicit logout

Authentication
──────────────
All endpoints except /health require a session token.
Obtain one via POST /auth. Present it as: Authorization: Bearer <token>

Tokens rotate on every authenticated request. The updated token is
returned in the X-Session-Token response header. Clients must use
this new token for the next request — the previous one is immediately
invalid. This is T-013 mitigation: a stolen token can only be replayed
until the legitimate client makes its next request.

Human Sovereignty
─────────────────
The ONTO loop includes a human checkpoint (GOVERN) for consequential
decisions. When a checkpoint is required and no human_decision is
provided, the API returns status "pending_checkpoint" with the examined
context. The client re-submits with human_decision to proceed.

Valid decisions: proceed | veto | flag | defer

CRISIS Protocol
───────────────
Inputs that trigger a CRISIS signal are never auto-processed, never
suppressed. The response carries status "crisis" and the safe messaging
text. The event is permanently committed to the audit trail regardless
of what the client does next.

Running the server
──────────────────
  pip install fastapi uvicorn[standard]
  uvicorn api.main:app --host 127.0.0.1 --port 8000

Documentation available at:
  http://127.0.0.1:8000/docs   (Swagger UI)
  http://127.0.0.1:8000/redoc  (ReDoc)
"""

import os
import sys
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

# ── Project root on sys.path ─────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.config import config
from core.ratelimit import rate_limiter
from core.session import session_manager
from core.verify import verify_principles
from modules import checkpoint, contextualize, intake, memory, surface
from modules.checkpoint import ALWAYS_ASK_CONFIDENCE, ALWAYS_ASK_WEIGHT


# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown lifecycle.

    On startup:
      - Verify the principles have not been tampered with.
        If they have, the server refuses to start — sys.exit(1) is called
        by verify_principles() and no HTTP traffic is served. This is
        correct: a server running with modified principles is not ONTO.
      - Initialize the memory database.
      - Record a SERVER_START event in the audit trail.

    On shutdown:
      - Record a SERVER_STOP event.
      - Clear all active sessions (no silent session persistence).
    """
    verify_principles()       # halts process if tampered — intentional
    memory.initialize()
    memory.record(
        event_type="SERVER_START",
        notes=f"ONTO API server started. Environment: {config.ENVIRONMENT}.",
    )

    yield

    memory.record(
        event_type="SERVER_STOP",
        notes="ONTO API server stopped.",
    )
    session_manager.reset()


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

_DESCRIPTION = """
ONTO — Ontological Context System. HTTP API, Stage 1.

## Authentication

All endpoints except `/health` require a Bearer token.

```
Authorization: Bearer <token>
```

Obtain a token via `POST /auth`. Tokens rotate on every request —
always use the `X-Session-Token` response header as your token for
the next call. The previous token is immediately invalid.

## Processing Loop

`POST /process` runs the full ONTO five-step loop:

1. **RELATE** (intake) — sanitize, classify, safety-check  
2. **RELATE** (contextualize) — build context from the relationship graph  
3. **NAVIGATE** (surface) — examine context and produce the response  
4. **GOVERN** (checkpoint) — human sovereignty gate  
5. **REMEMBER** (memory) — commit permanently to the audit trail  

### Checkpoint Flow

When a checkpoint is required, the response has `status: pending_checkpoint`.
The `display` field shows what the system sees. Re-submit the same input
with `human_decision` to proceed:

```json
{ "input": "...", "human_decision": "proceed" }
```

Valid decisions: `proceed` | `veto` | `flag` | `defer`

### CRISIS Protocol

CRISIS inputs are never suppressed. `status: crisis` always surfaces
safe messaging and records the event permanently.
"""

app = FastAPI(
    title="ONTO API",
    description=_DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    passphrase: str = Field(..., description="System passphrase")
    identity: str = Field(
        "local",
        description="Identity label written to audit records"
    )


class AuthResponse(BaseModel):
    token: str = Field(
        ...,
        description="Bearer token. Include in Authorization header."
    )
    expires_at: float = Field(
        ...,
        description="Unix timestamp when this token expires"
    )
    identity: str


class ProcessRequest(BaseModel):
    input: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="Input to process through the ONTO loop",
    )
    human_decision: Optional[str] = Field(
        None,
        description=(
            "Required when status is pending_checkpoint. "
            "One of: proceed | veto | flag | defer"
        ),
    )


class CheckpointInfo(BaseModel):
    required: bool = Field(..., description="Whether a checkpoint was triggered")
    skipped: bool = Field(False, description="True if auto-proceeded without human input")
    decision: Optional[str] = Field(None, description="The decision made")
    action: Optional[str] = Field(None, description="The resulting system action")
    options: List[str] = Field(
        default_factory=lambda: ["proceed", "veto", "flag", "defer"],
        description="Valid decisions when pending_checkpoint",
    )
    record_id: Optional[int] = Field(None, description="Audit record ID for this checkpoint")


class ProcessResponse(BaseModel):
    status: str = Field(
        ...,
        description=(
            "complete — processing finished and committed | "
            "pending_checkpoint — re-submit with human_decision | "
            "vetoed — human vetoed | "
            "flagged — flagged for review | "
            "deferred — decision deferred | "
            "crisis — CRISIS signal detected | "
            "unsafe — HARM or INTEGRITY signal"
        ),
    )
    display: str = Field(..., description="Examined context — present this to the human")
    confidence: float = Field(..., ge=0.0, le=1.0)
    safe: bool = Field(..., description="False if any safety signal was detected")
    safety_level: Optional[str] = Field(
        None,
        description="CRISIS | HARM | INTEGRITY when safe is False"
    )
    safety_message: Optional[str] = None
    checkpoint: CheckpointInfo
    record_ids: List[int] = Field(
        default_factory=list,
        description="Audit record IDs produced by this request",
    )
    classification: int = Field(
        0,
        description="Highest data sensitivity level detected (0–5)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT RESPONSE MODELS
# Replace the existing AuditResponse model in api/main.py with these.
# ─────────────────────────────────────────────────────────────────────────────
 
class AuditQueryResponse(BaseModel):
    records: List[dict]
    total: int = Field(..., description="Total matching records before pagination")
    limit: int
    offset: int
    filters: dict = Field(..., description="Filters applied — for audit of the audit")
    page: int = Field(..., description="Current page (1-based)")
    pages: int = Field(..., description="Total pages at this limit")
 
 
class AuditChainResponse(BaseModel):
    intact: bool = Field(
        ...,
        description="True if every record correctly links to its predecessor"
    )
    total: int = Field(..., description="Total records verified")
    gaps: int = Field(..., description="Number of chain breaks detected")
    gap_detail: List[dict] = Field(
        default_factory=list,
        description="Detail of each gap — record_id, expected hash, stored hash"
    )
    first_record_hash: Optional[str] = Field(
        None,
        description=(
            "SHA-256 hash of the genesis record. "
            "Publish this to allow independent verification that the chain "
            "started from a known, legitimate state."
        )
    )
 
 
class AuditSummaryResponse(BaseModel):
    total_records: int
    by_event_type: dict = Field(
        ...,
        description="Record count per event type, descending by count"
    )
    by_classification: dict = Field(
        ...,
        description="Record count per classification level with human-readable labels"
    )
    earliest_timestamp: Optional[str]
    latest_timestamp: Optional[str]
    chain_intact: bool
    chain_total: int
    chain_gaps: int
 
 
# ─────────────────────────────────────────────────────────────────────────────
# EXPANDED AUDIT ENDPOINTS
# Replace the existing get_audit() endpoint and add two new endpoints.
# ─────────────────────────────────────────────────────────────────────────────
 
@app.get(
    "/audit",
    response_model=AuditQueryResponse,
    tags=["Audit"],
    summary="Query the permanent audit trail with filters and pagination",
)
async def get_audit(
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    classification_min: int = 0,
    identity: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    order: str = "desc",
    auth: tuple = Depends(_require_session),
):
    """
    Query the permanent, append-only audit trail with composable filters.
 
    All parameters are optional. Combine any subset for targeted queries.
 
    ---
 
    ### Filters
 
    - **event_type** — exact match on event type string
      Examples: `CHECKPOINT`, `SESSION_START`, `SESSION_END`, `INTAKE`,
      `CRISIS`, `READ_ACCESS`, `SERVER_START`
 
    - **since** — ISO 8601 timestamp lower bound (inclusive)
      Example: `2026-01-01T00:00:00+00:00`
 
    - **until** — ISO 8601 timestamp upper bound (inclusive)
      Example: `2026-12-31T23:59:59+00:00`
 
    - **classification_min** — minimum sensitivity level (0–5, inclusive)
      `0` = all records | `2` = personal data and above | `3` = sensitive
 
    - **identity** — partial match on the human_decision / identity field
      Returns all records where this string appears in the decision field.
 
    - **search** — partial text search across `input` and `notes` fields
      Case-insensitive. May return records containing personal data —
      reads of classification ≥ 2 are automatically logged as READ_ACCESS
      events per U3 (read logging).
 
    ### Pagination
 
    Use `limit` and `offset` together. The response includes `total`
    (matching records before pagination) and `pages` so you can navigate.
 
    Example — page 3 of 20 records per page:
    ```
    GET /audit?limit=20&offset=40
    ```
 
    ### Sort order
 
    `order=desc` — newest first (default, useful for live monitoring)
    `order=asc`  — oldest first (useful for compliance review)
 
    ### Privacy
 
    Reads of records at classification level 2 or above generate a
    `READ_ACCESS` event in the audit trail. The audit of the audit
    is itself auditable.
    """
    _, new_token = auth
 
    try:
        result = memory.query(
            event_type=event_type,
            since=since,
            until=until,
            classification_min=classification_min,
            identity=identity,
            search=search,
            limit=limit,
            offset=offset,
            order=order,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Audit query failed: {type(exc).__name__}: {exc}",
        )
 
    total = result["total"]
    pages = max(1, (total + limit - 1) // limit) if total > 0 else 1
    page = (offset // limit) + 1 if limit > 0 else 1
 
    return JSONResponse(
        status_code=200,
        headers=_session_headers(new_token),
        content=AuditQueryResponse(
            records=result["records"],
            total=total,
            limit=result["limit"],
            offset=result["offset"],
            filters=result["filters"],
            page=page,
            pages=pages,
        ).model_dump(),
    )


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    session_active: bool
    principles_verified: bool


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMIT MIDDLEWARE
# ─────────────────────────────────────────────────────────────────────────────

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Apply the sliding window rate limiter to all endpoints except /health.
    Returns 429 with a clear reason and retry guidance when exceeded.
    Rate limit: configured via ONTO_RATE_LIMIT_PER_MINUTE (default 60/min).
    """
    if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
        return await call_next(request)

    allowed, reason = rate_limiter.check_and_record()
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": reason},
        )
    return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION DEPENDENCY
# ─────────────────────────────────────────────────────────────────────────────

async def _require_session(
    authorization: Optional[str] = Header(None),
) -> tuple:
    """
    FastAPI dependency that validates the Bearer token.
    Returns (session_record, new_token_or_none).

    The new token (from rotation) must be sent to the client
    in the X-Session-Token response header. Clients must use
    this token for all subsequent requests.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header required. Format: Bearer <token>",
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    session = session_manager.validate(raw_token)

    if session is None:
        raise HTTPException(
            status_code=401,
            detail=(
                "Session expired or invalid. "
                "Authenticate again via POST /auth."
            ),
        )

    # Rotate on every authenticated request — T-013 mitigation
    new_token = session_manager.rotate(raw_token)
    return session, new_token


def _session_headers(new_token) -> Dict[str, str]:
    """Build response headers containing the rotated session token."""
    return {"X-Session-Token": str(new_token) if new_token else ""}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _clean_record_ids(*ids) -> List[int]:
    """Filter out None and zero values from record ID lists."""
    return [i for i in ids if i and i > 0]


def _action_to_status(action: str) -> str:
    """Map a checkpoint action string to an API status string."""
    return {
        "PROCEED":         "complete",
        "AUTO_PROCEED":    "complete",
        "VETO":            "vetoed",
        "FLAG_FOR_REVIEW": "flagged",
        "DEFER":           "deferred",
        "CRISIS_FOLLOWUP": "crisis",
        "SAFETY_FOLLOWUP": "unsafe",
    }.get(action, "complete")


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Liveness check",
)
async def health():
    """
    Public endpoint. No authentication required.

    Returns current system status including whether principles are intact
    and whether a session is currently active. Safe to poll.
    """
    try:
        principles_ok = verify_principles()
    except SystemExit:
        principles_ok = False

    return HealthResponse(
        status="ok",
        version="1.0.0",
        environment=config.ENVIRONMENT,
        session_active=session_manager.is_active(),
        principles_verified=bool(principles_ok),
    )


@app.post(
    "/auth",
    response_model=AuthResponse,
    tags=["Authentication"],
    summary="Authenticate and receive session token",
    status_code=200,
)
async def authenticate(body: AuthRequest):
    """
    Authenticate with the system passphrase and receive a session token.

    The returned token must be presented in all subsequent requests:
    ```
    Authorization: Bearer <token>
    ```

    Tokens expire after `ONTO_SESSION_TTL_SECONDS` of inactivity (default 1 hour).
    Starting a new session supersedes any existing session — Stage 1 is single-user.

    Every successful authentication is recorded permanently in the audit trail.
    Every failed attempt is also recorded.
    """
    try:
        from core.auth import auth_manager
        result = auth_manager.authenticate(passphrase_input=body.passphrase)
    except Exception as exc:
        memory.record(
            event_type="AUTH_ERROR",
            notes=f"Authentication module error: {type(exc).__name__}",
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication module unavailable. "
                "Ensure the system has been initialized with a passphrase "
                "before using the API."
            ),
        )

    if not result.success:
        memory.record(
            event_type="AUTH_FAILURE",
            notes=result.reason,
        )
        raise HTTPException(status_code=401, detail=result.reason)

    identity = result.identity or body.identity
    token = session_manager.start(identity=identity)
    result.clear_passphrase()

    return AuthResponse(
        token=str(token),
        expires_at=token.expires_at,
        identity=identity,
    )


@app.post(
    "/process",
    response_model=ProcessResponse,
    tags=["Processing"],
    summary="Run the ONTO five-step processing loop",
)
async def process(
    body: ProcessRequest,
    auth: tuple = Depends(_require_session),
):
    """
    Run the full ONTO five-step loop on any input.

    ---

    ### Steps

    **Step 1 — RELATE: intake**
    Sanitizes the raw input, detects data classification (0–5),
    and checks for safety signals (CRISIS, HARM, INTEGRITY).

    **Step 2 — RELATE: contextualize**
    Places the input in the context of everything the system knows.
    Computes distance, weight, and a context summary.

    **Step 3 — NAVIGATE: surface**
    Examines the context and produces the display output.
    Confidence reflects how much context was available.

    **Step 4 — GOVERN: checkpoint**
    The human sovereignty gate. Required for high-weight or
    low-confidence inputs. CRISIS inputs always trigger this gate.

    **Step 5 — REMEMBER: memory**
    Every loop pass is committed permanently to the audit trail.

    ---

    ### Checkpoint Flow

    When `status` is `pending_checkpoint`:

    1. Present `display` to the human
    2. Collect their decision
    3. Re-submit with `human_decision`: `proceed` | `veto` | `flag` | `defer`

    ### CRISIS Protocol

    When `status` is `crisis`, the `display` field contains safe messaging
    text following AFSP/SAMHSA/WHO guidelines. The event is committed
    permanently regardless of the human's follow-up decision.

    Human wellbeing is the highest priority of this system.
    A CRISIS response is the system functioning correctly.
    """
    session, new_token = auth
    record_ids: List[int] = []

    # ── Step 1: RELATE — intake ───────────────────────────────────────────────
    try:
        package = intake.receive(body.input)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Intake failed: {type(exc).__name__}: {exc}",
        )

    if package.get("record_id"):
        record_ids.append(package["record_id"])

    # ── Step 2: RELATE — contextualize ───────────────────────────────────────
    try:
        enriched = contextualize.build(package)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Contextualize failed: {type(exc).__name__}: {exc}",
        )

    # ── Step 3: NAVIGATE — surface ────────────────────────────────────────────
    try:
        surfaced = surface.present(enriched)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Surface failed: {type(exc).__name__}: {exc}",
        )

    if surfaced.get("record_id"):
        record_ids.append(surfaced["record_id"])

    # Extract values used in checkpoint logic and response building
    display         = surfaced.get("display", "")
    confidence      = float(surfaced.get("confidence", 0.5))
    weight          = float(surfaced.get("weight", 0.5))
    safe            = bool(surfaced.get("safe", True))
    safety_info     = enriched.get("safety")
    safety_level    = safety_info.get("level")    if safety_info else None
    safety_message  = safety_info.get("message")  if safety_info else None
    classification  = int(enriched.get("classification", 0))

    # ── CRISIS: surface immediately, record permanently, never auto-proceed ───
    if safety_level == "CRISIS":
        crisis_record_id = memory.record(
            event_type="CHECKPOINT",
            input_data=body.input[:500],
            human_decision=body.human_decision or "NOT_PROVIDED",
            notes=(
                f"CRISIS signal detected via API. "
                f"Safe messaging displayed. "
                f"Operator: {session.identity}. "
                f"Client decision: {body.human_decision or 'none provided'}."
            ),
            classification=classification,
        )
        record_ids.append(crisis_record_id)

        return JSONResponse(
            status_code=200,
            headers=_session_headers(new_token),
            content=ProcessResponse(
                status="crisis",
                display=display,
                confidence=confidence,
                safe=False,
                safety_level="CRISIS",
                safety_message=safety_message,
                checkpoint=CheckpointInfo(
                    required=True,
                    skipped=False,
                    decision=body.human_decision,
                    options=["proceed", "veto"],
                ),
                record_ids=_clean_record_ids(*record_ids),
                classification=classification,
            ).model_dump(),
        )

    # ── Step 4: GOVERN — checkpoint ───────────────────────────────────────────
    #
    # Checkpoint is required when:
    #   - a non-CRISIS safety flag is present, OR
    #   - weight is high (consequential decision), OR
    #   - confidence is low (uncertain context)
    #
    # When required and no human_decision is provided:
    #   Return pending_checkpoint — client must re-submit with decision.
    #
    # When required and human_decision is provided:
    #   Inject the decision into the checkpoint via mock to avoid blocking
    #   on input(). The checkpoint still writes to the audit trail normally.

    needs_checkpoint = (
        not safe
        or weight   >= ALWAYS_ASK_WEIGHT
        or confidence <= ALWAYS_ASK_CONFIDENCE
    )

    if needs_checkpoint and body.human_decision is None:
        return JSONResponse(
            status_code=200,
            headers=_session_headers(new_token),
            content=ProcessResponse(
                status="pending_checkpoint",
                display=display,
                confidence=confidence,
                safe=safe,
                safety_level=safety_level,
                safety_message=safety_message,
                checkpoint=CheckpointInfo(
                    required=True,
                    skipped=False,
                    options=["proceed", "veto", "flag", "defer"],
                ),
                record_ids=_clean_record_ids(*record_ids),
                classification=classification,
            ).model_dump(),
        )

    # Human decision is available (or checkpoint not needed — auto-proceed).
    # Inject the decision so checkpoint.run() doesn't block on input().
    human_decision_value = body.human_decision or "proceed"

    def _api_decision(prompt: str, options=None, **kwargs) -> str:
        """
        Replaces checkpoint._ask_human() during API processing.
        Returns the client-provided decision rather than blocking
        on terminal input. The checkpoint still records everything normally.
        """
        return human_decision_value

    # Temporarily replace _ask_human so the checkpoint doesn't block
    # on terminal input() during API processing. Restored in finally.
    _orig_ask_human = checkpoint._ask_human
    checkpoint._ask_human = _api_decision
    try:
        checkpoint_result = checkpoint.run(surfaced, enriched)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Checkpoint failed: {type(exc).__name__}: {exc}",
        )
    finally:
        checkpoint._ask_human = _orig_ask_human

    if checkpoint_result.get("record_id"):
        record_ids.append(checkpoint_result["record_id"])

    action   = checkpoint_result.get("action", "VETO")
    decision = checkpoint_result.get("decision", human_decision_value)
    skipped  = bool(checkpoint_result.get("skipped", False))
    status   = _action_to_status(action)

    return JSONResponse(
        status_code=200,
        headers=_session_headers(new_token),
        content=ProcessResponse(
            status=status,
            display=display,
            confidence=confidence,
            safe=safe,
            safety_level=safety_level,
            safety_message=safety_message,
            checkpoint=CheckpointInfo(
                required=needs_checkpoint,
                skipped=skipped,
                decision=decision,
                action=action,
                record_id=checkpoint_result.get("record_id"),
            ),
            record_ids=_clean_record_ids(*record_ids),
            classification=classification,
        ).model_dump(),
    )


@app.get(
    "/audit",
    response_model=AuditResponse,
    tags=["Audit"],
    summary="Read the permanent audit trail",
)
@app.get(
    "/audit/chain",
    response_model=AuditChainResponse,
    tags=["Audit"],
    summary="Verify the cryptographic Merkle chain integrity of the audit trail",
)
async def get_audit_chain(
    auth: tuple = Depends(_require_session),
):
    """
    Verify the Merkle chain that links every audit record to its predecessor.
 
    Every record in the audit trail stores the SHA-256 hash of the previous
    record's content. This endpoint walks the entire chain, recomputes the
    expected hash at each step, and compares it to the stored value.
 
    **`intact: true`** — every record links correctly. The chain is unbroken.
 
    **`intact: false`** — one or more records have an incorrect chain_hash.
    This may indicate tampering, a gap from deletion, or a record written
    incorrectly due to a crash. The `gap_detail` field identifies exactly
    which record IDs are affected.
 
    The `first_record_hash` field is the SHA-256 hash of the genesis record —
    the first record ever written to this audit trail. If you publish this
    value publicly (for example, in the project Gist), any third party can
    verify that the chain started from a known legitimate state.
 
    This check is O(n) — it reads every record. On large databases it may
    take several seconds. Use `GET /audit/summary` for a fast chain status
    check in dashboards (it also returns `chain_intact` but with less detail).
    """
    _, new_token = auth
 
    try:
        result = memory.verify_chain()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Chain verification failed: {type(exc).__name__}: {exc}",
        )
 
    return JSONResponse(
        status_code=200,
        headers=_session_headers(new_token),
        content=AuditChainResponse(
            intact=result["intact"],
            total=result["total"],
            gaps=len(result["gaps"]),
            gap_detail=result["gaps"],
            first_record_hash=result["first_record_hash"],
        ).model_dump(),
    )
@app.get(
    "/audit/summary",
    response_model=AuditSummaryResponse,
    tags=["Audit"],
    summary="Aggregate statistics and chain status across the audit trail",
)
async def get_audit_summary(
    auth: tuple = Depends(_require_session),
):
    """
    Returns aggregate statistics across the entire audit trail.
 
    Designed for dashboards, health monitors, and compliance reports.
    Returns counts and distributions — no record content.
 
    **by_event_type** — record count per event type, descending.
    Shows what the system has been doing at a glance.
 
    **by_classification** — record count per sensitivity level.
    Shows how much personal or sensitive data has been processed.
    Useful for GDPR Article 30 records of processing activities.
 
    **chain_intact** — fast Merkle chain integrity flag.
    `true` = the audit trail is cryptographically unbroken.
    Use `GET /audit/chain` for full detail when this is `false`.
 
    This endpoint does not generate READ_ACCESS events — it returns
    only aggregate statistics, never record content.
    """
    _, new_token = auth
 
    try:
        result = memory.summarize()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Summary failed: {type(exc).__name__}: {exc}",
        )
 
    return JSONResponse(
        status_code=200,
        headers=_session_headers(new_token),
        content=AuditSummaryResponse(**result).model_dump(),
    )

@app.delete(
    "/session",
    tags=["Authentication"],
    summary="Logout — explicitly end the current session",
)
async def logout(auth: tuple = Depends(_require_session)):
    """
    Explicitly end the current session.

    The token is immediately invalidated. The SESSION_END event is
    committed permanently to the audit trail.

    GDPR Art. 5(1)(c): processing stops as soon as the purpose is achieved.
    Explicit logout ensures no session persists longer than intended.
    """
    session, _ = auth

    active = session_manager.active_session()
    if active:
        session_manager.terminate(active.token)

    return JSONResponse(
        status_code=200,
        content={
            "status": "logged_out",
            "identity": session.identity,
        },
    )
