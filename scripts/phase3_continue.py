"""Finish prespecified tail extension, then independently collect precision."""
import json
import subprocess
import time
from experiment import ROOT
PY=ROOT/'.venv/Scripts/python.exe'

def run(command,log):
    with (ROOT/log).open('x',encoding='utf-8') as output:
        subprocess.run([str(s) for s in command],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True)

if __name__=='__main__':
    while len(list((ROOT/'phase3/tail').rglob('complete.json')))<40:time.sleep(5)
    run([PY,'scripts/phase3_analyze.py','--out','phase3/analysis-initial'],'phase3/analysis-initial.log')
    decision=json.loads((ROOT/'phase3/analysis-initial/sample-decision.json').read_text(encoding='utf-8'))
    print('Initial sample decision',decision,flush=True)
    if decision['expand_if_below_20_trials']:
        run([PY,'scripts/phase3_experiment.py','--trials','10','--trial-start','10'],'phase3/tail-extension.log')
    run([PY,'scripts/phase3_analyze.py'],'phase3/analysis-final.log')
    print('Primary study complete; starting the independent precision study',flush=True)
    run(['cargo','fmt','--check'],'phase3/fmt-before-precision.log')
    run(['cargo','test','--all-targets','--locked'],'phase3/tests-before-precision.log')
    run(['cargo','build','--release','--bin','precision','--locked'],'phase3/precision-build.log')
    run([PY,'scripts/phase3_precision.py','--prepare'],'phase3/precision-preparation.log')
    run([PY,'scripts/phase3_precision.py','--allocate'],'phase3/allocations.log')
    run([PY,'scripts/phase3_precision.py'],'phase3/precision.log')
    run([PY,'scripts/phase3_precision.py','--correctness','--out','phase3/precision-correctness'],'phase3/precision-correctness.log')
    run([PY,'scripts/phase3_precision_analyze.py'],'phase3/precision-analysis.log')
    run([PY,'scripts/phase3_precision_analyze.py','--source','phase3/precision-correctness','--out','phase3/precision-correctness-analysis'],'phase3/precision-correctness-analysis.log')
    print('Precision collections and analysis complete',flush=True)
