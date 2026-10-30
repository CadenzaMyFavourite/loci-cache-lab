"""Check preservation of the Phase 1 evidence and fingerprint Phase 2 inputs."""
import hashlib
import json
from experiment import ROOT

def digest(path):
    return hashlib.file_digest(path.open('rb'),'sha256').hexdigest()

def main():
    before=json.loads((ROOT/'phase2/baseline-manifest.json').read_text(encoding='utf-8'))
    modified=[];preserved=[]
    for name,expected in before.items():
        actual=digest(ROOT/name)
        if actual==expected:preserved.append(name)
        else:modified.append(name)
    assert modified==['src/main.rs'],modified
    assert digest(ROOT/'phase2/baseline-source/main.rs')==before['src/main.rs']
    binaries={name:digest(ROOT/name) for name in [
        'phase2/baseline/loci-cache-lab-phase1.exe',
        'phase2/baseline/concurrency-ablation.exe',
        'target/release/concurrency.exe','target/release/loci-cache-lab.exe']}
    sources={str(path.relative_to(ROOT)):digest(path) for folder in ['src','scripts','tests'] for path in sorted((ROOT/folder).rglob('*')) if path.is_file() and path.suffix in ['.py','.rs']}
    sources['Cargo.lock']=digest(ROOT/'Cargo.lock')
    collection={}
    for cohort in ['ablation-clean','validation','correctness']:
        arms=[]
        for marker in sorted((ROOT/'phase2'/cohort).rglob('complete.json')):
            folder=marker.parent
            arms.append({'source':str(folder.relative_to(ROOT)),**json.loads(marker.read_text(encoding='utf-8')),'checksums':{path.name:digest(path) for path in sorted(folder.iterdir()) if path.is_file()}})
        collection[cohort]=arms
    result={'phase1_preserved_file_count':len(preserved),'intentional_source_changes':modified,
            'original_main_verified_in':'phase2/baseline-source/main.rs','binaries':binaries,
            'source_checksums':sources,'collections':collection,
            'probe_audit':{str(path.relative_to(ROOT)):digest(path) for path in sorted((ROOT/'phase2/probe-audit').rglob('*')) if path.is_file()},
            'deliverables':{name:digest(ROOT/name) for name in ['PHASE2_REPORT.md','docs/concurrency-root-cause.md','docs/concurrency-ablation.md','analysis/concurrency-before-after.png','phase2/analysis-final/summary.json']}}
    (ROOT/'phase2/integrity.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(f'Verified {len(preserved)} unchanged Phase 1 files; original main.rs preserved separately.')
    print({cohort:len(arms) for cohort,arms in collection.items()})

if __name__=='__main__':main()
