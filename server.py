import http.server
import mimetypes
import socketserver
import json
import sqlite3
import urllib.request
import urllib.error

DB_PATH = 'prompt_studio.db'
PORT = 8000
MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
THREADHUB_PORT = 8110


def is_safe_slug(slug):
    return bool(slug) and '/' not in slug and '..' not in slug


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

    def handle_get_thread(self, slug):
        if not is_safe_slug(slug):
            self.send_error(400, "Invalid slug")
            return
        self.proxy_threadhub_get(f"/t/{slug}.json")

    def handle_get_thread_verify(self, slug):
        if not is_safe_slug(slug):
            self.send_error(400, "Invalid slug")
            return
        self.proxy_threadhub_get(f"/t/{slug}/verify")

    def do_GET(self):
        if self.path == '/api/sessions':
            self.handle_get_sessions()
        elif self.path == '/api/prompts':
            self.handle_get_prompts()
        elif self.path == '/api/registry':
            self.serve_file('registry/INDEX.json', 'application/json')
        elif self.path.startswith('/registry-asset/'):
            rel = self.path[len('/registry-asset/'):]
            if '..' in rel or rel.startswith('/'):
                self.send_error(400)
                return
            self.serve_file('registry/' + rel)
        elif self.path == '/api/threads' or self.path.startswith('/api/threads?'):
            self.handle_get_threads()
        elif self.path.startswith('/api/threads/'):
            rest = self.path[len('/api/threads/'):].split('?', 1)[0]
            if rest.endswith('/verify'):
                self.handle_get_thread_verify(rest[:-len('/verify')])
            else:
                self.handle_get_thread(rest)
        elif self.path in ('/', '/sandbox', '/sandbox/'):
            self.serve_file('sandbox/index.html', 'text/html')
        elif self.path in ('/registry', '/registry/'):
            self.serve_file('registry/interface/registry_widget.html', 'text/html')
        elif self.path in ('/threads', '/threads/'):
            self.serve_file('threads/interface/threads_widget.html', 'text/html')
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
        elif self.path == '/api/prompts':
            self.handle_post_prompts()
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
        conn = self.get_db()
        try:
            cursor = conn.cursor()

            mapping = {
                "version": "version",
                "status": "status",
                "tier": "tier",
                "owner": "owner",
                "body": "body",
                "useCase": "use_case",
                "costPerRunUsd": "cost_per_run_usd",
                "tokensPromptBody": "tokens_prompt_body",
                "defaultModel": "default_model",
                "evalStatus": "eval_status",
                "file": "file",
                "notes": "notes",
                "composes": "composes",
                "testedOn": "tested_on",
                "updatedAt": "updated_at"
            }

            fields = []
            params = []
            for json_key, db_col in mapping.items():
                if json_key in data:
                    fields.append(f"{db_col} = ?")
                    val = data[json_key]
                    if json_key in ["composes", "testedOn"]:
                        val = json.dumps(val)
                    params.append(val)

            if fields:
                query = f"UPDATE prompts SET {', '.join(fields)} WHERE id = ?"
                params.append(prompt_id)
                cursor.execute(query, tuple(params))
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
    with socketserver.TCPServer(("", PORT), PromptStudioHandler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()
