// Render film.html frame by frame in the headless Chrome on port 9333 and pipe the frames to ffmpeg.
//   node capture.mjs <lang> stills <t1> <t2> ...   PNG stills into out/stills_<lang>/ to check a moment
//   node capture.mjs <lang> video [fps]            out/<lang>_video.mp4 (no sound) and out/<lang>_timeline.json
import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { pathToFileURL } from 'node:url'

const [lang, mode, ...rest] = process.argv.slice(2)
const PORT = 9333
const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json()
const ws = new WebSocket(t.webSocketDebuggerUrl)
ws.binaryType = 'arraybuffer'
await new Promise(r => ws.addEventListener('open', r))
let id = 0
const pending = new Map()
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } })
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
const js = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 800))
  return r.result?.result?.value
}
await send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: pathToFileURL(path.resolve('film.html')).href + `?lang=${lang}` })
for (let i = 0; i < 100; i++) { await new Promise(r => setTimeout(r, 300)); try { if (await js('window.__ready')) break } catch { } }
const total = await js('window.__total')
fs.mkdirSync('out', { recursive: true })
fs.writeFileSync(`out/${lang}_timeline.json`, JSON.stringify(await js('window.__timeline()'), null, 1))
const frame = async (sec, fmt = 'jpeg') => {
  await js(`window.__seek(${sec})`)
  const r = await send('Page.captureScreenshot', fmt === 'png' ? { format: 'png' } : { format: 'jpeg', quality: 93, optimizeForSpeed: true })
  return Buffer.from(r.result.data, 'base64')
}
if (mode === 'stills') {
  fs.mkdirSync(`out/stills_${lang}`, { recursive: true })
  for (const s of rest) { fs.writeFileSync(`out/stills_${lang}/t${String(s).padStart(6, '0')}.png`, await frame(+s, 'png')); console.log('still', s) }
} else {
  const fps = +(rest[0] || 60), n = Math.ceil(total * fps)
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p', '-r', String(fps), `out/${lang}_video.mp4`], { stdio: ['pipe', 'inherit', 'inherit'] })
  const t0 = Date.now()
  for (let i = 0; i < n; i++) {
    const buf = await frame(i / fps)
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r))
    if (i % 600 === 0) console.log(`${lang} frame ${i}/${n}  ${((Date.now() - t0) / 1000).toFixed(0)} s`)
  }
  ff.stdin.end()
  await new Promise(r => ff.on('close', r))
  console.log(`${lang} video: ${n} frames, ${total.toFixed(1)} s, rendered in ${((Date.now() - t0) / 1000).toFixed(0)} s`)
}
// close the tab, let the socket finish closing, then exit: exiting with it half closed trips a libuv assertion on
// Windows (exit 127)
await new Promise(r => { ws.addEventListener('close', r); fetch(`http://127.0.0.1:${PORT}/json/close/${t.id}`); setTimeout(r, 3000) })
setTimeout(() => process.exit(0), 200)
