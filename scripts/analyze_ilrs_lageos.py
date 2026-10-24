"""Summarize measured ILRS LAGEOS-1 normal-point return rates by station."""
import csv
import json
import pathlib
import statistics
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/'data/ground_sensor/ilrs_lageos1_npt'
SOURCE=DATA/'normal_points.csv'

def pct(values,p):return float(np.percentile(np.asarray(values,float),p)) if values else None

def main():
    if not SOURCE.exists():raise SystemExit('Run scripts/parse_ilrs_lageos.py first')
    groups={};days=set();files=set();all_rates=[];all_ranges=[];records=0
    with SOURCE.open(newline='') as stream:
        for row in csv.DictReader(stream):
            records+=1;files.add(row['source_file'])
            date=(row['observation_time_utc'] or row['session_start_utc'])[:10]
            if date:days.add(date)
            key=(row['station_name'],row['station_cdp_id'])
            group=groups.setdefault(key,{'dates':set(),'files':set(),'rates':[],'ranges':[],'normal_points':0})
            group['normal_points']+=1;group['files'].add(row['source_file']);group['dates'].add(date)
            rate=float(row['return_rate_percent']) if row['return_rate_percent'] else None
            distance=float(row['two_way_range_km_from_time_of_flight']) if row['two_way_range_km_from_time_of_flight'] else None
            if rate is not None and 0<=rate<=100:
                group['rates'].append(rate);all_rates.append(rate)
            if distance is not None and distance>0:
                group['ranges'].append(distance);all_ranges.append(distance)
    summary=[]
    for (name,station_id),group in sorted(groups.items()):
        r=group['rates'];d=group['ranges']
        summary.append({'station_name':name,'station_cdp_id':station_id,
            'normal_points':group['normal_points'],'days_with_observations':len(group['dates']),
            'daily_files_with_observations':len(group['files']),'normal_points_with_return_rate':len(r),
            'return_rate_mean_percent':statistics.fmean(r) if r else None,
            'return_rate_median_percent':statistics.median(r) if r else None,
            'return_rate_p10_percent':pct(r,10),'return_rate_p90_percent':pct(r,90),
            'two_way_range_median_km':statistics.median(d) if d else None})
    with (DATA/'station_return_summary.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
    result={'status':'completed','source':'ILRS/EUROLAS Data Center LAGEOS-1 CRD v2 normal points',
        'raw_measurement_records':records,'daily_files_with_measurements':len(files),
        'utc_days_with_measurements':len(days),'ground_stations':len(groups),
        'observations_with_return_rate':len(all_rates),
        'overall_return_rate_mean_percent':statistics.fmean(all_rates) if all_rates else None,
        'overall_return_rate_median_percent':statistics.median(all_rates) if all_rates else None,
        'overall_return_rate_p10_percent':pct(all_rates,10),'overall_return_rate_p90_percent':pct(all_rates,90),
        'median_two_way_range_km':statistics.median(all_ranges) if all_ranges else None,
        'station_summary_csv':str((DATA/'station_return_summary.csv').relative_to(ROOT)),
        'interpretation':'CRD return rate is the station-reported percentage for each normal-point bin. It describes returns during acquired tracking passes, not missed satellite acquisition attempts or independent hardware-outage probability.',
        'limitations':['One retroreflector-equipped MEO satellite (LAGEOS-1), not the all-orbit catalog.',
            'Pass observations are conditioned on the station scheduling/acquisition process; days without records are not confirmed sensor outages.',
            'Range residual calibration requires interpolation/application of CRD range supplements, station coordinates, and target center-of-mass corrections.']}
    (DATA/'sensor_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    if summary:
        labels=[f"{x['station_name']}\n{x['station_cdp_id']}" for x in summary]
        means=[x['return_rate_mean_percent'] or 0 for x in summary]
        fig,ax=plt.subplots(figsize=(max(8,len(summary)*.7),4));ax.bar(labels,means,color='#44bdb3')
        ax.set_ylabel('Reported normal-point return rate (%)');ax.set_title('ILRS LAGEOS-1 ground laser-ranging observations')
        ax.tick_params(axis='x',labelrotation=35);fig.tight_layout();fig.savefig(DATA/'station_return_rates.png');plt.close(fig)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
