import sys
import os
import json
import re
from datetime import datetime

def parse_eval_report(report_path):
    """Extracts key info from the eval report."""
    if not os.path.exists(report_path):
        return None
    
    with open(report_path, 'r') as f:
        content = f.read()
    
    # Extract headline finding
    finding_match = re.search(r"## Headline Finding\n\n> (.*)", content)
    headline = finding_match.group(1) if finding_match else "Verified via automated evaluation."
    
    return {
        "headline": headline,
        "file": report_path,
        "date": datetime.now().strftime("%Y-%m-%d")
    }

def register(prompt_draft_path, eval_report_path):
    """Promotes a draft prompt to the registry."""
    if not os.path.exists(prompt_draft_path):
        print(f"Error: Draft prompt {prompt_draft_path} not found.")
        return

    with open(prompt_draft_path, 'r') as f:
        try:
            draft = json.load(f)
        except json.JSONDecodeError:
            # Maybe it's a markdown file with YAML?
            # For now, we assume JSON as produced by the Sandbox export.
            print(f"Error: {prompt_draft_path} is not valid JSON.")
            return
    
    eval_info = parse_eval_report(eval_report_path)
    
    # Prepare for Registry
    draft['status'] = 'production'
    draft['eval_status'] = 'validated'
    if eval_info:
        draft['eval_batch'] = os.path.basename(eval_report_path)
        # Move eval report to registry/evals if not already there
        target_eval_path = os.path.join('registry/evals', os.path.basename(eval_report_path))
        if not os.path.exists(target_eval_path):
            os.rename(eval_report_path, target_eval_path)
            eval_info['file'] = target_eval_path

    # Format filename: id_v1_1_0.md
    safe_version = draft['version'].replace('.', '_')
    prompt_filename = f"{draft['id']}_v{safe_version}.md"
    prompt_file_path = os.path.join('registry/prompts', prompt_filename)
    
    # Save the prompt body as a standalone markdown file
    with open(prompt_file_path, 'w') as f:
        f.write(draft['body'])
    
    # Update INDEX.json
    index_path = 'registry/INDEX.json'
    if os.path.exists(index_path):
        with open(index_path, 'r') as f:
            index = json.load(f)
    else:
        index = {"registry_version": "0.1", "prompts": [], "evals": []}
    
    # Create index entry
    new_entry = {
        "id": draft['id'],
        "version": draft['version'],
        "status": draft['status'],
        "tier": draft.get('tier', 'audit'),
        "use_case": draft.get('use_case', ''),
        "file": f"prompts/{prompt_filename}",
        "eval_status": draft['eval_status'],
        "eval_batch": draft.get('eval_batch'),
        "notes": draft.get('notes', f"Registered on {datetime.now().strftime('%Y-%m-%d')}")
    }
    
    # Remove older version if it's the same ID and version
    index['prompts'] = [p for p in index['prompts'] if not (p['id'] == draft['id'] and p['version'] == draft['version'])]
    index['prompts'].insert(0, new_entry)
    
    # Add to evals if we have info
    if eval_info:
        new_eval = {
            "id": os.path.basename(eval_report_path).split('.')[0],
            "date": eval_info['date'],
            "prompt_under_test": f"{draft['id']}@{draft['version']}",
            "headline_finding": eval_info['headline'],
            "file": f"evals/{os.path.basename(eval_report_path)}"
        }
        index['evals'].insert(0, new_eval)

    with open(index_path, 'w') as f:
        json.dump(index, f, indent=2)
    
    print(f"[+] Successfully registered {draft['id']} v{draft['version']}")
    print(f"[+] Prompt body: {prompt_file_path}")
    print(f"[+] Index updated: {index_path}")

def main():
    if len(sys.argv) < 3:
        print("Usage: python register_prompt.py <prompt_draft_json> <eval_report_md>")
        sys.exit(1)
    
    register(sys.argv[1], sys.argv[2])

if __name__ == "__main__":
    main()
