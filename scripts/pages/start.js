(async () => {
  "use strict";
  const status = document.getElementById("startup-status");
  const links = [...document.querySelectorAll("[data-start]")];
  const expected = document.querySelector('meta[name="psm-build"]')?.content;
  function enable() {
    links.forEach(link => { link.removeAttribute("aria-disabled"); link.removeAttribute("tabindex"); });
    status.textContent = "已準備好，選擇案例即可開始操作。修改會自動保留在此瀏覽器。";
  }
  try {
    if (!("serviceWorker" in navigator)) throw new Error("此瀏覽器不支援互動展示，請改用新版 Chrome、Edge、Firefox 或 Safari。");
    const registration = await navigator.serviceWorker.register("./sw.js", { scope: "./", updateViaCache: "none" });
    await registration.update();
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
      const worker = registration.active;
      if (!worker || worker.state !== "activated" || registration.installing || navigator.serviceWorker.controller !== worker) {
        await new Promise(resolve => setTimeout(resolve, 100));
        continue;
      }
      const result = await new Promise((resolve, reject) => {
        const channel = new MessageChannel();
        const timer = setTimeout(() => { channel.port1.close(); reject(new Error("載入逾時，請重新整理。")); }, 120000);
        channel.port1.onmessage = event => {
          if (event.data.ready || event.data.error) {
            clearTimeout(timer); channel.port1.close();
            if (event.data.error) reject(new Error(event.data.error));
            else resolve(event.data);
          } else status.textContent = event.data.message;
        };
        worker.postMessage({ type: "BOOT" }, [channel.port2]);
      });
      if ((!expected || result.build === expected) && navigator.serviceWorker.controller === worker && registration.active === worker) {
        enable();
        const next = new URLSearchParams(location.search).get("next");
        if (next && next.startsWith(new URL("./app/", location.href).pathname)) location.replace(next);
        return;
      }
      status.textContent = "正在切換最新版本…";
      await registration.update();
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    throw new Error("網站正在更新，請稍後重新整理。");
  } catch (error) {
    status.textContent = "載入未完成，請重新整理再試。";
    document.getElementById("startup-error").textContent = String(error);
  }
})();
