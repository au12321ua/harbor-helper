import pathlib,os,json,socket,subprocess
base=pathlib.Path('/tmp/hh-final-integration-evidence')
skip={os.getpid()};pid=os.getppid()
while pid and pid not in skip:
 skip.add(pid)
 try:pid=int(pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[1])
 except (OSError,ValueError,IndexError):break
remaining=[]
for proc in pathlib.Path('/proc').iterdir():
 if not proc.name.isdigit() or int(proc.name) in skip:continue
 try:argv=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace');cwd=str((proc/'cwd').resolve())
 except OSError:continue
 if str(base)+'/' in argv or cwd.startswith(str(base)+'/'):
  remaining.append({'pid':int(proc.name),'cwd':cwd})
assert not remaining,remaining
for folder in ['research-fixed','research-complete']:
 events=[json.loads(s) for s in (base/folder/'capture/events.jsonl').read_text().splitlines()]
 teardown=[e for e in events if e['kind']=='teardown_identity'][-1]
 assert all(teardown['ports_closed'].values()) and teardown['worker_births_released']
 print(folder,teardown)
with socket.socket() as s:assert s.connect_ex(('127.0.0.1',4173))!=0
main='/home/pc/auua/projects/cad/harbor-helper'
assert subprocess.check_output(['git','status','--porcelain'],cwd=main)==b''
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=main).decode().strip()=='9451363155674f138123c94c5e1ba51687139b36'
print('No task-local process remains; fixture ports closed; UI4173 closed; protected main tree clean at94513631. Formal service/state/master not mutated; not a state-content audit.')
print(subprocess.check_output(['git','ls-remote','origin','refs/heads/dev','refs/heads/master'],cwd=main,text=True))
