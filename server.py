#!/usr/bin/env python3
"""Portfolio Builder — local server, no external packages required."""
import base64, json, os, re, ssl, subprocess, sys, urllib.parse, urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT       = 3001
ROOT       = Path(__file__).parent
WORKS      = ROOT / '00_works'
ORDER_FILE = ROOT / '_order.json'

# ── Find API key ───────────────────────────────────────────────────
def api_key():
    for src in [
        lambda: os.environ.get('ANTHROPIC_API_KEY',''),
        lambda: Path('~/.anthropic/api_key').expanduser().read_text().strip(),
        lambda: Path('~/.config/anthropic/api_key').expanduser().read_text().strip(),
        lambda: (ROOT / '_apikey.txt').read_text().strip(),
    ]:
        try:
            k = src()
            if k: return k
        except: pass
    return ''

# ── Scan projects ──────────────────────────────────────────────────
IMG_EXT = {'.jpg','.jpeg','.png','.gif','.webp'}
VID_EXT = {'.mp4','.mov','.webm'}

def load_order():
    try:
        if ORDER_FILE.exists():
            return json.loads(ORDER_FILE.read_text('utf-8'))
    except: pass
    return []

def scan():
    if not WORKS.exists(): return []
    out = []
    for d in sorted(WORKS.iterdir()):
        if not d.is_dir() or d.name.startswith('.'): continue
        files = [f.name for f in sorted(d.iterdir()) if not f.name.startswith('.')]
        imgs  = [f for f in files if Path(f).suffix.lower() in IMG_EXT]
        vids  = [f for f in files if Path(f).suffix.lower() in VID_EXT]
        saved = None
        jp = d / 'project.json'
        if jp.exists():
            try: saved = json.loads(jp.read_text('utf-8'))
            except: pass
        num = (re.match(r'^(\d+)', d.name) or type('',(),{'group':lambda *a:''})()).group(1)
        out.append({
            'id': d.name,
            'base': f'00_works/{d.name}/',
            'num': num or '',
            'defaultTitle': re.sub(r'^\d+_', '', d.name).replace('-',' ').replace('_',' '),
            'images': imgs,
            'videos': vids,
            'saved': saved,
        })
    order = load_order()
    if order:
        id_map = {p['id']: p for p in out}
        ordered = [id_map[i] for i in order if i in id_map]
        remaining = [p for p in out if p['id'] not in set(order)]
        return ordered + remaining
    return out

PROMPT = '''You are a design writer for ZIZONYUNDI, a Korean brand designer's portfolio.

Look at the attached project images and write concise professional English portfolio copy.
Respond with ONLY valid JSON — no markdown, no explanation:
{
  "title": "Short project name in English",
  "year": "YYYY",
  "category": "Brand Identity / Graphic Design / Motion / Editorial / Packaging / Type Design",
  "client": "Client name, or null if personal work",
  "scope": "Comma-separated deliverables in English",
  "description": "2–3 sentences. What the project is, its visual concept, what was made. Editorial tone, no filler."
}'''

# ── HTTP handler ───────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a): pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, data, code=200):
        b = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def send_response(self, code, message=None):
        super().send_response(code, message)
        path = self.path.split('?')[0]
        if path.endswith('.html'):
            self.send_header('Cache-Control', 'no-store')

    def do_GET(self):
        if self.path == '/api/projects':
            self._json(scan()); return
        super().do_GET()

    def do_POST(self):
        p = self.path

        # ── Generate with Claude ──────────────────────────────────
        if p == '/api/generate':
            key = api_key()
            if not key:
                self._json({'ok': False, 'error': 'API key not found.\nCreate a file _apikey.txt in the portfolio folder with your Anthropic API key.'}, 500)
                return
            b = self._body()
            base_path = ROOT / b.get('base', '')
            images    = b.get('images', [])[:6]

            content = []
            for fn in images:
                fp = base_path / fn
                if not fp.exists(): continue
                mt   = 'image/png' if fp.suffix.lower() == '.png' else 'image/jpeg'
                data = base64.b64encode(fp.read_bytes()).decode()
                content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mt, 'data': data}})

            if not content:
                self._json({'ok': False, 'error': 'No images found in project folder.'}, 400); return

            content.append({'type': 'text', 'text': PROMPT})

            try:
                req = urllib.request.Request(
                    'https://api.anthropic.com/v1/messages',
                    data=json.dumps({
                        'model': 'claude-sonnet-4-6',
                        'max_tokens': 600,
                        'messages': [{'role': 'user', 'content': content}]
                    }).encode(),
                    headers={
                        'x-api-key': key,
                        'anthropic-version': '2023-06-01',
                        'content-type': 'application/json',
                    },
                    method='POST'
                )
                with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=40) as r:
                    raw = json.loads(r.read())
                text = raw['content'][0]['text']
                m    = re.search(r'\{[\s\S]*\}', text)
                if not m: raise ValueError('No JSON in Claude response')
                self._json({'ok': True, 'data': json.loads(m.group())}); return
            except urllib.error.HTTPError as e:
                err = json.loads(e.read()).get('error', {}).get('message', str(e))
                self._json({'ok': False, 'error': err}, 500); return
            except Exception as e:
                self._json({'ok': False, 'error': str(e)}, 500); return

        # ── Save project.json ─────────────────────────────────────
        m = re.match(r'^/api/save/(.+)$', p)
        if m:
            pid    = urllib.parse.unquote(m.group(1))
            target = WORKS / pid / 'project.json'
            if not str(target.resolve()).startswith(str(WORKS)):
                self._json({'ok': False, 'error': 'Forbidden'}, 403); return
            target.parent.mkdir(parents=True, exist_ok=True)
            n = int(self.headers.get('Content-Length', 0))
            target.write_bytes(self.rfile.read(n))
            self._json({'ok': True}); return

        # ── New project ───────────────────────────────────────────
        if p == '/api/newproject':
            b    = self._body()
            name = re.sub(r'[^\w\-. ]', '', b.get('name', '')).strip()
            if not name:
                self._json({'ok': False, 'error': 'Invalid folder name'}, 400); return
            folder = WORKS / name
            folder.mkdir(parents=True, exist_ok=True)
            self._json({'ok': True, 'id': name, 'projects': scan()}); return

        # ── Publish → update index.html ───────────────────────────
        if p == '/api/publish':
            try:
                idx  = ROOT / 'index.html'
                html = idx.read_text('utf-8')
                b     = self._body()
                order = b.get('order', [])
                if order:
                    ORDER_FILE.write_text(json.dumps(order, ensure_ascii=False), 'utf-8')
                projects = scan()
                blocks = []
                for pr in projects:
                    s    = pr['saved'] or {}
                    all_media = sorted(pr['images'] + pr['videos'])
                    imgs = s.get('images') or [{'file': f, 'layout': 'full' if Path(f).suffix.lower() in VID_EXT else 'half'} for f in all_media]
                    first_media = all_media[0] if all_media else ''
                    obj  = {
                        'num':         pr['num'],
                        'title':       s.get('title', pr['defaultTitle']),
                        'year':        s.get('year', ''),
                        'category':    s.get('category', ''),
                        'client':      s.get('client'),
                        'scope':       s.get('scope', ''),
                        'description': s.get('description', ''),
                        'thumb':       s.get('thumb') or (f"{pr['base']}{first_media}" if first_media else ''),
                        'base':        pr['base'],
                        'video':       s.get('video') or (pr['videos'][0] if pr['videos'] else None),
                        'images':      imgs,
                    }
                    blocks.append(obj)
                START = '/* PORTFOLIO-DATA:START */'
                END   = '/* PORTFOLIO-DATA:END */'
                si = html.find(START)
                ei = html.find(END)
                if si < 0 or ei < 0:
                    self._json({'ok': False, 'error': 'Markers not found in index.html'}, 500); return
                new = (START + '\nconst PROJECTS = '
                       + json.dumps(blocks, indent=4, ensure_ascii=False)
                       + ';\n' + END)
                updated = html[:si] + new + html[ei + len(END):]
                idx.write_text(updated, 'utf-8')

                # ── Git commit + push ─────────────────────────────
                git_msg = None
                try:
                    subprocess.run(
                        ['git', 'add', 'index.html', '00_works', '01_figma', '01_music'],
                        cwd=str(ROOT), capture_output=True
                    )
                    cr = subprocess.run(
                        ['git', 'commit', '-m', 'publish: update portfolio'],
                        cwd=str(ROOT), capture_output=True, text=True
                    )
                    if cr.returncode != 0 and 'nothing to commit' in (cr.stdout + cr.stderr):
                        git_msg = 'nothing to commit'
                    else:
                        pr = subprocess.run(
                            ['git', 'push'],
                            cwd=str(ROOT), capture_output=True, text=True
                        )
                        git_msg = 'pushed' if pr.returncode == 0 else pr.stderr.strip()
                except Exception as ge:
                    git_msg = str(ge)

                self._json({'ok': True, 'git': git_msg}); return
            except Exception as e:
                self._json({'ok': False, 'error': str(e)}, 500); return

        self._json({'ok': False, 'error': 'Not found'}, 404)

# ── Start ──────────────────────────────────────────────────────────
key_status = 'found ✓' if api_key() else 'NOT FOUND — create _apikey.txt'
print(f'\n  Portfolio Builder  →  http://localhost:{PORT}')
print(f'  API key: {key_status}\n')
try:
    HTTPServer(('', PORT), Handler).serve_forever()
except KeyboardInterrupt:
    print('\n  Server stopped.')
