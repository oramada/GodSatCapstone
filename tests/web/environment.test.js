import test from 'node:test';
import assert from 'node:assert/strict';
import {EnvironmentIndex,magnitude} from '../../web/studio/environment.js';
test('environment samples appear only inside their validity interval, including scrubbing backwards',()=>{
 const sample={time_utc:'2026-01-01T00:00:00Z',valid_until_utc:'2026-01-01T00:00:01Z',values:{cloud_fraction:.5}};
 const index=new EnvironmentIndex({sources:[],samples:[sample]});const t=Date.parse(sample.time_utc);
 for(const [time,count] of [[t-1,0],[t,1],[t+1000,1],[t+1000.5,0],[t+1001,0],[t,1]])assert.equal(index.at(time).length,count);
});
test('magnetic vectors keep the three component magnitude and missing fields unavailable',()=>{
 assert.equal(magnitude({values:{magnetic_east_nt:3,magnetic_north_nt:4,magnetic_up_nt:0}},'magnetic'),5);
 assert.equal(magnitude({values:{cloud_fraction:0}},'cloud_fraction'),0);
 assert.equal(magnitude({values:{}},'vertical_tec_tecu'),null);
});
