"""Validate a local publication candidate without changing research evidence."""
import argparse
import collections
import json
import re
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET

from release_evidence import ROOT, sha
from release_export import scan


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def preservation():
    manifest = ROOT / 'phase4/prior-manifest.json'
    if not manifest.exists():
        return {'status': 'unavailable in this checkout; requires private prior manifest'}
    prior = json.loads(manifest.read_text(encoding='utf-8'))
    changed = []
    for name, digest in prior.items():
        path = ROOT / name
        require(path.is_file(), 'Prior file missing: ' + name)
        if sha(path) != digest:
            changed.append(name)
    require(set(changed) == {'README.md', '.gitignore'},
            'Unexpected prior-file changes: ' + json.dumps(changed))
    require(sha(ROOT / 'phase4/baseline/README.md') == prior['README.md'],
            'Archived README differs from prior manifest')
    require(sha(ROOT / 'phase4/baseline/gitignore.txt') == prior['.gitignore'],
            'Archived ignore rules differ from prior manifest')
    return {'prior_files': len(prior), 'unchanged': len(prior) - len(changed),
            'authorized_changes': changed, 'missing': 0}


def links(folder):
    checked = 0
    for path in folder.rglob('*.md'):
        text = path.read_text(encoding='utf-8')
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
            if target.startswith(('https://', 'http://', '#', 'mailto:')):
                continue
            local = urllib.parse.unquote(target.strip('<>').split('#')[0])
            destination = (path.parent / local).resolve()
            require(destination.is_relative_to(folder), 'Link escapes publication: ' + str(path.relative_to(folder)))
            require(destination.exists(), 'Broken local link in ' + str(path.relative_to(folder)) + ': ' + local)
            checked += 1
    return checked


def evidence(folder):
    index = json.loads((folder / 'evidence/index.json').read_text(encoding='utf-8'))
    counts = collections.defaultdict(collections.Counter)
    records = 0
    for line in (folder / 'evidence/requests.jsonl').open(encoding='utf-8'):
        row = json.loads(line)
        counts[row['stage']][row['phase']] += 1
        if not row['success']:
            counts[row['stage']][row['phase'] + '_failures'] += 1
        require(not row['success'] or row['ttft_ms'] is not None, 'Successful request lacks TTFT')
        records += 1
    for stage, expected in index['cohorts'].items():
        for field in ['measured', 'warmup', 'measured_failures', 'warmup_failures']:
            require(counts[stage][field] == expected[field], 'Evidence denominator mismatch: ' + stage + '/' + field)
    configs = json.loads((folder / 'evidence/configurations.json').read_text(encoding='utf-8'))
    require(len(configs) == sum(c['arms'] for c in index['cohorts'].values()), 'Missing configuration headers')
    require({r['source'] for r in configs} == {r['source'] for r in index['request_sources']}, 'Configuration lineage mismatch')
    for name, meta in index['summaries'].items():
        require(sha(folder / 'evidence' / name) == meta['review_copy_sha256'], 'Portable summary hash mismatch: ' + name)
    trace = json.loads((folder / 'evidence/early-binding.json').read_text(encoding='utf-8'))
    for row in trace['requests']:
        require(row['timings']['prompt_n'] + row['timings']['cache_n'] == row['input_tokens'], 'Trace counter mismatch')
    return {'records': records, 'configurations': len(configs), 'cohorts': index['cohorts']}


def application(folder):
    text = (folder / 'docs/APPLICATION_RESPONSE.md').read_text(encoding='utf-8')
    written = text.split('## Written answer', 1)[1].split('## Approximately', 1)[0]
    spoken = text.split('## Approximately 90-second spoken explanation', 1)[1].split('## Evidence', 1)[0]
    written_count = len(written.split())
    spoken_count = len(spoken.split())
    require(130 <= written_count <= 180, 'Application response outside 130–180 words')
    require(180 <= spoken_count <= 240, 'Spoken explanation needs pacing review')
    return {'written_words': written_count, 'spoken_words': spoken_count,
            'spoken_seconds_at_140_wpm': round(spoken_count / 140 * 60, 1)}


def presentation(folder):
    path = folder / 'presentations/engineering-case-study.pptx'
    with zipfile.ZipFile(path) as package:
        require(package.testzip() is None, 'PPTX CRC error')
        slides = [n for n in package.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)]
        chart_tag = '{http://schemas.openxmlformats.org/drawingml/2006/chart}chartSpace'
        table_tag = '{http://schemas.openxmlformats.org/drawingml/2006/main}tbl'
        # Native parts need not use PowerPoint's usual chart1.xml filename.
        charts = [n for n in package.namelist() if n.endswith('.xml')
                  and ET.fromstring(package.read(n)).tag == chart_tag]
        tables = sum(sum(1 for _ in ET.fromstring(package.read(n)).iter(table_tag)) for n in slides)
        workbooks = [n for n in package.namelist() if n.endswith('.xlsx')]
        require(len(slides) == 9 and len(charts) == 2 and tables == 5, 'Unexpected slide/chart/table structure')
        require(len(workbooks) == 2, 'Native chart data workbooks missing')
    return {'sha256': sha(path), 'slides': len(slides), 'charts': len(charts), 'tables': tables,
            'embedded_workbooks': len(workbooks), 'native_powerpoint_execution': 'not tested'}


def archive(candidate):
    info_path = candidate / 'archive-info.json'
    if not info_path.exists():
        return {'status': 'not requested'}
    info = json.loads(info_path.read_text(encoding='utf-8'))
    path = candidate / info['path']
    require(sha(path) == info['sha256'], 'Raw archive checksum mismatch')
    # Verify each member after redaction; original digests are distinct provenance.
    import hashlib
    with zipfile.ZipFile(path) as package:
        require(package.testzip() is None, 'Raw archive CRC error')
        members = json.loads(package.read('ARCHIVE_MANIFEST.json'))
        require(len(members) == info['files'], 'Archive member count mismatch')
        for row in members:
            require(hashlib.sha256(package.read(row['path'])).hexdigest() == row['archive_sha256'],
                    'Archive member checksum mismatch: ' + row['path'])
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', default='runs/phase4-publication/repository')
    parser.add_argument('--out', default='phase4/release-validation.json')
    args = parser.parse_args()
    folder = (ROOT / args.publication).resolve()
    require(folder.is_dir(), 'Publication directory missing')
    findings = scan(folder)
    require(not findings, 'Bounded publication scan findings: ' + json.dumps(findings))
    files = [p for p in folder.rglob('*') if p.is_file()]
    banned = {'.exe', '.dll', '.gguf', '.zip', '.nsys-rep', '.sqlite', '.env'}
    for path in files:
        require(path.suffix.lower() not in banned, 'Excluded binary/secret asset: ' + str(path.relative_to(folder)))
        require(path.stat().st_size <= 25 * 1024 * 1024, 'Publication file exceeds 25 MiB: ' + str(path.relative_to(folder)))
    manifest = json.loads((folder.parent / 'publication-manifest.json').read_text(encoding='utf-8'))
    require(len(files) == len(manifest['files']), 'Unmanifested publication files')
    for row in manifest['files']:
        require(sha(folder / row['path']) == row['publication_sha256'], 'Publication checksum mismatch: ' + row['path'])
        require(sha(ROOT / row['path']) == row['original_sha256'], 'Source changed after export: ' + row['path'])
    report = {'status': 'pass', 'preservation': preservation(),
              'publication': {'files': len(files), 'bytes': sum(p.stat().st_size for p in files),
                              'largest_file_bytes': max(p.stat().st_size for p in files),
                              'local_links_checked': links(folder), 'bounded_scan_findings': findings},
              'evidence': evidence(folder), 'application': application(folder),
              'presentation': presentation(folder), 'archive': archive(folder.parent)}
    destination = ROOT / args.out
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
