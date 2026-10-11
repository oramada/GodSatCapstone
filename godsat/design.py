"""The PDF's seven factor levels, correct generator group, and quadratic models."""
import itertools
import numpy as np
from scipy.optimize import minimize
from scipy.stats import f as f_distribution, norm

FACTORS=['learning_rate','discount','actor_width','critic_depth','entropy','claim_resolution','target_tau']
LOW=np.array([1e-5,.90,64,2,.01,32,.001])
HIGH=np.array([1e-3,.99,256,4,.10,128,.05])

def decode(x):
    values=(HIGH+LOW)/2+np.asarray(x)*(HIGH-LOW)/2
    result=dict(zip(FACTORS,values.tolist()))
    for k in ['actor_width','critic_depth','claim_resolution']:result[k]=int(round(result[k]))
    return result

def encode(hp): return (np.array([hp[k] for k in FACTORS])-(HIGH+LOW)/2)/((HIGH-LOW)/2)

def screening(seed=2026):
    rows=[]
    # A changes fastest in standard order.
    for d,c,b,a in itertools.product([-1.,1.],repeat=4): rows.append([a,b,c,d,a*b*c,a*b*d,a*c*d])
    design=np.array(rows);order=np.random.default_rng(seed).permutation(16)
    return design[order],order

def defining_words():
    generators=[set('ABCE'),set('ABDF'),set('ACDG')];words={'I'}
    for flags in itertools.product([0,1],repeat=3):
        word=set()
        for include,g in zip(flags,generators):
            if include:word^=g
        words.add(''.join(sorted(word)) or 'I')
    return sorted(words,key=lambda w:(len(w),w))

def aliases(effect):
    e=set(effect) if effect!='I' else set()
    return sorted((''.join(sorted(e^(set(w) if w!='I' else set()))) or 'I' for w in defining_words()),key=lambda w:(len(w),w))

def screening_analysis(x,y):
    y=np.asarray(y);effects=2*np.sum(np.asarray(x)*y[:,None],axis=0)/len(y)
    # Pool six unique residual contrast columns (15 contrasts minus 7 main effects
    # leaves 8 columns; all are low-order aliases, so this is assumption-dependent).
    cols=[];labels=[]
    mains=[x[:,i] for i in range(7)]
    for i,j in itertools.combinations(range(7),2):
        col=x[:,i]*x[:,j]
        if any(np.array_equal(col,c) or np.array_equal(col,-c) for c in mains+cols):continue
        cols.append(col);labels.append(chr(65+i)+chr(65+j))
    contrasts=2*np.sum(np.array(cols)*y[None,:],axis=1)/len(y)
    residual_variance=float(np.sum((contrasts/2)**2)*len(y)/len(cols)) if cols else None
    order=np.argsort(-np.abs(effects))
    return {'main_effects':dict(zip(FACTORS,effects.tolist())),
        'selected_indices':order[:3].tolist(),'selected_factors':[FACTORS[i] for i in order[:3]],
        'two_factor_alias_effects':{label:{'effect':float(value),'aliases':aliases(label)} for label,value in zip(labels,contrasts)},
        'pooled_residual_variance':residual_variance,
        'noise_assumption':'All eight pooled two-factor alias contrasts are assumed inactive; no pure-error estimate.',
        'defining_relation':defining_words()}

def ccd(center_replicates=1,seed=2026):
    cube=list(itertools.product([-1.,1.],repeat=3));axial=[]
    for i in range(3):
        for sign in [-1.,1.]:
            p=[0.,0.,0.];p[i]=sign;axial.append(p)
    x=np.array(cube+axial+[[0.,0.,0.]]*center_replicates)
    return x[np.random.default_rng(seed).permutation(len(x))]

def quadratic_matrix(x):
    x=np.atleast_2d(x)
    return np.column_stack([np.ones(len(x)),x,x*x,x[:,0]*x[:,1],x[:,0]*x[:,2],x[:,1]*x[:,2]])

def fit_surface(x,y):
    x=np.array(x);y=np.array(y);matrix=quadratic_matrix(x)
    beta,resid,rank,_=np.linalg.lstsq(matrix,y,rcond=None)
    if rank<10: raise ValueError('Second-order model is not identifiable')
    predicted=np.sum(matrix*beta[None,:],axis=1);residual=y-predicted;sse=float(np.sum(residual*residual));df=len(y)-rank
    B=np.diag(beta[4:7]);B[0,1]=B[1,0]=beta[7]/2;B[0,2]=B[2,0]=beta[8]/2;B[1,2]=B[2,1]=beta[9]/2
    eig=np.linalg.eigvalsh(B)
    try:stationary=np.linalg.solve(2*B,-beta[1:4])
    except np.linalg.LinAlgError:stationary=None
    def predicted_y(point): return float(np.sum(quadratic_matrix(point)[0]*beta))
    starts=[np.zeros(3)]+[np.array(p) for p in itertools.product([-1,1],repeat=3)]
    options=[minimize(lambda p:-predicted_y(p),s,bounds=[(-1,1)]*3,method='L-BFGS-B') for s in starts]
    best=min(options,key=lambda r:r.fun)
    ridge=[]
    for radius in np.linspace(.25,np.sqrt(3),8):
        fits=[minimize(lambda p:-predicted_y(p),np.zeros(3),bounds=[(-1,1)]*3,
            constraints=[{'type':'ineq','fun':lambda p,r=radius:r*r-np.sum(p*p)}],method='SLSQP')]
        for s in starts[1:]:
            fits.append(minimize(lambda p:-predicted_y(p),s*min(radius/np.sqrt(3),1),bounds=[(-1,1)]*3,
                constraints=[{'type':'ineq','fun':lambda p,r=radius:r*r-np.sum(p*p)}],method='SLSQP'))
        valid=[r for r in fits if r.success and np.sum(r.x*r.x)<=radius*radius+1e-6]
        if valid:
            r=min(valid,key=lambda r:r.fun);ridge.append({'radius':float(radius),'point':r.x.tolist(),'prediction':float(-r.fun)})
    groups={}
    for row,value in zip(x,y):groups.setdefault(tuple(row),[]).append(value)
    pure_df=sum(len(v)-1 for v in groups.values());pure_sse=sum(sum((np.array(v)-np.mean(v))**2) for v in groups.values())
    lof_df=len(groups)-rank
    if pure_df>0 and pure_sse>0 and lof_df>0:
        F=max(0,sse-pure_sse)/lof_df/(pure_sse/pure_df)
        lof={'F':float(F),'p_value':float(f_distribution.sf(F,lof_df,pure_df)),
             'pure_error_df':int(pure_df),'lack_of_fit_df':int(lof_df)}
    else:lof={'available':False,'reason':'No positive replicated pure-error estimate; a 15-run CCD has only one center observation.'}
    return {'coefficients':beta.tolist(),'coefficient_order':['intercept','x1','x2','x3','x1_squared','x2_squared','x3_squared','x1_x2','x1_x3','x2_x3'],
        'rank':int(rank),'residual_df':int(df),'sse':sse,'rmse':float(np.sqrt(sse/df)) if df>0 else None,
        'stationary_point':stationary.tolist() if stationary is not None else None,
        'eigenvalues':eig.tolist(),'classification':'maximum' if np.all(eig<0) else 'minimum' if np.all(eig>0) else 'saddle_or_flat',
        'bounded_optimum':best.x.tolist(),'predicted_optimum':float(-best.fun),'ridge':ridge,
        'lack_of_fit':lof,'residuals':residual.tolist(),'predicted':predicted.tolist()}
