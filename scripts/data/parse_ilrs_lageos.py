"""Parse ILRS CRD normal-point measurements while retaining raw CRD files."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import csv
import datetime as dt
import json
import math
import pathlib
import argparse

ROOT=pathlib.Path(__file__).resolve().parents[2]
DATA=ROOT/'data/ground_sensor/ilrs_lageos1_npt'
OUT=DATA/'normal_points.csv'
SPEED_OF_LIGHT_M_S=299_792_458.0

FIELDS=['source_file','station_name','station_cdp_id','station_system_number',
    'station_occupation','station_epoch_time_scale','target_name','ilrs_satellite_id',
    'target_sic','norad_id','spacecraft_epoch_time_scale','target_class','target_location',
    'data_type','session_start_utc','session_end_utc','seconds_of_day','observation_time_utc',
    'time_of_flight_seconds','two_way_range_km_from_time_of_flight','system_configuration_id',
    'epoch_event','normal_point_window_seconds','number_of_raw_ranges','bin_rms_ps',
    'refraction_correction_applied','center_of_mass_correction_applied',
    'receive_amplitude_correction_applied','station_system_delay_applied',
    'spacecraft_system_delay_applied','range_type','data_quality_alert',
    'prediction_type','prediction_year','prediction_datetime','prediction_provider',
    'prediction_sequence',
    'bin_skew','bin_kurtosis','bin_peak_minus_mean_ps','return_rate_percent',
    'detector_channel','signal_to_noise_ratio']

def optional_int(value):
    try:return int(value)
    except (TypeError,ValueError):return None

def optional_float(value):
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError):return None

def parse_file(path,writer):
    station={};target={};session={};prediction={};count=0;bad=0
    session_start=None;session_end=None;previous_observation=None
    with path.open(errors='replace') as stream:
        for raw in stream:
            fields=raw.split()
            if not fields:continue
            kind=fields[0].lower()
            if kind=='h2' and len(fields)>=6:
                station={'station_name':fields[1],'station_cdp_id':fields[2],
                    'station_system_number':fields[3],'station_occupation':fields[4],
                    'station_epoch_time_scale':fields[5]}
            elif kind=='h3' and len(fields)>=8:
                target={'target_name':fields[1],'ilrs_satellite_id':fields[2],
                    'target_sic':fields[3],'norad_id':fields[4],
                    'spacecraft_epoch_time_scale':fields[5],'target_class':fields[6],
                    'target_location':fields[7]}
            elif kind=='h5' and len(fields)>=6:
                prediction={'prediction_type':optional_int(fields[1]),
                    'prediction_year':optional_int(fields[2]),
                    'prediction_datetime':fields[3],
                    'prediction_provider':fields[4],
                    'prediction_sequence':fields[5]}
            elif kind=='h4' and len(fields)>=14:
                try:
                    begin=dt.datetime(*(int(v) for v in fields[2:8]),tzinfo=dt.timezone.utc)
                    end=dt.datetime(*(int(v) for v in fields[8:14]),tzinfo=dt.timezone.utc)
                    session_start,session_end=begin,end
                    previous_observation=None
                    session={'data_type':fields[1],'session_start_utc':begin.isoformat(),
                             'session_end_utc':end.isoformat()}
                    # CRD v2 H4 flags indicate whether these pass-level corrections
                    # have already been applied to the normal points.
                    names=('refraction_correction_applied','center_of_mass_correction_applied',
                        'receive_amplitude_correction_applied','station_system_delay_applied',
                        'spacecraft_system_delay_applied','range_type','data_quality_alert')
                    for name,value in zip(names,fields[15:22]):
                        session[name]=optional_int(value)
                except ValueError:
                    session={};bad+=1
            elif kind=='11':
                if len(fields)<13 or not session:
                    bad+=1;continue
                try:seconds=float(fields[1]);tof=optional_float(fields[2])
                except (TypeError,ValueError):bad+=1;continue
                scale=optional_int(station.get('station_epoch_time_scale'))
                observation=None
                if scale in {3,4,7} and session_start is not None and session_end is not None and 0<=seconds<86400:
                    midnight=dt.datetime.combine(session_start.date(),dt.time(),tzinfo=dt.timezone.utc)
                    observation=midnight+dt.timedelta(seconds=seconds)
                    while observation<session_start:
                        observation+=dt.timedelta(days=1)
                    while previous_observation is not None and observation<previous_observation:
                        observation+=dt.timedelta(days=1)
                    if observation>session_end:
                        observation=None
                obs_time=observation.isoformat() if observation is not None else ''
                if observation is not None:previous_observation=observation
                # CRD fields 11-13 are stable in v2; field 14 is optional S:N.
                row={'source_file':str(path.relative_to(ROOT)),**station,**target,**session,**prediction,
                    'seconds_of_day':seconds,'observation_time_utc':obs_time,
                    'time_of_flight_seconds':tof,
                    'two_way_range_km_from_time_of_flight':(tof*SPEED_OF_LIGHT_M_S/2000.0) if tof is not None else None,
                    'system_configuration_id':fields[3],'epoch_event':optional_int(fields[4]),
                    'normal_point_window_seconds':optional_float(fields[5]),
                    'number_of_raw_ranges':optional_int(fields[6]),'bin_rms_ps':optional_float(fields[7]),
                    'refraction_correction_applied':session.get('refraction_correction_applied'),
                    'center_of_mass_correction_applied':session.get('center_of_mass_correction_applied'),
                    'receive_amplitude_correction_applied':session.get('receive_amplitude_correction_applied'),
                    'station_system_delay_applied':session.get('station_system_delay_applied'),
                    'spacecraft_system_delay_applied':session.get('spacecraft_system_delay_applied'),
                    'range_type':session.get('range_type'),'data_quality_alert':session.get('data_quality_alert'),
                    'bin_skew':optional_float(fields[8]),'bin_kurtosis':optional_float(fields[9]),
                    'bin_peak_minus_mean_ps':optional_float(fields[10]),'return_rate_percent':optional_float(fields[11]),
                    'detector_channel':optional_int(fields[12]),'signal_to_noise_ratio':optional_float(fields[13]) if len(fields)>13 else None}
                writer.writerow({field:row.get(field,'') if row.get(field) is not None else '' for field in FIELDS});count+=1
    return count,bad

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',default=str(DATA),help='target-specific ILRS data directory')
    args=parser.parse_args()
    data=pathlib.Path(args.data_dir).resolve()
    out=data/'normal_points.csv'
    files=sorted(p for p in data.glob('[0-9][0-9][0-9][0-9]/*.np2') if p.name!='normal_points.csv')
    if not files:raise SystemExit('No raw .np2 files found; run scripts/data/download_ilrs_lageos.py --target <slug> first')
    station_counts={};daily_counts={};records=0;bad=0
    with out.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader()
        for i,path in enumerate(files,1):
            count,errors=parse_file(path,writer);records+=count;bad+=errors
            day=path.stem.rsplit('_',1)[-1];daily_counts[day]=daily_counts.get(day,0)+count
            if i%250==0:print(f'parsed {i}/{len(files)} files; {records:,} normal points',flush=True)
    with out.open(newline='') as stream:
        for row in csv.DictReader(stream):
            key=(row['station_name'],row['station_cdp_id'])
            station_counts[key]=station_counts.get(key,0)+1
    manifest_path=data/'manifest.json';manifest=json.loads(manifest_path.read_text())
    manifest['parsed_normal_points']={'csv':str(out.relative_to(ROOT)),'records':records,
        'station_count':len(station_counts),'stations':[
            {'station_name':key[0],'station_cdp_id':key[1],'normal_points':value}
            for key,value in sorted(station_counts.items())],
        'daily_files_with_normal_points':sum(v>0 for v in daily_counts.values()),
        'records_with_parse_warnings':bad,
        'range_note':'Two-way geometric range proxy = speed of light × CRD time-of-flight / 2. CRD supplementary corrections and calibration must be applied for precise range residuals.'}
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'normal_points':records,'stations':len(station_counts),
        'days_with_measurements':manifest['parsed_normal_points']['daily_files_with_normal_points'],
        'records_with_parse_warnings':bad,'csv':str(out)},indent=2))

if __name__=='__main__':main()
