from pathlib import Path
import hashlib, json, subprocess, tarfile, zipfile
root=Path('/tmp/hh-checker-wt-2e5a71-20261012')
out=Path('/tmp/hh-checker-independent-2e5a71-20261012')
old='8519109ee3c7d012d826fdfa5df7ec894b783c71'
version_fix='2c104ac1bf5d3b565fef8264c44b7c74922b9752'
changed=subprocess.check_output(['git','diff','--name-only',version_fix,'HEAD'],cwd=root,text=True).splitlines()
product=subprocess.check_output(['git','diff','--name-only',version_fix,'HEAD','--','src','tests','skills','frontend/src','frontend/qa','pyproject.toml','uv.lock'],cwd=root,text=True).splitlines()
assert not product, product
# Version-only lineage was applied in the base; this final candidate adds evidence/report files only.
assert all(p.startswith('docs/') for p in changed), changed
# Build output itself is byte-equivalent to the candidate static tree.
subprocess.run(['git','diff','--exit-code','HEAD','--','src/harbor_helper/static'],cwd=root,check=True)
tracked=subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines()
wheel=out/'dist/harbor_helper-0.2.0-py3-none-any.whl'
sdist=out/'dist/harbor_helper-0.2.0.tar.gz'
with zipfile.ZipFile(wheel) as z:
 names=set(z.namelist())
 meta=z.read('harbor_helper-0.2.0.dist-info/METADATA').decode()
 entries=z.read('harbor_helper-0.2.0.dist-info/entry_points.txt').decode()
 assert '\nVersion: 0.2.0\n' in meta
 assert 'harbor-helper = harbor_helper.cli:main' in entries
 for p in tracked:
  if p.startswith('src/harbor_helper/'):
   packaged=p.removeprefix('src/')
   assert packaged in names and z.read(packaged)==(root/p).read_bytes(),p
with tarfile.open(sdist) as t:
 names=set(t.getnames())
 prefix='harbor_helper-0.2.0/'
 for p in tracked:
  packaged=prefix+p
  if packaged in names:
   assert t.extractfile(packaged).read()==(root/p).read_bytes(),p
# dependency lock equality versus the 0.1.0 metadata baseline, allowing only harbor-helper's own version.
import tomllib
lock=tomllib.loads((root/'uv.lock').read_text())
old_lock=tomllib.loads(subprocess.check_output(['git','show',old+':uv.lock'],cwd=root,text=True))
cur_pkg=next(x for x in lock['package'] if x['name']=='harbor-helper')
old_pkg=next(x for x in old_lock['package'] if x['name']=='harbor-helper')
assert cur_pkg['version']=='0.2.0' and old_pkg['version']=='0.1.0'
cur_pkg['version']=old_pkg['version']
assert lock==old_lock
result={
 'candidate_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
 'package_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [wheel,sdist]},
 'dist_files':[p.name for p in [wheel,sdist]],
 'candidate_build_static_matches_tree':True,
 'wheel_python_and_static_files_match_tracked_candidate':True,
 'sdist_tracked_file_matches_checked_when_included':True,
 'cli_entrypoint':'harbor_helper.cli:main',
 'version':'0.2.0',
 'dependency_lock_semantics_unchanged_except_local_package_version':True,
 'changed_paths_since_version_fix':changed,
}
(out/'capture/package-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
