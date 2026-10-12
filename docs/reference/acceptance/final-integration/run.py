import json,os,pathlib,subprocess,sys,time
base=pathlib.Path('/tmp/hh-final-integration-evidence'); work=pathlib.Path('/tmp/hh-final-integration')
env={'PATH':'/home/pc/.local/bin:/home/pc/.nvm/versions/node/v22.23.1/bin:/usr/local/bin:/usr/bin:/bin','HOME':str(base/'home'),'UV_CACHE_DIR':str(base/'uv-cache'),'npm_config_cache':str(base/'npm-cache'),'PLAYWRIGHT_BROWSERS_PATH':'/home/pc/.cache/ms-playwright','HH_TEST_BROWSER':'1','LANG':'C.UTF-8'}
for key,suffix in {'XDG_CONFIG_HOME':'home/.config','XDG_CACHE_HOME':'home/.cache','XDG_DATA_HOME':'home/.local/share','HARBOR_HOME':'profile','HARBOR_CONFIG':'profile/.config','HARBOR_CACHE':'profile/.cache','HF_HOME':'profile/hf','DOCKER_CONFIG':'profile/docker'}.items():env[key]=str(base/suffix)
for key,value in env.items():
 if key.endswith('_HOME') or key in ('HOME','UV_CACHE_DIR','npm_config_cache','HARBOR_HOME','HARBOR_CONFIG','HARBOR_CACHE','HF_HOME','DOCKER_CONFIG'):pathlib.Path(value).mkdir(parents=True,exist_ok=True)
name=sys.argv[1]; argv=sys.argv[2:]; cwd=work/'frontend' if name.startswith(('npm','build','lint','ui')) else work
if name.startswith('research-'):env['HH_TASK_ROOT']=str(base/name)
capture=base/'capture';capture.mkdir(exist_ok=True)
(capture/(name+'.command.json')).write_text(json.dumps({'argv':argv,'cwd':str(cwd),'env_allowlist':env,'version':subprocess.check_output(['git','rev-parse','HEAD'],cwd=work,text=True).strip(),'started':time.time()},ensure_ascii=False,indent=2)+'\n')
with (capture/(name+'.stdout')).open('wb') as out,(capture/(name+'.stderr')).open('wb') as err:
 result=subprocess.run(argv,cwd=cwd,env=env,stdout=out,stderr=err)
(capture/(name+'.exit')).write_text(str(result.returncode)+'\n')
print(name,'exit',result.returncode);print((capture/(name+'.stdout')).read_text()[-3000:]);print((capture/(name+'.stderr')).read_text()[-1500:]);sys.exit(result.returncode)
