import hashlib
import hmac
import http.server
import mimetypes
import re
import os
import socketserver
import json
import logging
import sqlite3
import urllib.request
import urllib.error
import urllib.parse

def _load_dotenv(path=".env"):
    """Load key=value pairs from .env into os.environ (no-op if file absent)."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
    except FileNotFoundError:
        pass

# BEFORE the local imports: objections.py reads the front-door env
# (STUDIO_PUBLIC_MODE, STUDIO_OPERATOR_TOKEN, ...) at module top, so .env
# must already be in os.environ when it is imported.
_load_dotenv()

import anchors
import challenge
import objections
import seal
import promotion_store
import promotion_evidence
import promotion_seal
import writers

try:
    import anthropic
except ImportError:
    anthropic = None

DB_PATH = os.environ.get("DB_PATH", "prompt_studio.db")
EVALS_DIR = os.environ.get("EVALS_DIR")  # None -> promotion_evidence default
PORT = int(os.environ.get("PORT", 8000))
MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
THREADHUB_PORT = 8110


def is_safe_slug(slug):
    return bool(slug) and re.fullmatch(r'[A-Za-z0-9_-]+', slug) is not None

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')


def migrate_db(conn):
    """Migrate prompts table to composite (id, version) primary key if needed."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='prompts'"
    )
    row = cursor.fetchone()
    if not row:
        return  # table doesn't exist yet; schema.sql will create it
    if 'PRIMARY KEY (id, version)' in row[0]:
        return  # already migrated
    # Recreate table with composite PK
    conn.execute("BEGIN")
    try:
        conn.execute("""
            CREATE TABLE prompts_new (
                id TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT,
                tier TEXT,
                owner TEXT,
                body TEXT,
                use_case TEXT,
                cost_per_run_usd REAL,
                tokens_prompt_body INTEGER,
                default_model TEXT,
                eval_status TEXT,
                file TEXT,
                notes TEXT,
                composes TEXT,
                tested_on TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                PRIMARY KEY (id, version)
            )
        """)
        conn.execute("""
            INSERT INTO prompts_new (
                id, version, status, tier, owner, body, use_case,
                cost_per_run_usd, tokens_prompt_body, default_model, eval_status,
                file, notes, composes, tested_on, created_at, updated_at
            )
            SELECT
                id, version, status, tier, owner, body, use_case,
                cost_per_run_usd, tokens_prompt_body, default_model, eval_status,
                file, notes, composes, tested_on, created_at, updated_at
            FROM prompts
        """)
        conn.execute("DROP TABLE prompts")
        conn.execute("ALTER TABLE prompts_new RENAME TO prompts")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def migrate_actor_columns(conn):
    """Phase 5 slice 2 (writer identity everywhere): thread the acting writer
    through promotions and objections. Guarded pragma-table_info ALTERs —
    idempotent, and a no-op on DBs that don't have the tables yet (schema.sql
    creates them with these columns included). Pre-migration rows keep NULL:
    the historical actor is unknown, not backfilled."""
    def _cols(table):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

    additions = {
        "promotions": ("opened_by", "resolved_by"),
        "promotion_objections": ("author_writer", "resolved_by", "channel",
                                 "token_id", "sealed_record_hash"),
    }
    for table, wanted in additions.items():
        have = _cols(table)
        if not have:
            continue  # table doesn't exist yet; schema.sql will create it complete
        for col in wanted:
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
    conn.commit()


def migrate_sessions(conn):
    """Migrate sessions table from the old Flask schema (data TEXT) to the current schema
    (panes TEXT + vault_config TEXT).  Preserves existing session data."""
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'")
    row = cursor.fetchone()
    if not row:
        return
    sql = row[0]
    if 'vault_config' in sql:
        return  # already on current schema
    if 'data TEXT' not in sql and 'data' not in sql:
        return  # unknown schema — leave it alone

    # Read all existing sessions before dropping the table
    old_rows = conn.execute("SELECT * FROM sessions").fetchall()
    col_names = [d[0] for d in conn.execute("PRAGMA table_info(sessions)").fetchall()]

    conn.execute("BEGIN")
    try:
        conn.execute("DROP TABLE sessions")
        conn.execute("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                panes TEXT NOT NULL,
                vault_config TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions (created_at DESC)"
        )
        def iter_values():
            for row in old_rows:
                d = dict(zip(col_names, row))
                row_id   = str(d.get('id', ''))
                name     = d.get('name', 'Untitled')
                created  = str(d.get('created_at') or d.get('createdAt') or '')
                updated  = str(d.get('updated_at') or d.get('updatedAt') or created)
                # Old schema stored everything in a 'data' JSON blob
                raw_data = d.get('data') or d.get('panes') or '[]'
                try:
                    parsed = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                except Exception:
                    parsed = []
                try:
                    if isinstance(parsed, dict):
                        vault_cfg = json.dumps(parsed.get('vaultConfig') or parsed.get('vault') or {})
                        panes_val = json.dumps(parsed.get('panes', []))
                    else:
                        vault_cfg = '{}'
                        panes_val = json.dumps(parsed)
                except Exception:
                    continue
                if not row_id or not created:
                    continue
                yield (row_id, name, created, updated, panes_val, vault_cfg)

        conn.executemany(
            "INSERT OR IGNORE INTO sessions (id, name, created_at, updated_at, panes, vault_config) VALUES (?,?,?,?,?,?)",
            iter_values()
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _seed_prompts_from_index(conn):
    """Backfill prompts from registry/INDEX.json on every boot.

    INSERT OR IGNORE keyed on (id, version) makes this idempotent: rows the
    DB already has keep their live state (status flips from the promotion
    flow win); INDEX entries the DB lacks are added. Runs each startup so a
    table that diverged from the snapshot converges instead of staying stuck
    (an early guard skipped seeding entirely once the table was non-empty,
    which left this DB with 1 of 8 registry prompts)."""
    index_path = os.path.join(os.path.dirname(__file__), "registry", "INDEX.json")
    if not os.path.exists(index_path):
        return
    try:
        with open(index_path) as f:
            index = json.load(f)
    except Exception:
        return
    owner = index.get("owner", "")
    params = []
    for p in index.get("prompts", []):
        body = ""
        fpath = p.get("file")
        if fpath:
            full = os.path.join(os.path.dirname(__file__), "registry", fpath)
            try:
                with open(full) as bf:
                    body = bf.read()
            except FileNotFoundError:
                pass
        params.append((
            p.get("id"), p.get("version"), p.get("status"),
            p.get("tier"), owner, body, p.get("use_case"),
            p.get("cost_per_run_usd"), p.get("tokens_prompt_body"),
            p.get("default_model"), p.get("eval_status"),
            p.get("file"), p.get("notes"),
            json.dumps(p.get("composes", [])),
            json.dumps(p.get("tested_on", [])),
        ))

    if params:
        try:
            conn.executemany(
                """INSERT OR IGNORE INTO prompts
                   (id, version, status, tier, owner, body, use_case,
                    cost_per_run_usd, tokens_prompt_body, default_model,
                    eval_status, file, notes, composes, tested_on,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                   strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                   strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
                params
            )
            conn.commit()
        except Exception:
            pass


def init_db():
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    conn = sqlite3.connect(DB_PATH)
    try:
        migrate_sessions(conn)
        migrate_db(conn)
        migrate_actor_columns(conn)
        conn.executescript(schema)
        # Slice 6 (guarded, idempotent) — after schema.sql so the promotions
        # table fcp_tokens references exists first. Deliberately not IN
        # schema.sql: see objections.ensure_tokens_table.
        objections.ensure_tokens_table(conn)
        conn.commit()
        _seed_prompts_from_index(conn)
    finally:
        conn.close()

class PromptStudioHandler(http.server.SimpleHTTPRequestHandler):
    _anthropic_clients = {}
    def end_headers(self):
        request_origin = self.headers.get('Origin')
        allowed_origins = [
            o.strip()
            for o in os.environ.get('ALLOWED_ORIGIN', 'http://localhost:7777').split(',')
        ]

        origin_to_send = None
        if request_origin in allowed_origins or '*' in allowed_origins:
            origin_to_send = request_origin
        elif allowed_origins:
            origin_to_send = allowed_origins[0]

        if origin_to_send:
            self.send_header('Access-Control-Allow-Origin', origin_to_send)

        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    # ── Task 13: the front door ────────────────────────────────────────────
    # ONE dispatch-path gate: every verb handler (do_GET/do_POST/do_PUT/
    # do_DELETE/do_OPTIONS) enters through _front_door before any routing.
    # (do_HEAD is not gated: it already answers a uniform 404 for EVERY path
    # in every mode — no differential, no oracle.)

    @staticmethod
    def _skeptic_surface(method, path):
        """The ONLY surface a public deployment serves: the skeptic's
        objection page, filing endpoint and receipt/status route.

        Static assets: NONE, deliberately — objections.render_object_page is
        fully self-contained (inline CSS + inline JS, no /js/ imports), so
        the skeptic surface needs zero static files. Serving none keeps the
        public surface minimal and leaves no file-existence oracle."""
        if method == 'GET':
            return path.startswith('/object/')
        if method == 'POST':
            return path.startswith('/api/object/')
        return False

    def operator_authorized(self):
        """True when no STUDIO_OPERATOR_TOKEN is configured (localhost
        posture — current behavior), or when the request carries
        `Authorization: Bearer <token>` matching it. Comparison is
        constant-time over sha256 digests (hmac.compare_digest; hashing
        first makes the comparison length-independent too)."""
        expected = objections.OPERATOR_TOKEN
        if not expected:
            return True
        header = self.headers.get('Authorization') or ''
        supplied = header[len('Bearer '):] if header.startswith('Bearer ') else ''
        return hmac.compare_digest(
            hashlib.sha256(supplied.encode('utf-8')).digest(),
            hashlib.sha256(expected.encode('utf-8')).digest())

    def _send_unauthorized(self):
        body = b"unauthorized\n"
        self.send_response(401)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('WWW-Authenticate', 'Bearer')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _front_door(self, method, route):
        """The one public-mode + operator-auth gate on the dispatch path
        (Task 13).

        STUDIO_PUBLIC_MODE=1: every non-skeptic route — operator API, studio
        UI, static assets, unknown paths alike — answers the byte-identical
        generic 404 the token paths use. An outsider probing the front door
        cannot distinguish a walled-off route from a nonexistent one or from
        an invalid token (no route-existence oracle). The code being public
        means the route LIST is not a secret; reachability is the wall.

        Order matters: the public-mode wall runs FIRST, so on a public
        deployment an operator route 404s generically rather than 401ing —
        a 401 would be a route-existence oracle.

        Auth: when STUDIO_OPERATOR_TOKEN is set, every state-changing verb
        (POST/PUT/DELETE) outside the skeptic write surface (/api/object/*)
        requires the bearer token."""
        path = self.path.split('?', 1)[0]
        if objections.PUBLIC_MODE and not self._skeptic_surface(method, path):
            self._send_generic_404_page()
            return
        if (method in ('POST', 'PUT', 'DELETE')
                and not path.startswith('/api/object/')
                and not self.operator_authorized()):
            self._send_unauthorized()
            return
        route()

    def do_GET(self):
        self._front_door('GET', self._route_GET)

    def do_POST(self):
        self._front_door('POST', self._route_POST)

    def do_PUT(self):
        self._front_door('PUT', self._route_PUT)

    def do_DELETE(self):
        self._front_door('DELETE', self._route_DELETE)

    def do_OPTIONS(self):
        self._front_door('OPTIONS', self._route_OPTIONS)

    def _route_OPTIONS(self):
        self.send_response(200, "ok")
        self.end_headers()

    def get_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def send_raw_json(self, json_string, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json_string.encode('utf-8'))

    def proxy_threadhub_get(self, th_path):
        url = f"http://localhost:{THREADHUB_PORT}{th_path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            body = e.read()
            status = e.code
        except urllib.error.URLError:
            self.send_json(
                {"error": "ThreadHub is not reachable", "code": "threadhub_unreachable"},
                status=502,
            )
            return
        self.send_raw_json(body.decode('utf-8', errors='replace'), status=status)

    def handle_get_threads(self):
        self.proxy_threadhub_get("/threads")

    def _reject_bad_slug(self, slug):
        if not is_safe_slug(slug):
            self.send_error(400, "Invalid slug")
            return True
        return False

    def handle_get_thread(self, slug):
        if self._reject_bad_slug(slug):
            return
        self.proxy_threadhub_get(f"/t/{slug}.json")

    def handle_get_thread_verify(self, slug):
        if self._reject_bad_slug(slug):
            return
        self.proxy_threadhub_get(f"/t/{slug}/verify")

    def _route_GET(self):
        if self.path == '/api/sessions':
            self.handle_get_sessions()
        elif self.path == '/api/prompts':
            self.handle_get_prompts()
        elif self.path == '/api/registry':
            self.handle_get_registry()
        elif self.path.startswith('/registry-asset/'):
            rel = self.path[len('/registry-asset/'):]
            if '..' in rel or rel.startswith('/'):
                self.send_error(400)
                return
            self.serve_file('registry/' + rel)
        elif self.path.startswith('/api/challenge/'):
            self.handle_get_challenge(self.path.removeprefix('/api/challenge/').split('?', 1)[0])
        elif self.path == '/api/promotions':
            self.handle_get_promotions()
        elif self.path.split('?', 1)[0] == '/api/promotions/metrics':
            self.handle_get_promotion_metrics()
        elif self.path.startswith('/api/promotions/'):
            self.handle_get_promotion(self.path.removeprefix('/api/promotions/'))
        elif self.path == '/api/threads' or self.path.startswith('/api/threads?'):
            self.handle_get_threads()
        elif self.path.startswith('/api/threads/'):
            rest = self.path[len('/api/threads/'):].split('?', 1)[0]
            if rest.endswith('/verify'):
                self.handle_get_thread_verify(rest[:-len('/verify')])
            else:
                self.handle_get_thread(rest)
        elif self.path.startswith('/object/'):
            self.handle_object_get(self.path.removeprefix('/object/'))
        elif self.path in ('/', '/sandbox', '/sandbox/'):
            self.serve_sandbox_index()
        elif self.path in ('/registry', '/registry/'):
            self.serve_file('registry/interface/registry_widget.html', 'text/html')
        elif self.path in ('/threads', '/threads/'):
            self.serve_file('threads/interface/threads_widget.html', 'text/html')
        elif self.path.startswith('/js/'):
            # Only serve files from sandbox/js/
            js_path = self.path.removeprefix('/js/').lstrip('/')
            if not js_path:
                self.send_error(404)
                return
            self.serve_file(os.path.join('sandbox', 'js', js_path), 'application/javascript')
        else:
            self.send_error(404)

    def do_HEAD(self):
        self.send_error(404)

    def serve_sandbox_index(self):
        """Serve index.html with LM_STUDIO_URL injected from environment.

        Read fresh per request — this repo's dev loop is edit → reload with
        no build step, so caching the rendered page breaks it."""
        try:
            with open('sandbox/index.html', 'rb') as f:
                data = f.read()
            lm_url = os.environ.get('LM_STUDIO_URL', '')
            if lm_url:
                safe_lm_url = json.dumps(lm_url).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
                inject = f'<script>window.LM_STUDIO_URL={safe_lm_url};</script>'.encode()
                data = data.replace(b'<script type="module"', inject + b'<script type="module"', 1)

            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404)

    def serve_file(self, path, content_type=None):
        try:
            # Secure path resolution: ensure the path stays within allowed subdirectories
            base_dir = os.path.abspath(os.path.dirname(__file__))
            requested_path = os.path.abspath(os.path.join(base_dir, path))

            allowed_subdirs = [
                os.path.abspath(os.path.join(base_dir, 'sandbox')),
                os.path.abspath(os.path.join(base_dir, 'registry')),
                os.path.abspath(os.path.join(base_dir, 'threads'))
            ]

            try:
                if not any(os.path.commonpath([d, requested_path]) == d for d in allowed_subdirs):
                    self.send_error(404, f"File not found: {path}")
                    return
            except ValueError:
                self.send_error(404, f"File not found: {path}")
                return

            with open(requested_path, 'rb') as f:
                data = f.read()
            mime = content_type or mimetypes.guess_type(requested_path)[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            self.send_error(404, f"File not found: {path}")

    def _route_POST(self):
        if self.path == '/api/sessions':
            self.handle_post_sessions()
        elif self.path.startswith('/api/prompts/'):
            parts = self.path.removeprefix('/api/prompts/').split('/')
            if len(parts) == 2 and parts[1] == 'draft':
                self.handle_post_prompt_draft(parts[0])
            elif len(parts) == 3 and parts[2] == 'validate':
                self.handle_post_prompt_validate(parts[0], parts[1])
            elif len(parts) == 3 and parts[1] == 'promote':
                self.handle_post_promote(parts[0], parts[2])
            elif len(parts) == 3 and parts[1] == 'demote':
                self.handle_post_demote(parts[0], parts[2])
            else:
                self.send_error(404)
        elif self.path.startswith('/api/promotions/'):
            parts = self.path.removeprefix('/api/promotions/').split('/')
            if len(parts) == 2 and parts[1] in ('object', 'close', 'waive', 'abort', 'reseal'):
                self.handle_promotion_action(parts[0], parts[1])
            elif len(parts) == 2 and parts[1] == 'tokens':
                self.handle_token_mint(parts[0])
            elif len(parts) == 4 and parts[1] == 'tokens' and parts[3] == 'revoke':
                self.handle_token_revoke(parts[0], parts[2])
            elif len(parts) == 4 and parts[1] == 'objections' and parts[3] == 'resolve':
                self.handle_objection_resolve(parts[0], parts[2])
            else:
                self.send_error(404)
        elif self.path.startswith('/api/evals/'):
            parts = self.path.removeprefix('/api/evals/').split('/')
            if len(parts) == 2 and parts[1] == 'grade':
                self.handle_grade_eval(parts[0])
            else:
                self.send_error(404)
        elif self.path == '/api/prompts':
            self.handle_post_prompts()
        elif self.path == '/api/chat':
            self.handle_post_chat()
        elif self.path == '/api/challenge':
            self.handle_post_challenge()
        elif self.path == '/api/threads/seal':
            self.handle_seal()
        elif self.path.startswith('/api/object/'):
            self.handle_object_post(self.path.removeprefix('/api/object/'))
        else:
            self.send_error(404)

    def _route_PUT(self):
        if self.path.startswith('/api/sessions/'):
            session_id = self.path.split('/')[-1]
            self.handle_put_session(session_id)
        elif self.path.startswith('/api/prompts/'):
            prompt_id = self.path.split('/')[-1]
            self.handle_put_prompt(prompt_id)
        else:
            self.send_error(404)

    def _route_DELETE(self):
        if self.path.startswith('/api/sessions/'):
            session_id = self.path.split('/')[-1]
            self.handle_delete_session(session_id)
        elif self.path.startswith('/api/prompts/'):
            prompt_id = self.path.split('/')[-1]
            self.handle_delete_prompt(prompt_id)
        else:
            self.send_error(404)

    def read_json_body(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            return None
        if content_length > MAX_BODY_BYTES:
            self.send_error(413, "Request body too large")
            return None
        body = self.rfile.read(content_length)
        try:
            return json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "Invalid JSON")
            return None

    def handle_get_sessions(self):
        conn = self.get_db()
        try:
            cursor = conn.cursor()
            query = """
                SELECT json_group_array(
                    json_object(
                        'id', id,
                        'name', name,
                        'createdAt', created_at,
                        'updatedAt', updated_at,
                        'panes', json(panes),
                        'vaultConfig', json(vault_config)
                    )
                ) FROM (SELECT * FROM sessions ORDER BY created_at DESC)
            """
            cursor.execute(query)
            result = cursor.fetchone()[0]
        finally:
            conn.close()
        self.send_raw_json(result if result else "[]")

    def handle_post_sessions(self):
        data = self.read_json_body()
        if data is None:
            return
        required = ("id", "name", "createdAt", "updatedAt", "panes", "vaultConfig")
        if not all(k in data for k in required):
            self.send_error(400, "Missing required fields")
            return
        conn = self.get_db()
        try:
            cursor = conn.cursor()

            cursor.execute(
                "INSERT INTO sessions (id, name, created_at, updated_at, panes, vault_config) VALUES (?, ?, ?, ?, ?, ?)",
                (data["id"], data["name"], data["createdAt"], data["updatedAt"], json.dumps(data["panes"]), json.dumps(data["vaultConfig"]))
            )
            conn.commit()
        finally:
            conn.close()
        self.send_json({"status": "success"})

    def handle_delete_prompt(self, prompt_id):
        conn = self.get_db()
        try:
            cursor = conn.cursor()

            # Deletes all versions of this prompt ID intentionally
            cursor.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
            conn.commit()
            if cursor.rowcount == 0:
                self.send_error(404, "Prompt not found")
                return
        finally:
            conn.close()
        self.send_json({"status": "success"})

    def handle_put_prompt(self, prompt_id):
        data = self.read_json_body()
        if data is None:
            return
        version = data.get('version')
        if version is None:
            self.send_error(400, "version required")
            return
        if data.get('status') == 'production':
            conn = self.get_db()
            try:
                row = conn.execute("SELECT status FROM prompts WHERE id=? AND version=?",
                                   (prompt_id, version)).fetchone()
            finally:
                conn.close()
            if row is not None and row['status'] != 'production':
                self.send_json(
                    {"error": "status=production requires the promotion flow",
                     "use": f"POST /api/prompts/{prompt_id}/promote/{version}"},
                    status=409)
                return
        conn = self.get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE prompts SET
                   status=?, tier=?, owner=?, body=?, use_case=?,
                   cost_per_run_usd=?, tokens_prompt_body=?, default_model=?,
                   eval_status=?, file=?, notes=?, composes=?, tested_on=?,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                   WHERE id=? AND version=?""",
                (
                    data.get('status'), data.get('tier'), data.get('owner'),
                    data.get('body'), data.get('use_case'),
                    data.get('cost_per_run_usd'), data.get('tokens_prompt_body'),
                    data.get('default_model'), data.get('eval_status'),
                    data.get('file'), data.get('notes'),
                    data.get('composes'), data.get('tested_on'),
                    prompt_id, version,
                )
            )
            conn.commit()
            if cursor.rowcount == 0:
                self.send_error(404, "Prompt not found")
                return
        finally:
            conn.close()
        self.send_json({"status": "success"})

    def handle_put_session(self, session_id):
        data = self.read_json_body()
        if data is None:
            return
        conn = self.get_db()
        try:
            cursor = conn.cursor()

            fields = []
            params = []
            if "name" in data:
                fields.append("name = ?")
                params.append(data["name"])
            if "panes" in data:
                fields.append("panes = ?")
                params.append(json.dumps(data["panes"]))
            if "vaultConfig" in data:
                fields.append("vault_config = ?")
                params.append(json.dumps(data["vaultConfig"]))
            if "updatedAt" in data:
                fields.append("updated_at = ?")
                params.append(data["updatedAt"])

            if fields:
                query = f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?"
                params.append(session_id)
                cursor.execute(query, tuple(params))
                conn.commit()
                if cursor.rowcount == 0:
                    self.send_error(404, "Session not found")
                    return
        finally:
            conn.close()
        self.send_json({"status": "success"})

    def handle_delete_session(self, session_id):
        conn = self.get_db()
        try:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            if cursor.rowcount == 0:
                self.send_error(404, "Session not found")
                return
        finally:
            conn.close()
        self.send_json({"status": "success"})

    def handle_post_prompts(self):
        data = self.read_json_body()
        if data is None:
            return
        if data.get("status") == "production":
            self.send_json(
                {"error": "status=production requires the promotion flow",
                 "use": f"POST /api/prompts/{data.get('id')}/promote/{data.get('version')}"},
                status=409)
            return
        conn = self.get_db()
        try:
            cursor = conn.cursor()

            cursor.execute(
                """INSERT INTO prompts (
                    id, version, status, tier, owner, body, use_case,
                    cost_per_run_usd, tokens_prompt_body, default_model,
                    eval_status, file, notes, composes, tested_on,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("id"), data.get("version"), data.get("status"), data.get("tier"),
                    data.get("owner"), data.get("body"), data.get("useCase"),
                    data.get("costPerRunUsd"), data.get("tokensPromptBody"),
                    data.get("defaultModel"), data.get("evalStatus"), data.get("file"),
                    data.get("notes"), json.dumps(data.get("composes", [])),
                    json.dumps(data.get("testedOn", [])), data.get("createdAt"),
                    data.get("updatedAt")
                )
            )
            conn.commit()
        finally:
            conn.close()
        self.send_json({"status": "success"})

    def handle_post_prompt_draft(self, prompt_id):
        data = self.read_json_body()
        if data is None:
            return
        body = data.get('body', '')
        conn = self.get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT version FROM prompts WHERE id=?
                   ORDER BY
                     CAST(SUBSTR(version, 1, INSTR(version,'.')-1) AS INTEGER) DESC,
                     CAST(SUBSTR(version, INSTR(version,'.')+1,
                       INSTR(SUBSTR(version, INSTR(version,'.')+1), '.')-1) AS INTEGER) DESC,
                     CAST(SUBSTR(version,
                       INSTR(version,'.')+1 + INSTR(SUBSTR(version, INSTR(version,'.')+1), '.'))
                       AS INTEGER) DESC
                   LIMIT 1""",
                (prompt_id,)
            )
            rows = cursor.fetchall()
            if rows:
                parts = rows[0][0].split('.')
                new_version = f"{parts[0]}.{int(parts[1]) + 1}.0"
            else:
                new_version = "1.0.0"
            cursor.execute(
                """INSERT INTO prompts (id, version, status, body,
                   created_at, updated_at)
                   VALUES (?, ?, 'draft', ?,
                   strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                   strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                   ON CONFLICT(id, version) DO UPDATE SET
                   body=excluded.body,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
                (prompt_id, new_version, body)
            )
            conn.commit()
        finally:
            conn.close()
        self.send_json({"status": "draft", "id": prompt_id, "version": new_version})

    def handle_post_prompt_validate(self, prompt_id, version):
        # Phase 4: direct production flips are retired — promotion goes through the FCP flow.
        self.send_json(
            {"error": "direct validation retired",
             "use": f"POST /api/prompts/{prompt_id}/promote/{version}"},
            status=409)

    def _promotion_error(self, e):
        self.send_json({"error": e.message}, status=e.status)

    def _decided_by(self, conn, prompt_id, version):
        row = conn.execute("SELECT owner FROM prompts WHERE id=? AND version=?",
                           (prompt_id, version)).fetchone()
        return (row["owner"] if row and row["owner"] else "Prompt Studio owner")

    def _writers_for_promotion(self, conn, promotion):
        """Resolve the per-record writer mapping for a promotion seal
        (DR-phase5-topology 5.2: evidence author = grader, default = operator).

        DB-lookup-only — the request path never mints identities. Until the
        operator writer has been provisioned (writers.ensure_writer, run
        deliberately, not mid-request), returns (None, legacy decidedBy) so the
        seal falls back to the shared studio author instead of failing."""
        operator = writers.get_writer(conn, "operator")
        if operator is None:
            return None, self._decided_by(
                conn, promotion["prompt_id"], promotion["version"])

        def _required(name, role):
            # Fail-closed per the silent-action DR ("systems that cannot write
            # at action time must fail the action rather than act unwitnessed"):
            # a NAMED actor that cannot be resolved to a provisioned writer must
            # fail the seal — a seal that misattributes their record to the
            # operator is worse than a seal_error (DR 5.2: semantic author =
            # transport writer). _seal_promotion turns this raise into recorded
            # seal_error bookkeeping; reseal recovers once the writer is
            # provisioned. Slice 6 MUST provision objector writers before
            # sealing — this guard makes that a hard requirement, not a
            # convention. Only a NULL/absent actor may use the default author.
            w = writers.get_writer(conn, name)
            if w is None:
                raise writers.WriterError(
                    f"{role} '{name}' is not a provisioned writer — refusing to "
                    "seal misattributed (fail-closed); provision it via "
                    "writers.ensure_writer, then reseal")
            return w

        resolved_by = promotion.get("resolved_by")
        decider = _required(resolved_by, "deciding writer") if resolved_by else operator
        writer_map = {"default": operator["threadhub_id"],
                      "claim": decider["threadhub_id"]}
        evidence = promotion.get("evidence")
        if isinstance(evidence, dict) and evidence.get("graded_by"):
            grader = writers.get_writer(conn, evidence["graded_by"])
            if grader:  # unknown grader -> default author, absence not faked
                writer_map["evidence"] = grader["threadhub_id"]
        objection_ids = []
        for o in promotion.get("objections", []):
            name = o.get("author_writer")
            ow = _required(name, "objection author") if name else operator
            objection_ids.append(ow["threadhub_id"])
        if objection_ids:
            writer_map["objections"] = objection_ids
        return writer_map, decider

    def _seal_promotion(self, conn, promotion, outcome):
        """Seal a terminal promotion; never raises — failure is recorded, not fatal.
        Payload construction lives inside the try too: malformed stored evidence
        (or anything else about this promotion) must record a seal_error, never
        crash the request or leave the promotion permanently unresealable.

        After a successful seal the thread head is anchored (anchors.anchor_seal,
        DR-phase5-topology Decision 4) and the anchored/anchor_error/
        anchor_pushed/anchor_push_error fields ride on the response. Anchoring
        happens OUTSIDE the try: anchor_seal never raises by contract, and an
        anchoring failure must never be recorded as a seal_error — the seal
        exists in the hub regardless (rule 2.1).

        Slice 6: when the seal return carries the extended per-record list,
        each objection's sealed_record_hash is back-filled from the n-th
        ObjectionRaised record (count-asserted: a mismatch is recorded as a
        seal_error with NO partial back-fill — see
        objections.backfill_sealed_records). A legacy return without
        'records' skips back-fill; those receipts simply stay at 'filed'."""
        try:
            writer_map, decided_by = self._writers_for_promotion(conn, promotion)
            payload = promotion_seal.build_seal_payload(promotion, outcome, decided_by)
            result = seal.seal_decision(payload, writers=writer_map)
            if "records" in result:
                objections.backfill_sealed_records(
                    conn, promotion, result["records"], slug=result.get("slug"))
            p = promotion_store.mark_seal_result(
                conn, promotion["id"], slug=result["slug"],
                citation_hash=result.get("citationHash"))
        except Exception as e:
            # FIRST: discard any uncommitted work from the failed attempt —
            # a mid-loop back-fill failure leaves earlier UPDATEs pending on
            # this conn, and mark_seal_result ends in conn.commit(), which
            # would otherwise smuggle a PARTIAL back-fill in beside the error
            # bookkeeping (the count assertion only guards the mismatch mode).
            conn.rollback()
            msg = getattr(e, "message", None) or str(e)
            return promotion_store.mark_seal_result(conn, promotion["id"], error=msg)
        p.update(anchors.anchor_seal(result["slug"]))
        return p

    def handle_post_promote(self, prompt_id, version):
        data = self.read_json_body()
        if data is None:
            return
        if "evidence" in data:
            evidence = data["evidence"]
            if evidence is not None and (
                not isinstance(evidence, dict)
                or "source_file" not in evidence
                or "content_hash" not in evidence
            ):
                self.send_json(
                    {"error": "evidence must include source_file and content_hash"},
                    status=422)
                return
            # evidence is either a valid dict or an explicit None (disclosed absence
            # — do NOT auto-pin in that case).
        else:
            evidence = promotion_evidence.pin_evidence(prompt_id, version)
        try:
            window_hours = float(data.get("window_hours", 24))
        except (TypeError, ValueError):
            self.send_json({"error": "window_hours must be numeric"}, status=422)
            return
        conn = self.get_db()
        try:
            try:
                p = promotion_store.open_promotion(
                    conn, prompt_id, version,
                    window_hours=window_hours, evidence=evidence)
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
                return
        finally:
            conn.close()
        self.send_json(p, status=200)

    def handle_get_promotions(self):
        conn = self.get_db()
        try:
            self.send_json(promotion_store.list_promotions(conn))
        finally:
            conn.close()

    def handle_get_promotion_metrics(self):
        """GET /api/promotions/metrics?window=<days> — Slice 5 waive-ratio
        metrics (DR-2026-07-12-fcp-metrics). window is a whole number of
        days; absent means all-time."""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        raw = query.get("window", [None])[0]
        window_days = None
        if raw is not None:
            try:
                window_days = int(raw)
            except ValueError:
                self.send_json({"error": "window must be a whole number of days"},
                               status=422)
                return
            if window_days <= 0:
                self.send_json({"error": "window must be a positive number of days"},
                               status=422)
                return
        conn = self.get_db()
        try:
            self.send_json(promotion_store.metrics(conn, window_days))
        finally:
            conn.close()

    def handle_get_promotion(self, pid):
        conn = self.get_db()
        try:
            try:
                self.send_json(promotion_store.get_promotion(conn, pid))
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
        finally:
            conn.close()

    def handle_promotion_action(self, pid, action):
        data = self.read_json_body() if action in ('object', 'waive') else {}
        if data is None:
            return
        conn = self.get_db()
        try:
            try:
                if action == 'object':
                    self.send_json(promotion_store.add_objection(conn, pid, data.get("body")))
                    return
                if action == 'close':
                    p = promotion_store.close_promotion(conn, pid)
                    self.send_json(self._seal_promotion(conn, p, "promoted"))
                    return
                if action == 'waive':
                    p = promotion_store.waive_promotion(conn, pid, data.get("reason"))
                    self.send_json(self._seal_promotion(conn, p, "promoted"))
                    return
                if action == 'abort':
                    p = promotion_store.abort_promotion(conn, pid)
                    self.send_json(self._seal_promotion(conn, p, "aborted"))
                    return
                if action == 'reseal':
                    p = promotion_store.get_promotion(conn, pid)
                    if p["state"] == "open":
                        self.send_json({"error": "promotion still open"}, status=409)
                        return
                    if p["sealed"]:
                        self.send_json(p)  # idempotent
                        return
                    outcome = "aborted" if p["state"] == "aborted" else "promoted"
                    self.send_json(self._seal_promotion(conn, p, outcome))
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
        finally:
            conn.close()

    def handle_objection_resolve(self, pid, oid):
        data = self.read_json_body()
        if data is None:
            return
        conn = self.get_db()
        try:
            try:
                p = promotion_store.resolve_objection(
                    conn, pid, oid, data.get("resolution"), data.get("body"))
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
                return
            if p["state"] == "aborted":  # upheld objection forced the abort — seal it
                p = self._seal_promotion(conn, p, "aborted")
            self.send_json(p)
        finally:
            conn.close()

    # -- Slice 6: the public /object/* surface -----------------------------

    def _send_generic_404_page(self):
        """The ONE page every /object/* validation failure gets — identical
        bytes whether the token is unknown, revoked, exhausted, expired, or
        its promotion closed (no oracle)."""
        body = objections.GENERIC_404_HTML.encode('utf-8')
        self.send_response(404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_object_get(self, rest):
        parts = [urllib.parse.unquote(p) for p in rest.split('?', 1)[0].split('/')]
        if len(parts) == 1 and parts[0]:
            self.handle_object_page(parts[0])
        elif len(parts) == 3 and parts[1] == 'status':
            self.handle_object_status(parts[0], parts[2])
        else:
            self._send_generic_404_page()

    def handle_object_page(self, raw):
        """GET /object/<token> — the standalone objection page (no studio
        shell; server-rendered string template, user-derived strings all
        escaped in objections.render_object_page)."""
        conn = self.get_db()
        try:
            try:
                token, promotion = objections.validate_token(conn, raw)
            except objections.TokenInvalid:
                self._send_generic_404_page()
                return
        finally:
            conn.close()
        body = objections.render_object_page(promotion, token, raw).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_object_status(self, raw, oid):
        conn = self.get_db()
        try:
            try:
                self.send_json(objections.objection_status(conn, raw, oid))
            except objections.TokenInvalid:
                self.send_json(objections.GENERIC_404_JSON, status=404)
        finally:
            conn.close()

    def handle_object_post(self, token):
        """POST /api/object/<token> {body, contact, label?} — file the
        objection. Rate-limited per IP (objections.allow_request) — the
        ONLY rate-limited surface, per the plan: /api/object/* only."""
        ip = self.client_address[0] if getattr(self, 'client_address', None) else '?'
        if not objections.allow_request(ip):
            self.send_json({"error": "rate limited — try again shortly"},
                           status=429)
            return
        data = self.read_json_body()
        if data is None:
            return
        conn = self.get_db()
        try:
            try:
                receipt = objections.file_objection(
                    conn, urllib.parse.unquote(token.split('?', 1)[0]),
                    data.get("body"), data.get("contact"),
                    label=data.get("label"))
            except objections.TokenInvalid:
                self.send_json(objections.GENERIC_404_JSON, status=404)
                return
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
                return
            except writers.WriterError as e:
                self.send_json({"error": e.message}, status=e.status)
                return
            except seal.SealError as e:
                body = {"error": e.message}
                body.update(e.extra)
                self.send_json(body, status=e.status)
                return
        finally:
            conn.close()
        self.send_json(receipt)

    def handle_token_mint(self, pid):
        """POST /api/promotions/<pid>/tokens {invitee_label?, use_limit?} —
        mint an objection token (Slice 6). The raw token appears ONCE, in
        this response; only its hash is stored. Refuses 409 when the
        operator writer is unprovisioned (see objections.mint_token).
        "Operator-only" is enforced bearer auth when STUDIO_OPERATOR_TOKEN
        is set (_front_door), deployment posture (localhost) otherwise —
        objections.posture_note() derives the honest disclosure from live
        config and rides on the response."""
        data = self.read_json_body()
        if data is None:
            return
        conn = self.get_db()
        try:
            try:
                minted = objections.mint_token(
                    conn, pid,
                    invitee_label=data.get("invitee_label"),
                    use_limit=data.get("use_limit", 1))
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
                return
        finally:
            conn.close()
        # Share URL from CONFIG, never the Host header (a client-controlled
        # Host must not steer where an invitation points): STUDIO_PUBLIC_BASE_URL
        # when configured, the local bind otherwise.
        base = objections.PUBLIC_BASE_URL or f"http://localhost:{PORT}"
        minted["url"] = f"{base}{minted.pop('url_path')}"
        self.send_json(minted)

    def handle_token_revoke(self, pid, token_id):
        conn = self.get_db()
        try:
            try:
                self.send_json(objections.revoke_token(conn, pid, token_id))
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
        finally:
            conn.close()

    def handle_grade_eval(self, eval_id):
        """POST /api/evals/<eval_id>/grade {grade, notes, writer} — grading is
        an act with an actor. The writer name is resolved (minting its custodial
        identity if this is its first act) BEFORE anything is stamped."""
        if not is_safe_slug(eval_id):
            self.send_error(400, "Invalid eval id")
            return
        data = self.read_json_body()
        if data is None:
            return
        grade = (data.get("grade") or "").strip()
        if not grade:
            self.send_json({"error": "grade required"}, status=422)
            return
        writer_name = (data.get("writer") or "operator").strip()
        conn = self.get_db()
        try:
            writer = writers.ensure_writer(conn, writer_name)
        except writers.WriterError as e:
            self.send_json({"error": e.message}, status=e.status)
            return
        except seal.SealError as e:
            body = {"error": e.message}
            body.update(e.extra)
            self.send_json(body, status=e.status)
            return
        finally:
            conn.close()
        try:
            result = promotion_evidence.grade_eval(
                eval_id, grade, data.get("notes"), writer["name"], evals_dir=EVALS_DIR)
        except promotion_evidence.GradeError as e:
            self.send_json({"error": e.message}, status=e.status)
            return
        self.send_json(result, status=200)

    def handle_post_demote(self, prompt_id, version):
        data = self.read_json_body()
        if data is None:
            return
        reason = (data.get("reason") or "").strip()
        if not reason:
            self.send_json({"error": "reason required"}, status=422)
            return
        conn = self.get_db()
        try:
            row = conn.execute("SELECT status FROM prompts WHERE id=? AND version=?",
                               (prompt_id, version)).fetchone()
            if row is None:
                self.send_error(404, "Prompt not found")
                return
            if row["status"] != "production":
                self.send_json(
                    {"error": "only production prompts can be deprecated",
                     "status": row["status"]},
                    status=409)
                return
            slug_row = conn.execute(
                """SELECT thread_slug FROM promotions WHERE prompt_id=? AND version=?
                   AND thread_slug IS NOT NULL ORDER BY id DESC LIMIT 1""",
                (prompt_id, version)).fetchone()
            superseded = slug_row["thread_slug"] if slug_row else None
            conn.execute(
                """UPDATE prompts SET status='deprecated',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=? AND version=?""",
                (prompt_id, version))
            conn.commit()
            payload = promotion_seal.build_demotion_payload(
                prompt_id, version, reason,
                self._decided_by(conn, prompt_id, version), superseded_slug=superseded)
            try:
                result = seal.seal_decision(payload)
            except (seal.SealError, seal.SealValidationError) as e:
                msg = getattr(e, "message", None) or str(e)
                self.send_json({"status": "deprecated", "sealed": False, "seal_error": msg})
            else:
                anchor = anchors.anchor_seal(result["slug"])
                self.send_json({"status": "deprecated", "sealed": True,
                                **result, **anchor})
        finally:
            conn.close()

    # OpenAI-compatible provider config: provider → (base_url, env_var)
    _OPENAI_COMPAT = {
        "openai": ("https://api.openai.com/v1/chat/completions",                                      "OPENAI_API_KEY"),
        "xai":    ("https://api.x.ai/v1/chat/completions",                                            "XAI_API_KEY"),
        "google": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",        "GEMINI_API_KEY"),
    }

    def handle_post_chat(self):
        data = self.read_json_body()
        if data is None:
            return

        model_id = data.get('model', '')
        if not model_id:
            self.send_json({"error": "model required"}, status=400)
            return

        provider = data.get('provider', 'anthropic')

        if provider == 'anthropic':
            self._stream_anthropic(model_id, data.get('messages', []))
        elif provider in self._OPENAI_COMPAT:
            endpoint_url, env_var = self._OPENAI_COMPAT[provider]
            api_key = os.environ.get(env_var)
            if not api_key:
                self.send_json({"error": f"{env_var} not configured"}, status=503)
                return
            self._stream_openai_compat(endpoint_url, api_key, model_id, data.get('messages', []))
        else:
            self.send_json({"error": f"Unknown provider: {provider}"}, status=400)

    def _stream_anthropic(self, model_id, messages):
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            self.send_json({"error": "ANTHROPIC_API_KEY not configured"}, status=503)
            return
        if anthropic is None:
            self.send_json({"error": "anthropic package not installed"}, status=503)
            return

        system_msgs = [m for m in messages if m.get('role') == 'system']
        user_msgs   = [m for m in messages if m.get('role') != 'system']
        system = "\n\n".join(m['content'] for m in system_msgs) if system_msgs else ''

        if api_key not in self._anthropic_clients:
            self._anthropic_clients[api_key] = anthropic.Anthropic(api_key=api_key)
        client = self._anthropic_clients[api_key]

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

        try:
            with client.messages.stream(
                model=model_id,
                max_tokens=8096,
                system=system,
                messages=user_msgs,
            ) as stream:
                for text in stream.text_stream:
                    chunk = json.dumps({"choices": [{"delta": {"content": text}}]})
                    self.wfile.write(f"data: {chunk}\n\n".encode())
                    self.wfile.flush()
                msg = stream.get_final_message()
                usage_chunk = json.dumps({
                    "choices": [{"delta": {}}],
                    "usage": {
                        "prompt_tokens": msg.usage.input_tokens,
                        "completion_tokens": msg.usage.output_tokens,
                    }
                })
                self.wfile.write(f"data: {usage_chunk}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
        except Exception as err:
            logging.error("Anthropic stream error", exc_info=True)
            error_chunk = json.dumps({"error": "An internal error occurred."})
            self.wfile.write(f"data: {error_chunk}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    def _stream_openai_compat(self, endpoint_url, api_key, model_id, messages):
        """Proxy an OpenAI-compatible streaming request. Response is already OpenAI SSE
        format so it can be piped directly to the client without translation."""
        payload = json.dumps({
            "model":      model_id,
            "messages":   messages,
            "stream":     True,
            "max_tokens": 8096,
        }).encode()

        req = urllib.request.Request(endpoint_url, data=payload, method='POST')
        req.add_header('Content-Type',  'application/json')
        req.add_header('Authorization', f'Bearer {api_key}')

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

        try:
            with urllib.request.urlopen(req) as response:
                while True:
                    chunk = response.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as err:
            body = err.read().decode('utf-8', errors='replace')
            try:
                msg = json.loads(body).get('error', {}).get('message', body)
            except Exception:
                msg = body[:200]
            error_chunk = json.dumps({"error": msg})
            self.wfile.write(f"data: {error_chunk}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except Exception as err:
            logging.error("OpenAI-compat stream error", exc_info=True)
            error_chunk = json.dumps({"error": "An internal error occurred."})
            self.wfile.write(f"data: {error_chunk}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    # ── Slice 7: the Challenge Run (challenge.py owns the orchestration) ──

    def handle_post_challenge(self):
        """POST /api/challenge — validate fail-closed (only production prompts
        with a sealed promotion thread are eligible as role system prompts;
        anything else is a 409, never inlined silently), then spawn the run on
        a daemon worker thread and return {job_id} immediately. This handler
        stays quick — the single-threaded TCPServer must never wait on a model
        call; the UI polls GET /api/challenge/<job_id>."""
        data = self.read_json_body()
        if data is None:
            return
        conn = self.get_db()
        try:
            try:
                cfg = challenge.validate_request(conn, data)
            except challenge.ChallengeError as e:
                body = {"error": e.message}
                body.update(e.extra)
                self.send_json(body, status=e.status)
                return
        finally:
            conn.close()
        job_id = challenge.start_job(cfg)
        self.send_json({"job_id": job_id}, status=202)

    def handle_get_challenge(self, rest):
        """GET /api/challenge/demo — the built-in fraud-threshold scenario.
        GET /api/challenge/<job_id> — the polled job snapshot (status, stage,
        event stream including any GateRejectionRecorded, result, error)."""
        if rest == 'demo':
            self.send_json({
                "scenario": challenge.DEMO_SCENARIO,
                "source": challenge.DEMO_SCENARIO_SOURCE,
                "defaults": {
                    "provider": challenge.DEFAULT_PROVIDER,
                    "model": challenge.DEFAULT_MODEL,
                    "rounds": challenge.DEFAULT_ROUNDS,
                    "max_rounds": challenge.MAX_ROUNDS,
                },
            })
            return
        snapshot = challenge.get_job(rest)
        if snapshot is None:
            self.send_json({"error": "unknown challenge job"}, status=404)
            return
        self.send_json(snapshot)

    def handle_seal(self):
        data = self.read_json_body()
        if data is None:
            return
        try:
            result = seal.seal_decision(data)
        except seal.SealValidationError as e:
            self.send_json({"error": "validation failed", "fields": e.fields}, status=400)
            return
        except seal.SealError as e:
            body = {"error": e.message}
            body.update(e.extra)
            self.send_json(body, status=e.status)
            return
        # Seal is not done until the anchor commit exists or the failure is
        # loudly reported (anchored/anchor_error — same pattern as
        # sealed/seal_error). anchor_seal never raises; failure never unwinds
        # the seal — the hub record already exists.
        result.update(anchors.anchor_seal(result["slug"]))
        self.send_json(result, status=200)

    def handle_get_registry(self):
        """Live registry view — the DB is the source of truth for prompt state.

        Serves the INDEX.json shape (the widget/picker contract) built from the
        prompts table, so status flips from the promotion FCP flow appear
        immediately instead of lagging the static snapshot. Header metadata
        (registry_version, owner, evals, open_questions) still comes from
        INDEX.json; generated_at becomes the newest DB updated_at."""
        conn = self.get_db()
        try:
            rows = conn.execute(
                """SELECT id, version, status, tier, use_case, cost_per_run_usd,
                          tokens_prompt_body, default_model, eval_status, file,
                          notes, composes, tested_on, updated_at
                   FROM prompts ORDER BY id, version"""
            ).fetchall()
        finally:
            conn.close()
        prompts = []
        latest = None
        for row in rows:
            entry = dict(row)
            for key in ("composes", "tested_on"):
                try:
                    entry[key] = json.loads(entry[key]) if entry[key] else []
                except (ValueError, TypeError):
                    entry[key] = []
            updated = entry.pop("updated_at", None)
            if updated and (latest is None or updated > latest):
                latest = updated
            prompts.append(entry)
        meta = {"registry_version": "?"}
        try:
            index_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "registry", "INDEX.json")
            with open(index_path) as f:
                idx = json.load(f)
            for key in ("registry_version", "owner", "owner_entity", "evals", "open_questions"):
                if key in idx:
                    meta[key] = idx[key]
        except (OSError, ValueError):
            pass
        self.send_json({**meta, "generated_at": latest, "source": "live-db",
                        "prompts": prompts})

    def handle_get_prompts(self):
        conn = self.get_db()
        try:
            cursor = conn.cursor()
            query = """
                SELECT json_group_array(
                    json_object(
                        'id', id,
                        'version', version,
                        'status', status,
                        'tier', tier,
                        'owner', owner,
                        'body', body,
                        'useCase', use_case,
                        'costPerRunUsd', cost_per_run_usd,
                        'tokensPromptBody', tokens_prompt_body,
                        'defaultModel', default_model,
                        'evalStatus', eval_status,
                        'file', file,
                        'notes', notes,
                        'composes', json(CASE WHEN composes IS NOT NULL AND composes != '' THEN composes ELSE '[]' END),
                        'testedOn', json(CASE WHEN tested_on IS NOT NULL AND tested_on != '' THEN tested_on ELSE '[]' END),
                        'createdAt', created_at,
                        'updatedAt', updated_at
                    )
                ) FROM prompts
            """
            cursor.execute(query)
            result = cursor.fetchone()[0]
        finally:
            conn.close()
        self.send_raw_json(result if result else "[]")

if __name__ == '__main__':
    init_db()
    with socketserver.TCPServer(("", PORT), PromptStudioHandler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()
