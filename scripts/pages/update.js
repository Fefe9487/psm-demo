(() => {
  "use strict";
  const script = document.currentScript;
  const current = script.dataset.psmBuild;
  const root = new URL(script.dataset.psmRoot, location.origin);
  let checking = false, shown = false;
  async function check() {
    if (checking || shown || document.visibilityState === "hidden") return;
    checking = true;
    try {
      const response = await fetch(new URL("version.json", root), { cache: "no-store" });
      if (!response.ok) return;
      const latest = await response.json();
      if (!latest.build_id || latest.build_id === current) return;
      shown = true;
      const notice = document.createElement("aside");
      notice.setAttribute("role", "status");
      notice.style.cssText = "padding:12px 18px;background:#fff3d5;border-bottom:1px solid #d2b66b";
      notice.append("網站已有新版。請先儲存目前修改，再載入更新。 ");
      const link = document.createElement("a");
      const destination = new URL(root);
      destination.searchParams.set("v", latest.build_id);
      destination.searchParams.set("next", location.pathname + location.search + location.hash);
      link.href = destination.href;
      link.textContent = "載入新版";
      notice.append(link);
      document.body.prepend(notice);
    } catch (error) { /* Offline visitors can keep using their current version. */ }
    finally { checking = false; }
  }
  check();
  setInterval(check, 60000);
  window.addEventListener("focus", check);
  document.addEventListener("visibilitychange", check);
})();
