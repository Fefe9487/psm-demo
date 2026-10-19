(async () => {
  "use strict";
  const status = document.getElementById("startup-status");
  const links = [...document.querySelectorAll("[data-start]")];
  function enable() {
    links.forEach(link => { link.removeAttribute("aria-disabled"); link.removeAttribute("tabindex"); });
    status.textContent = "已準備好，選擇案例即可開始操作。修改會自動保留在此瀏覽器。";
  }
  try {
    if (!("serviceWorker" in navigator)) throw new Error("此瀏覽器不支援互動展示，請改用新版 Chrome、Edge、Firefox 或 Safari。");
    const registration = await navigator.serviceWorker.register("./sw.js", { scope: "./", updateViaCache: "none" });
    const installing = registration.installing || registration.waiting;
    if (installing && installing.state !== "activated") await new Promise((resolve, reject) => {
      installing.addEventListener("statechange", () => {
        if (installing.state === "activated") resolve();
        if (installing.state === "redundant") reject(new Error("系統更新失敗，請重新整理。"));
      });
    });
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) await new Promise(resolve => navigator.serviceWorker.addEventListener("controllerchange", resolve, { once: true }));
    const channel = new MessageChannel();
    channel.port1.onmessage = event => {
      if (event.data.ready) {
        enable(); channel.port1.close();
        const next = new URLSearchParams(location.search).get("next");
        if (next && next.startsWith(new URL("./app/", location.href).pathname)) location.replace(next);
      }
      else if (event.data.error) { status.textContent = "載入未完成，請重新整理再試。"; document.getElementById("startup-error").textContent = event.data.error; }
      else status.textContent = event.data.message;
    };
    registration.active.postMessage({ type: "BOOT" }, [channel.port2]);
  } catch (error) {
    status.textContent = "載入未完成，請重新整理再試。";
    document.getElementById("startup-error").textContent = String(error);
  }
})();
