import os, pathlib, subprocess, sys, time
root=pathlib.Path('/tmp/hh-admission-numeric-correction/capture')
name, cwd, *argv=sys.argv[1:]
env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','UV_CACHE_DIR','PLAYWRIGHT_BROWSERS_PATH') if k in os.environ}
env.update(HOME='/tmp/hh-admission-numeric-correction/home', HARBOR_HOME='/tmp/hh-admission-numeric-correction/profile', XDG_CONFIG_HOME='/tmp/hh-admission-numeric-correction/home/.config', XDG_CACHE_HOME='/tmp/hh-admission-numeric-correction/home/.cache', HH_TEST_BROWSER='1', PLAYWRIGHT_BROWSERS_PATH='/home/pc/.cache/ms-playwright', LITELLM_LOCAL_MODEL_COST_MAP='True')
with (root/(name+'.log')).open('wb') as f:
 p=subprocess.run(argv,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
(root/(name+'.exit')).write_text(str(p.returncode)+'\n')
print(name, 'exit',p.returncode)
print((root/(name+'.log')).read_text()[-6000:])
sys.exit(p.returncode)
