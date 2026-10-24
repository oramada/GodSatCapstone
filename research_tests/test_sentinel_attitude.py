import io
import tarfile

from godsat.sentinel_attitude import gps_to_utc,parse_product


def make_product(lines):
    body=('\n'.join(lines)+'\n').encode('ascii')
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz') as archive:
        info=tarfile.TarInfo('S1A_TEST.DBL');info.size=len(body)
        archive.addfile(info,io.BytesIO(body))
    return stream.getvalue()


def test_gps_time_is_converted_to_utc_with_leap_seconds():
    utc,_=gps_to_utc('2022/10/09','00:00:00.000')
    assert utc=='2022-10-08T23:59:42Z'


def test_parse_quaternions_keeps_source_flag_and_resamples():
    product=make_product([
        '# Parameter list : Q_COMPR Q_COMP1 Q_COMP2 Q_COMP3 ATT_MODE SOURCE',
        '# Satellite : Sentinel-1A',
        '# Start date (GPS): 2022/10/09 00:00:18',
        '# End date (GPS): 2022/10/09 00:01:18',
        '# Step (sec): 1',
        '# Nr. records: 3',
        '2022/10/09 00:00:18.000 1 0 0 0 15 r',
        '2022/10/09 00:00:19.000 0.999 0.01 0 0 15 i',
        '2022/10/09 00:01:18.000 0.998 0.02 0 0 15 s',
    ])

    rows=parse_product(product,'S1A_OPER_AUX_PROQUA_POD__20221009_TEST',sample_seconds=60)

    assert len(rows)==2
    assert [row['source_flag'] for row in rows]==['r','s']
    assert rows[0]['norad_id']==39634
    assert abs(rows[0]['quaternion_norm']-1.)<1e-12
    assert [row['epoch_utc'] for row in rows]==[
        '2022-10-09T00:00:00Z','2022-10-09T00:01:00Z'
    ]
