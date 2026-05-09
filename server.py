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
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        return json.loads(body.decode('utf-8'))

    def handle_get_sessions(self):
        conn = self.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()

        sessions = []
        for row in rows:
            sessions.append({
                "id": row["id"],
                "name": row["name"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "panes": json.loads(row["panes"]),
                "vaultConfig": json.loads(row["vault_config"])
            })
        self.send_json(sessions)

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

    def handle_delete_prompt(self, prompt_id):
        conn = self.get_db()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        conn.commit()
        conn.close()
        self.send_json({"status": "success"})

    def handle_put_prompt(self, prompt_id):
        data = self.read_json_body()
        conn = self.get_db()
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

        conn.close()
        self.send_json({"status": "success"})

    def handle_put_session(self, session_id):
        data = self.read_json_body()
        conn = self.get_db()
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

        conn.close()
        self.send_json({"status": "success"})

    def handle_delete_session(self, session_id):
        conn = self.get_db()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()
        self.send_json({"status": "success"})

    def handle_post_prompts(self):
        data = self.read_json_body()
        conn = self.get_db()
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
        conn.close()
        self.send_json({"status": "success"})

    def handle_get_prompts(self):
        conn = self.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM prompts")
        rows = cursor.fetchall()
        conn.close()

        prompts = []
        for row in rows:
            prompts.append({
                "id": row["id"],
                "version": row["version"],
                "status": row["status"],
                "tier": row["tier"],
                "owner": row["owner"],
                "body": row["body"],
                "useCase": row["use_case"],
                "costPerRunUsd": row["cost_per_run_usd"],
                "tokensPromptBody": row["tokens_prompt_body"],
                "defaultModel": row["default_model"],
                "evalStatus": row["eval_status"],
                "file": row["file"],
                "notes": row["notes"],
                "composes": json.loads(row["composes"]) if row["composes"] else [],
                "testedOn": json.loads(row["tested_on"]) if row["tested_on"] else [],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"]
            })
        self.send_json(prompts)

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), PromptStudioHandler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()
