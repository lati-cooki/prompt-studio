import http.server
import mimetypes
import os
import socketserver
import json
import sqlite3

try:
    import anthropic
except ImportError:
    anthropic = None

DB_PATH = 'prompt_studio.db'
PORT = 8000
MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
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


def init_db():
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    conn = sqlite3.connect(DB_PATH)
    try:
        migrate_db(conn)
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()

class PromptStudioHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
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

    def do_GET(self):
        if self.path == '/api/sessions':
            self.handle_get_sessions()
        elif self.path == '/api/prompts':
            self.handle_get_prompts()
        elif self.path in ('/', '/sandbox', '/sandbox/'):
            self.serve_file('sandbox/index.html', 'text/html')
        elif self.path in ('/registry', '/registry/'):
            self.serve_file('registry/interface/registry_widget.html', 'text/html')
        elif self.path.startswith('/js/'):
            self.serve_file('sandbox' + self.path, 'application/javascript')
        else:
            self.send_error(404)

    def do_HEAD(self):
        self.send_error(404)

    def serve_file(self, path, content_type=None):
        try:
            with open(path, 'rb') as f:
                data = f.read()
            mime = content_type or mimetypes.guess_type(path)[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404, f"File not found: {path}")

    def do_POST(self):
        if self.path == '/api/sessions':
            self.handle_post_sessions()
        elif self.path.startswith('/api/prompts/'):
            parts = self.path.removeprefix('/api/prompts/').split('/')
            if len(parts) == 2 and parts[1] == 'draft':
                self.handle_post_prompt_draft(parts[0])
            elif len(parts) == 3 and parts[2] == 'validate':
                self.handle_post_prompt_validate(parts[0], parts[1])
            else:
                self.send_error(404)
        elif self.path == '/api/prompts':
            self.handle_post_prompts()
        elif self.path == '/api/chat':
            self.handle_post_chat()
        else:
            self.send_error(404)

    def do_PUT(self):
        if self.path.startswith('/api/sessions/'):
            session_id = self.path.split('/')[-1]
            self.handle_put_session(session_id)
        elif self.path.startswith('/api/prompts/'):
            prompt_id = self.path.split('/')[-1]
            self.handle_put_prompt(prompt_id)
        else:
            self.send_error(404)

    def do_DELETE(self):
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
                "SELECT version FROM prompts WHERE id=? ORDER BY version DESC",
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
        conn = self.get_db()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE prompts SET status='production', eval_status='validated',
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE id=? AND version=?""",
            (prompt_id, version)
        )
        conn.commit()
        if cursor.rowcount == 0:
            self.send_error(404, "Prompt not found")
            return
        self.send_json({"status": "validated", "id": prompt_id, "version": version})

    def handle_post_chat(self):
        data = self.read_json_body()
        if data is None:
            return
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            self.send_error(503, "ANTHROPIC_API_KEY not configured")
            return
        if anthropic is None:
            self.send_error(503, "anthropic package not installed")
            return

        model_id = data.get('model', '')
        if not model_id:
            self.send_error(400, "model required")
            return
        messages = data.get('messages', [])
        system_msgs = [m for m in messages if m.get('role') == 'system']
        user_msgs   = [m for m in messages if m.get('role') != 'system']
        system = "\n\n".join(m['content'] for m in system_msgs) if system_msgs else ''

        client = anthropic.Anthropic(api_key=api_key)
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
            error_chunk = json.dumps({"error": str(err)})
            self.wfile.write(f"data: {error_chunk}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

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
