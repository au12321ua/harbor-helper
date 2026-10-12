import pathlib,re,zipfile,tarfile,hashlib,json,subprocess
root=pathlib.Path('/tmp/hh-final-integration');base=pathlib.Path('/tmp/hh-final-integration-evidence')
files=[root/'README.md',root/'AGENTS.md',root/'docs/HANDOFF.md']+list((root/'docs/guides').glob('*.md'))+list((root/'docs/reference').glob('*.md'))+list((root/'skills').rglob('*.md'))+list((root/'docs/architecture').glob('*.md'))+[root/'docs/README.md']
links=[]
for p in files:
 for ref in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)',p.read_text()):
  if '://' in ref or ref.startswith(('mailto:','#')):continue
  target=(p.parent/ref.split('#')[0]).resolve();assert target.exists(),(p,ref);links.append([str(p.relative_to(root)),ref])
print('current product/skill Markdown targets valid:',len(links),'(existence; heading anchors checked separately)')
wheel=next((base/'dist-fixed').glob('*.whl'));sdist=next((base/'dist-fixed').glob('*.tar.gz'))
with zipfile.ZipFile(wheel) as z:
 names=z.namelist();assert not any('/state/' in n or '/private/' in n for n in names)
 metadata=z.read('harbor_helper-0.1.0.dist-info/METADATA').decode();assert 'Version: 0.1.0' in metadata
 for p in (root/'src/harbor_helper/static').rglob('*'):
  if p.is_file():assert z.read(str(p.relative_to(root/'src')))==p.read_bytes()
 assert 'harbor-helper = harbor_helper.cli:main' in z.read('harbor_helper-0.1.0.dist-info/entry_points.txt').decode()
 print('wheel metadata=0.1.0, CLI entrypoint and all static bytes match source')
with tarfile.open(sdist) as t:
 names=t.getnames();prefix=names[0].split('/')[0]
 for p in (root/'skills/harbor-helper-research').rglob('*'):
  if p.is_file():assert t.extractfile(prefix+'/'+str(p.relative_to(root))).read()==p.read_bytes()
 for rel in ['README.md','AGENTS.md','docs/HANDOFF.md','docs/README.md','frontend/package.json','frontend/package-lock.json','frontend/src/App.tsx','frontend/src/api.ts','frontend/qa/final-integration-production.mjs','pyproject.toml','uv.lock']:
  assert t.extractfile(prefix+'/'+rel).read()==(root/rel).read_bytes()
 print('sdist product docs, frontend source/QA and locks match fixed candidate; complete copyable research skill; wheel intentionally ships Python/static')
assert json.loads((root/'frontend/package.json').read_text())['version']=='0.1.0'
assert not subprocess.check_output(['git','diff','6db930d','HEAD','--','src','tests','skills','uv.lock','pyproject.toml','frontend/package.json','frontend/package-lock.json','frontend/src'],cwd=root)
print('product/static/tests/skills/locks same as full-tested 6db930d; only new QA harness+archive')
print('release identifier 0.1.0 unchanged; no release tag selected or moved; Root must decide target before publication')
print(subprocess.check_output(['git','diff','94513631','HEAD','--','README.md','AGENTS.md','docs/HANDOFF.md','docs/guides','docs/reference/automation-api.md','docs/reference/service-acceptance.md','skills'],cwd=root,text=True))
