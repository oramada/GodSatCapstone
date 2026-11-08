"""Bounded local numerical jobs. No shell commands or caller-chosen output paths."""
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time

MAX_REQUEST = 2 * 1024 * 1024
MAX_OBJECTS = 2000
MAX_OBJECT_STEPS = 2_000_000
TIMEOUT_SECONDS = 180


def read_json(path):
    if path.stat().st_size > MAX_REQUEST:raise ValueError('Experiment input exceeds 2 MiB')
    return json.loads(path.read_text())


def atomic_json(path, value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,allow_nan=False));tmp.replace(path)


class ExperimentJobs:
    def __init__(self,root,catalog):
        self.root=Path(root);self.catalog=catalog;self.token=secrets.token_urlsafe(32)
        self.jobs={};self.lock=threading.Lock()

    def options(self):
        rows=self.catalog.scan()['artifacts'];templates=[];drivers=[]
        for row in rows:
            if not row['local']:continue
            if row['format']=='csv' and 'space-weather' in row['name'].lower():drivers.append({'id':row['id'],'name':row['path']})
            if row['format']!='json' or row['bytes']>MAX_REQUEST:continue
            if not (row['path'].startswith('configs/') or row['name']=='initial.json'):continue
            try:
                value=read_json(self.catalog.get(row['id']))
                if isinstance(value,dict) and value.get('schema')=='godsat.numerical.v1':
                    templates.append({'id':row['id'],'name':row['path']})
            except (ValueError,OSError):continue
        return {'token':self.token,'templates':templates,'drivers':drivers,
                'limits':{'max_objects':MAX_OBJECTS,'max_object_steps':MAX_OBJECT_STEPS,'timeout_seconds':TIMEOUT_SECONDS}}

    def template(self,identity):
        value=read_json(self.catalog.get(identity))
        from godsat.simulation.numerical import validate_experiment
        validate_experiment(value)
        return value

    def prepare(self,payload):
        from godsat.simulation.numerical import validate_experiment
        value=payload.get('config')
        epoch=validate_experiment(value)
        count=len(value['objects']);steps=round(value['duration_seconds']/value['integration_step_seconds'])
        if count>MAX_OBJECTS or count*steps>MAX_OBJECT_STEPS:raise ValueError('Interactive limit: 2,000 spacecraft and 2,000,000 spacecraft integration steps. Reduce count, duration, or use a larger step.')
        if importlib.util.find_spec('astropy') is None:raise ValueError('Numerical runs require the project simulation dependencies (Astropy).')
        driver=None
        if value.get('forces',{}).get('drag'):
            if not payload.get('driver_id'):raise ValueError('Select a local space-weather file for atmospheric drag.')
            path=self.catalog.get(payload['driver_id'])
            if path.suffix.lower()!='.csv':raise ValueError('Space-weather drivers must be CSV')
            from godsat.simulation.atmosphere import SpaceWeather
            weather=SpaceWeather(path)
            # Every driver bin touched by the run must be available before launch.
            end=epoch+dt.timedelta(seconds=value['duration_seconds']);instant=epoch
            while instant<end:
                weather.at(instant);instant+=dt.timedelta(hours=3)
            weather.at(end)
            if importlib.util.find_spec('pymsis') is None:raise ValueError('Atmospheric drag requires the project dynamics dependencies (pymsis).')
            driver={'path':path,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        return value,driver,{'objects':count,'frames':round(value['duration_seconds']/value['output_step_seconds'])+1,
            'duration_seconds':value['duration_seconds'],'integration_steps':steps,'object_steps':count*steps,
            'source_kind':value['source']['kind'],'forces':[k for k,v in value.get('forces',{}).items() if v],
            'note':'New numerical experiment from explicit osculating states. Results are model predictions, not observed tracks.'}

    def start(self,payload):
        config,driver,summary=self.prepare(payload)
        with self.lock:
            for job in self.jobs.values():
                self._refresh(job)
                if job['status']=='running':raise ValueError('A simulation is already running. Wait or cancel it first.')
            identity=secrets.token_hex(10)
            parent=self.root/'outputs'/'studio-runs'
            if parent.is_symlink() or (self.root/'outputs').is_symlink():raise ValueError('Run output directory must not be a symbolic link')
            parent.mkdir(parents=True,exist_ok=True);folder=parent/identity;folder.mkdir()
            atomic_json(folder/'initial.json',config)
            if driver:
                raw=driver['path'].read_bytes()
                if hashlib.sha256(raw).hexdigest()!=driver['sha256']:raise ValueError('Driver file changed during validation. Validate again.')
                (folder/'space-weather.csv').write_bytes(raw)
                atomic_json(folder/'driver-source.json',{'source':str(driver['path']),'sha256':driver['sha256']})
            log=(folder/'worker.log').open('wb')
            try:
                process=subprocess.Popen([sys.executable,'-m','godsat.studio.experiments','--worker',str(folder)],cwd=self.root,
                    stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPATH':str(self.root),'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
            finally:log.close()
            job={'id':identity,'status':'running','process':process,'folder':folder,'started':time.time(),'summary':summary}
            self.jobs[identity]=job
            timer=threading.Timer(TIMEOUT_SECONDS+.1,lambda:self._expire(identity));timer.daemon=True;timer.start()
            if len(self.jobs)>20:
                for key in list(self.jobs):
                    if key!=identity and self.jobs[key]['status']!='running':del self.jobs[key];break
            return self._public(job)

    def _expire(self,identity):
        with self.lock:
            if identity in self.jobs:self._refresh(self.jobs[identity])

    def _refresh(self,job):
        if job['status']!='running':return
        process=job['process'];code=process.poll()
        if code is None and time.time()-job['started']>TIMEOUT_SECONDS:
            process.kill();process.wait();job.update(status='failed',error='Run exceeded the 180-second interactive limit. Reduce the workload.');return
        if code is None:return
        result_path=job['folder']/'result.json'
        result=read_json(result_path) if result_path.is_file() else {'error':'Simulation worker exited without a result. See worker.log in the run folder.'}
        if code==0 and result.get('status')=='succeeded':
            job.update(status='succeeded',result=result)
            scene=(job['folder']/'scene.json').resolve()
            self.catalog.scan();job['scene_id']=hashlib.sha256(str(scene).encode()).hexdigest()[:20]
        else:job.update(status='failed',error=result.get('error','Simulation failed'))
        job['finished']=time.time()

    def _public(self,job):
        return {k:v for k,v in job.items() if k not in {'process','folder'}}|{'output':str(job['folder'].relative_to(self.root))}

    def get(self,identity):
        with self.lock:
            if identity not in self.jobs:raise ValueError('Unknown simulation job')
            job=self.jobs[identity];self._refresh(job);return self._public(job)

    def cancel(self,identity):
        with self.lock:
            if identity not in self.jobs:raise ValueError('Unknown simulation job')
            job=self.jobs[identity];self._refresh(job)
            if job['status']=='running':
                job['process'].terminate()
                try:job['process'].wait(timeout=3)
                except subprocess.TimeoutExpired:job['process'].kill();job['process'].wait()
                job.update(status='cancelled',finished=time.time())
            return self._public(job)


def worker(folder):
    folder=Path(folder);started=time.perf_counter()
    try:
        from godsat.simulation.numerical import integrate_experiment
        from godsat.simulation.atmosphere import SpaceWeather,MsisAtmosphere
        config=read_json(folder/'initial.json')
        driver=folder/'space-weather.csv'
        atmosphere=MsisAtmosphere(SpaceWeather(driver)) if driver.exists() else None
        scene,_=integrate_experiment(config,atmosphere)
        scene['title']=f'Experiment · {len(scene["objects"]):,} spacecraft'
        raw=json.dumps(scene,allow_nan=False,separators=(',',':')).encode()
        if len(raw)>64*1024*1024:raise ValueError('Result exceeds the 64 MiB interactive scene limit')
        temporary=folder/'scene.tmp';temporary.write_bytes(raw);temporary.replace(folder/'scene.json')
        atomic_json(folder/'result.json',{'status':'succeeded','elapsed_seconds':time.perf_counter()-started,
            'scene_sha256':hashlib.sha256(raw).hexdigest(),'objects':len(scene['objects']),'frames':len(scene['times'])})
    except Exception as exc:
        atomic_json(folder/'result.json',{'status':'failed','error':str(exc)[:2000]})
        raise


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--worker',type=Path,required=True)
    worker(parser.parse_args().worker)
