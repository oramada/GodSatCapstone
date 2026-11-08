// Coordinates and derivatives must share a frame. Missing data stays missing.
export function interpolatePosition(object,times,step){
 const t=Math.max(0,Math.min(step,times.length-1)),a=Math.floor(t),b=Math.min(a+1,times.length-1),u=t-a;
 const p=object.positions_km[a],q=object.positions_km[b];
 if(!p)return null;if(u===0)return p;if(!q)return null;
 if(!object.velocities_km_s)return p.map((v,k)=>v+(q[k]-v)*u);
 const v=object.velocities_km_s[a],w=object.velocities_km_s[b];if(!v||!w)return null;
 const h=(Date.parse(times[b])-Date.parse(times[a]))/1000,u2=u*u,u3=u2*u;
 return p.map((x,k)=>(2*u3-3*u2+1)*x+(u3-2*u2+u)*h*v[k]+(-2*u3+3*u2)*q[k]+(u3-u2)*h*w[k]);
}
