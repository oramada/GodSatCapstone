import csv
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import socket
import time
import numpy as np
import torch
from scipy.stats import norm, t as student_t
from .orbits import ROOT
from .scenario import prepare, load
from .learning import train,evaluate,compute_device
from .design import FACTORS,decode,encode,screening,screening_analysis,ccd,fit_surface

RESPONSES=['objective','custody_continuity','slew_energy_proxy','false_track_proxy','wall_seconds','gpu_hours']

def runtime_provenance():
    package_names = ['duckdb', 'matplotlib', 'numpy', 'pyarrow', 'pytz', 'scipy', 'sgp4', 'torch']
    source_digest = hashlib.sha256()
    for source in sorted((ROOT / 'godsat').glob('*.py')):
        source_digest.update(source.name.encode())
        source_digest.update(source.read_bytes())
    return {
        'godsat_factorial': importlib.metadata.version('godsat-factorial'),
        'source_sha256': source_digest.hexdigest(),
        'python': platform.python_version(),
        'python_implementation': platform.python_implementation(),
        'platform': platform.platform(),
        'machine': platform.machine(),
        'packages': {name: importlib.metadata.version(name) for name in package_names},
    }

def device_provenance(config):
    device = compute_device(config)
    result = {'requested': config.get('compute_device', 'cpu'), 'selected': str(device)}
    if device.type == 'cuda':
        result['accelerator'] = torch.cuda.get_device_name(device)
        result['compute_capability'] = list(torch.cuda.get_device_capability(device))
    return result

def scenario_fingerprint(scenarios):
    """Hash every array used by the experiment so changed data invalidates caches."""
    digest = hashlib.sha256()
    for split in sorted(scenarios):
        for index, scenario in enumerate(scenarios[split]):
            for key in sorted(scenario):
                value = scenario[key]
                if not isinstance(value, np.ndarray):
                    continue
                array = np.ascontiguousarray(value)
                header = json.dumps({
                    'split': split, 'index': index, 'key': key,
                    'dtype': array.dtype.str, 'shape': array.shape,
                }, sort_keys=True).encode()
                digest.update(header)
                digest.update(array.tobytes())
    return digest.hexdigest()

def write_json(path,obj):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(obj,indent=2,allow_nan=False));temp.replace(path)

def export_csv(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with open(path,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def write_regime_replays(folder,scenarios,traces,config):
    """Save a dashboard replay for each test regime at the first held-out date."""
    regimes=config.get('test_regimes',['leo'])
    if len(scenarios['test']) < len(regimes) or len(traces) < len(regimes):
        raise ValueError('Missing held-out scenario traces for one or more test regimes')
    replay_folder=pathlib.Path(folder)/'replays';replay_folder.mkdir(parents=True,exist_ok=True)
    for index,regime in enumerate(regimes):
        scenario=scenarios['test'][index]
        replay={'date':config['test_dates'][0],'orbit_regime':regime,
            'times':scenario['times'].tolist(),'ids':scenario['ids'].tolist(),
            'agents':int(scenario['agents']),
            'positions_km':np.nan_to_num(scenario['states'][:,:,:3]).tolist(),
            'valid':np.isfinite(scenario['states'][:,:,0]).tolist(),
            'trace':traces[index],'frame':'TEME'}
        write_json(replay_folder/f'{regime}.json',replay)
        if index==0:
            write_json(pathlib.Path(folder)/'replay.json',replay)

def cost_performance_ratios(validation):
    """Summarize tasking outcomes per measured end-to-end second, by seed.

    These are descriptive ratios, not a substitute for calibrated electrical
    energy or GPU-hours. Learned-policy wall time includes training and test;
    heuristic wall time covers evaluation only, so comparisons must preserve
    that accounting boundary in the report.
    """
    from scipy.stats import t as student_t
    result={}
    labels=sorted({row['configuration'] for row in validation})
    for label in labels:
        rows=[row for row in validation if row['configuration']==label]
        def ratio(row,metric):
            runtime=row.get('wall_seconds')
            if runtime in (None,'') or float(runtime)<=0:return None
            value=row.get(metric)
            if value in (None,''):return None
            return float(value)/float(runtime)
        values={
            'custody_per_wall_second':[
                value for row in rows if (value:=ratio(row,'custody_continuity')) is not None],
            'slew_proxy_per_wall_second':[
                value for row in rows if (value:=ratio(row,'slew_energy_proxy')) is not None],
        }
        result[label]={}
        for name,observations in values.items():
            n=len(observations)
            mean=float(np.mean(observations)) if n else None
            if n>1:
                half=float(student_t.ppf(.975,n-1)*np.std(observations,ddof=1)/np.sqrt(n))
            else:
                half=None
            result[label][name]={'mean':mean,'ci95_half_width':half,'n':n}
    return result

def run_treatment(name,hp,scenarios,config,folder,seed,force=False):
    path=folder/'runs'/(name+'.json');checkpoint=folder/'models'/(name+'.pt')
    runtime=runtime_provenance()
    device=device_provenance(config)
    scenario_sha256=config.get('_scenario_sha256') or scenario_fingerprint(scenarios)
    signature=hashlib.sha256(json.dumps({
        'hp':hp,'config':config,'seed':seed,'runtime':runtime,
        'device':device,'scenario_sha256':scenario_sha256,
    },sort_keys=True).encode()).hexdigest()
    if path.exists() and not force:
        record=json.loads(path.read_text())
        if record['signature']!=signature:
            raise ValueError('Resume config, scenario data, or software/device runtime differs: use a new output folder')
        original_keys=set(record)
        record.setdefault('compute_device','cpu');record.setdefault('gpu_hours',0.)
        record.setdefault('gpu_active_seconds',record['gpu_hours']*3600.)
        record.setdefault('energy_estimate_kwh',None)
        record.setdefault('runtime',runtime);record.setdefault('device_provenance',device)
        if set(record)!=original_keys:
            write_json(path,record)
        return record
    start=time.perf_counter();cpu_start=time.process_time()
    model,history,train_seconds,gpu_seconds=train(scenarios['train'],config,hp,seed)
    metrics,_,validation_gpu_seconds=evaluate(model,scenarios['validation'],config,hp,9001)
    gpu_seconds+=validation_gpu_seconds
    wall=time.perf_counter()-start
    record={'name':name,'hyperparameters':hp,'seed':seed,'signature':signature,**metrics,
        'wall_seconds':wall,'train_seconds':train_seconds,'cpu_seconds':time.process_time()-cpu_start,
        'gpu_active_seconds':gpu_seconds,'gpu_hours':gpu_seconds/3600.,
        'compute_device':str(model.actor[0].weight.device),'device_provenance':device,'energy_estimate_kwh':None,
        'energy_estimate_note':'No calibrated machine power measurement; accelerator active time is measured with CUDA or MPS events when available.',
        'node':socket.gethostname(),'runtime':runtime,
        'python':platform.python_version(),'torch':torch.__version__,
        'numpy':np.__version__,'timestamp_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        'training_history':history}
    if config.get('assumed_host_power_watts') is not None:
        power=float(config['assumed_host_power_watts'])
        if power<=0 or not np.isfinite(power):raise ValueError('Assumed host power must be finite and positive')
        record.update(assumed_host_power_watts=power,assumed_host_energy_kwh=power*wall/3.6e6,
            assumed_host_energy_note='Scenario assumption times measured treatment wall duration; not calibrated electrical energy or incremental process power.')
    checkpoint.parent.mkdir(parents=True,exist_ok=True);torch.save({'hp':hp,'obs_dim':model.actor[0].in_features,'actions':model.actor[-1].out_features,'state_dict':{k:v.detach().cpu() for k,v in model.state_dict().items()}},checkpoint)
    write_json(path,record);print(f"{name}: custody={record['custody_continuity']:.3f}, objective={record['objective']:.3f}, {wall:.1f}s",flush=True)
    return record

def bayesian_candidates(records,rng):
    if len(records)<8: return rng.uniform(-1,1,7)
    X=np.array([encode(r['hyperparameters']) for r in records]);y=np.array([r['objective'] for r in records])
    # Several coded points collapse to the same integer network/resolution after
    # decoding. Aggregate duplicates and keep kernel scales fixed: fitting seven
    # length scales to a small, noisy, quantized sample can overflow the posterior.
    unique,inverse=np.unique(X,axis=0,return_inverse=True)
    means=np.array([y[inverse==i].mean() for i in range(len(unique))])
    if len(unique)<4:return rng.uniform(-1,1,7)
    # Stable Matérn-3/2 GP with fixed length scale and explicit Cholesky jitter.
    # This is equivalent to a fixed-prior Gaussian-process acquisition model but
    # avoids unstable hyperparameter fitting in the small, quantized design.
    def covariance(a,b):
        distance=np.sqrt(np.maximum(0.,((a[:,None,:]-b[None,:,:])**2).sum(axis=-1)))
        scaled=np.sqrt(3.)*distance
        return (1.+scaled)*np.exp(-scaled)
    scale=max(float(means.std()),1e-8);y_norm=(means-means.mean())/scale
    gram=covariance(unique,unique)+np.eye(len(unique))*.1
    try:
        chol=np.linalg.cholesky(gram)
        weights=np.linalg.solve(chol.T,np.linalg.solve(chol,y_norm))
    except np.linalg.LinAlgError:
        return rng.uniform(-1,1,7)
    candidates=rng.uniform(-1,1,(2048,7));cross=covariance(candidates,unique)
    # Avoid the platform BLAS GEMV path here: this small matrix-vector product
    # has emitted invalid/overflow results on macOS despite bounded inputs.
    mean=means.mean()+scale*np.sum(cross*weights[None,:],axis=1)
    projected=np.linalg.solve(chol,cross.T)
    std=scale*np.sqrt(np.maximum(1.-np.sum(projected*projected,axis=0),1e-12))
    gain=mean-y.max()-.005;z=gain/np.maximum(std,1e-12)
    ei=gain*norm.cdf(z)+std*norm.pdf(z)
    if not np.isfinite(ei).all():return rng.uniform(-1,1,7)
    return candidates[np.argmax(ei)]

def campaign(config,folder,center_replicates=1,force=False):
    from .scope import validate_execution
    validate_execution()
    folder=pathlib.Path(folder);folder.mkdir(parents=True,exist_ok=True)
    response_metrics=list(dict.fromkeys(RESPONSES+config.get('additional_responses',[])))
    run_config={**config,'response_surface_center_replicates':int(center_replicates)}
    cfg_path=folder/'config.json'
    if cfg_path.exists() and json.loads(cfg_path.read_text())!=run_config:raise ValueError('Output folder already uses another configuration')
    write_json(cfg_path,run_config)
    scenarios={split:[load(prepare(date,config,regime=regime))
        for date in config[split+'_dates'] for regime in config.get(split+'_regimes',['leo'])]
        for split in ['training','validation','test']}
    scenarios['train']=scenarios.pop('training')
    scenario_sha256=scenario_fingerprint(scenarios)
    execution_config={**config,'_scenario_sha256':scenario_sha256}
    x,order=screening(config['design_seed']);screen=[]
    for i,row in enumerate(x): screen.append(run_treatment(f'screen_{i:02d}',decode(row),scenarios,execution_config,folder,config['training_seed'],force))
    design_rows=[dict(run=i,standard_order=int(order[i]),**{chr(65+j):float(v) for j,v in enumerate(row)},**decode(row)) for i,row in enumerate(x)]
    export_csv(folder/'screening_design.csv',design_rows)
    analyses={metric:screening_analysis(x,[r[metric] for r in screen]) for metric in response_metrics}
    selection=analyses['objective']['selected_indices'];write_json(folder/'screening_analysis.json',analyses)
    local=ccd(center_replicates,config['design_seed']);responses=[];center_number=0
    for i,p in enumerate(local):
        full=np.zeros(7);full[selection]=p
        seed=config['training_seed']
        if np.all(p==0):seed+=center_number*7919;center_number+=1
        responses.append(run_treatment(f'rsm_{i:02d}',decode(full),scenarios,execution_config,folder,seed,force))
    export_csv(folder/'rsm_design.csv',[dict(run=i,x1=float(p[0]),x2=float(p[1]),x3=float(p[2]),**r['hyperparameters']) for i,(p,r) in enumerate(zip(local,responses))])
    surfaces={m:fit_surface(local,[r[m] for r in responses]) for m in response_metrics}
    write_json(folder/'response_surfaces.json',surfaces)
    optimum=np.zeros(7);optimum[selection]=surfaces['objective']['bounded_optimum'];recommended=decode(optimum)
    bo=[];rng=np.random.default_rng(config['design_seed'])
    # Matched treatment budget: 31 for exact paper design; augmented design matches its larger actual count.
    for i in range(len(screen)+len(responses)):
        coded=bayesian_candidates(bo,rng);bo.append(run_treatment(f'bo_{i:02d}',decode(coded),scenarios,execution_config,folder,config['training_seed'],force))
    bo_best=max(bo,key=lambda r:r['objective'])['hyperparameters']
    configs={'baseline':config['baseline'],'doe_recommended':recommended,'bayesian_best':bo_best}
    validation=[]
    # Retrain from scratch for all five seeds. Test dates were never used in fitting or selection.
    for label,hp in configs.items():
        for seed in config['validation_seeds']:
            r=run_treatment(f'validate_{label}_{seed}',hp,scenarios,execution_config,folder,seed,force)
            checkpoint=folder/'models'/(r['name']+'.pt')
            from .learning import Agent
            saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
            model=Agent(saved['obs_dim'],saved['actions'],saved['hp']);model.load_state_dict(saved['state_dict'])
            from .learning import compute_device
            model=model.to(compute_device(config))
            evaluation_started=time.perf_counter()
            test,trace,test_gpu_seconds=evaluate(model,scenarios['test'],config,hp,seed+50000,traces=True)
            end_to_end_seconds=r['wall_seconds']+time.perf_counter()-evaluation_started
            validation.append(dict(configuration=label,seed=seed,**test,wall_seconds=end_to_end_seconds,
                gpu_hours=r.get('gpu_hours',0.)+test_gpu_seconds/3600.,compute_device=r.get('compute_device','cpu'),energy_estimate_kwh=None))
            if label=='doe_recommended' and seed==config['validation_seeds'][0]:
                write_regime_replays(folder,scenarios,trace,config)
    for policy in ['greedy','random']:
        for seed in config['validation_seeds']:
            evaluation_started=time.perf_counter()
            test,_,_=evaluate(None,scenarios['test'],config,config['baseline'],seed+50000,policy=policy)
            validation.append(dict(configuration=policy,seed=seed,**test,wall_seconds=time.perf_counter()-evaluation_started,
                gpu_hours=0.,compute_device='cpu',energy_estimate_kwh=None))
    export_csv(folder/'validation.csv',validation)
    all_runs=screen+responses+bo
    export_csv(folder/'responses.csv',[{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in all_runs])
    summaries={}
    for label in list(configs)+['greedy','random']:
        entries=[r for r in validation if r['configuration']==label];n=len(entries)
        summaries[label]={}
        for metric in response_metrics:
            v=np.array([r[metric] for r in entries]);se=v.std(ddof=1)/np.sqrt(n) if n>1 else 0
            margin=float(student_t.ppf(.975,n-1)*se) if n>1 else None
            summaries[label][metric]={'mean':float(v.mean()),'ci95_half_width':margin,'n':n}
    comparisons={}
    baseline=[r for r in validation if r['configuration']=='baseline'];optimized=[r for r in validation if r['configuration']=='doe_recommended']
    for metric in list(dict.fromkeys(['custody_continuity','slew_energy_proxy','false_track_proxy','objective']+config.get('additional_responses',[]))):
        before=np.array([r[metric] for r in baseline]);after=np.array([r[metric] for r in optimized]);delta=after-before
        se=delta.std(ddof=1)/np.sqrt(len(delta));margin=float(student_t.ppf(.975,len(delta)-1)*se)
        comparisons[metric]={'paired_mean_change':float(delta.mean()),'paired_ci95_half_width':margin,
            'relative_change_percent':float((after.mean()/before.mean()-1)*100) if abs(before.mean())>1e-12 else None}
    ground_summary_path=ROOT/'data/ground_sensor/ilrs_lageos1_npt/sensor_summary.json'
    ground_summary=json.loads(ground_summary_path.read_text()) if ground_summary_path.exists() else None
    if ground_summary and ground_summary.get('status')=='completed':
        ground_observations=f"{ground_summary['raw_measurement_records']} ILRS LAGEOS-1 normal points from {ground_summary['ground_stations']} stations; not used to train tasking or dropout policies"
        ground_locations='station identifiers in CRD; surveyed coordinates not included in this dataset'
    else:
        ground_observations='not available at campaign execution time'
        ground_locations='none in campaign inputs'
    result={'status':'completed','study_kind':config.get('study_kind','research'),
        'screening_runs':len(screen),'rsm_runs':len(responses),'bayesian_runs':len(bo),
        'rsm_center_replicates':int(center_replicates),'rsm_augmented_for_pure_error':center_replicates>1,
        'validation_retrains':len(configs)*len(config['validation_seeds']),
        'selected_factors':[FACTORS[i] for i in selection],'recommended_hyperparameters':recommended,
        'sensor_cohort':config.get('sensor_cohort','current_payload'),
        'sensor_host_status_interpretation':(
            'Current active-GP/SATCAT snapshot backcast through the archive; does not establish historical operating status.'
            if config.get('sensor_cohort')=='current_active_payload' else None),
        'compute_device':device_provenance(config)['selected'],
        'compute_device_requested':config.get('compute_device','cpu'),
        'device_provenance':device_provenance(config),
        'scenario_sha256':scenario_sha256,
        'runtime':runtime_provenance(),
        'sensor_response_model':config.get('sensor_response_model','legacy_proxy'),
        'additional_responses':config.get('additional_responses',[]),
        'total_gpu_hours':float(sum(r.get('gpu_hours',0.) for r in all_runs)+sum(r.get('gpu_hours',0.) for r in validation if r['configuration'] in configs)),
        'energy_estimates_available':False,
        'target_cohort':config.get('target_cohort','current_payload'),
        'comparison_configurations':configs,'heldout_test_dates':config['test_dates'],
        'scenario_regimes':{split:config.get(split+'_regimes',['leo']) for split in ['training','validation','test']},
        'test_summary':summaries,'paired_comparisons':comparisons,
        'cost_performance_ratios':cost_performance_ratios(validation),
        'total_training_wall_seconds':float(sum(r['wall_seconds'] for r in all_runs)+sum(r['wall_seconds'] for r in validation if r['configuration'] in configs)),
        'published_baseline_available':False,'sensor_data_provenance':{'ground_sensor_observations':ground_observations,'ground_station_locations':ground_locations,'measured_sensor_performance':'ILRS LAGEOS-1 CRD normal-point return rates; observations are conditioned on acquired passes and do not label failed acquisitions','study_ground_data_used':False,'sensor_model':'hypothetical onboard sensors with configuration-defined detection, field of regard, slew limit, and normalized slew proxy','targets':'catalog orbital objects from the configured historical cohort; may include payloads, debris, and rocket bodies'},'limitations':['New implementation, not original GoDSAT','No catalog-wide measured sensor calibration or failed-acquisition labels','Synthetic space-to-space sensor assumptions','Slew and false-track responses are proxies','Reduced-precision historical elements','Short sampled episodes do not cover every orbit','One date per validation/test split']+(['Three center runs provide only two pure-error degrees of freedom'] if center_replicates>1 else ['One center point means no pure-error replication or formal lack-of-fit estimate'])}
    write_json(folder/'summary.json',result)
    from .report import generate
    generate(folder,x,screen,local,responses,analyses,surfaces,result)
    return result
