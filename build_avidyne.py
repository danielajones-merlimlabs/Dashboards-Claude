#!/usr/bin/env python3
"""Build avidyne.html by injecting index.html data into template-avidyne.html."""
import os, sys

root = os.path.dirname(os.path.abspath(__file__))

# ── Extract embedded data from the already-built index.html ──────────────────
index_path = os.path.join(root, 'index.html')
with open(index_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

dr_json = closed_json = timestamp = ''
for line in lines:
    if line.startswith('const DR_DATA = '):
        dr_json = line.strip()[len('const DR_DATA = '):-1]
    elif line.startswith('const CLOSED_DATA = '):
        closed_json = line.strip()[len('const CLOSED_DATA = '):-1]
    elif line.startswith('const SYNC_TIMESTAMP = '):
        timestamp = line.strip()[len('const SYNC_TIMESTAMP = '):-1].strip('"')

if not dr_json:
    print('ERROR: DR_DATA not found in index.html', file=sys.stderr)
    sys.exit(1)
if not closed_json:
    print('ERROR: CLOSED_DATA not found in index.html', file=sys.stderr)
    sys.exit(1)

# ── Inject into template ──────────────────────────────────────────────────────
template_path = os.path.join(root, 'template-avidyne.html')
if not os.path.exists(template_path):
    print(f'ERROR: {template_path} not found', file=sys.stderr)
    sys.exit(1)

with open(template_path, 'r', encoding='utf-8') as f:
    html = f.read()

if '__DR_DATA_PLACEHOLDER__' not in html:
    print('ERROR: placeholder not found in template-avidyne.html', file=sys.stderr)
    sys.exit(1)

html = html.replace('__DR_DATA_PLACEHOLDER__',      dr_json)
html = html.replace('__CLOSED_DATA_PLACEHOLDER__',  closed_json)
html = html.replace('__SYNC_TIMESTAMP_PLACEHOLDER__', timestamp)

out_path = os.path.join(root, 'avidyne.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'avidyne.html written — {len(html):,} bytes, timestamp={timestamp}')
