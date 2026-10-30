"use strict";
(() => {
  const panel = document.getElementById("playlist-zip");
  if (!panel) return;
  const button = panel.querySelector("button");
  const status = panel.querySelector("[role=status]");
  const progress = panel.querySelector("progress");
  const link = panel.querySelector("a");
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {...options, cache: "no-store", signal: AbortSignal.timeout(30000)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "ZIP preparation failed. Try again.");
    return data;
  }
  button.addEventListener("click", async () => {
    button.disabled = true;
    link.hidden = true;
    progress.hidden = false;
    progress.removeAttribute("value");
    status.textContent = "Checking playlist files…";
    try {
      const ticket = await fetchJSON(panel.dataset.url, {
        method: "POST", headers: {"X-Amaterasu-Action": "archive"}
      });
      let failures = 0;
      while (true) {
        let state;
        try { state = await fetchJSON(ticket.status_url); failures = 0; }
        catch (error) {
          if (++failures >= 3) throw error;
          status.textContent = "Connection interrupted. Reconnecting…";
          await wait(2000); continue;
        }
        if (state.state === "ready") {
          progress.value = 1;
          link.href = ticket.download_url;
          link.hidden = false;
          status.textContent = "Your ZIP is ready. Downloads support pause, resume, and multiple connections.";
          break;
        }
        if (state.state !== "preparing") throw new Error("The ZIP expired or preparation failed. Try again.");
        progress.value = state.total ? Math.min(state.bytes / state.total, 1) : 0;
        status.textContent = `Preparing files: ${(state.bytes / 1048576).toFixed(1)} / ${(state.total / 1048576).toFixed(1)} MiB`;
        await wait(2000);
      }
    } catch (error) {
      status.textContent = error.name === "TimeoutError" ? "The server took too long. Try preparing the ZIP again." : error.message;
      progress.hidden = true;
    } finally { button.disabled = false; }
  });
})();
