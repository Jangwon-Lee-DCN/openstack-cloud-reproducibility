(function () {
  "use strict";
  const root = document.getElementById("dcn-core");
  if (!root) return;
  const resources = {operations: "/operations", templates: "/launch-templates", scaling: "/auto-scaling-groups", recycle: "/recycle-bin"};
  const escape = value => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  Promise.all(Object.entries(resources).map(([target, path]) => fetch(root.dataset.api + path, {credentials: "same-origin", headers: {"X-CSRFToken": window.CSRF_TOKEN || ""}})
    .then(response => { if (!response.ok) throw new Error("API " + response.status); return response.json(); })
    .then(page => { document.getElementById(target).innerHTML = "<pre>" + escape(JSON.stringify(page.items || page, null, 2)) + "</pre>"; })))
    .then(() => { document.getElementById("core-status").textContent = "Project-scoped resources loaded."; })
    .catch(error => { const status = document.getElementById("core-status"); status.className = "alert alert-danger"; status.textContent = "Core orchestration API unavailable: " + error.message; });
}());
