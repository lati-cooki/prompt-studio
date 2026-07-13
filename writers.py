"""Writer identity registry — one DISTINCT custodial ThreadHub identity per studio
actor (DR-phase5-topology rule 5.2: semantic author = transport writer, never shared).

Custodial (rule 5.5): the hub holds the keys; this table stores only the minted id.
No key material ever lands here.

Minting is mint-first, insert-after: a crash between the hub POST and the local
INSERT leaves an orphan hub identity — harmless, disclosed, and healed by the next
ensure_writer call minting a fresh one.
"""
import seal

# Well-known studio writers. `studio` is the legacy shared author: it ADOPTS the
# id cached in .seal_author_id (via seal.ensure_author) instead of re-minting, so
# historical records and new ones cite the same identity.
WELL_KNOWN = {
    "operator": {"display_name": "Troy", "kind": "human"},
    "delegate": {"display_name": "Claude (delegate)", "kind": "agent"},
    "studio": {"display_name": "Prompt Studio", "kind": "agent"},
}

_COLS = ("name", "threadhub_id", "display_name", "kind", "custodial")


class WriterError(Exception):
    def __init__(self, message, status=422):
        self.message = message
        self.status = status
        super().__init__(message)


def ensure_table(conn):
    """Create the writers table if this DB predates slice 2. The server creates
    it at boot via schema.sql (keep the DDL there in sync with this); scripts
    hitting an older DB copy call this before resolving writers."""
    conn.execute("""CREATE TABLE IF NOT EXISTS writers (
        name TEXT PRIMARY KEY,
        threadhub_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        custodial INTEGER NOT NULL DEFAULT 1
    )""")
    conn.commit()


def _row_to_dict(row):
    if row is None:
        return None
    w = {col: row[i] for i, col in enumerate(_COLS)}
    w["custodial"] = bool(w["custodial"])
    return w


def get_writer(conn, name):
    """Lookup only — never talks to the hub, never mints. None when unknown."""
    row = conn.execute(
        "SELECT name, threadhub_id, display_name, kind, custodial FROM writers WHERE name=?",
        (name,)).fetchone()
    return _row_to_dict(row)


def ensure_writer(conn, name, display_name=None, kind=None, custodial=True):
    """Return the writer row for `name`, minting a custodial hub identity first
    if it does not exist yet (mint-first, insert-after). Idempotent."""
    existing = get_writer(conn, name)
    if existing:
        return existing
    defaults = WELL_KNOWN.get(name, {})
    display_name = display_name or defaults.get("display_name")
    kind = kind or defaults.get("kind")
    if not display_name or not kind:
        raise WriterError(
            f"unknown writer '{name}' — pass display_name and kind to mint it")
    if name == "studio":
        # Legacy adoption: reuse the cached shared-author id; mints only if the
        # cache never existed (same behaviour ensure_author always had).
        threadhub_id = seal.ensure_author()
    else:
        threadhub_id = seal._capture(
            seal._th("POST", "/identities",
                     {"display_name": display_name, "kind": kind}), "id")
    conn.execute(
        "INSERT INTO writers (name, threadhub_id, display_name, kind, custodial) "
        "VALUES (?,?,?,?,?)",
        (name, threadhub_id, display_name, kind, 1 if custodial else 0))
    conn.commit()
    return get_writer(conn, name)
