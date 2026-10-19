/* The original Python app executes here, isolated from the page UI thread. */
importScripts("./vendor/pyodide/pyodide.js", "./vendor/pyodide/pyodide.asm.js");
const ROOT = new URL("./", self.location.href);
const PREFIX = ROOT.pathname.replace(/\/$/, "") + "/app";
let runtime;
let serial = Promise.resolve();

async function boot(progress = () => {}) {
  if (runtime) return runtime;
  runtime = (async () => {
    progress("載入填報系統…");
    const py = await loadPyodide({ indexURL: new URL("vendor/pyodide/", ROOT).href });
    progress("準備資料庫與表單…");
    await py.loadPackage(["pydantic", "anyio", "sqlite3", "markupsafe", "micropip"]);
    const manifest = await (await fetch(new URL("wheels.json", ROOT))).json();
    py.globals.set("wheel_urls", py.toPy(manifest.map(file => new URL(file, ROOT).href)));
    await py.runPythonAsync("import micropip\nawait micropip.install(wheel_urls, deps=False)");
    const archive = new Uint8Array(await (await fetch(new URL("application.zip", ROOT))).arrayBuffer());
    py.unpackArchive(archive, "zip", { extractDir: "/bundle" });
    py.FS.mkdirTree("/psm-browser-data-v1");
    py.FS.mount(py.FS.filesystems.IDBFS, {}, "/psm-browser-data-v1");
    await new Promise((resolve, reject) => py.FS.syncfs(true, error => error ? reject(error) : resolve()));
    py.globals.set("app_prefix", PREFIX);
    await py.runPythonAsync("import sys\nsys.path.insert(0, '/bundle')\nfrom browser_bridge import boot\nbrowser_app = boot('/bundle', '/psm-browser-data-v1', app_prefix)");
    await new Promise((resolve, reject) => py.FS.syncfs(false, error => error ? reject(error) : resolve()));
    progress("可以開始操作了");
    return py;
  })().catch(error => { runtime = undefined; throw error; });
  return runtime;
}

async function dispatch(request) {
  const py = await boot();
  const url = new URL(request.url);
  const payload = {
    method: request.method,
    path: url.pathname.slice(PREFIX.length) || "/",
    query: url.search.slice(1),
    headers: Array.from(request.headers),
    body: Array.from(new Uint8Array(await request.arrayBuffer()))
  };
  py.globals.set("http_request", py.toPy(payload));
  const resultProxy = await py.runPythonAsync("await browser_app.request(http_request['method'], http_request['path'], http_request['query'], http_request['headers'], bytes(http_request['body']))");
  const result = resultProxy.toJs({ dict_converter: Object.fromEntries });
  resultProxy.destroy();
  // GET case selection also changes cookies; persist it before returning its
  // redirect, so a restarted worker keeps the selected case.
  await new Promise((resolve, reject) => py.FS.syncfs(false, error => error ? reject(error) : resolve()));
  const headers = new Headers(result.headers);
  headers.set("Cache-Control", "no-store");
  return new Response(request.method === "HEAD" ? null : result.body, { status: result.status, headers });
}

self.addEventListener("install", event => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("message", event => {
  if (event.data?.type !== "BOOT") return;
  const port = event.ports[0];
  event.waitUntil(boot(message => port.postMessage({ message }))
    .then(() => port.postMessage({ ready: true }))
    .catch(error => { console.error(error); port.postMessage({ error: String(error) }); }));
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (url.origin !== ROOT.origin || !(url.pathname === PREFIX || url.pathname.startsWith(PREFIX + "/"))) return;
  const response = serial.then(() => dispatch(event.request));
  serial = response.catch(() => {});
  event.respondWith(response.catch(error => {
    console.error(error);
    return new Response("操作未完成，請回首頁重新載入。" + String(error), {
      status: 500, headers: { "Content-Type": "text/plain;charset=utf-8" }
    });
  }));
});
