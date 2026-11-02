import copy
import time
import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical
from .environment import TaskingEnv
from .sensorphysics import environment_class

def configure(seed,device):
    torch.set_num_threads(1)
    torch.manual_seed(seed);np.random.seed(seed)
    # Current MPS builds lack deterministic implementations for some gradient
    # operations (notably scatter_reduce). Preserve seeded runs but surface a
    # warning on MPS; keep strict determinism for CPU and CUDA.
    torch.use_deterministic_algorithms(True,warn_only=device.type=='mps')

def compute_device(config):
    name=config.get('compute_device','cpu')
    if name == 'auto':
        if torch.cuda.is_available():
            name = 'cuda'
        elif getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available():
            name = 'mps'
        else:
            name = 'cpu'
    device=torch.device(name)
    if device.type=='mps' and not getattr(torch.backends, 'mps', None):
        raise RuntimeError('MPS was requested but is unavailable in this PyTorch runtime')
    if device.type=='mps' and not torch.backends.mps.is_available():
        raise RuntimeError('MPS was requested but is unavailable in this PyTorch runtime')
    if device.type=='cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA was requested but is unavailable in this PyTorch runtime')
    if device.type not in {'cpu','mps','cuda'}:
        raise ValueError('compute_device must be cpu, cuda, mps, or auto')
    return device

def _timed(function,device):
    if device.type=='mps':
        start=torch.mps.Event(enable_timing=True);end=torch.mps.Event(enable_timing=True)
        start.record();result=function();end.record();torch.mps.synchronize()
        return result,float(start.elapsed_time(end))/1000.
    if device.type=='cuda':
        start=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True)
        start.record();result=function();end.record();torch.cuda.synchronize(device)
        return result,float(start.elapsed_time(end))/1000.
    return function(),0.

class Agent(nn.Module):
    def __init__(self,obs_dim,actions,hp):
        super().__init__();w=int(hp['actor_width'])
        self.actor=nn.Sequential(nn.Linear(obs_dim,w),nn.Tanh(),nn.Linear(w,w),nn.Tanh(),nn.Linear(w,actions))
        layers=[];size=obs_dim*2
        for _ in range(int(hp['critic_depth'])):
            layers.extend([nn.Linear(size,w),nn.Tanh()]);size=w
        self.critic=nn.Sequential(*layers,nn.Linear(size,1))
        self.target_critic=copy.deepcopy(self.critic)
        for p in self.target_critic.parameters():p.requires_grad_(False)

    def central(self,obs):
        return torch.cat([obs,obs.mean(dim=-2,keepdim=True).expand_as(obs)],dim=-1)

    def distribution(self,obs,mask):
        return Categorical(logits=self.actor(obs).masked_fill(~mask,-1e9))

    def value(self,obs,target=False):
        net=self.target_critic if target else self.critic
        return net(self.central(obs)).squeeze(-1)

    def update_target(self,tau):
        with torch.no_grad():
            for t,p in zip(self.target_critic.parameters(),self.critic.parameters()): t.lerp_(p,tau)

def train(scenarios,config,hp,seed,episodes=None):
    device=compute_device(config)
    configure(seed,device);start=time.perf_counter();episodes=episodes or config['training_episodes']
    gpu_seconds=0.
    env_type=environment_class(config) if config.get('sensor_response_model') else TaskingEnv
    sample=env_type(scenarios[0],config,hp['claim_resolution'],seed)
    ob,_=sample.reset();model=Agent(ob.shape[-1],sample.k+1,hp).to(device)
    optimizer=torch.optim.Adam(list(model.actor.parameters())+list(model.critic.parameters()),lr=hp['learning_rate'])
    history=[]
    for episode in range(episodes):
        env=env_type(scenarios[episode%len(scenarios)],config,hp['claim_resolution'],seed+episode*1009)
        (ob,mask)=env.reset();observations=[];masks=[];actions=[];rewards=[];next_observations=[];dones=[]
        for _ in range(env.steps):
            x=torch.tensor(ob,device=device);m=torch.tensor(mask,device=device)
            with torch.no_grad():
                action,active=_timed(lambda:model.distribution(x,m).sample().cpu().numpy(),device)
                gpu_seconds+=active
            (next_ob,next_mask),reward,done=env.step(action)
            observations.append(ob);masks.append(mask);actions.append(action);rewards.append(reward)
            next_observations.append(next_ob);dones.append(done)
            ob,mask=next_ob,next_mask
        x=torch.tensor(np.array(observations),device=device);m=torch.tensor(np.array(masks),device=device);act=torch.tensor(np.array(actions),device=device)
        nxt=torch.tensor(np.array(next_observations),device=device);r=torch.tensor(rewards,dtype=torch.float32,device=device)[:,None]
        alive=1-torch.tensor(dones,dtype=torch.float32,device=device)[:,None]
        def update():
            with torch.no_grad(): target=r+hp['discount']*alive*model.value(nxt,target=True)
            value=model.value(x);advantage=(target-value).detach()
            advantage=(advantage-advantage.mean())/(advantage.std()+1e-6)
            dist=model.distribution(x,m)
            actor_loss=-(dist.log_prob(act)*advantage).mean()-hp['entropy']*dist.entropy().mean()
            critic_loss=(value-target).square().mean()
            loss=actor_loss+0.5*critic_loss
            if not torch.isfinite(loss): raise RuntimeError('Non-finite training loss')
            optimizer.zero_grad();loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.0);optimizer.step()
            model.update_target(hp['target_tau'])
            return loss
        loss,active=_timed(update,device);gpu_seconds+=active
        history.append(dict(episode=episode,loss=float(loss.detach().cpu().item()),**env.metrics()))
    return model,history,time.perf_counter()-start,gpu_seconds

def evaluate(model,scenarios,config,hp,seed,policy='learned',traces=False):
    records=[];trace_data=[]
    env_type=environment_class(config) if config.get('sensor_response_model') else TaskingEnv
    device=next(model.parameters()).device if policy=='learned' and model is not None else torch.device('cpu')
    gpu_seconds=0.
    for si,scenario in enumerate(scenarios):
        env=env_type(scenario,config,hp['claim_resolution'],seed+si*1009)
        ob,mask=env.reset()
        for _ in range(env.steps):
            if policy=='learned':
                x=torch.tensor(ob,device=device);m=torch.tensor(mask,device=device)
                with torch.no_grad():
                    act,active=_timed(lambda:model.distribution(x,m).probs.argmax(-1).cpu().numpy(),device)
                    gpu_seconds+=active
            elif policy=='random':
                act=np.array([env.rng.choice(np.flatnonzero(m)) for m in mask])
            elif policy=='greedy':
                _,_,angle,_,allowed=env.geometry();act=np.full(env.a,env.k);claimed=set()
                urgency=np.clip((env.t*env.dt-env.last_seen)/env.c['custody_seconds'],0,5)
                for i in range(env.a):
                    score=urgency-env.c['slew_penalty']*angle[i]**2
                    score[~allowed[i]]=-np.inf
                    for j in claimed: score[j]=-np.inf
                    if np.isfinite(score).any():act[i]=np.argmax(score);claimed.add(act[i])
            else: raise ValueError('Unknown policy')
            (ob,mask),_,done=env.step(act)
        records.append(env.metrics())
        if traces: trace_data.append(env.trace)
    aggregate={key:float(np.mean([r[key] for r in records])) for key in records[0]}
    return aggregate,trace_data,gpu_seconds
