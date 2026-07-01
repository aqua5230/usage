"""JS template for the HTML usage report. Extracted verbatim from html_report.

Braces are doubled for str.format(); the three placeholders below are filled
by html_report._render_scripts.
"""

REPORT_JS_TEMPLATE = """const shareConfig = {share_config_json};
const csvData = {csv_data_json};
const maskedCsvData = {masked_csv_data_json};
const shareDialog = document.querySelector('[data-share-dialog]');
const shareFileMask = document.querySelector('[data-share-file-mask]');
const shareToast = document.querySelector('[data-share-toast]');
let shareToastTimer = null;

function showShareToast(message) {{
  window.clearTimeout(shareToastTimer);
  shareToast.textContent = message;
  shareToast.classList.add('show');
  shareToastTimer = window.setTimeout(() => {{
    shareToast.classList.remove('show');
  }}, 2500);
}}

async function copyText(text) {{
  try {{
    await navigator.clipboard.writeText(text);
    return true;
  }} catch (_) {{
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let success = false;
    try {{ success = document.execCommand('copy'); }} catch (_e) {{}}
    document.body.removeChild(ta);
    return success;
  }}
}}

function downloadBlob(blob, filename) {{
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}}

function closeShareModal() {{
  if (!shareDialog) return;
  if (shareDialog.open && typeof shareDialog.close === 'function') {{
    shareDialog.close();
  }} else {{
    shareDialog.removeAttribute('open');
  }}
}}

function downloadHtml(maskProjects) {{
  closeShareModal();
  const restores = [];
  const detached = [];
  if (maskProjects) {{
    document.querySelectorAll('.project-section .name').forEach((el, i) => {{
      restores.push({{el, original: el.textContent}});
      el.textContent = `Project ${{i + 1}}`;
    }});
    document.querySelectorAll('.session-section .name').forEach((el, i) => {{
      restores.push({{el, original: el.textContent}});
      el.textContent = `Project ${{i + 1}}`;
    }});
    document.querySelectorAll('[data-mask]').forEach((el) => {{
      restores.push({{el, original: el.textContent}});
      el.textContent = '—';
    }});
  }}
  document.querySelectorAll('[data-share-dialog], [data-share-open]').forEach((el) => {{
    detached.push({{el, parent: el.parentNode, next: el.nextSibling}});
    el.remove();
  }});
  const html = '<!doctype html>\\n' + document.documentElement.outerHTML;
  detached.forEach((item) => {{
    item.parent.insertBefore(item.el, item.next);
  }});
  restores.forEach((item) => {{
    item.el.textContent = item.original;
  }});
  const blob = new Blob([html], {{type: 'text/html'}});
  downloadBlob(blob, `usage-report-${{new Date().toISOString().slice(0, 10)}}.html`);
}}

function downloadCsv(maskProjects) {{
  closeShareModal();
  const csvText = maskProjects ? maskedCsvData : csvData;
  const blob = new Blob([csvText], {{type: 'text/csv;charset=utf-8'}});
  downloadBlob(blob, `usage-report-${{new Date().toISOString().slice(0, 10)}}.csv`);
}}

document.querySelector('[data-share-open]')?.addEventListener('click', () => {{
  shareFileMask.checked = true;
  if (typeof shareDialog.showModal === 'function') {{
    shareDialog.showModal();
  }} else {{
    shareDialog.setAttribute('open', '');
  }}
  shareFileMask.focus();
}});

document.querySelector('[data-share-close]')?.addEventListener('click', () => {{
  closeShareModal();
}});

shareDialog?.addEventListener('click', (e) => {{
  if (e.target === shareDialog) closeShareModal();
}});

document.addEventListener('click', (e) => {{
  const btn = e.target.closest('[data-share-file]');
  if (!btn) return;
  const action = btn.dataset.shareFile;
  if (action === 'download') {{
    downloadHtml(Boolean(shareFileMask?.checked));
    return;
  }}
  if (action === 'csv') {{
    downloadCsv(Boolean(shareFileMask?.checked));
  }}
}});
"""
