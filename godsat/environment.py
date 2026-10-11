"""Configurable, explicitly synthetic sensor model over real historical orbit geometry."""
import numpy as np
from .scenario import line_of_sight


def rescale_markov_persistence(persistence, stationary_outage_rate,
                               reference_step_seconds, step_seconds):
    """Convert a two-state outage persistence probability between cadences.

    The stationary outage fraction is held fixed.  The second eigenvalue of the
    reference transition matrix is raised to the elapsed-time ratio, yielding
    the equivalent transition matrix at the simulation cadence.
    """
    persistence = float(persistence)
    rate = float(stationary_outage_rate)
    reference = float(reference_step_seconds)
    step = float(step_seconds)
    if not 0 <= persistence < 1:
        raise ValueError("persistence must be in [0, 1)")
    if not 0 <= rate < 1:
        raise ValueError("stationary_outage_rate must be in [0, 1)")
    if reference <= 0 or step <= 0:
        raise ValueError("reference and simulation steps must be positive")
    if rate == 1:
        return persistence
    entry = rate * (1 - persistence) / max(1 - rate, 1e-12)
    eigenvalue = persistence - entry
    exponent = step / reference
    if eigenvalue < 0:
        rounded = round(exponent)
        if not np.isclose(exponent, rounded):
            raise ValueError("cannot rescale a negative Markov eigenvalue by a fractional step")
        scaled_eigenvalue = eigenvalue ** int(rounded)
    else:
        scaled_eigenvalue = eigenvalue ** exponent
    return float(rate + (1 - rate) * scaled_eigenvalue)

class TaskingEnv:
    def __init__(self,scenario,config,resolution=64,seed=0,dropout_probability=0.0,dropout_mode='independent'):
        self.s=scenario;self.c=config;self.resolution=int(resolution)
        self.a=int(scenario['agents']);self.k=len(scenario['ids'])-self.a
        self.steps=len(scenario['times'])-1;self.dt=config['step_seconds']
        if not 0<=dropout_probability<1: raise ValueError('dropout_probability must be in [0, 1)')
        if dropout_mode not in {'independent','burst'}: raise ValueError('dropout_mode must be independent or burst')
        self.dropout_probability=float(dropout_probability);self.dropout_mode=dropout_mode
        self.seed=int(seed);self.reset()

    def reset(self):
        action_seed,priority_seed,detection_seed,dropout_seed,burst_initial_seed,burst_transition_seed=np.random.SeedSequence(self.seed).spawn(6)
        # Keep policy sampling, random sensor priority, nominal detections, and
        # injected failures on independent streams. Pre-drawn per (step, agent,
        # target) uniforms preserve common random numbers across dropout rates.
        self.rng=np.random.default_rng(action_seed)
        self.priority_rng=np.random.default_rng(priority_seed)
        self.detection_uniforms=np.random.default_rng(detection_seed).random((self.steps,self.a,self.k))
        self.dropout_uniforms=np.random.default_rng(dropout_seed).random((self.steps,self.a,self.k))
        self.burst_initial_uniforms=np.random.default_rng(burst_initial_seed).random(self.a)
        self.burst_transition_uniforms=np.random.default_rng(burst_transition_seed).random((self.steps,self.a))
        self.t=0;self.last_seen=np.full(self.k,-np.inf)
        self.pointing=np.zeros((self.a,3));self.pointing[:,0]=1
        self.previous_claims=np.zeros((self.a,self.k),bool)
        self.custody=[];self.observable_custody=[];self.energy=[];self.failures=0
        self.attempts=0;self.failures=0;self.dropout_trials=0;self.dropout_misses=0;self.conflicts=0;self.valid_steps=0;self.detected_steps=0
        self.dropout_state=self.burst_initial_uniforms<self.dropout_probability if self.dropout_mode=='burst' else np.zeros(self.a,dtype=bool)
        self.trace=[]
        return self.observation()

    def geometry(self):
        states=self.s['states'][self.t,:,:3]
        agents=states[:self.a];targets=states[self.a:]
        delta=targets[None,:,:]-agents[:,None,:]
        ranges=np.linalg.norm(delta,axis=-1)
        directions=delta/np.maximum(ranges[:,:,None],1e-9)
        finite=np.isfinite(directions).all(axis=-1)
        visible=finite&line_of_sight(agents[:,None,:],targets[None,:,:])&(ranges<=self.c['max_range_km'])&(ranges>1)
        angles=np.arccos(np.clip(np.sum(directions*self.pointing[:,None,:],axis=-1),-1,1))
        allowed=visible&(angles<=np.deg2rad(self.c['slew_rate_deg_s']*self.dt))
        # Sensor mounting field of regard is relative to local outward radial axis.
        outward=agents/np.maximum(np.linalg.norm(agents,axis=-1)[:,None],1)
        look=np.arccos(np.clip(np.sum(directions*outward[:,None,:],axis=-1),-1,1))
        allowed &= look<=np.deg2rad(self.c['field_of_regard_deg'])
        return np.nan_to_num(directions),np.nan_to_num(ranges),np.nan_to_num(angles),visible,allowed

    def observation(self):
        directions,ranges,angles,visible,allowed=self.geometry()
        age=np.clip((self.t*self.dt-self.last_seen)/self.c['custody_seconds'],0,5)/5
        claims=np.zeros((self.a,self.k))
        # Resolution discretizes shared inertial sky bins. A target may share a bin
        # with another claim; counts are relative to each observer's local geometry.
        az=np.arctan2(directions[:,:,1],directions[:,:,0]);el=np.arcsin(np.clip(directions[:,:,2],-1,1))
        bins=np.floor((az+np.pi)/(2*np.pi)*self.resolution).astype(int)*self.resolution
        bins+=np.clip(np.floor((el+np.pi/2)/np.pi*self.resolution).astype(int),0,self.resolution-1)
        for i in range(self.a):
            other=self.previous_claims.sum(axis=0)-self.previous_claims[i]
            for j in range(self.k): claims[i,j]=min(1,float(other[bins[i]==bins[i,j]].sum()))
        features=np.concatenate([directions,ranges[:,:,None]/self.c['max_range_km'],
            angles[:,:,None]/np.pi,visible[:,:,None],np.broadcast_to(age,(self.a,self.k))[:,:,None],
            claims[:,:,None]],axis=-1)
        obs=np.concatenate([features.reshape(self.a,-1),self.pointing],axis=1).astype(np.float32)
        mask=np.concatenate([allowed,np.ones((self.a,1),bool)],axis=1)
        return obs,mask

    def step(self,actions):
        actions=np.asarray(actions,int)
        if actions.shape!=(self.a,): raise ValueError('One action per sensor required')
        if np.any((actions<0)|(actions>self.k)): raise ValueError('Action outside target/idle range')
        if self.dropout_mode=='burst' and self.t>0:
            persistence=float(self.c.get('dropout_burst_persistence',0.8))
            if not 0<=persistence<1: raise ValueError('dropout_burst_persistence must be in [0, 1)')
            reference_step=float(self.c.get('dropout_burst_reference_step_seconds',self.dt))
            persistence=rescale_markov_persistence(
                persistence, self.dropout_probability, reference_step, self.dt)
            entry=self.dropout_probability*(1-persistence)/max(1-self.dropout_probability,1e-12)
            draw=self.burst_transition_uniforms[self.t]
            self.dropout_state=np.where(self.dropout_state,draw<persistence,draw<entry)
        directions,ranges,angles,visible,allowed=self.geometry()
        observed=np.zeros(self.k,bool);claims=np.zeros((self.a,self.k),bool)
        energies=np.zeros(self.a);attempts=0;failures=0;conflicts=0
        # Random priority removes fixed sensor-index preference; seed controls ties.
        for i in self.priority_rng.permutation(self.a):
            j=actions[i]
            if j==self.k: continue
            attempts+=1
            if not allowed[i,j]: failures+=1;continue
            if claims[:,j].any(): conflicts+=1;continue
            claims[i,j]=True
            self.dropout_trials+=1
            energies[i]=float((angles[i,j]/np.pi)**2)  # normalized squared slew angle, not joules
            self.pointing[i]=directions[i,j]
            epoch_age=self.s['ages'][self.t,self.a+j]
            probability=np.clip(self.c['detection_probability']-
                self.c['range_detection_penalty']*ranges[i,j]/self.c['max_range_km']-
                self.c['stale_detection_penalty']*epoch_age/self.c['max_element_age_hours'],0,1)
            dropped=False
            if self.dropout_mode=='burst':
                dropped=bool(self.dropout_state[i])
            else: dropped=self.dropout_uniforms[self.t,i,j]<self.dropout_probability
            if self.detection_uniforms[self.t,i,j]<probability and not dropped: observed[j]=True
            else:
                failures+=1
                if dropped:self.dropout_misses+=1
        self.last_seen[observed]=self.t*self.dt
        custody=(self.t*self.dt-self.last_seen)<=self.c['custody_seconds']
        valid=np.isfinite(self.s['states'][self.t,self.a:,0])
        opportunities=visible.any(axis=0)&valid
        continuity=float(custody[valid].mean()) if valid.any() else 0.
        observable=float(custody[opportunities].mean()) if opportunities.any() else 0.
        reward=continuity-self.c['slew_penalty']*energies.mean()-self.c['false_penalty']*failures/self.a-self.c['collision_penalty']*conflicts/self.a
        self.custody.append(continuity);self.observable_custody.append(observable);self.energy.append(energies.mean())
        self.valid_steps+=int(valid.sum());self.detected_steps+=int((custody&valid).sum())
        self.attempts+=attempts;self.failures+=failures;self.conflicts+=conflicts;self.previous_claims=claims
        self.trace.append({'step':self.t,'actions':actions.tolist(),'detected':np.flatnonzero(observed).tolist(),
                           'custody':continuity,'slew_proxy':float(energies.mean()),'reward':float(reward)})
        self.t+=1;done=self.t>=self.steps
        return self.observation(),float(reward),done

    def metrics(self):
        return {'custody_continuity':float(np.mean(self.custody)),
            'observable_custody':float(np.mean(self.observable_custody)),
            'slew_energy_proxy':float(np.mean(self.energy)),
            'false_track_proxy':self.failures/max(self.attempts,1),
            'conflict_rate':self.conflicts/max(self.attempts,1),
            'objective':float(np.mean([x['reward'] for x in self.trace])),
            'attempts':self.attempts,'steps':self.steps,'valid_target_fraction':self.valid_steps/(self.steps*self.k),
            'dropout_probability':self.dropout_probability,
            'dropout_misses':self.dropout_misses,'dropout_trials':self.dropout_trials,
            'dropout_rate_observed':self.dropout_misses/max(self.dropout_trials,1)}
