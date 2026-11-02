import io
import json
from datetime import date
import urllib.error

import pytest

pytest.importorskip('cdflib')

from scripts.data import fetch_epop_attitude as fetcher


def test_transient_attitude_connection_reset_is_retried(monkeypatch):
    attempts = []

    def open_url(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.URLError(ConnectionResetError("connection reset"))
        return io.BytesIO(b"source data")

    monkeypatch.setattr(fetcher.urllib.request, "urlopen", open_url)
    monkeypatch.setattr(fetcher.time, "sleep", lambda seconds: None)
    assert fetcher.read_url("https://example.test/product") == b"source data"
    assert len(attempts) == 3


def test_missing_product_is_not_retried(monkeypatch):
    attempts = []

    def open_url(*args, **kwargs):
        attempts.append(1)
        raise urllib.error.HTTPError("https://example.test", 404, "missing", {}, None)

    monkeypatch.setattr(fetcher.urllib.request, "urlopen", open_url)
    with pytest.raises(urllib.error.HTTPError) as error:
        fetcher.read_url("https://example.test/product")
    assert error.value.code == 404
    assert len(attempts) == 1


def test_persistent_source_failure_remains_an_error(monkeypatch):
    attempts = []

    def open_url(*args, **kwargs):
        attempts.append(1)
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(fetcher.urllib.request, "urlopen", open_url)
    monkeypatch.setattr(fetcher.time, "sleep", lambda seconds: None)
    with pytest.raises(urllib.error.URLError):
        fetcher.read_url("https://example.test/product")
    assert len(attempts) == 4


def test_direct_product_fallback_keeps_actual_source_version(monkeypatch):
    urls = []

    def read(url):
        urls.append(url)
        if "2.0.0" not in url:
            raise urllib.error.HTTPError(url, 404, "missing", {}, None)
        return b"verified later by the CDF parser"

    monkeypatch.setattr(fetcher, "read_url", read)
    url, payload = fetcher.read_known_product(date(2022, 10, 9))
    assert url.endswith("20221009T235959_2.0.0.cdf.zip")
    assert payload == b"verified later by the CDF parser"
    assert len(urls) == 3


def test_missing_known_versions_do_not_establish_unpublished_day(monkeypatch):
    def read(url):
        raise urllib.error.HTTPError(url, 404, "missing", {}, None)

    monkeypatch.setattr(fetcher, "read_url", read)
    with pytest.raises(FileNotFoundError, match="directory availability is unverified"):
        fetcher.read_known_product(date(2022, 10, 9))


def test_unpublished_day_requires_recognized_publisher_listing_and_saved_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(fetcher, 'read_url', lambda *args, **kwargs: b'<html>temporary service error</html>')
    with pytest.raises(ValueError, match='absence is unverified'):
        fetcher.find_product(date(2022, 10, 9), tmp_path)
    assert not list(tmp_path.rglob('*.json'))

    monkeypatch.setattr(fetcher, 'read_url', lambda *args, **kwargs: b'<html><table><tr><td>Other products</td></tr></table></html>')
    assert fetcher.find_product(date(2022, 10, 9), tmp_path) is None
    probe = json.loads((tmp_path/'2022/2022-10-09.json').read_text())
    assert probe['http_status'] == 200
    assert probe['recognized_directory_listing']
    assert probe['products'] == []
    assert probe['listing_sha256']
    assert (tmp_path/'2022/2022-10-09.html').exists()


def test_error_only_retry_preserves_validated_and_publisher_absent_days(monkeypatch, tmp_path):
    (tmp_path/'manifest.json').write_text(json.dumps({
        'requested_start_utc': '2024-01-01', 'requested_end_exclusive_utc': '2024-01-04',
        'requested_days': 3, 'per_day_status': {'2024-01-01': 'validated',
            '2024-01-02': 'not_published', '2024-01-03': 'error'}}))
    called = []

    def process(day, *args):
        called.append(day.isoformat())
        return {'date_utc': day.isoformat(), 'status': 'validated'}

    monkeypatch.setattr(fetcher, 'process_day', process)
    result = fetcher.run(date(2024, 1, 1), date(2024, 1, 4), tmp_path, 1, retry_errors=True)
    assert called == ['2024-01-03']
    assert result['status'] == 'completed'
    assert result['products_validated'] == 2
    assert result['days_not_published'] == 1
    assert result['days_processed'] == 3
