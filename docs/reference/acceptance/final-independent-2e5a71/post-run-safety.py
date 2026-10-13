import json, os, signal, socket, subprocess, sys, time
from pathlib import Path
import httpx
from harbor_helper.persistence.store import Store
from harbor_helper.service.api import create_app
import uvicorn

base=Path(os.environ['HH_TASK_ROOT'])
state=base/'state'
capture=base/'capture'
store=Store(state)
rows=[r for r in store.runs() if r['status']=='succeeded' and r['audit_status']=='clean']
assert len(rows)>=2, len(rows)
audit_id=rows[-1]['id']; cleanup_id=rows[-2]['id']

def port():
 s=socket.socket(); s.bind(('127.0.0.1',0)); v=s.getsockname()[1]; s.close(); return v
p=port(); url=f'http://127.0.0.1:{p}'
log=(capture/'post-run-http-fifth.log').open('wb')
proc=subprocess.Popen([sys.executable,'-c',f"import uvicorn; from harbor_helper.service.api import create_app; uvicorn.run(create_app({str(state)!r},start_scheduler=False),host='127.0.0.1',port={p},access_log=False)"],cwd=os.environ['HH_CANDIDATE_ROOT'],env=os.environ.copy(),stdout=log,stderr=log,start_new_session=True)
try:
 for _ in range(200):
  try: httpx.get(url+'/api/v1/health',timeout=1,trust_env=False); break
  except httpx.RequestError: time.sleep(.05)
 else: raise RuntimeError('HTTP did not start')
 configure=subprocess.run([sys.executable,'-m','harbor_helper.cli','service','configure-token','--url',url,'--token-file',str(base/'private/checker-replacement.pat'),'--profile','postcheck','--json'],cwd=os.environ['HH_CANDIDATE_ROOT'],env=os.environ.copy(),capture_output=True,timeout=30,check=False)
 (capture/'post5-configure.stdout').write_bytes(configure.stdout); (capture/'post5-configure.stderr').write_bytes(configure.stderr); (capture/'post5-configure.exit').write_text(str(configure.returncode)+'\n')
 assert configure.returncode==0,configure.stderr
 readonly=subprocess.run([sys.executable,'-m','harbor_helper.cli','service','configure-token','--url',url,'--token-file',str(base/'private/checker-read-only.pat'),'--profile','readonly-probe','--json'],cwd=os.environ['HH_CANDIDATE_ROOT'],env=os.environ.copy(),capture_output=True,timeout=30,check=False)
 (capture/'post5-readonly-configure.stdout').write_bytes(readonly.stdout); (capture/'post5-readonly-configure.stderr').write_bytes(readonly.stderr); (capture/'post5-readonly-configure.exit').write_text(str(readonly.returncode)+'\n')
 assert readonly.returncode==0,readonly.stderr
 readonly_submit=subprocess.run([sys.executable,'-m','harbor_helper.cli','--remote-profile','readonly-probe','--json','submit','--dataset','fixture/checker-cedar@1','--agent','oracle','--task','fixture/checker-task','--attempts','1','--concurrency','1','--wall-seconds','120','--idempotency-key','checker-readonly-denied-20261012'],cwd=os.environ['HH_CANDIDATE_ROOT'],env=os.environ.copy(),capture_output=True,timeout=30,check=False)
 (capture/'post5-readonly-submit.stdout').write_bytes(readonly_submit.stdout); (capture/'post5-readonly-submit.stderr').write_bytes(readonly_submit.stderr); (capture/'post5-readonly-submit.exit').write_text(str(readonly_submit.returncode)+'\n')
 assert readonly_submit.returncode==1 and b'HTTP 403' in readonly_submit.stderr,readonly_submit.stderr
 event={'candidate_sha':os.environ['HH_CANDIDATE_SHA'],'fixture_marker':'synthetic post-run state changes; no container fault','readonly_submit_exit':readonly_submit.returncode,'readonly_submit_error':'HTTP 403','audit_run_id':audit_id,'cleanup_run_id':cleanup_id}
 # The isolated supervisor is stopped. Inject the audit axis only, keeping the recorded execution resource released.
 store.update(audit_id,audit_status='incomplete',audit_reason='Synthetic checker audit damage; fixture only')
 def cli(label,*args):
  cmd=[sys.executable,'-m','harbor_helper.cli','--remote-profile','postcheck','--json',*args]
  result=subprocess.run(cmd,cwd=os.environ['HH_CANDIDATE_ROOT'],env=os.environ.copy(),capture_output=True,timeout=30,check=False)
  for suffix,data in [('stdout',result.stdout),('stderr',result.stderr)]: (capture/f'post5-{label}.{suffix}').write_bytes(data)
  (capture/f'post5-{label}.exit').write_text(str(result.returncode)+'\n')
  try: value=json.loads(result.stdout)
  except Exception: value=None
  return value,result
 a,_=cli('audit-state','service','query',audit_id)
 assert a['resource']['state']=='released' and a['audit']['state']=='incomplete' and a['report']['state']=='blocked',a
 _,blocked=cli('audit-report','service','report',audit_id)
 assert blocked.returncode==1,blocked.returncode
 event['audit_gate']={'resource':a['resource'],'audit':a['audit'],'report':a['report'],'report_exit':blocked.returncode}
 # Distinct synthetic cleanup case: audit remains clean while unconfirmed cleanup occupies active capacity.
 store.update(cleanup_id,status='cleanup_blocked',reason='Synthetic unconfirmed resource cleanup; fixture only')
 c,_=cli('cleanup-state','service','query',cleanup_id)
 usage,_=cli('cleanup-capacity','usage')
 assert c['resource']['state']=='cleanup_blocked' and c['audit']['state']=='clean' and c['report']['state']=='blocked',c
 assert usage['active_jobs']>=1 and usage['active_trials']>=1,usage
 event['cleanup_gate']={'run':c,'active_jobs':usage['active_jobs'],'active_trials':usage['active_trials']}
 (capture/'post-run-safety-fifth.json').write_text(json.dumps(event,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(event,ensure_ascii=False,indent=2))
finally:
 if proc.poll() is None:
  proc.send_signal(signal.SIGTERM)
  proc.wait(timeout=10)
 log.close()
 with socket.socket() as s: closed=s.connect_ex(('127.0.0.1',p))!=0
 (capture/'post-run-teardown-fifth.json').write_text(json.dumps({'pid':proc.pid,'exit':proc.returncode,'port_closed':closed},indent=2)+'\n')
 assert closed and proc.poll() is not None
