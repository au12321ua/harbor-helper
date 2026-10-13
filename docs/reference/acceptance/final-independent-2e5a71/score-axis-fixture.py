import json,shutil
from pathlib import Path
from harbor_helper.results.reports import report
from harbor_helper.service.machine import report_view
base=Path('/tmp/hh-checker-independent-2e5a71-20261012')
work=Path('/tmp/hh-checker-wt-2e5a71-20261012')
source=base/'live-verified/state/runs/hh-a301f09670c44e93'
out=base/'synthetic-score-cases-retry'
out.mkdir(mode=0o700,exist_ok=True)
manifest=json.loads((source/'manifest.json').read_text())
class Store:
 def __init__(self,root): self.root=root; self.status='succeeded'; self.reason=None
 def path(self,_): return self.root/'runs'/'sample'
 def get(self,_): return {'status':self.status,'reason':self.reason}
 def update(self,_,**fields): self.status=fields.get('status',self.status); self.reason=fields.get('reason',self.reason)

def case(name,rewards,exception):
 path=out/name/'runs'/'sample'; trial=path/'harbor'/'run-fixture'/'task__fixture'; trial.mkdir(mode=0o700,parents=True,exist_ok=False)
 (path/'manifest.json').write_text(json.dumps(manifest))
 (trial/'result.json').write_text(json.dumps({'task_name':'fixture/checker-task','trial_name':'task__fixture','verifier_result':{'rewards':rewards},'exception_info':exception}))
 store=Store(out/name); value=report(store,'sample'); view=report_view(value)
 return {'case':name,'report_status':value['status'],'complete':value['complete'],'valid_attempts':value['valid_attempts'],'attempt':view['tasks'][0]['attempts'][0]}
values=[case('zero',{'reward':0.0},None),case('missing',{},None),case('execution-failure',{'reward':0.0},{'exception_type':'SyntheticExecutionFailure','exception_message':'fixture-only failure'})]
assert values[0]['attempt']['failure'] is None and values[0]['attempt']['rewards']=={'reward':0.0}
assert values[1]['attempt']['failure']=='missing_score' and values[1]['attempt']['rewards'] is None
assert values[2]['attempt']['failure']=='execution_failure' and values[2]['attempt']['rewards'] is None
(base/'capture/score-axis-fixtures-retry.json').write_text(json.dumps({'fixture_only':True,'candidate_sha':'2e5a71f2e7e47c6b19cca2d2219ae62384502097','cases':values},indent=2)+'\n')
print(json.dumps(values,indent=2))
