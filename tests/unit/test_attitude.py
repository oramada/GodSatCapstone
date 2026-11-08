import copy
import json
import pytest
from godsat.studio.scene import base, load_scene
from godsat.studio.sequence import roster_hash, boundary_hash


def example():
    return dict(frame='ITRS', direction='body_to_reference', order='xyzw',
        source=dict(kind='observed', reference='Synthetic test fixture; not real telemetry'),
        body_axes=dict(x='panel axis', y='bus top', z='completes right-handed triad'),
        quaternions=[[0,0,0,1], None, [0,0,1,0]])


def scene(attitude):
    return base('Attitude fixture', 'ITRS', ['2026-01-01T00:00:00Z','2026-01-01T00:01:00Z','2026-01-01T00:02:00Z'],
        [dict(id='1',name='Fixture',kind='satellite',positions_km=[[7000,0,0]]*3,attitude=attitude)],
        dict(kind='illustrative',description='Synthetic test only'))


def test_attitude_preserved_and_missing_not_repaired(tmp_path):
    value=scene(example());path=tmp_path/'scene.json';path.write_text(json.dumps(value))
    assert load_scene(path)['objects'][0]['attitude']==example()


@pytest.mark.parametrize('key,value', [('frame','GCRS'),('direction','reference_to_body'),('order','wxyz'),('source',{}),('body_axes',{}),('quaternions',[[0,0,0,2]]*3),('quaternions',[[True,0,0,0]]*3),('quaternions',[[float('nan'),0,0,1]]*3),('quaternions',[])])
def test_ambiguous_or_invalid_attitude_rejected(key,value):
    attitude=example();attitude[key]=value
    with pytest.raises(ValueError,match='Attitude'):scene(attitude)


def test_sequence_hashes_bind_attitude_values_and_convention():
    objects=scene(example())['objects'];changed=copy.deepcopy(objects)
    changed[0]['attitude']['quaternions'][0]=[0,1,0,0]
    assert boundary_hash(objects,0)!=boundary_hash(changed,0)
    assert roster_hash(objects)==roster_hash(changed)
    changed[0]['attitude']['body_axes']['x']='different axis'
    assert roster_hash(objects)!=roster_hash(changed)
