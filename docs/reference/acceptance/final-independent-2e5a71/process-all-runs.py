from pathlib import Path
import json,subprocess
from harbor_helper.execution.worker import process_birth
from harbor_helper.persistence.store import Store
base=Path('/tmp/hh-checker-independent-2e5a71-20261012')
work=Path('/tmp/hh-checker-wt-2e5a71-20261012')
checks=[]; alive=[]; open_ports=[]
for root in sorted(base.glob('live*')):
 if not (root/'state/queue.sqlite').exists(): continue
 rows=Store(root/'state').runs(); matches=[]
 for row in rows:
  if row.get('pid') and process_birth(row['pid'])==row.get('birth'):
   item={'root':root.name,'run':row['id'],'pid':row['pid'],'birth':row.get('birth')}; alive.append(item);matches.append(item)
 events=root/'capture/events.jsonl'
 closed=[]
 if events.exists():
  for line in events.read_text().splitlines():
   try:e=json.loads(line)
   except json.JSONDecodeError:continue
   if e.get('kind')=='teardown_identity': closed.append(all(e.get('ports_closed',{}).values()))
 post=[]
 for p in (root/'capture').glob('post-run-teardown-*.json'):
  try:post.append(json.loads(p.read_text()).get('port_closed') is True)
  except Exception:post.append(False)
 checks.append({'root':root.name,'run_rows':len(rows),'live_birth_matches':matches,'recorded_service_proxy_ports_closed':closed,'post_run_ports_closed':post})
assert not alive,alive
assert all(all(x['recorded_service_proxy_ports_closed']) and all(x['post_run_ports_closed']) for x in checks),checks
value={'candidate_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=work,text=True).strip(),'isolated_roots':checks,'live_worker_birth_matches':alive}
(base/'capture/process-all-runs.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value,indent=2))
