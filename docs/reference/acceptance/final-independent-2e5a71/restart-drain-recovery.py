import json,os,signal,subprocess,sys,time
from pathlib import Path
base=Path(os.environ['HH_EVIDENCE_ROOT']);root=base/'live-maintenance-drain';state=root/'state';work=root/'fixture-execution';capture=root/'capture'
sys.path.insert(0,str(Path(os.environ['HH_CANDIDATE_ROOT'])/'src'))
from harbor_helper.persistence.store import Store
from harbor_helper.service.application import Application
from harbor_helper.service.admission import maintenance,readiness
from harbor_helper.service.machine import run_state,scheduler
store=Store(state)
running=[r for r in store.runs() if r['id']=='hh-6f386af263f64b11'][0]
queued=[r for r in store.runs() if r['id']=='hh-886fe967a39a442d'][0]
assert running['status']=='running' and (store.path(running['id'])/'outcome.json').exists()
assert queued['status']=='queued' and queued['cancel']==1
proc=subprocess.Popen([sys.executable,'-m','harbor_helper.worker','supervise',str(state)],cwd=work,env=os.environ.copy(),stdout=(capture/'recovery-supervisor.log').open('wb'),stderr=subprocess.STDOUT,start_new_session=True)
try:
 for _ in range(200):
  marker=state/'scheduler.json'
  if marker.exists() and json.loads(marker.read_text()).get('pid')==proc.pid:break
  if proc.poll() is not None:raise RuntimeError('fixture supervisor exited before ready')
  time.sleep(.05)
 else:raise RuntimeError('fixture scheduler did not publish ready identity')
 app=Application(store)
 start_ready=readiness(app,'044e53195e1742edae3a14fa6d569322')
 assert start_ready['maintenance']['paused'] is True and start_ready['scheduler']['state']=='ready',start_ready
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  a=store.get(running['id']);b=store.get(queued['id'])
  if a['status'] in {'succeeded','failed','cancelled'} and b['status']=='cancelled':break
  time.sleep(.1)
 a=store.get(running['id']);b=store.get(queued['id'])
 assert a['status']=='succeeded',a
 assert b['status']=='cancelled',b
 assert store.get(running['id'])['audit_status']=='clean'
 first_state=run_state(app,running['id']).model_dump();second_submission=app.data.submission('sub-c010ad4adcb44efd')
 assert first_state['resource']['state']=='released' and first_state['report']['state']=='available',first_state
 assert second_submission['status']=='cancelled',second_submission
 assert maintenance(app.data)['paused'] is True
 result={'fixture_only':True,'supervisor_restarted':True,'first_run_reconciled_from_existing_outcome':running['id'],'first_run_status':a['status'],'first_report_state':first_state['report']['state'],'queued_submission_cancel_flag_honored':queued['id'],'cancelled_run_status':b['status'],'maintenance_remained_paused':True,'scheduler_ready_did_not_resume_admission':True}
 (capture/'restart-drain-recovery.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
finally:
 if proc.poll() is None:
  proc.send_signal(signal.SIGTERM)
  try:proc.wait(timeout=10)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
 from harbor_helper.execution.processes import process_birth
 alive=[r['id'] for r in store.runs() if r.get('pid') and process_birth(r['pid'])==r.get('birth')]
 (capture/'restart-drain-teardown.json').write_text(json.dumps({'pid':proc.pid,'exit':proc.returncode,'live_worker_birth_matches':alive},indent=2)+'\n')
 assert not alive
