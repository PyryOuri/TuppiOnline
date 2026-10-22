#!/usr/bin/env python3
"""Generate an immutable offline asset inventory after the runtime build."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import argparse

root = Path(__file__).resolve().parents[1]
source_web = root / 'web'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--capabilities', choices=['network', 'offline'], default='network')
parser.add_argument('--output', type=Path, help='Separate release directory; defaults to web for network builds')
parser.add_argument('--retain', type=Path, action='append', default=[], help='Prior web release whose immutable recovery assets must remain served')
args = parser.parse_args()
if args.capabilities == 'offline' and args.output is None:
    parser.error('Offline variants require --output to preserve the development source.')
web = args.output.resolve() if args.output else source_web
network_enabled = args.capabilities == 'network'
if not network_enabled and web == source_web:
    parser.error('The offline variant must use a directory separate from web.')
if web != source_web:
    web.mkdir(parents=True, exist_ok=True)
    for path in source_web.iterdir():
        # Copy the maintained source and fixed runtime inputs, not stale bundles.
        if path.is_file() and (path.suffix in {'.mjs', '.html', '.css', '.svg', '.png', '.webmanifest'}
                              or path.name == 'deployment.json') and not re.search(r'\.[a-f0-9]{16}\.', path.name) and path.name != 'sw.mjs':
            shutil.copyfile(path, web / path.name)
    shutil.copytree(source_web / 'assets', web / 'assets', dirs_exist_ok=True)
capability_source = (source_web / 'capabilities.mjs').read_text().replace('networkEnabled = true', f'networkEnabled = {str(network_enabled).lower()}')
if web != source_web:
    (web / 'capabilities.mjs').write_text(capability_source)
    if not network_enabled:
        index = (web / 'index.html').read_text().replace('id="home-friends"', 'id="home-friends" hidden')
        (web / 'index.html').write_text(index)


def merge_modules(names):
    """Merge only the small, explicit local ESM graph; retain native imports."""
    chunks = []
    for name in names:
        source = capability_source if name == 'capabilities.mjs' else (source_web / name).read_text()
        source = re.sub(r'^import\s+\{[^}]*\}\s+from\s+[\'\"]\./(?:storage|table|runtime|session|offline|network|hand|presentation|capabilities|lobby|preferences|timeline|replay|live)\.mjs[\'\"];\s*', '', source, flags=re.M)
        source = re.sub(r'^export (?=(?:async )?function|class|const)', '', source, flags=re.M)
        chunks.append(f'// Source: {name}\n{source}')
    return '\n'.join(chunks)


# Content-addressed entry points keep HTTP/service-worker caches from mixing
# frontend helpers across releases. Old filenames remain available for tabs
# already using them; model/runtime identity is unchanged.
asset_names = ['tuppi.mjs', 'tuppi.wasm', 'models.json', 'build.json',
               'vrpo1_actor_0504.f32', 'vrpo3_final.f32', 'equity.f64']
build = json.loads((web / 'assets/build.json').read_text())
asset_names += [record['file'] for record in build['outputs'] if record['file'] not in asset_names]
runtime_identity = hashlib.sha256((web/'assets/models.json').read_bytes() + (web/'assets/build.json').read_bytes()).hexdigest()
runtime_path = f'runtime/{runtime_identity}'
(web/runtime_path).mkdir(parents=True, exist_ok=True)
for name in asset_names:
    destination = web/runtime_path/name
    if destination.exists() and destination.read_bytes() != (web/'assets'/name).read_bytes():
        raise ValueError(f'Immutable runtime file changed: {name}')
    shutil.copyfile(web/'assets'/name, destination)
engine_source = merge_modules(['runtime.mjs', 'session.mjs', 'timeline.mjs', 'worker.mjs'])
engine_source = engine_source.replace("'./assets/tuppi.mjs'", f"'./{runtime_path}/tuppi.mjs'")
engine_source = engine_source.replace("new URL('./assets/', import.meta.url)", f"new URL('./{runtime_path}/', import.meta.url)")
engine_hash = hashlib.sha256(engine_source.encode()).hexdigest()
engine_name = f'engine.{engine_hash[:16]}.mjs'
(web / engine_name).write_text(engine_source)
client_source = merge_modules(['capabilities.mjs', 'preferences.mjs', 'storage.mjs', 'table.mjs', 'hand.mjs', 'presentation.mjs', 'offline.mjs', 'network.mjs', 'lobby.mjs', 'replay.mjs', 'live.mjs', 'app.mjs'])
client_source = client_source.replace('const packagedRuntimeIdentity = null;', f'const packagedRuntimeIdentity = {json.dumps(runtime_identity)};')
if "new URL('./worker.mjs', import.meta.url)" not in client_source:
    raise ValueError('Worker entry changed; update the explicit packaging graph.')
client_source = client_source.replace("new URL('./worker.mjs', import.meta.url)", f"new URL('./{engine_name}', import.meta.url)")
if re.search(r'^import ', client_source, flags=re.M):
    raise ValueError('Frontend imports changed; update the explicit packaging graph.')
client_hash = hashlib.sha256(client_source.encode()).hexdigest()
client_name = f'client.{client_hash[:16]}.mjs'
(web / client_name).write_text(client_source)
frontend = {'schema': 'tuppi.browser.frontend.v1', 'client': client_name, 'client_sha256': client_hash,
            'engine': engine_name, 'engine_sha256': engine_hash, 'runtime_identity': runtime_identity,
            'worker_protocol': 'tuppi.local.worker.v1', 'capabilities': {'offline': True, 'network': network_enabled}}
shell_hash = hashlib.sha256(json.dumps([frontend, (web/'index.html').read_text(),
    (web/'styles.css').read_text(), (web/'bootstrap.mjs').read_text()], sort_keys=True).encode()).hexdigest()
shell_id = shell_hash[:16]
css_source = (web/'styles.css').read_text()
css_name = f'styles.{hashlib.sha256(css_source.encode()).hexdigest()[:16]}.css'
(web/css_name).write_text(css_source)
immutable_manifest = f'frontend.{shell_id}.json'
bootstrap_source = (web/'bootstrap.mjs').read_text().replace("fetch('./frontend.json'", f"fetch('./{immutable_manifest}'")
bootstrap_name = f'bootstrap.{hashlib.sha256(bootstrap_source.encode()).hexdigest()[:16]}.mjs'
(web/bootstrap_name).write_text(bootstrap_source)
launch_name = f'launch.{shell_id}.html'
launch_source = (web/'index.html').read_text().replace('href="./styles.css"', f'href="./{css_name}"')
launch_source = launch_source.replace('src="./bootstrap.mjs"', f'src="./{bootstrap_name}"')
if css_name not in launch_source or bootstrap_name not in launch_source:
    raise ValueError('HTML entry references changed; update the packaging graph.')
(web/launch_name).write_text(launch_source)
frontend.update({'launch': launch_name, 'styles': css_name, 'bootstrap': bootstrap_name, 'manifest': immutable_manifest})
(web / 'frontend.json').write_text(json.dumps(frontend, indent=2) + '\n')
(web / immutable_manifest).write_text(json.dumps(frontend, indent=2) + '\n')
# Recovery fetches this network-only alias, which is never put in a SW cache.
(web / 'current-release.json').write_text(json.dumps(frontend, indent=2) + '\n')

paths = ['index.html', 'app.mjs', 'styles.css', 'table.mjs', 'runtime.mjs', 'session.mjs', 'worker.mjs', 'storage.mjs', 'offline.mjs',
         'network.mjs', 'hand.mjs', 'presentation.mjs', 'capabilities.mjs', 'lobby.mjs', 'preferences.mjs',
         'manifest.webmanifest', 'icon.svg', 'icon-180.png', 'icon-192.png', 'icon-512.png']
paths += [f'{runtime_path}/{name}' for name in asset_names]
paths += ['bootstrap.mjs', 'recover.html', 'frontend.json', client_name, engine_name]
paths += [launch_name, css_name, bootstrap_name, immutable_manifest]
records = [{'path': path, 'sha256': hashlib.sha256((web/path).read_bytes()).hexdigest(),
            'bytes': (web/path).stat().st_size, 'shared': path.startswith('runtime/')} for path in paths]
shell_downloads = []
for record in records:
    if record['path'].endswith('.html'):
        # Hosts may decorate documents; the installer needs the exact bytes.
        source_path = f'offline-shell.{record["sha256"][:16]}.txt'
        (web/source_path).write_bytes((web/record['path']).read_bytes())
        record['source_path'] = source_path
        shell_downloads.append({'path': source_path, 'sha256': record['sha256'], 'bytes': record['bytes']})
template = (root / 'tools/service_worker.template.mjs').read_text()
release = hashlib.sha256((json.dumps(records, sort_keys=True) + template).encode()).hexdigest()
records.append({**records[0], 'path': './'})
source = template.replace('__RELEASE__', json.dumps(release)).replace('__FILES__', json.dumps(records)).replace('__FRONTEND__', json.dumps(frontend))
(web/'sw.mjs').write_text(source)
manifest = {'schema': 'tuppi.browser.offline.v1', 'release': release, 'files': records,
            'service_worker_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'cache_bytes': sum(record['bytes'] for record in records)}
network_path = web/'current-release.json'
manifest['network_files'] = [{'path': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                             'bytes': p.stat().st_size} for p in [network_path, web/'deployment.json']]
manifest['network_files'] += shell_downloads
retained = {}
current = {record['path'] for record in records + manifest['network_files']}
for previous_web in args.retain:
    previous_web = previous_web.resolve()
    previous = json.loads((previous_web / 'offline-manifest.json').read_text())
    for record in previous['files'] + previous.get('network_files', []):
        name = record['path']
        immutable = (re.fullmatch(r'runtime/[a-f0-9]{64}/[A-Za-z0-9_.-]+', name) or
                     re.fullmatch(r'(?:client|engine|bootstrap|styles|launch|frontend|offline-shell)\.[a-f0-9]{16}\.(?:mjs|css|html|json|txt)', name))
        if not immutable or name in current or name in retained:
            continue
        source_file = (previous_web / name).resolve()
        if not source_file.is_relative_to(previous_web):
            raise ValueError('Retained runtime leaves its release directory')
        data = source_file.read_bytes()
        if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Retained runtime failed verification: ' + name)
        destination = web / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError('Retained immutable runtime conflicts: ' + name)
        destination.write_bytes(data)
        retained[name] = {'path': name, 'bytes': len(data), 'sha256': record['sha256']}
manifest['network_files'] += list(retained.values())
(web/'offline-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps({'release': release, 'files': len(records), 'cache_bytes': manifest['cache_bytes']}))
