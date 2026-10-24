import io
import json

import scripts.audit_sentinel_attitude_access as audit_module


class Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]


def test_access_audit_uses_inventory_and_records_auth_boundaries(tmp_path, monkeypatch):
    sample_id = "sample-product"
    metadata = {"Id": sample_id, "Name": "S2B_OPER_AUX_PROQUA_TEST",
                "S3Path": "/eodata/Sentinel-2/AUX/AUX_PROQUA/sample.TGZ",
                "ContentLength": 1234}
    monkeypatch.setattr(audit_module.urllib.request, "urlopen",
                        lambda *args, **kwargs: Response(json.dumps(metadata).encode()))

    def bounded(url, headers=None, timeout=25):
        if "download.dataspace" in url:
            return {"status_code": 401, "range_bytes_read": 96}
        if "eodata.dataspace" in url:
            return {"status_code": 403, "range_bytes_read": 160}
        if "scihub.copernicus.eu" in url:
            return {"error_type": "URLError", "error": "unreachable"}
        return {"status_code": 200, "range_bytes_read": 400}

    monkeypatch.setattr(audit_module, "bounded_get", bounded)
    output = tmp_path / "access_audit.json"
    result = audit_module.run(output)

    assert result["inventory_products"] == 7896
    assert result["inventory_content_bytes"] > 12_000_000_000
    assert result["probes"]["public_catalogue_product_metadata"]["status_code"] == 200
    assert result["probes"]["odata_product_download_without_token"]["status_code"] == 401
    assert result["probes"]["s3_object_without_keys"]["status_code"] == 403
    assert result["probes"]["legacy_pod_catalogue"]["error_type"] == "URLError"
    assert json.loads(output.read_text())["sample_product"]["s3_path"] == metadata["S3Path"]


def test_bounded_get_limits_successful_response_to_one_kilobyte(monkeypatch):
    class LargeResponse(Response):
        def __init__(self):
            self.body = b"x" * 100_000
            self.read_size = None

        def read(self, size=-1):
            self.read_size = size
            return super().read(size)

    response = LargeResponse()
    monkeypatch.setattr(audit_module.urllib.request, "urlopen",
                        lambda *args, **kwargs: response)
    result = audit_module.bounded_get("https://example.test/product")
    assert response.read_size == 1024
    assert result["range_bytes_read"] == 1024
