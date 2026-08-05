import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'output'
LOG = ROOT / 'logging'
outs = sorted(OUT.glob('EC_*.json'))
if not outs:
    print('no outputs')
    sys.exit(1)

meta = {
    'model':'local_placeholder_model',
    'parameters':'<=10B',
    'framework':'python',
    'runtime':sys.platform
}
# write trace
with (LOG / 'trace.jsonl').open('w', encoding='utf-8') as f:
    for p in outs:
        o = json.loads(p.read_text(encoding='utf-8'))
        f.write(json.dumps({'case_id': o.get('case_id'), 'status':'processed'}) + '\n')
# write metadata at root and logging
(ROOT / 'metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
(LOG / 'metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('wrote', len(outs))
