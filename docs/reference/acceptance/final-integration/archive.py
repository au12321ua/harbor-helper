import pathlib,shutil,json,hashlib,re
base=pathlib.Path('/tmp/hh-final-integration-evidence');dest=pathlib.Path('/tmp/hh-final-integration/docs/reference/acceptance/final-integration');capture=dest/'capture';capture.mkdir(exist_ok=True)
# Whitelisted captures, never whole state/home/profile/cache/private or screenshots.
for p in (base/'capture').iterdir():
 if p.is_file():shutil.copyfile(p,capture/p.name)
for folder in ['research','research-second','research-fixed','research-complete']:
 source=base/folder/'capture'
 for p in source.iterdir():
  if p.is_file() and p.suffix!='.png':
   target=capture/folder/p.name;target.parent.mkdir(exist_ok=True);shutil.copyfile(p,target)
for p in (base/'python-full-state').rglob('*'):
 if p.is_file() and p.name in {'http.log','http2.log','teardown.json','admission-cli.jsonl','browser.stdout','browser.stderr','browser.exit'}:
  target=capture/'python-full-fixture'/p.relative_to(base/'python-full-state');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
for name in ['run.py','check-release.py','check-cleanup.py','archive.py']:
 shutil.copyfile(base/name,dest/name)
secrets=[p.read_bytes().strip() for p in base.glob('research*/private/*.pat')]
secrets += [p.read_bytes() for p in base.glob('research*/private/master.key')]
for p in dest.rglob('*'):
 if not p.is_file():continue
 contents=p.read_bytes()
 assert not re.search(rb'hh_pat_v1_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])',contents),p
 assert not any(v and v in contents for v in secrets),p
 assert p.suffix not in {'.png','.sqlite','.whl','.gz'},p
metadata={'tested_product':'6db930d37b7e0f78e20fe3ec8221357b286b6352','final_harness':'efbc35908fd608da3f6cf11f8bd185586c5e4c79','packaging_version':'0.1.0','scope':'isolated actual loopback HTTP/static/browser/CLI/scheduler; source/execution fixtures only','excluded':['screenshots','state','home','profile','cache','private','PAT/master values','binary distribution files'],'artifacts':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (base/'dist-fixed').iterdir() if p.is_file()},'fixture_failed_first_run':'browser strict locator matched two new-experiment links;原stdout/stderr/exit及脚本快照保留','raw_capture_count':len([p for p in capture.rglob('*') if p.is_file()])}
(dest/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
print('whitelisted capture files',metadata['raw_capture_count'],'; no fake PAT/master raw bytes or screenshots/state in archive')
