import http.server
import socketserver
import json
import sqlite3
import os

DB_PATH = 'prompt_studio.db'
PORT = 8000

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
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/sessions':
            self.handle_post_sessions()
        else:
            self.send_error(404)

    def do_PUT(self):
        if self.path.startswith('/api/sessions/'):
            session_id = self.path.split('/')[-1]
            self.handle_put_session(session_id)
        else:
            self.send_error(404)

    def do_DELETE(self):
        if self.path.startswith('/api/sessions/'):
            session_id = self.path.split('/')[-1]
            self.handle_delete_session(session_id)
        else:
            self.send_error(404)

    def read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        return json.loads(body.decode('utf-8'))

    # Will implement these methods in the next step
    def handle_get_sessions(self):
        conn = self.get_db()
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
        conn.close()
        self.send_raw_json(result if result else "[]")

    def handle_post_sessions(self):
        data = self.read_json_body()
        conn = self.get_db()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO sessions (id, name, created_at, updated_at, panes, vault_config) VALUES (?, ?, ?, ?, ?, ?)",
            (data["id"], data["name"], data["createdAt"], data["updatedAt"], json.dumps(data["panes"]), json.dumps(data["vaultConfig"]))
        )
        conn.commit()
        conn.close()
        self.send_json({"status": "success"})

    def handle_put_session(self, session_id):
        data = self.read_json_body()
        conn = self.get_db()
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE sessions SET name = ? WHERE id = ?",
            (data["name"], session_id)
        )
        conn.commit()
        conn.close()
        self.send_json({"status": "success"})

    def handle_delete_session(self, session_id):
        conn = self.get_db()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()
        self.send_json({"status": "success"})

    def handle_get_prompts(self):
        conn = self.get_db()
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
        conn.close()
        self.send_raw_json(result if result else "[]")

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), PromptStudioHandler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()
