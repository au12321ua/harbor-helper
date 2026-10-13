import json,os,shutil,signal,socket,subprocess,sys,time
from pathlib import Path
import httpx
base=Path(os.environ['HH_EVIDENCE_ROOT']); source=base/'live-certified'; root=Path(os.environ.get('HH_DRAIN_ROOT',str(base/'live-maintenance-drain'))); state=root/'state'; private=root/'private'; work=root/'fixture-execution'; capture=root/'capture'
for p in (root,private,work,capture,root/'home',root/'home/.config',root/'home/.cache',root/'home/.local/share',root/'profile/.config',root/'profile/.cache',root/'profile/hf',root/'profile/docker'):p.mkdir(mode=0o700,parents=True,exist_ok=True)
shutil.copytree(source/'state',state,dirs_exist_ok=True)
shutil.copy(source/'private/master.key',private/'master.key'); (private/'master.key').chmod(0o600)
service=json.loads((state/'service.json').read_text());service['master_file']=str(private/'master.key');(state/'service.json').write_text(json.dumps(service)+'\n');(state/'service.json').chmod(0o600)
shutil.copytree(source/'fixture-execution',work,dirs_exist_ok=True)
worker=work/'harbor_helper/execution/worker.py';worker.write_text(worker.read_text().replace('time.sleep(8)','time.sleep(20)'))
sys.path.insert(0,str(work))
from harbor_helper.persistence.store import Store
store=Store(state)
for row in store.runs():
 fields={}
 if row['status']=='cleanup_blocked':fields.update(status='succeeded',reason=None)
 if row.get('audit_status')!='clean':fields.update(audit_status='clean',audit_reason=None)
 if fields:store.update(row['id'],**fields)

def port():
 s=socket.socket();s.bind(('127.0.0.1',0));p=s.getsockname()[1];s.close();return p
api_port=port();url=f'http://127.0.0.1:{api_port}';http_log=(capture/'http-service.log').open('wb');worker_log=(capture/'supervisor.log').open('wb')
api_code=f"import uvicorn; from harbor_helper.service.api import create_app; uvicorn.run(create_app({str(state)!r},start_scheduler=False),host='127.0.0.1',port={api_port},access_log=False)"
start_time=time.time()
api=subprocess.Popen([sys.executable,'-c',api_code],cwd=os.environ['HH_CANDIDATE_ROOT'],env=os.environ.copy(),stdout=http_log,stderr=http_log)
worker_proc=None
try:
 for _ in range(200):
  try:httpx.get(url+'/api/v1/health',timeout=1,trust_env=False);break
  except httpx.RequestError:time.sleep(.05)
 else:raise RuntimeError('isolated API did not start')
 worker_proc=subprocess.Popen([sys.executable,'-m','harbor_helper.worker','supervise',str(state)],cwd=work,env=os.environ.copy(),stdout=worker_log,stderr=worker_log,start_new_session=True)
 for _ in range(300):
  marker=state/'scheduler.json'
  if marker.exists() and json.loads(marker.read_text()).get('pid')==worker_proc.pid:break
  if worker_proc.poll() is not None:raise RuntimeError('fixture supervisor exited before ready')
  time.sleep(.05)
 else:raise RuntimeError('fixture supervisor did not become ready')
 (capture/'drain-inputs.json').write_text(json.dumps({'url':url,'dataset_id':'fixture-dataset'})+'\n')
 browser=subprocess.run(['node',str(Path(os.environ['HH_CANDIDATE_ROOT'])/'frontend/qa/maintenance-drain-followup.mjs')],cwd=os.environ['HH_CANDIDATE_ROOT'],env={**os.environ,'HH_BROWSER_EVIDENCE':str(capture)},capture_output=True,timeout=100,check=False)
 (capture/'browser.stdout').write_bytes(browser.stdout);(capture/'browser.stderr').write_bytes(browser.stderr);(capture/'browser.exit').write_text(str(browser.returncode)+'\n')
 if browser.returncode:raise RuntimeError('browser drain flow failed; raw browser stderr retained')
finally:
 if worker_proc and worker_proc.poll() is None:
  worker_proc.send_signal(signal.SIGTERM)
  try:worker_proc.wait(timeout=10)
  except subprocess.TimeoutExpired:worker_proc.kill();worker_proc.wait(timeout=5)
 if api.poll() is None:
  api.send_signal(signal.SIGTERM)
  try:api.wait(timeout=10)
  except subprocess.TimeoutExpired:api.kill();api.wait(timeout=5)
 http_log.close();worker_log.close()
 with socket.socket() as s:closed=s.connect_ex(('127.0.0.1',api_port))!=0
 alive=[]
 from harbor_helper.execution.worker import process_birth
 for row in Store(state).runs():
  if row.get('pid') and process_birth(row['pid'])==row.get('birth'):alive.append(row['id'])
 (capture/'cleanup.json').write_text(json.dumps({'api_pid':api.pid,'api_exit':api.returncode,'supervisor_pid':worker_proc.pid if worker_proc else None,'supervisor_exit':worker_proc.returncode if worker_proc else None,'api_port':api_port,'api_port_closed':closed,'live_worker_birth_matches':alive},indent=2)+'\n')
 assert closed and not alive
