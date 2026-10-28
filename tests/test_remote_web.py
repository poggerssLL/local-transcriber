"""Synthetic contract tests for the private remote web surface."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
import test_remote_gateway as gateway_tests
from fastapi.testclient import TestClient

from local_transcriber.remote_gateway import REMOTE_PREFIX, create_remote_gateway_app

WEB = Path(__file__).parents[1] / "src" / "local_transcriber" / "remote_web"
SECURITY = {
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


@pytest.fixture
def remote_web(tmp_path):
    runtime = gateway_tests.runtime.__wrapped__(tmp_path)
    clock = gateway_tests.Clock()
    app = create_remote_gateway_app(
        runtime.config, gateway_config=gateway_tests._settings(runtime), clock=clock
    )
    with TestClient(app) as client:
        client.test_clock = clock
        yield client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/remote",
        "/remote/",
        "/remote/assets/styles.css",
        "/remote/assets/app.js",
        "/remote/assets/api.js",
        "/remote/assets/dom.js",
    ],
)
def test_private_web_serving(remote_web, path):
    response = remote_web.get(path, headers=gateway_tests._headers(**{"sec-fetch-site": "none"}))
    assert response.status_code == 200
    for name, value in SECURITY.items():
        assert response.headers[name] == value
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert "unsafe-eval" not in response.headers["content-security-policy"]
    if path.endswith(".js"):
        assert "javascript" in response.headers["content-type"]
    elif path.endswith(".css"):
        assert "text/css" in response.headers["content-type"]
    else:
        assert "text/html" in response.headers["content-type"]


@pytest.mark.parametrize(
    "headers",
    [
        {"tailscale-funnel-request": ""},
        {"tailscale-user-login": ""},
        {"host": "evil.example"},
        {"sec-fetch-site": "cross-site"},
    ],
)
@pytest.mark.parametrize("path", ["/", "/remote/assets/styles.css", "/remote/assets/app.js"])
def test_web_boundary(remote_web, path, headers):
    response = remote_web.get(path, headers={**gateway_tests._headers(), **headers})
    assert response.status_code in {400, 401, 403}
    assert "Transcrever aula" not in response.text
    for name, value in SECURITY.items():
        assert response.headers[name] == value


def test_missing_assets_do_not_fallback(remote_web):
    for path in ["/remote/assets/missing.js", "/remote/assets/%2e%2e/api.py", "/remote/v1/missing"]:
        response = remote_web.get(path, headers=gateway_tests._headers())
        assert response.status_code in {403, 404}
        assert "Transcrever aula" not in response.text


def test_originless_status_exception(remote_web):
    headers = gateway_tests._session(remote_web)
    body = b"RIFF" + b"\x00" * 40
    response = remote_web.post(
        f"{REMOTE_PREFIX}/uploads/resumable",
        headers={
            **headers,
            "Idempotency-Key": "remote-web-synthetic-0001",
            "X-Expected-Sha256": hashlib.sha256(body).hexdigest(),
        },
        json={"filename": "synthetic.wav", "total_bytes": len(body)},
    )
    assert response.status_code in {200, 201}, response.text
    path = f"{REMOTE_PREFIX}/uploads/resumable/{response.json()['upload_id']}"
    base = {**headers, "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors"}
    base.pop("origin")
    assert remote_web.get(path, headers=base).status_code == 200
    for omitted in ["x-csrf-token", "cookie", "sec-fetch-site", "sec-fetch-mode"]:
        bad = {k: v for k, v in base.items() if k != omitted}
        remote_web.cookies.clear()
        assert remote_web.get(path, headers=bad).status_code == 403
    for change in [
        {"origin": "null"},
        {"sec-fetch-site": "none"},
        {"sec-fetch-mode": "navigate"},
        {"x-csrf-token": "forged"},
    ]:
        remote_web.cookies.clear()
        assert remote_web.get(path, headers={**base, **change}).status_code == 403
    for duplicate in ["x-csrf-token", "sec-fetch-site", "sec-fetch-mode", "origin"]:
        pairs = [(key, value) for key, value in base.items()]
        pairs.append((duplicate, base.get(duplicate, "null")))
        remote_web.cookies.clear()
        assert remote_web.get(path, headers=pairs).status_code == 403
    remote_web.cookies.clear()
    assert (
        remote_web.get(
            path, headers={**base, "tailscale-user-login": "colega@example.com"}
        ).status_code
        == 403
    )
    assert remote_web.get(f"{path}/finalize", headers=base).status_code == 403
    remote_web.test_clock.value += 3601
    assert remote_web.get(path, headers=base).status_code == 403


def test_static_csp_and_dom_contract():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'src="/remote/assets/app.js"' in html
    assert 'href="/remote/assets/styles.css"' in html
    assert "aria-live" in html and "viewport-fit=cover" in html
    for name in ["index.html", "app.js", "api.js", "dom.js"]:
        content = (WEB / name).read_text(encoding="utf-8")
        for banned in [
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
            "eval(",
            ".style.",
            "onclick=",
        ]:
            assert banned not in content
    assert "safe-area-inset" in (WEB / "styles.css").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_sha256_incremental_vectors():
    script = r"""
import { Sha256, hashFile } from './src/local_transcriber/remote_web/app.js';
import { createHash } from 'node:crypto';
for (const n of [0, 3, 55, 56, 63, 64, 65, 1025]) {
  const bytes = n === 3 ? new TextEncoder().encode('abc')
    : Uint8Array.from({length:n}, (_,i)=>i%251);
  const expected = createHash('sha256').update(bytes).digest('hex');
  const hash = new Sha256();
  for (let p=0;p<bytes.length;p+=7) hash.update(bytes.subarray(p,p+7));
  if (hash.digest() !== expected) throw new Error(`incremental ${n}`);
  const file = {size: bytes.length,
    slice: (a,b) => ({arrayBuffer: async()=>bytes.slice(a,b).buffer})};
  const result = await hashFile(file, {chunkBytes: 11});
  if (result.total !== expected) throw new Error(`file ${n}`);
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=WEB.parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_js_global_read_queue_and_retry_after():
    script = r"""
import { RemoteApi } from './src/local_transcriber/remote_web/api.js';
let now = 0;
const calls = [];
const replies = [
  {status:200, body:[]}, {status:200, body:[]},
  {status:429, retry:'12'}, {status:200, body:[]},
  {status:503, retry:'2'}, {status:200, body:[]},
];
const fetcher = async (path, options) => {
  calls.push({path, method:options.method, at:now});
  const item = replies.shift();
  return {ok:item.status===200, status:item.status, redirected:false,
    headers:{get:(name)=>name==='Retry-After' ? item.retry : null},
    json:async()=>item.body};
};
const api = new RemoteApi({fetcher, now:()=>now,
  sleep:async(ms)=>{now+=ms;}});
await Promise.all([api.subjects(), api.subjects()]);
await api.subjects();
await api.subjects();
if (calls[1].at - calls[0].at < 3000) throw new Error('read queue');
if (calls[3].at - calls[2].at < 12000) throw new Error('429 cooldown');
if (calls[5].at - calls[4].at < 2000) throw new Error('503 cooldown');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=WEB.parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_js_upload_job_and_strict_reselection():
    script = r"""
import { RemoteController } from './src/local_transcriber/remote_web/app.js';
import { createHash } from 'node:crypto';
const nodes = new Map();
const node = () => ({hidden:false,disabled:false,value:'',textContent:'',
  append(){},replaceChildren(){}});
globalThis.document = {getElementById(id) {
  if (!nodes.has(id)) nodes.set(id,node()); return nodes.get(id);
}, createElement:node, createTextNode:(text)=>({textContent:text})};
const values = new Map();
globalThis.localStorage = {getItem:(k)=>values.get(k)||null,
  setItem:(k,v)=>values.set(k,v), removeItem:(k)=>values.delete(k)};
const bytes = new TextEncoder().encode('abc');
const file = (data) => ({name:'same.wav',size:data.length,
  slice:(a,b)=>({arrayBuffer:async()=>data.slice(a,b).buffer})});
const total = createHash('sha256').update(bytes).digest('hex');
const id = 'a'.repeat(32), jobId = 'b'.repeat(36);
let offset=0, patches=0, finalizes=0, jobs=0;
const status = () => ({upload_id:id,state:'uploading',total_bytes:3,
  current_offset:offset,chunk_bytes:8388608,expected_sha256:total});
const api = {maxUpload:100, init:async()=>status(), status:async()=>status(),
  patch:async(_id,at,buf,hash)=>{
    if(at!==0 || hash!==total || buf.byteLength!==3) throw Error('bad patch');
    patches++; offset=3; return 3;
  }, finalize:async()=>{finalizes++; return {...status(),state:'completed',job_id:jobId};},
  job:async()=>{jobs++; return {status:'succeeded',transcript_available:true};},
  transcript:async()=>({text:'<script>literal</script>',segments:[]})};
const controller = new RemoteController(api);
await controller.start(file(bytes),'subject-id','','');
if (patches!==1 || finalizes!==1 || jobs!==1) throw Error('flow count');
if (nodes.get('transcript').value!=='<script>literal</script>') throw Error('transcript');
if (values.get('lt.remote.pending.v1').includes('<script>')) throw Error('text persisted');
const other = new RemoteController(api);
other.intent = {...controller.intent,upload_id:id,job_id:null,confirmed_offset:0};
let rejected=false;
try { await other.reselect(file(new TextEncoder().encode('abd'))); }
catch (error) { rejected = /Conteúdo diferente/.test(error.message); }
if (!rejected || patches!==1) throw Error('reselection accepted wrong file');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=WEB.parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_sha256_streaming_200_mib():
    chunk = b"Z" * (8 * 1024 * 1024)
    expected = hashlib.sha256()
    for _ in range(25):
        expected.update(chunk)
    script = r"""
import { hashFile } from './src/local_transcriber/remote_web/app.js';
const size = 200 * 1024 * 1024;
let largest = 0, reads = 0;
const file = {size, slice(start,end) {
  const length = end-start; largest=Math.max(largest,length); reads++;
  return {arrayBuffer:async()=>new Uint8Array(length).fill(90).buffer};
}};
const digest = await hashFile(file);
if (digest.total !== process.argv[1] || largest > 8388608 || reads !== 25) {
  throw new Error('200 MiB streaming digest or slice bound');
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, expected.hexdigest()],
        cwd=WEB.parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_package_data_declares_remote_assets():
    config = (WEB.parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    for pattern in ["remote_web/*.html", "remote_web/*.css", "remote_web/*.js"]:
        assert pattern in config
