#!/usr/bin/env python3
"""Best-effort upload of a small CI artifact to the official GoFile upload API.

Only metadata needed for downloading is emitted. Account/guest tokens and raw
API responses are never logged. This program does not upload ROM-sized files.
Official API: https://gofile.io/api (global endpoint, guest upload supported).
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

UPLOAD_URL = "https://upload.gofile.io/uploadfile"
MAX_ARTIFACT_BYTES = 128 * 1024**2
MAX_RESPONSE_BYTES = 1024**2
DEFAULT_TIMEOUT = 45


class UploadError(Exception):
    """A controlled diagnostic that never includes a token or response body."""


@dataclass(frozen=True)
class UploadedArtifact:
    name: str
    size: int
    sha256: str
    download_page: str


def allowed_service_url(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        return (
            parts.scheme == "https"
            and (host == "gofile.io" or host.endswith(".gofile.io"))
            and not parts.username
            and not parts.password
            and parts.port in (None, 443)
            and not parts.fragment
        )
    except (TypeError, ValueError):
        return False


class GoFileRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_service_url(newurl):
            raise UploadError("O servidor indicou redirecionamento fora do GoFile HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_json(request: urllib.request.Request, timeout: float) -> dict:
    # Default proxy/CA handling is preserved; no network-policy bypass or custom
    # TLS verification settings. urllib's timeout applies to socket operations.
    opener = urllib.request.build_opener(GoFileRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise UploadError("O GoFile retornou um status HTTP inesperado")
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except UploadError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        # Do not print exc: transport errors may include URLs/response details.
        raise UploadError("Falha de rede, HTTP ou tempo limite no GoFile") from None
    if len(data) > MAX_RESPONSE_BYTES:
        raise UploadError("Resposta do GoFile maior que o limite")
    try:
        result = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise UploadError("Resposta JSON invalida do GoFile") from None
    if not isinstance(result, dict):
        raise UploadError("Formato de resposta invalido do GoFile")
    return result


def _safe_filename(name: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:180]
    if not result or result in (".", ".."):
        raise UploadError("Nome de artefato invalido")
    return result


def _download_url(value) -> str:
    if not isinstance(value, str) or not allowed_service_url(value):
        raise UploadError("Link de download ausente ou fora do GoFile HTTPS")
    parts = urllib.parse.urlsplit(value)
    if parts.hostname != "gofile.io" or parts.query or not re.fullmatch(r"/d/[A-Za-z0-9_-]{4,128}", parts.path):
        raise UploadError("Formato inesperado do link de download")
    return "https://gofile.io" + parts.path


def upload_artifact(path: Path, *, token: str | None = None, timeout: float = DEFAULT_TIMEOUT,
                    transport=request_json) -> UploadedArtifact:
    if not 0 < timeout <= 60:
        raise UploadError("O timeout deve ser maior que zero e no maximo 60 segundos")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise UploadError("O artefato deve ser um arquivo regular, sem link simbolico")
    if not path.name.lower().endswith((".zip", ".tar.gz", ".tgz", ".tar.xz", ".tar.zst")):
        raise UploadError("Escolha um artefato ZIP ou TAR comprimido")
    if not 0 < path.stat().st_size <= MAX_ARTIFACT_BYTES:
        raise UploadError("Artefato vazio ou maior que 128 MiB; esta ferramenta nao envia ROMs")
    with path.open("rb") as stream:
        data = stream.read(MAX_ARTIFACT_BYTES + 1)
    if not 0 < len(data) <= MAX_ARTIFACT_BYTES:
        raise UploadError("O tamanho do artefato mudou durante a leitura")
    sha256 = hashlib.sha256(data).hexdigest()
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    filename = _safe_filename(path.name)
    boundary = "r8q-" + uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        'Content-Type: application/octet-stream\r\n\r\n'
    ).encode("ascii") + data + f"\r\n--{boundary}--\r\n".encode("ascii")
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}",
               "Content-Length": str(len(body)), "Accept": "application/json",
               "User-Agent": "r8q-port-ci/1"}
    if token:
        if len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise UploadError("Formato invalido de GOFILE_TOKEN")
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(UPLOAD_URL, data=body, headers=headers, method="POST")
    result = transport(request, timeout)
    if not isinstance(result, dict) or result.get("status") != "ok" or not isinstance(result.get("data"), dict):
        # Never echo status/message, as untrusted API data may include credentials.
        raise UploadError("O GoFile nao confirmou o upload")
    uploaded = result["data"]
    link = _download_url(uploaded.get("downloadPage"))
    if "size" in uploaded and (type(uploaded["size"]) is not int or uploaded["size"] != len(data)):
        raise UploadError("O tamanho remoto informado difere do artefato local")
    if "md5" in uploaded and (not isinstance(uploaded["md5"], str) or uploaded["md5"].lower() != md5):
        raise UploadError("O MD5 de transporte informado difere do artefato local")
    with path.open("rb") as stream:
        after = hashlib.file_digest(stream, "sha256").hexdigest()
    if after != sha256:
        raise UploadError("O artefato local mudou durante o upload")
    return UploadedArtifact(filename, len(data), sha256, link)


def append_summary(path: Path | None, result: UploadedArtifact | None, failure: str | None = None):
    if path is None:
        return
    with Path(path).open("a", encoding="utf-8") as stream:
        if result is not None:
            stream.write(f"\nGoFile: [{result.name}]({result.download_page})\n\n")
            stream.write(f"Tamanho: {result.size} bytes. SHA256: `{result.sha256}`.\n")
        else:
            stream.write("\nGoFile indisponivel; use o artefato do GitHub Actions.\n")
            if failure:
                stream.write(f"\n{failure}\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--strict", action="store_true", help="falhar o passo se o espelho GoFile falhar")
    parser.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    parser.add_argument("--result", type=Path, help="salvar somente metadados publicos em JSON")
    args = parser.parse_args(argv)
    try:
        result = upload_artifact(args.artifact, token=os.environ.get("GOFILE_TOKEN"), timeout=args.timeout)
    except (UploadError, OSError) as exc:
        message = str(exc) if isinstance(exc, UploadError) else "Falha ao ler o artefato local"
        print("GoFile indisponivel: " + message, file=sys.stderr)
        try:
            append_summary(args.summary, None, message)
        except OSError:
            print("Nao foi possivel atualizar o resumo do CI", file=sys.stderr)
        return 1 if args.strict else 0
    print(json.dumps(asdict(result), ensure_ascii=True))
    try:
        append_summary(args.summary, result)
        if args.result:
            args.result.write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")
    except OSError:
        print("Upload confirmado; falha ao salvar metadados locais", file=sys.stderr)
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
