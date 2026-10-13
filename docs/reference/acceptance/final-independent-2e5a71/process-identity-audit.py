from pathlib import Path
import json,subprocess
from harbor_helper.execution.worker import process_birth
from harbor_helper.persistence.store import Store
b=Path("/tmp/hh-checker-independent-2e5a71-20261012");w=Path("/tmp/hh-checker-wt-2e5a71-20261012");live=b/"live-verified"
store=Store(live/"state");rows=store.runs();alive=[]
for row in rows:
 pid=row.get("pid");birth=row.get("birth")
 if pid and process_birth(pid)==birth: alive.append({"run":row["id"],"pid":pid,"birth":birth})
ports=[]
for line in (live/"capture/events.jsonl").read_text().splitlines():
 d=json.loads(line)
 if d.get("kind")=="teardown_identity" and not all(d.get("ports_closed",{}).values()): ports.append(d)
assert not alive,alive
assert not ports,ports
result={"candidate_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=w,text=True).strip(),"run_rows":len(rows),"live_worker_birth_matches":alive,"teardown_port_failures":ports,"tracked_product_static_diff":subprocess.check_output(["git","diff","--name-only","HEAD","--","src/harbor_helper/static"],cwd=w,text=True).splitlines()}
(b/"capture/process-identity-final.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result,indent=2))
