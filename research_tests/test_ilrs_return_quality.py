import csv
import json

from scripts.analyze_ilrs_return_quality import analyze


def write_csv(path, fields, rows):
    with path.open('w', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_ilrs_return_quality_joins_measured_rows_and_excludes_invalid_rates(tmp_path):
    normal_path=tmp_path/'normal_points.csv'
    range_path=tmp_path/'range_validation.csv'
    output=tmp_path/'return_quality.json'
    normal_fields=['source_file','observation_time_utc','station_name',
        'epoch_event','two_way_range_km_from_time_of_flight','return_rate_percent']
    range_fields=['source_file','observation_time_utc','station_name','epoch_event',
        'observed_one_way_equivalent_range_m','range_residual_with_dhf_biases_m',
        'data_quality_alert']
    source='2025/test.np2'; station='TEST'; event='2'
    normal=[]; ranges=[]
    observations=[('2025-01-01T00:00:00+00:00',.5,2.0),
        ('2025-01-01T00:01:00+00:00',50.0,1.0),
        ('2025-01-02T00:00:00+00:00',101.0,2.0),
        ('2025-01-02T00:01:00+00:00',.5,200.0)]
    for timestamp,rate,residual in observations:
        normal.append({'source_file':source,'observation_time_utc':timestamp,
            'station_name':station,'epoch_event':event,
            'two_way_range_km_from_time_of_flight':'8000.0',
            'return_rate_percent':str(rate)})
        ranges.append({'source_file':source,'observation_time_utc':timestamp,
            'station_name':station,'epoch_event':event,
            'observed_one_way_equivalent_range_m':'8000000.0',
            'range_residual_with_dhf_biases_m':str(residual),
            'data_quality_alert':'0'})
    write_csv(normal_path,normal_fields,normal)
    write_csv(range_path,range_fields,ranges)

    result=analyze(normal_path,range_path,output,replicates=100,seed=7)
    assert result['join']['joined_rows']==4
    assert result['validity']['return_rates_outside_spec_excluded']==1
    assert result['validity']['absolute_range_residual_over_100m_excluded']==1
    assert result['validity']['analyzed_rows']==2
    assert result['paired_station_day_low_vs_high_return']['unit']=='m'
    assert json.loads(output.read_text())['status']=='completed'
