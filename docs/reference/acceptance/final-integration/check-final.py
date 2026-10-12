import pathlib,re,subprocess,hashlib,json
root=pathlib.Path('/tmp/hh-final-integration');base=pathlib.Path('/tmp/hh-final-integration-evidence');dest=root/'docs/reference/acceptance/final-integration'
for path in [root/'docs/README.md',*dest.glob('*.md')]:
 for ref in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)',path.read_text()):
  if '://' in ref or ref.startswith(('#','mailto:')):continue
  assert (path.parent/ref.split('#')[0]).resolve().exists(),(path,ref)
print('new report/navigation links resolve; skill targets checked in release-fixed-check')
code=['src','frontend','tests','skills','uv.lock','pyproject.toml']
assert not subprocess.check_output(['git','diff','efbc359','--',*code],cwd=root)
print('report-only suffix: entire src/frontend/tests/skills/uv.lock/pyproject.toml matches fixed efbc359')
assert not subprocess.check_output(['git','diff','6db930d','HEAD','--','docs/reference/acceptance/admission','docs/reference/acceptance/admission-numeric-correction','docs/reference/acceptance/research-skill-0b05daf','docs/reference/acceptance/attachment-28102','docs/reference/acceptance/automation-50b0'],cwd=root)
print('all existing historical failure/limited evidence directories unchanged')
original=pathlib.Path('/tmp/hh-checker-admission-6db930-evidence');archive=root/'docs/reference/acceptance/admission-independent-6db930'
for p in archive.rglob('*'):
 if not p.is_file() or p.name in {'README.md','SHA256SUMS'}:continue
 rel=p.relative_to(archive);source=original/('SHA256SUMS' if p.name=='source-SHA256SUMS' else rel)
 assert p.read_bytes()==source.read_bytes(),rel
print('original admission report/metadata/necessary safe capture/source index byte-identical')
subprocess.run(['git','diff','--check','--','.',' :(exclude)**/capture/**'.strip()],cwd=root,check=True)
print('new product/docs diff whitespace check passed, raw capture deliberately excluded')
print(json.dumps({p:subprocess.check_output(['git','rev-parse','efbc359:'+p],cwd=root,text=True).strip() for p in code},indent=2))
