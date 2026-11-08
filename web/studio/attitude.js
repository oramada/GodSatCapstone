// Hamilton xyzw, active body-to-reference rotations. Never bridge a null sample.
export function attitudeAt(object,time){
 const rows=object?.attitude?.quaternions;if(!rows||!Number.isFinite(time)||time<0||time>rows.length-1)return null;
 const i=Math.floor(time),a=rows[i];if(!a)return null;
 const f=time-i;if(f===0)return a.slice();const b=rows[i+1];if(!b)return null;
 let dot=a.reduce((s,x,k)=>s+x*b[k],0),sign=1;if(dot<0){dot=-dot;sign=-1;}
 dot=Math.min(1,Math.max(-1,dot));let left,right;
 if(dot>.9995){left=1-f;right=f*sign;}
 else{const angle=Math.acos(dot),denom=Math.sin(angle);left=Math.sin((1-f)*angle)/denom;right=sign*Math.sin(f*angle)/denom;}
 const q=a.map((x,k)=>left*x+right*b[k]),length=Math.hypot(...q);return q.map(x=>x/length);
}

// Reference XYZ -> display X,Z,-Y; body axes are the unmodified mesh axes.
export function displayAttitude(q){
 const [x,y,z,w]=q,s=Math.SQRT1_2;
 return [s*(x-w),s*(y+z),s*(z-y),s*(w+x)];
}

export function attitudeCaption(object,time){
 if(!object?.attitude)return 'Spacecraft shape and Earth-pointing pose are generic illustrations, not measured geometry or attitude.';
 const a=object.attitude;
 if(!attitudeAt(object,time))return 'Attitude unavailable at this time. Missing samples are not interpolated; the spacecraft model is hidden.';
 return `${a.source.kind.toUpperCase()} attitude · ${a.frame} · ${a.source.reference}. Generic shape, not measured geometry. Body axes: X ${a.body_axes.x}; Y ${a.body_axes.y}; Z ${a.body_axes.z}. Adjacent samples use shortest-path SLERP; intermediate motion is modeled.`;
}
