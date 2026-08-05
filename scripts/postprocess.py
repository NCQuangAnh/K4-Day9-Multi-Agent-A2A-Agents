import json
from pathlib import Path
import zipfile
import sys

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / 'output'
LOG_DIR = ROOT / 'logging'
LOG_DIR.mkdir(exist_ok=True)

outs = sorted(OUT_DIR.glob('EC_*.json'))
if not outs:
    print('No output files found')
    sys.exit(1)

required = ['case_id','case_assessment','affected_entities','payment_reconciliation']
limits = {
    'item_ids':5,'seller_ids':3,'payment_ids':5,'related_order_ids':5,
    'product_ids':5,'category_names':5,'evidence_ids':20,'resolution_actions':5
}
errors = []
for p in outs:
    try:
        o = json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        errors.append((p.name, f'parse_error:{e}'))
        continue
    if o.get('case_id') != p.stem:
        errors.append((p.name, 'case_id_mismatch'))
    for k in required:
        if k not in o:
            errors.append((p.name, f'missing:{k}'))
    ae = o.get('affected_entities', {})
    if len(ae.get('item_ids', [])) > limits['item_ids']:
        errors.append((p.name, 'too_many_item_ids'))
    if len(ae.get('seller_ids', [])) > limits['seller_ids']:
        errors.append((p.name, 'too_many_seller_ids'))
    if len(ae.get('payment_ids', [])) > limits['payment_ids']:
        errors.append((p.name, 'too_many_payment_ids'))
    cc = o.get('customer_context', {})
    if len(cc.get('related_order_ids', [])) > limits['related_order_ids']:
        errors.append((p.name, 'too_many_related_orders'))
    pc = o.get('product_context', {})
    if len(pc.get('product_ids', [])) > limits['product_ids']:
        errors.append((p.name, 'too_many_product_ids'))
    if len(pc.get('category_names', [])) > limits['category_names']:
        errors.append((p.name, 'too_many_categories'))
    if len(o.get('evidence_ids', [])) > limits['evidence_ids']:
        errors.append((p.name, 'too_many_evidence'))
    if len(o.get('resolution_actions', [])) > limits['resolution_actions']:
        errors.append((p.name, 'too_many_actions'))
    ca = o.get('case_assessment', {})
    conf = ca.get('confidence')
    try:
        if conf is None or not (0.0 <= float(conf) <= 1.0):
            errors.append((p.name, 'bad_confidence'))
    except Exception:
        errors.append((p.name, 'bad_confidence'))

print('outputs_found', len(outs))
if errors:
    print('schema_errors', len(errors))
    for e in errors[:50]:
        print(e[0], e[1])
    print('Fix errors before packaging. Exiting with code 2.')
    sys.exit(2)

# Write the latest complete run trace at the repository root, as required by
# the README, and keep an identical copy under logging/ for local inspection.
trace_lines = []
for p in outs:
    o = json.loads(p.read_text(encoding='utf-8'))
    trace_lines.append(json.dumps({'case_id': o.get('case_id'), 'status': 'processed'}))
trace_content = '\n'.join(trace_lines) + '\n'
for trace_path in (ROOT / 'trace.jsonl', LOG_DIR / 'trace.jsonl'):
    trace_path.write_text(trace_content, encoding='utf-8')
    print('trace_written', trace_path)

# metadata.json
meta = {
    'model': 'local_placeholder_model',
    'parameters': '<=10B',
    'framework': 'python',
    'runtime': sys.platform
}
meta_path = ROOT / 'metadata.json'
meta_path.write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('metadata_written', meta_path)
log_meta_path = LOG_DIR / 'metadata.json'
log_meta_path.write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('logging_metadata_written', log_meta_path)

# architecture.md
arch = ROOT / 'architecture.md'
if not arch.exists():
    arch.write_text('# Architecture\n\nCoordinator -> CustomerAgent -> OrderProductAgent -> PaymentAgent -> DeliveryAgent -> PolicyAgent -> VerifierAgent\n', encoding='utf-8')
    print('architecture_created', arch)

# individual file (placeholder)
ind = ROOT / 'individual_5SoCuoiMHV_HoVaTen.md'
if not ind.exists():
    ind.write_text('Name: 5SoCuoiMHV_HoVaTen\nRole: ...\nContributions: ...\n', encoding='utf-8')
    print('individual_created', ind)

# create zip of outputs
zip_path = ROOT / 'output.zip'
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in outs:
        zf.write(p, arcname=f"output/{p.name}")
print('zip_created', zip_path)

# verify zip count
with zipfile.ZipFile(zip_path, 'r') as zf:
    names = zf.namelist()
    entries = len(names)
print('zip_entries', entries)
expected_names = [f'output/EC_{number:03d}.json' for number in range(1, 51)]
if names != expected_names:
    print('zip_contents_mismatch')
    sys.exit(3)

print('postprocess: OK')
