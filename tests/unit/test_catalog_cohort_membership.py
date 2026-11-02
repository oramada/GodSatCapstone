import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.data.build_validated_catalog_union import verify_membership


def test_same_cohort_cardinality_does_not_establish_correct_object_identity(tmp_path):
    path = tmp_path/'part.parquet'
    pq.write_table(pa.table({'norad_id':[1,1,99,99]}),path)
    with duckdb.connect() as connection:
        with pytest.raises(ValueError,match='unknown=2'):
            verify_membership(connection,[str(path)],[1,2])


def test_null_object_id_is_rejected_as_unknown(tmp_path):
    path=tmp_path/'part.parquet';pq.write_table(pa.table({'norad_id':[1,2,None]}),path)
    with duckdb.connect() as connection:
        with pytest.raises(ValueError,match='unknown=1'):
            verify_membership(connection,[str(path)],[1,2])


def test_every_expected_object_is_present_in_each_part(tmp_path):
    paths=[]
    for index,ids in enumerate([[1,1,2,2],[1,2]]):
        path=tmp_path/f'{index}.parquet';pq.write_table(pa.table({'norad_id':ids}),path);paths.append(str(path))
    with duckdb.connect() as connection:
        result=verify_membership(connection,paths,[1,2])
    assert sorted(row['rows'] for row in result)==[2,4]
    assert all(row['unknown_id_rows']==0 and row['objects']==2 for row in result)
