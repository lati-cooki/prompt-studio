import os
import sys
import sqlite3
import json
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = "prompt_studio.db"
SCHEMA_PATH = "schema.sql"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(SCHEMA_PATH):
        print(f"Schema file {SCHEMA_PATH} not found!")
        return
    if os.path.exists(DB_PATH):
        return
    with open(SCHEMA_PATH, 'r') as f:
        schema = f.read()
    conn = get_db()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print("Database initialized.")

# Static files
@app.route('/')
@app.route('/sandbox/')
def serve_sandbox():
    return send_from_directory('sandbox', 'index.html')

@app.route('/sandbox/<path:path>')
def serve_sandbox_static(path):
    return send_from_directory('sandbox', path)

@app.route('/registry/')
def serve_registry():
    return send_from_directory('registry/interface', 'registry_widget.html')

@app.route('/registry/<path:path>')
def serve_registry_static(path):
    return send_from_directory('registry/interface', path)

# API Endpoints for Sessions
@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    conn = get_db()
    sessions = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
    conn.close()
    result = []
    for s in sessions:
        d = dict(s)
        try: d['data'] = json.loads(d['data'])
        except: pass
        result.append(d)
    return jsonify(result)

@app.route('/api/sessions', methods=['POST'])
def create_session():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (name, pane_count, data) VALUES (?, ?, ?)",
        (data['name'], data.get('pane_count', 1), json.dumps(data.get('data', {})))
    )
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": session_id, "status": "created"})

@app.route('/api/sessions/<int:id>', methods=['PUT'])
def update_session(id):
    data = request.json
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET name = ?, pane_count = ?, data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (data['name'], data.get('pane_count', 1), json.dumps(data.get('data', {})), id)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})

@app.route('/api/sessions/<int:id>', methods=['DELETE'])
def delete_session(id):
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route('/api/sessions/<int:id>/promote', methods=['POST'])
def promote_session(id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (id,)).fetchone()
    if not session:
        conn.close()
        return jsonify({"error": "Session not found"}), 404
    session_data = json.loads(session['data'])
    pane = session_data['panes'][0]
    prompt_id = ''.join(e for e in session['name'].lower().replace(' ', '_') if e.isalnum() or e == '_')[:40]
    try:
        conn.execute(
            """INSERT INTO registered_prompts 
               (id, version, status, tier, owner, body, use_case, metadata) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (prompt_id, "1.0.0", "draft", "audit", "troy_builds",
             pane['systemPrompt'], f"Promoted from Sandbox: {session['name']}",
             json.dumps({"original_session_id": id, "promoted_at": datetime.now().isoformat()}))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Prompt {prompt_id} v1.0.0 already exists"}), 400
    finally:
        conn.close()
    return jsonify({"status": "promoted", "prompt_id": prompt_id, "version": "1.0.0"})

# API Endpoints for Registered Prompts
@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    conn = get_db()
    prompts = conn.execute("SELECT * FROM registered_prompts ORDER BY updated_at DESC").fetchall()
    conn.close()
    result = []
    for p in prompts:
        d = dict(p)
        for field in ['contract', 'dependencies', 'context_profile', 'value_surface', 'metadata']:
            if d.get(field):
                try: d[field] = json.loads(d[field])
                except: pass
        result.append(d)
    return jsonify(result)

@app.route('/api/prompts/evaluate', methods=['POST'])
def trigger_evaluation():
    data = request.json
    prompt_id, version = data.get('id'), data.get('version')
    directive = data.get('directive', 'registry/evals/strategiai_directive.md')
    model = data.get('model', 'qwen3-27b:localhost:8092')
    conn = get_db()
    prompt = conn.execute("SELECT body FROM registered_prompts WHERE id = ? AND version = ?", (prompt_id, version)).fetchone()
    conn.close()
    if not prompt: return jsonify({"error": "Prompt not found"}), 404
    temp_path = f"temp_eval_{prompt_id}_{version}.md"
    with open(temp_path, 'w') as f: f.write(prompt['body'])
    try:
        cmd = [sys.executable, "scripts/evaluate_prompt.py", temp_path, directive, model]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if os.path.exists(temp_path): os.remove(temp_path)
        if result.returncode != 0: return jsonify({"error": "Eval failed", "details": result.stderr}), 500
        report_file = next((l.split("Report saved to:")[1].strip() for l in result.stdout.split('\n') if "Report saved to:" in l), "")
        
        # NEW: Update the database with the eval result
        if report_file and os.path.exists(report_file):
            with open(report_file, 'r') as rf:
                report_content = rf.read()
            
            # Simple parsing for status and headline
            eval_status = "validated" if "Error:" not in report_content else "failed"
            headline = "Evaluation failed. Check report."
            if eval_status == "validated":
                # Try to extract the first finding or just a generic success
                if "**Verdict Summary:**" in report_content:
                    headline = report_content.split("**Verdict Summary:**")[1].split('\n')[1].strip('> ')
                else:
                    headline = "Completed automated evaluation."

            conn = get_db()
            conn.execute(
                "UPDATE registered_prompts SET eval_status = ?, notes = ? WHERE id = ? AND version = ?",
                (eval_status, headline[:200], prompt_id, version)
            )
            conn.commit()
            conn.close()

        return jsonify({"status": "evaluated", "report": report_file, "output": result.stdout})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/evaluate_raw', methods=['POST'])
def trigger_raw_evaluation():
    """Triggers the evaluation script for a raw prompt body."""
    data = request.json
    body = data.get('body')
    model = data.get('model', 'mlx-community/Qwen3-4B-Instruct-2507-4bit:localhost:8091')
    directive = 'registry/evals/strategiai_directive.md'
    
    if not body:
        return jsonify({"error": "Prompt body is required"}), 400
        
    temp_path = f"temp_raw_eval_{int(datetime.now().timestamp())}.md"
    with open(temp_path, 'w') as f:
        f.write(body)
        
    try:
        cmd = [sys.executable, "scripts/evaluate_prompt.py", temp_path, directive, model]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        if result.returncode != 0:
            return jsonify({"error": "Evaluation script failed", "details": result.stderr}), 500
            
        report_file = next((l.split("Report saved to:")[1].strip() for l in result.stdout.split('\n') if "Report saved to:" in l), "")
        return jsonify({"status": "evaluated", "report": report_file})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=7777, threaded=True, debug=True)
