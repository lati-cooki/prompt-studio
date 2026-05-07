import re

with open('TODO.md', 'r') as f:
    content = f.read()

content = content.replace('- [ ] Read `sandbox/README.md`', '- [x] Read `sandbox/README.md`')
content = content.replace('- [ ] Modify the `sandbox/js/sessions.js`', '- [x] Modify the `sandbox/js/sessions.js`')
content = content.replace('- [ ] Build a simple Python API', '- [x] Build a simple Python API')
content = content.replace('- [ ] Create a Python script `scripts/evaluate_prompt.py`', '- [x] Create a Python script `scripts/evaluate_prompt.py`')
content = content.replace('- [ ] Create a script `scripts/register_prompt.py`', '- [x] Create a script `scripts/register_prompt.py`')
content = content.replace('- [ ] Write a wrapper script `scripts/execute_with_jules.sh`', '- [x] Write a wrapper script `scripts/execute_with_jules.sh`')

with open('TODO.md', 'w') as f:
    f.write(content)
