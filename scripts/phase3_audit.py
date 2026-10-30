"""Final preservation, raw-evidence coverage and artifact integrity checks."""
import hashlib
import json
from experiment import ROOT

def sha(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()

if __name__=='__main__':
    prior=json.loads((ROOT/'phase3/prior-manifest.json').read_text(encoding='utf-8'))
    changed=[name for name,digest in prior.items() if sha(ROOT/name)!=digest]
    assert changed==['README.md'],changed
    assert sha(ROOT/'phase3/baseline/README.md')==prior['README.md']
    primary=json.loads((ROOT/'phase3/analysis/summary.json').read_text(encoding='utf-8'))
    trials=primary['groups'][0]['trials']
    collections={}
    for cohort,expected in [('tail',trials*4),('precision',80),('precision-correctness',20)]:
        markers=sorted((ROOT/'phase3'/cohort).rglob('complete.json'));assert len(markers)==expected,(cohort,len(markers),expected)
        collections[cohort]=[]
        for marker in markers:
            folder=marker.parent
            collections[cohort].append({'source':str(folder.relative_to(ROOT)),**json.loads(marker.read_text(encoding='utf-8')),
                'sha256':{p.name:sha(p) for p in sorted(folder.iterdir()) if p.is_file()}})
    files=['README.md','PHASE3_REPORT.md','docs/phase3-equivalence.md','docs/kv-cache-precision.md','docs/loci-application.md','docs/interview-walkthrough.md',
        'analysis/phase3-tail-distributions.png','analysis/phase3-trial-p95.png','analysis/phase3-kv-precision.png']
    deliverables={p:sha(ROOT/p) for p in files}
    sources={str(p.relative_to(ROOT)):sha(p) for folder in ['src','scripts','tests'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.py','.rs']}
    (ROOT/'phase3/integrity.json').write_text(json.dumps({'prior_unchanged_files':len(prior)-1,'intentional_changes':changed,'original_readme_preserved':True,
        'deliverables':deliverables,'sources':sources,'collections':collections},indent=2),encoding='utf-8')
    print(f'{len(prior)-1} prior files unchanged; original README preserved; source and raw results retained.')
    print({k:len(v) for k,v in collections.items()})
