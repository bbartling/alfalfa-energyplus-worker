import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path('_alfalfa_upstream')
reference = sys.argv[1] if len(sys.argv) > 1 else 'af3caee5036d6c6ac10558307d7fd31fe12857de'
Path('work').mkdir(exist_ok=True)
report = {}
for service, tracked, prefix in [('worker', 'alfalfa_worker', '/alfalfa'),
                                  ('web', 'alfalfa_web/server', '/srv/alfalfa')]:
    files = subprocess.check_output(['git', '-C', str(root), 'ls-files', tracked], text=True).splitlines()
    files = [f for f in files if Path(f).suffix in ('.py', '.rb', '.js', '.osw')]
    paths = {f: prefix + '/' + (f if service == 'worker' else f.removeprefix('alfalfa_web/')) for f in files}
    manifest = json.dumps(paths)
    script = """import hashlib,json,pathlib,sys
paths=json.loads(sys.stdin.read())
print(json.dumps({k:hashlib.sha256(pathlib.Path(v).read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest() if pathlib.Path(v).is_file() else None for k,v in paths.items()}))
"""
    if service == 'worker':
        result = subprocess.check_output(['docker','compose','exec','-T','worker','python3','-c',script], input=manifest, text=True)
    else:
        js = "const fs=require('fs'),c=require('crypto'),paths=JSON.parse(fs.readFileSync(0,'utf8')); console.log(JSON.stringify(Object.fromEntries(Object.entries(paths).map(([k,v])=>[k,fs.existsSync(v)?c.createHash('sha256').update(fs.readFileSync(v,'utf8').replaceAll('\\r\\n','\\n')).digest('hex'):null]))))"
        result = subprocess.check_output(['docker','compose','exec','-T','web','node','-e',js], input=manifest, text=True)
    actual = json.loads(result)
    def expected(f):
        return subprocess.check_output(['git','-C',str(root),'show',reference+':'+f])
    mismatches = [f for f in files if actual[f] != hashlib.sha256(expected(f).replace(b'\r\n',b'\n')).hexdigest()]
    report[service] = {'files_checked': len(files), 'mismatches': mismatches}
Path('work/upstream-source-audit.json').write_text(json.dumps({'reference': reference, 'services': report},indent=2))
print(json.dumps(report))
assert not any(v['mismatches'] for v in report.values())
