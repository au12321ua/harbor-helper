from pathlib import Path
import hashlib, subprocess, tarfile, json
root=Path('/tmp/hh-checker-wt-2e5a71-20261012'); archive=Path('/tmp/hh-checker-independent-2e5a71-20261012/dist/harbor_helper-0.2.0.tar.gz')
tracked=subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines()
with tarfile.open(archive) as t:
 names=set(t.getnames())
 missing=[p for p in tracked if 'harbor_helper-0.2.0/'+p not in names]
 skill=[p for p in tracked if p.startswith('skills/harbor-helper-research/')]
 assert not missing,missing
 for p in skill: assert t.extractfile('harbor_helper-0.2.0/'+p).read()==(root/p).read_bytes(),p
 value={'version':'0.2.0','tracked_files':len(tracked),'missing_tracked_files':missing,'research_skill_files':len(skill),'skill_bytes_match':True,'sdist_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
 print(json.dumps(value,indent=2)); Path('/tmp/hh-checker-independent-2e5a71-20261012/capture/sdist-completeness.json').write_text(json.dumps(value,indent=2)+'\n')
