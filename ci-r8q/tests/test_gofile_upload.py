from pathlib import Path
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "tools/gofile_upload.py"
spec = importlib.util.spec_from_file_location("gofile_upload", MODULE)
g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = g
spec.loader.exec_module(g)


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "tools test.zip"
        self.data = b"fixture CI artifact"
        self.path.write_bytes(self.data)

    def response(self, **changes):
        data = dict(downloadPage="https://gofile.io/d/AbC12345", size=len(self.data),
                    md5=hashlib.md5(self.data, usedforsecurity=False).hexdigest(), guestToken="DO-NOT-LOG")
        data.update(changes)
        return dict(status="ok", data=data)

    def test_guest_upload_and_metadata(self):
        def transport(request, timeout):
            self.assertEqual(request.full_url, g.UPLOAD_URL)
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(timeout, 45)
            self.assertNotIn("Authorization", request.headers)
            self.assertIn(b'filename="tools_test.zip"', request.data)
            self.assertIn(self.data, request.data)
            return self.response()
        result = g.upload_artifact(self.path, transport=transport)
        self.assertEqual(result.sha256, hashlib.sha256(self.data).hexdigest())
        self.assertEqual(result.name, "tools_test.zip")
        self.assertNotIn("DO-NOT-LOG", repr(result))

    def test_token_header_only_and_not_result(self):
        def transport(request, timeout):
            self.assertEqual(request.get_header("Authorization"), "Bearer SECRET")
            self.assertNotIn(b"SECRET", request.data)
            return self.response()
        self.assertNotIn("SECRET", repr(g.upload_artifact(self.path, token="SECRET", transport=transport)))

    def test_wrong_remote_size_and_md5(self):
        for value in [dict(size=1), dict(size=str(len(self.data))), dict(md5="0"*32)]:
            with self.subTest(value=value), self.assertRaises(g.UploadError):
                g.upload_artifact(self.path, transport=lambda *_: self.response(**value))

    def test_missing_optional_remote_digests_still_emits_local_sha(self):
        response = self.response(); del response["data"]["md5"]; del response["data"]["size"]
        result = g.upload_artifact(self.path, transport=lambda *_: response)
        self.assertEqual(result.size, len(self.data))
        self.assertEqual(len(result.sha256), 64)

    def test_url_restrictions(self):
        bad = ["http://gofile.io/d/AbC12345", "https://gofile.io.evil.invalid/d/AbC12345",
               "https://evil.gofile.io/d/AbC12345", "https://user:pass@gofile.io/d/AbC12345",
               "https://gofile.io:444/d/AbC12345", "https://gofile.io/d/AbC12345?token=SECRET",
               "https://gofile.io/d/AbC12345#x", "https://gofile.io/d/<script>", None]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(g.UploadError):
                g.upload_artifact(self.path, transport=lambda *_: self.response(downloadPage=value))

    def test_redirects_confined_to_official_domain(self):
        self.assertTrue(g.allowed_service_url("https://upload-na-phx.gofile.io/uploadfile"))
        for value in ["https://gofile.io.evil.invalid/", "https://evil.invalid/", "http://gofile.io/"]:
            self.assertFalse(g.allowed_service_url(value))
        req = g.urllib.request.Request(g.UPLOAD_URL, data=b"x", method="POST")
        with self.assertRaises(g.UploadError):
            g.GoFileRedirects().redirect_request(req, None, 302, "Found", {}, "https://evil.invalid/")

    def test_mutation_during_upload_rejected(self):
        def transport(*_):
            self.path.write_bytes(b"different")
            return self.response()
        with self.assertRaises(g.UploadError):
            g.upload_artifact(self.path, transport=transport)

    def test_size_limit_and_file_type_before_network(self):
        with patch.object(g, "MAX_ARTIFACT_BYTES", 3), self.assertRaises(g.UploadError):
            g.upload_artifact(self.path, transport=lambda *_: self.fail("network called"))
        self.path.unlink(); self.path.symlink_to(self.root / "missing")
        with self.assertRaises(g.UploadError): g.upload_artifact(self.path)
        other = self.root / "private.log"; other.write_bytes(b"x")
        with self.assertRaises(g.UploadError): g.upload_artifact(other)

    def test_bad_token_and_timeout_before_network(self):
        for token in ["bad\nheader", "bad token", "\u2603"]:
            with self.assertRaises(g.UploadError): g.upload_artifact(self.path, token=token)
        for timeout in [0, -1, 61]:
            with self.assertRaises(g.UploadError): g.upload_artifact(self.path, timeout=timeout)

    def test_failure_response_redacted(self):
        with self.assertRaises(g.UploadError) as error:
            g.upload_artifact(self.path, transport=lambda *_: dict(status="SECRET", message="DO-NOT-LOG"))
        self.assertNotIn("SECRET", str(error.exception))
        self.assertNotIn("DO-NOT-LOG", str(error.exception))

    def test_main_default_best_effort_and_strict_failure(self):
        for strict, expected in [(False, 0), (True, 1)]:
            with patch.object(g, "upload_artifact", side_effect=g.UploadError("controlled")):
                with contextlib.redirect_stderr(io.StringIO()):
                    result = g.main([str(self.path)] + (["--strict"] if strict else []))
            self.assertEqual(result, expected)

    def test_main_public_summary_json_only(self):
        summary = self.root / "summary.md"; output = self.root / "result.json"
        result = g.UploadedArtifact("tools.zip", len(self.data), hashlib.sha256(self.data).hexdigest(),
                                    "https://gofile.io/d/AbC12345")
        with patch.object(g, "upload_artifact", return_value=result), contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(g.main([str(self.path), "--summary", str(summary), "--result", str(output)]), 0)
        self.assertIn(result.download_page, summary.read_text())
        self.assertEqual(json.loads(output.read_text())["sha256"], result.sha256)
        self.assertNotIn("Token", captured.getvalue())

    def test_http_transport_uses_bounded_json_and_timeout(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"status":"ok","data":{}}'
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        request = g.urllib.request.Request(g.UPLOAD_URL, data=b"x", method="POST")
        with patch.object(g.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(g.request_json(request, 30), dict(status="ok", data={}))
        opener.open.assert_called_once_with(request, timeout=30)
        response.read.assert_called_once_with(g.MAX_RESPONSE_BYTES + 1)

    def test_http_network_errors_do_not_leak_remote_text(self):
        opener = unittest.mock.Mock()
        opener.open.side_effect = g.urllib.error.URLError("SECRET REMOTE ERROR")
        request = g.urllib.request.Request(g.UPLOAD_URL)
        with patch.object(g.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(g.UploadError) as error:
                g.request_json(request, 20)
        self.assertNotIn("SECRET", str(error.exception))

    def test_http_invalid_body_and_non200_rejected(self):
        for status, body in [(403, b'{"message":"SECRET"}'), (200, b'not JSON'),
                             (200, b'[]'), (200, b'x' * (g.MAX_RESPONSE_BYTES + 1))]:
            with self.subTest(status=status, body_length=len(body)):
                response = unittest.mock.MagicMock()
                response.__enter__.return_value = response
                response.status = status
                response.read.return_value = body
                opener = unittest.mock.Mock()
                opener.open.return_value = response
                with patch.object(g.urllib.request, "build_opener", return_value=opener):
                    with self.assertRaises(g.UploadError) as error:
                        g.request_json(g.urllib.request.Request(g.UPLOAD_URL), 20)
                self.assertNotIn("SECRET", str(error.exception))


if __name__ == "__main__":
    unittest.main()
