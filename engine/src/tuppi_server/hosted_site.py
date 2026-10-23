"""Serve the prebuilt browser and room API from one HTTPS origin."""
from __future__ import annotations
import json
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .hosted import create_hosted_app, validate_origins


def content_security_policy(origin):
    """Only this origin's own files run: no inline or injected script, styles
    only from files, WebAssembly allowed (Safari 16+), sockets to this host.
    Violations are counted at /v1/csp-report (hosted.py)."""
    url = urlsplit(origin)
    socket = f"{'wss' if url.scheme == 'https' else 'ws'}://{url.netloc}"
    return ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; img-src 'self' data:; "
            f"connect-src 'self' {socket}; worker-src 'self'; manifest-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; report-uri /v1/csp-report; report-to csp")


def create_hosted_site():
    origin = os.environ.get('TUPPI_PUBLIC_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL','')
    validate_origins(origin)
    return HostedSite(create_hosted_app(), Path(os.environ['TUPPI_WEB_DIR']), origin)


class HostedSite:
    def __init__(self, game, web, origin):
        self.game, self.web, self.origin = game, Path(web).resolve(), origin
        manifest = json.loads((self.web/'offline-manifest.json').read_text())
        self.allowed = {r['path'] for r in manifest['files']+manifest.get('network_files',[])}
        self.allowed |= {'sw.mjs','offline-manifest.json','deployment.json'}
        game.release = manifest.get('release')
        # Every file carries the policy: workers take theirs from their own
        # script, and the offline installer keeps each file's headers.
        self.security_headers = [(b'content-security-policy',content_security_policy(origin).encode()),
            (b'reporting-endpoints',f'csp="{origin}/v1/csp-report"'.encode()),
            (b'referrer-policy',b'no-referrer'),(b'x-frame-options',b'DENY')]

    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or scope.get('path','').startswith('/v1/') or scope.get('path')=='/healthz':
            await self.game(scope,receive,send)
            return
        path = scope.get('path','/')[1:] or 'index.html'
        if scope.get('method') not in {'GET','HEAD'} or path not in self.allowed:
            await self.game.game._json_response(send,404,{'error':'not_found'})
            return
        if path=='deployment.json':
            await self.game.game._json_response(send,200,{'schema':'tuppi.browser.deployment.v1','backend':self.origin})
            return
        file = (self.web/path).resolve()
        if not file.is_relative_to(self.web) or not file.is_file():
            await self.game.game._json_response(send,404,{'error':'not_found'})
            return
        mime = {'.mjs':'text/javascript; charset=utf-8','.wasm':'application/wasm',
            '.webmanifest':'application/manifest+json','.f32':'application/octet-stream',
            '.f64':'application/octet-stream'}.get(file.suffix,mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        immutable = bool(re.search(r'\.[a-f0-9]{16}\.',path) or path.startswith('runtime/'))
        headers=[(b'content-type',mime.encode()),(b'content-length',str(file.stat().st_size).encode()),
            (b'cache-control',b'public, max-age=31536000, immutable' if immutable else b'no-cache'),
            (b'x-content-type-options',b'nosniff'),
            (b'cross-origin-opener-policy',b'same-origin'),
            (b'cross-origin-embedder-policy',b'require-corp'),
            (b'cross-origin-resource-policy',b'same-origin'),*self.security_headers]
        if path=='sw.mjs': headers.append((b'service-worker-allowed',b'/'))
        await send({'type':'http.response.start','status':200,'headers':headers})
        if scope['method']=='HEAD':
            await send({'type':'http.response.body','body':b''})
            return
        with file.open('rb') as stream:
            while data:=stream.read(65536):
                await send({'type':'http.response.body','body':data,'more_body':True})
        await send({'type':'http.response.body','body':b''})
