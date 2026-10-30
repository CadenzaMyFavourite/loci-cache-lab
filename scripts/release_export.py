"""Prepare a portable publication copy and separate redacted evidence archive.

Original evidence is read-only. This command never initializes Git or uploads.
"""
import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import zipfile
from release_evidence import ROOT,sha

def safe_text(text):
    for form in [str(ROOT).replace('\\','\\\\'),str(ROOT),str(ROOT).replace('\\','/')]:text=text.replace(form,'<WORKSPACE>')
    text=re.sub(r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s"<>]+','<USER_HOME>',text)
    name=pathlib.Path.home().name
    if len(name)>3:text=re.sub(re.escape(name),'<LOCAL_USER>',text,flags=re.I)
    return text

def transformed(path):
    raw=path.read_bytes()
    if path.suffix.lower() in ['.png','.pptx']:return raw
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise RuntimeError(f'Unexpected non-text asset: {path.relative_to(ROOT)}')
    return safe_text(text).encode('utf-8')

def inputs():
    rootfiles=['README.md','Cargo.toml','Cargo.lock','LICENSE','.gitignore','requirements.txt','requirements.lock.txt',
        'demo.ps1','THIRD_PARTY_NOTICES.md','DATA_ARCHIVE.md','RELEASE_CHECKLIST.md','FINAL_HANDOFF.md','PHASE2_REPORT.md','PHASE3_REPORT.md']
    files=[ROOT/p for p in rootfiles]
    for folder,extensions in [('src',{'.rs'}),('scripts',{'.py'}),('tests',{'.py','.rs'}),('docs',{'.md'}),
        ('evidence',{'.json','.jsonl'}),('analysis',{'.png'}),('.github',{'.yml','.yaml'}),('presentations',{'.mjs','.pptx'})]:
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in extensions and '__pycache__' not in str(p))
    files.append(ROOT/'environment/artifacts.json')
    return sorted(files)

def rewrite_missing_links(path,data,included):
    if path.suffix!='.md':return data
    text=data.decode('utf-8')
    def replace(m):
        label,target=m.groups()
        if target.startswith(('http://','https://','#','mailto:')):return m[0]
        dest=(path.parent/target.split('#')[0]).resolve()
        if dest in included:return m[0]
        # Original reports and their exact locators remain in the raw archive.
        # Point archive-only links in review copies at a working archive guide.
        relative=os.path.relpath(ROOT/'DATA_ARCHIVE.md',path.parent).replace('\\','/')
        return f'[{label}]({relative})'
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',replace,text).encode('utf-8')

RULES={
        'private_home':r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s"<>]+',
        'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'openai_credential':r'\bsk-(?:proj-)?[A-Za-z0-9_-]{25,}',
        'github_credential':r'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{25,}',
        'aws_access_key':r'\bAKIA[A-Z0-9]{16}\b'}

def scan_text(name,text):
    findings=[]
    for rule,pattern in RULES.items():
        count=sum(1 for _ in re.finditer(pattern,text))
        if count:findings.append({'path':name,'rule':rule,'count':count})
    return findings

def scan(folder):
    findings=[]
    for p in folder.rglob('*'):
        if not p.is_file() or p.suffix=='.png':continue
        name=str(p.relative_to(folder))
        if p.suffix=='.pptx':
            with zipfile.ZipFile(p) as package:
                for part in package.namelist():
                    if part.endswith(('.xml','.rels')):
                        findings.extend(scan_text(name+'!'+part,package.read(part).decode('utf-8')))
                    elif part.endswith('.xlsx'):
                        with zipfile.ZipFile(io.BytesIO(package.read(part))) as workbook:
                            for sheet in workbook.namelist():
                                if sheet.endswith(('.xml','.rels')):
                                    findings.extend(scan_text(name+'!'+part+'!'+sheet,workbook.read(sheet).decode('utf-8')))
        else:findings.extend(scan_text(name,p.read_text(encoding='utf-8')))
    return findings

def archive_inputs():
    files=[ROOT/'phase4/prior-manifest.json',ROOT/'PHASE2_REPORT.md',ROOT/'PHASE3_REPORT.md']
    for directory in ['results','workloads','environment','analysis','docs','phase2','phase3','phase4/baseline','runs/phase4-mini-demo']:
        files.extend(sorted((ROOT/directory).rglob('*')))
    return [p for p in files if p.is_file() and '__pycache__' not in str(p)
            and p.suffix.lower() in ['.json','.jsonl','.log','.md','.py','.rs','.png','.txt','.csv','.toml','.lock','.ps1','.yml','.yaml']]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',default='runs/phase4-publication');parser.add_argument('--archive',action='store_true');a=parser.parse_args()
    out=ROOT/a.out
    if out.exists():raise RuntimeError('Refusing to overwrite a publication candidate; choose another --out')
    public=out/'repository';public.mkdir(parents=True)
    selected=inputs();included=set(selected);manifest=[]
    for p in selected:
        if not p.exists():raise RuntimeError(f'Missing release file {p.relative_to(ROOT)}')
        target=public/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        data=rewrite_missing_links(p,transformed(p),included);target.write_bytes(data)
        manifest.append({'path':str(p.relative_to(ROOT)).replace('\\','/'),'original_sha256':sha(p),'publication_sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'copy_changed':data!=p.read_bytes()})
    findings=scan(public)
    if findings:raise RuntimeError('Publication scan failed: '+json.dumps(findings))
    # The source/publication hashes document location/link normalization only.
    (out/'publication-manifest.json').write_text(json.dumps({'files':manifest,'secret_scan':'no matches for bounded credential/home-path rules; not a proof of absence'},indent=2),encoding='utf-8')
    if a.archive:
        archive_manifest=[]
        with zipfile.ZipFile(out/'raw-evidence-redacted.zip','x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for p in archive_inputs():
                data=transformed(p);name=str(p.relative_to(ROOT)).replace('\\','/')
                if p.suffix.lower()!='.png':
                    findings=scan_text(name,data.decode('utf-8'))
                    if findings:raise RuntimeError('Archive scan failed: '+json.dumps(findings))
                archive.writestr(name,data);archive_manifest.append({'path':name,'original_sha256':sha(p),'archive_sha256':hashlib.sha256(data).hexdigest()})
            archive.writestr('ARCHIVE_MANIFEST.json',json.dumps(archive_manifest,indent=2))
        (out/'archive-info.json').write_text(json.dumps({'path':'raw-evidence-redacted.zip','bytes':(out/'raw-evidence-redacted.zip').stat().st_size,'sha256':sha(out/'raw-evidence-redacted.zip'),'files':len(archive_manifest),'scope':'location-redacted copies; originals remain local and unchanged'},indent=2),encoding='utf-8')
    print(json.dumps({'publication_files':len(manifest),'publication_bytes':sum(r['bytes'] for r in manifest),'root':str(public),'archive':a.archive},indent=2))

if __name__=='__main__':main()
