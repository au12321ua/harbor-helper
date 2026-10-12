import subprocess,pathlib,hashlib,re,json
root=pathlib.Path('/tmp/hh-final-integration');dest=root/'docs/reference/acceptance/version-0.2.0';base=pathlib.Path('/tmp/hh-version-020-evidence')
assert not subprocess.check_output(['git','diff','2c104ac','--','src','frontend','tests','skills','pyproject.toml','uv.lock','README.md'],cwd=root)
assert not subprocess.check_output(['git','diff','8519109','HEAD','--','docs/reference/acceptance'],cwd=root)
assert hashlib.sha256((root/'docs/reference/acceptance/final-integration/engineering-report.md').read_bytes()).hexdigest()=='81934e3bcb35584406659d8f9ebf112329e56a271f3056c09995ec39c6a11133'
for path in [root/'docs/README.md',*dest.glob('*.md')]:
 for ref in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)',path.read_text()):
  if '://' not in ref and not ref.startswith('#'):assert (path.parent/ref.split('#')[0]).resolve().exists(),(path,ref)
for path in (dest/'capture').iterdir():assert path.read_bytes()==(base/'capture'/path.name).read_bytes(),path
subprocess.run(['git','diff','--check','--','.',' :(exclude)**/capture/**'.strip()],cwd=root,check=True)
print('Report-only suffix: all src/frontend/tests/skills/metadata locks/README unchanged from fixed2c104ac; old evidence tree and851 report hash unchanged; links/capture source equality/diff whitespace pass')
print(json.dumps({p:subprocess.check_output(['git','rev-parse','2c104ac:'+p],cwd=root,text=True).strip() for p in ['src','frontend','tests','skills','pyproject.toml','uv.lock','README.md']},indent=2))
