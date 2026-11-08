import {screenSamples} from './analytics.js';
self.onmessage=({data})=>{
 try{self.postMessage({result:screenSamples(data,value=>self.postMessage({progress:value}))});}
 catch(error){self.postMessage({error:error.message});}
};
