// Screenshot the setup wizard (demo mode) in a new headless tab: node setup_shots.mjs <url>
import fs from 'node:fs'
const PORT = 9333
const url = process.argv[2]
const prefix = process.argv[3] || 'setup'
const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json()
const ws = new WebSocket(t.webSocketDebuggerUrl)
await new Promise(r => ws.addEventListener('open', r))
let id = 0
const pending = new Map()
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } })
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
const sleep = ms => new Promise(r => setTimeout(r, ms))
const js = async expr => (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value
const shot = async name => { const r = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(`frames/live/${prefix}_${name}`, Buffer.from(r.result.data, 'base64')); console.log('saved', name) }
await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 2, mobile: false })
await send('Page.navigate', { url })
await sleep(3000)
if (prefix === 'zh') {  // the page keeps its language in localStorage; switch it with its own button
  await js(`[...document.querySelectorAll('button')].find(b => b.innerText.trim() === '中文')?.click()`)
  await sleep(800)
}
console.log(await js(`[...document.querySelectorAll('button')].map(b => b.innerText.trim()).filter(Boolean).join(' | ')`))
await shot('setup_1.png')
const clicked = await js(`(() => { const b = [...document.querySelectorAll('button')].find(b => /^(Install|Set up|Start|开始)/i.test(b.innerText.trim())); if (b) { b.click(); return b.innerText.trim() } return null })()`)
console.log('clicked', clicked)
await sleep(1200)
await shot('setup_2.png')
console.log('clicked', await js(`(() => { const b = [...document.querySelectorAll('button')].find(b => /^(Install now|马上安装)/i.test(b.innerText.trim())); if (b) { b.click(); return 'Install now' } return null })()`))
for (let i = 0; i < 40; i++) { await sleep(400); await shot(`setup_3_${String(i).padStart(2, '0')}.png`); if (await js(`/All set|装好了/.test(document.body.innerText)`)) break }
await sleep(2500)
await shot('setup_4.png')
await fetch(`http://127.0.0.1:${PORT}/json/close/${t.id}`)
ws.close()
