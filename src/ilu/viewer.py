"""`ilu view`: look at a model or a folder of tiles in the browser.

Serves the file's folder on localhost and opens a page that draws it with
three.js (loaded from a CDN, so the page needs internet). Nothing is
uploaded anywhere: the model is read from your machine by your browser.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import sys
import threading
import webbrowser

THREE = 'https://cdn.jsdelivr.net/npm/three@0.160.0'

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ìlú viewer</title>
<style>
  html, body { margin: 0; height: 100%; background: #cfe0ec; font: 14px system-ui, sans-serif; color: #1d2733; }
  canvas { display: block; }
  #panel { position: fixed; left: 12px; top: 12px; max-width: min(420px, calc(100% - 24px));
           background: rgba(255,255,255,.88); border-radius: 8px; padding: 10px 12px; line-height: 1.45; }
  #panel b { font-weight: 600; }
  #credit { position: fixed; right: 8px; bottom: 6px; max-width: 70%; text-align: right; font-size: 11px;
            color: #33414f; background: rgba(255,255,255,.7); padding: 2px 6px; border-radius: 4px; }
</style>
<script type="importmap">
{ "imports": { "three": "THREE/build/three.module.js", "three/addons/": "THREE/examples/jsm/" } }
</script>
</head>
<body>
<div id="panel"><b>Ìlú viewer</b><div id="info">Loading...</div>
<div>Drag to orbit, right-drag to pan, scroll to zoom.</div></div>
<div id="credit"></div>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const FILES = FILES_JSON;
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xcfe0ec);
scene.fog = new THREE.Fog(0xcfe0ec, 2500, 9000);
scene.add(new THREE.HemisphereLight(0xe8f1ff, 0x5a6b45, 1.6));
const sun = new THREE.DirectionalLight(0xfff4e0, 2.2);
sun.position.set(400, 700, -300);
scene.add(sun);
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 1, 30000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.maxPolarAngle = Math.PI * 0.495;
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

const loader = new GLTFLoader();
const box = new THREE.Box3();
let triangles = 0, loaded = 0;
const credits = new Set();
function count(obj) {
  obj.traverse(o => { if (o.isMesh) triangles += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3; });
}
function frame() {
  const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
  const r = Math.max(s.x, s.z) * 0.45 + 50;
  controls.target.copy(c);
  camera.position.set(c.x + r * 0.6, c.y + r * 0.55, c.z + r * 0.75);
  camera.far = r * 12; camera.updateProjectionMatrix();
  scene.fog.near = r * 1.2; scene.fog.far = r * 6;
}
for (const f of FILES) {
  loader.load(f, gltf => {
    scene.add(gltf.scene); count(gltf.scene); box.expandByObject(gltf.scene);
    const a = gltf.parser.json.asset || {}; if (a.copyright) a.copyright.split('; ').forEach(c => credits.add(c));
    loaded++; if (loaded === 1 || loaded === FILES.length) frame();
    document.getElementById('info').textContent =
      `${loaded} of ${FILES.length} file${FILES.length > 1 ? 's' : ''}, ${Math.round(triangles).toLocaleString()} triangles`;
    document.getElementById('credit').textContent = [...credits].join(' | ');
  }, undefined, err => { document.getElementById('info').textContent = 'Could not load ' + f + ': ' + err; });
}
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
</script>
</body>
</html>
"""


def page(files: list[str]) -> str:
    """The viewer page for model files given as URLs relative to the served folder."""
    return PAGE.replace('THREE/', THREE + '/').replace('FILES_JSON', json.dumps(files))


def files_for(path: str) -> tuple[str, list[str]]:
    """(folder to serve, model files in it) for a .glb or a folder written with --tile-size."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        index = os.path.join(path, 'tiles.json')
        if os.path.exists(index):
            with open(index, encoding='utf-8') as f:
                return path, [t['file'] for t in json.load(f)['tiles']]
        found = sorted(f for f in os.listdir(path) if f.endswith('.glb'))
        if not found:
            raise FileNotFoundError(f'no .glb files in {path}')
        return path, found
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return os.path.dirname(path), [os.path.basename(path)]


def serve(path: str, port: int = 0, open_browser: bool = True) -> None:
    """Serve a model and its viewer on localhost until interrupted."""
    folder, files = files_for(path)
    html = page(files).encode('utf-8')

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ('/', '/index.html'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return
            super().do_GET()

        def log_message(self, format: str, *args: object) -> None:
            pass

    handler = functools.partial(Handler, directory=folder)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    print(f'Viewing {path} at {url} (Ctrl+C to stop)')
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(file=sys.stderr)
    finally:
        server.server_close()
