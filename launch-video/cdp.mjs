// Drive the headless Chrome that shows the AgentCAD viewer (started with --remote-debugging-port=9333).
// node cdp.mjs open <url>           load a page (1700x1000 CSS px, 2x pixels)
// node cdp.mjs shot <file.png>      screenshot the page
// node cdp.mjs eval "<js>"          run JS in the page and print the result
const PORT = 9333
const [cmd, arg] = process.argv.slice(2)
const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
const page = targets.find(t => t.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise(r => ws.addEventListener('open', r))
let id = 0
const pending = new Map()
ws.addEventListener('message', e => {
  const m = JSON.parse(e.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
const sleep = ms => new Promise(r => setTimeout(r, ms))
await send('Emulation.setDeviceMetricsOverride', { width: 1700, height: 1000, deviceScaleFactor: 2, mobile: false })
if (cmd === 'open') {
  await send('Page.navigate', { url: arg })
  await sleep(4000)
} else if (cmd === 'shot') {
  await sleep(1500)
  const r = await send('Page.captureScreenshot', { format: 'png' })
  const fs = await import('node:fs')
  fs.writeFileSync(arg, Buffer.from(r.result.data, 'base64'))
  console.log('saved', arg)
} else if (cmd === 'eval') {
  const r = await send('Runtime.evaluate', { expression: arg, awaitPromise: true, returnByValue: true })
  console.log(JSON.stringify(r.result?.result?.value ?? r.result))
}
ws.close()
