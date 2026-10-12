import hashlib,importlib.metadata,json,os,pathlib,subprocess,sys,tarfile,tomllib,zipfile
root=pathlib.Path('/tmp/hh-final-integration');base=pathlib.Path('/tmp/hh-version-020-evidence');old='8519109ee3c7d012d826fdfa5df7ec894b783c71'
def previous(rel):return subprocess.check_output(['git','show',old+':'+rel],cwd=root)
project=tomllib.loads((root/'pyproject.toml').read_text());before=tomllib.loads(previous('pyproject.toml').decode());assert project['project'].pop('version')=='0.2.0';assert before['project'].pop('version')=='0.1.0';assert project==before
lock=tomllib.loads((root/'uv.lock').read_text());before=tomllib.loads(previous('uv.lock').decode())
for content,expected in [(lock,'0.2.0'),(before,'0.1.0')]:
 item=next(p for p in content['package'] if p['name']=='harbor-helper');assert item.pop('version')==expected
assert lock==before
for rel in ['frontend/package.json','frontend/package-lock.json']:
 current=json.loads((root/rel).read_text());before=json.loads(previous(rel))
 assert current.pop('version')=='0.2.0' and before.pop('version')=='0.1.0'
 if 'packages' in current:assert current['packages'][''].pop('version')=='0.2.0' and before['packages'][''].pop('version')=='0.1.0'
 assert current==before
assert importlib.metadata.version('harbor-helper')=='0.2.0'
assert not subprocess.check_output(['git','diff',old,'HEAD','--','src','tests','skills','frontend/src','frontend/qa','docs/reference/acceptance'],cwd=root)
assert not subprocess.check_output(['git','diff','HEAD','--','src','tests','skills','frontend','pyproject.toml','uv.lock'],cwd=root)
print('Only metadata versions and README label changed; all dependencies/resolutions/integrities unchanged; installed editable metadata 0.2.0; product/static/QA/tests/skills and all original evidence unchanged')
wheel=base/'dist/harbor_helper-0.2.0-py3-none-any.whl';sdist=base/'dist/harbor_helper-0.2.0.tar.gz';out=base/'wheel-inspect';out.mkdir(exist_ok=False)
tracked=subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines()
with zipfile.ZipFile(wheel) as z:
 metadata=z.read('harbor_helper-0.2.0.dist-info/METADATA').decode();assert '\nVersion: 0.2.0\n' in metadata
 assert 'harbor-helper = harbor_helper.cli:main' in z.read('harbor_helper-0.2.0.dist-info/entry_points.txt').decode()
 for rel in tracked:
  if rel.startswith('src/harbor_helper/'):assert z.read(rel.removeprefix('src/'))==(root/rel).read_bytes(),rel
 z.extractall(out)
 print('0.2.0 wheel metadata/CLI entrypoint and every tracked Python/static source byte match fixed candidate')
with tarfile.open(sdist) as t:
 prefix='harbor_helper-0.2.0/'
 for rel in tracked:
  assert t.extractfile(prefix+rel).read()==(root/rel).read_bytes(),rel
 print('0.2.0 sdist every tracked file matches fixed candidate, including package/locks/docs/frontend/static/complete research skill and all historical raw evidence')
cli=subprocess.run([sys.executable,'-m','harbor_helper.cli','--help'],cwd=out,env={**os.environ,'PYTHONPATH':str(out)},capture_output=True,check=False)
(base/'capture/wheel-cli.stdout').write_bytes(cli.stdout);(base/'capture/wheel-cli.stderr').write_bytes(cli.stderr);(base/'capture/wheel-cli.exit').write_text(str(cli.returncode)+'\n');(base/'capture/wheel-cli.command.json').write_text(json.dumps({'argv':[sys.executable,'-m','harbor_helper.cli','--help'],'cwd':str(out),'env_override':{'PYTHONPATH':str(out)},'parent_env_allowlist':'version-check.command.json','source':'extracted built 0.2.0 wheel'},indent=2)+'\n')
assert cli.returncode==0 and b'harbor-helper' in cli.stdout
print('Built wheel CLI help entry executes without HTTP/source/execution calls')
print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [wheel,sdist]},indent=2))
subprocess.run(['git','diff',old,'HEAD','--check'],cwd=root,check=True)
print(subprocess.check_output(['git','diff',old,'HEAD'],cwd=root,text=True))
