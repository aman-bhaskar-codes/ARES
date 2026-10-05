import os
import re

css_path = 'apps/web/src/styles.css'
out_dir = 'apps/web/src/styles'
os.makedirs(out_dir, exist_ok=True)

with open(css_path, 'r') as f:
    css = f.read()

blocks = []
current_block = ""
brace_count = 0

for char in css:
    current_block += char
    if char == '{':
        brace_count += 1
    elif char == '}':
        brace_count -= 1
        if brace_count == 0:
            blocks.append(current_block.strip())
            current_block = ""

if current_block.strip():
    blocks.append(current_block.strip())

def assign_block(block):
    if block.startswith('@media'):
        return 'responsive.css'
    elif ':root' in block or 'data-theme' in block:
        return 'tokens.css'
    elif block.startswith('*') or block.startswith('body') or block.startswith('button') or block.startswith('.sr-only') or block.startswith('input:'):
        return 'base.css'
    elif '.app-shell' in block or '.nav-rail' in block or '.topbar' in block or '.auth-gate' in block or '.brand' in block or '.account' in block:
        return 'shell.css'
    elif '.composer' in block or '.followup' in block or '.send-button' in block or '.mode-toggle' in block:
        return 'composer.css'
    elif '.workspace-panel' in block or '.tool-list' in block or '.ingestion' in block or '.document' in block or '.activity' in block or '.upload-dropzone' in block or 'media-waveform' in block or '.microphone' in block or 'readiness' in block:
        return 'workspace.css'
    elif '.visual' in block or '.evidence-graph' in block or '.evidence-chart' in block or 'react-flow' in block or 'timeline' in block:
        return 'visualizations.css'
    elif '.evidence-drawer' in block or '.evidence-preview' in block or '.evidence-table' in block or '.source-scope' in block or '.evidence-index' in block or 'pdf-page-stage' in block or 'image-evidence-stage' in block:
        return 'evidence.css'
    elif '.home-state' in block or '.thread-view' in block or '.answer-card' in block or '.claim-list' in block or '.gap-card' in block or '.failure-card' in block or '.quality' in block or '.export-bar' in block or 'answer-claim' in block or 'answer-prose' in block or 'citations' in block:
        return 'research.css'
    else:
        return 'research.css'

files = {
    'tokens.css': [],
    'base.css': [],
    'shell.css': [],
    'composer.css': [],
    'research.css': [],
    'evidence.css': [],
    'visualizations.css': [],
    'workspace.css': [],
    'responsive.css': []
}

for block in blocks:
    if not block: continue
    dest = assign_block(block)
    files[dest].append(block)

for fname, content in files.items():
    with open(os.path.join(out_dir, fname), 'w') as f:
        f.write("\n\n".join(content) + "\n")

with open(css_path, 'w') as f:
    for fname in files.keys():
        f.write(f'@import "./styles/{fname}";\n')

print("CSS Split completed.")
