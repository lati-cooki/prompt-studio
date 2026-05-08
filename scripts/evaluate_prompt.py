import sys
import os
import json
import requests
import time
from datetime import datetime

def evaluate(prompt_content, directive_content, model_endpoint, model_id):
    """Executes a single evaluation run."""
    print(f"[*] Testing model: {model_id}...")
    
    start_time = time.time()
    try:
        response = requests.post(
            model_endpoint,
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": prompt_content},
                    {"role": "user", "content": f"## Directive\n\n{directive_content}"}
                ],
                "temperature": 0.0
            },
            timeout=300 # 5 minute timeout for long audits
        )
        duration = time.time() - start_time
        
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text}", "model_id": model_id}

        result = response.json()
        content = result['choices'][0]['message']['content']
        usage = result.get('usage', {})
        
        return {
            "model_id": model_id,
            "output": content,
            "duration": duration,
            "usage": usage,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "model_id": model_id}

def generate_markdown_report(results, prompt_id, version, directive_name):
    """Formats results into a markdown report similar to eval_batch_001.md."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    report = [
        f"# Eval Report — {directive_name}",
        "",
        f"**Prompt under test:** {prompt_id}@{version}",
        f"**Date:** {date_str}",
        f"**Directive:** {directive_name}",
        "",
        "## Headline Finding",
        "",
        "> [AUTO-GENERATED] Evaluation run completed. Review the model outputs below for arithmetic validation and strategic depth.",
        "",
        "## Comparison Matrix",
        "",
        "| Dimension | " + " | ".join([r['model_id'] for r in results]) + " |",
        "|---| " + " | ".join(["---" for _ in results]) + " |",
        "| Caught arithmetic | " + " | ".join(["?" for _ in results]) + " |",
        "| Output tokens | " + " | ".join([str(r.get('usage', {}).get('completion_tokens', 'N/A')) for r in results]) + " |",
        "| Duration (s) | " + " | ".join([f"{r.get('duration', 0):.1f}" for r in results]) + " |",
        "",
        "## Per-Model Summaries",
        ""
    ]
    
    for r in results:
        report.append(f"### {r['model_id']}")
        report.append("")
        if "error" in r:
            report.append(f"**Error:** {r['error']}")
        else:
            # Show a snippet or the whole thing if requested
            report.append("**Verdict Summary:**")
            # Extract verdict if it follows standard protocol
            if "VERDICT:" in r['output']:
                verdict_line = [l for l in r['output'].split('\n') if 'VERDICT:' in l][0]
                report.append(f"> {verdict_line}")
            
            report.append("")
            report.append("<details>")
            report.append("<summary>Click to view full output</summary>")
            report.append("")
            report.append(r['output'])
            report.append("")
            report.append("</details>")
        report.append("")
        
    return "\n".join(report)

def main():
    if len(sys.argv) < 3:
        print("Usage: python evaluate_prompt.py <prompt_file> <directive_file> [model_id:endpoint ...]")
        print("Example: python evaluate_prompt.py registry/prompts/consensus_protocol_v1_1_0.md registry/evals/strategiai_directive.md gemma-4-26b:http://localhost:8080/v1/chat/completions")
        sys.exit(1)

    prompt_file = sys.argv[1]
    directive_file = sys.argv[2]
    model_configs = sys.argv[3:]

    if not model_configs:
        # Fallback to a default if nothing provided
        model_configs = ["gemma-4-26b:http://localhost:8080/v1/chat/completions"]

    with open(prompt_file, 'r') as f:
        prompt_content = f.read()
    with open(directive_file, 'r') as f:
        directive_content = f.read()

    results = []
    for config in model_configs:
        if ':' in config:
            mid, url = config.split(':', 1)
            # Basic URL check
            if not url.startswith('http'):
                url = f"http://{url}"
            if '/v1' not in url:
                url = url.rstrip('/') + '/v1/chat/completions'
        else:
            mid = config
            url = "http://localhost:8080/v1/chat/completions" # Default
        
        res = evaluate(prompt_content, directive_content, url, mid)
        results.append(res)

    report_md = generate_markdown_report(results, os.path.basename(prompt_file), "draft", os.path.basename(directive_file))
    
    output_file = f"eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(output_file, 'w') as f:
        f.write(report_md)
    
    print(f"\n[+] Evaluation complete. Report saved to: {output_file}")

if __name__ == "__main__":
    main()
