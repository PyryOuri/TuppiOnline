"""Serve the prebuilt browser and room API from one HTTPS origin."""
from __future__ import annotations
import asyncio
import json
import mimetypes
import os
from pathlib import Path
import re

from .hosted import create_hosted_app, validate_origins


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
            (b'x-content-type-options',b'nosniff')]
        if path=='sw.mjs': headers.append((b'service-worker-allowed',b'/'))
        await send({'type':'http.response.start','status':200,'headers':headers})
        if scope['method']=='HEAD':
            await send({'type':'http.response.body','body':b''})
            return
        with file.open('rb') as stream:
            while data:=stream.read(65536):
                await send({'type':'http.response.body','body':data,'more_body':True})
                # A fast reader never applies back-pressure, so send() need
                # not yield: without this a 12.7 MB model stalls every room
                # for ~100 ms. Not a thread: the default executor runs bots.
                await asyncio.sleep(0)
        await send({'type':'http.response.body','body':b''})
