'use strict';
const http = require('http');
const fs   = require('fs');
const path = require('path');
const url  = require('url');

const PORT  = 3001;
const ROOT  = path.resolve(__dirname);
const WORKS = path.join(ROOT, '00_works');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css':  'text/css',
  '.js':   'application/javascript',
  '.json': 'application/json',
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png':  'image/png',
  '.gif':  'image/gif',
  '.webp': 'image/webp',
  '.mp4':  'video/mp4',
  '.mov':  'video/quicktime',
  '.webm': 'video/webm',
  '.svg':  'image/svg+xml',
};

function serveFile(res, filePath) {
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    return res.end('Not found');
  }
  const ext  = path.extname(filePath).toLowerCase();
  const type = MIME[ext] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': type });
  fs.createReadStream(filePath).pipe(res);
}

function readBody(req) {
  return new Promise(resolve => {
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString()));
  });
}

function getProjects() {
  if (!fs.existsSync(WORKS)) return [];
  return fs.readdirSync(WORKS)
    .filter(d => {
      try { return fs.statSync(path.join(WORKS, d)).isDirectory() && !d.startsWith('.'); }
      catch { return false; }
    })
    .sort()
    .map(dir => {
      const dirPath  = path.join(WORKS, dir);
      const jsonPath = path.join(dirPath, 'project.json');
      const all      = fs.readdirSync(dirPath).filter(f => !f.startsWith('.') && f !== 'project.json' && f !== 'index.html');
      const images   = all.filter(f => /\.(jpg|jpeg|png|gif|webp)$/i.test(f)).sort();
      const videos   = all.filter(f => /\.(mp4|mov|webm)$/i.test(f)).sort();
      let saved = null;
      if (fs.existsSync(jsonPath)) {
        try { saved = JSON.parse(fs.readFileSync(jsonPath, 'utf8')); } catch {}
      }
      const numMatch    = dir.match(/^(\d+)/);
      const defaultTitle = dir.replace(/^\d+_/, '').replace(/[-_]/g, ' ').trim();
      return { id: dir, base: `00_works/${dir}/`, images, videos, saved, defaultTitle, num: numMatch ? numMatch[1] : '00' };
    });
}

function publish() {
  const indexPath = path.join(ROOT, 'index.html');
  if (!fs.existsSync(indexPath)) return { ok: false, error: 'index.html not found' };
  let html = fs.readFileSync(indexPath, 'utf8');

  const projects = getProjects();
  const blocks = projects.map(p => {
    const s      = p.saved || {};
    const title  = s.title || p.defaultTitle;
    const images = s.images || p.images.map(f => ({ file: f, layout: 'half' }));
    const thumb  = s.thumb  || `${p.base}${p.images[0] || ''}`;
    const video  = s.video  !== undefined ? s.video : (p.videos[0] || null);

    const imgStr = images.map(i =>
      `        {file:${JSON.stringify(i.file)},layout:${JSON.stringify(i.layout||'half')}}`
    ).join(',\n');

    return `    {
        num:${JSON.stringify(p.num)},title:${JSON.stringify(title)},
        year:${JSON.stringify(s.year||'')},category:${JSON.stringify(s.category||'')},
        client:${s.client?JSON.stringify(s.client):'null'},scope:${JSON.stringify(s.scope||'')},
        description:${JSON.stringify(s.description||'')},
        thumb:${JSON.stringify(thumb)},base:${JSON.stringify(p.base)},
        video:${video?JSON.stringify(video):'null'},
        images:[\n${imgStr}\n        ]
    }`;
  });

  const newBlock = `/* PORTFOLIO-DATA:START */\nconst PROJECTS = [\n${blocks.join(',\n')}\n];\n/* PORTFOLIO-DATA:END */`;
  const updated  = html.replace(/\/\* PORTFOLIO-DATA:START \*\/[\s\S]*?\/\* PORTFOLIO-DATA:END \*\//, newBlock);

  if (updated === html) return { ok: false, error: 'Markers not found in index.html. Add /* PORTFOLIO-DATA:START */ and /* PORTFOLIO-DATA:END */ around const PROJECTS.' };
  fs.writeFileSync(indexPath, updated);
  return { ok: true };
}

// ── Server ────────────────────────────────────────────────────
http.createServer(async (req, res) => {
  const { pathname } = url.parse(req.url);

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }

  // API: list projects
  if (pathname === '/api/projects' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify(getProjects()));
  }

  // API: save project.json
  const saveMatch = pathname.match(/^\/api\/save\/(.+)$/);
  if (saveMatch && req.method === 'POST') {
    const id     = decodeURIComponent(saveMatch[1]);
    const target = path.join(WORKS, id, 'project.json');
    if (!target.startsWith(WORKS)) { res.writeHead(403); return res.end('Forbidden'); }
    fs.writeFileSync(target, await readBody(req));
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ ok: true }));
  }

  // API: publish → update index.html
  if (pathname === '/api/publish' && req.method === 'POST') {
    const result = publish();
    res.writeHead(result.ok ? 200 : 500, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify(result));
  }

  // builder UI
  if (pathname === '/' || pathname === '/builder') {
    return serveFile(res, path.join(ROOT, 'builder.html'));
  }

  // Static files (images, videos, etc.)
  serveFile(res, path.join(ROOT, decodeURIComponent(pathname)));

}).listen(PORT, () => {
  console.log(`\n  Portfolio Builder → http://localhost:${PORT}\n`);
});
