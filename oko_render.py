"""Server-rendered HTML for OKO: static fragments, the page frame, auth/marketplace pages,
and URL/lang helpers. Presentation only — depends on oko_config + oko_i18n + stdlib, never on
app-level data helpers (data is passed in, e.g. the prebuilt sidebar `shell`). No cycles.
"""
import json
import re
from html import escape as html_escape, unescape
from urllib.parse import urlencode, quote, urlparse, parse_qs

from oko_config import *  # noqa: F401,F403
from oko_i18n import t, detect_ui_lang, SUPPORTED_UI_LANGS


def render_dashboard_base_styles() -> str:
    return """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800;900&display=swap');
:root{
  --bg:#F3F4F8;
  --bg-soft:#EAECF2;
  --surface:#FFFFFF;
  --surface-strong:#FFFFFF;
  --surface-muted:#F9FAFB;
  --border:#E5E7EB;
  --border-strong:#D1D5DB;
  --ink:#0C0C14;
  --ink-soft:#6B7280;
  --ink-faint:#9CA3AF;
  --accent:#5B6AF9;
  --accent-soft:#EEF0FE;
  --good:#2f8a57;
  --good-soft:#edf8f1;
  --warn:#9b6a19;
  --warn-soft:#fff7ea;
  --bad:#b3473f;
  --bad-soft:#fff1ef;
  --shadow:0 20px 56px rgba(12,12,20,.07);
  --shadow-soft:0 4px 16px rgba(12,12,20,.05);
  --radius-xl:18px;
  --radius-lg:18px;
  --radius-md:14px;
  --space-1:4px;
  --space-2:8px;
  --space-3:12px;
  --space-4:16px;
  --space-5:20px;
  --space-6:24px;
}
*{box-sizing:border-box}
html{color-scheme:light}
body{
  margin:0;
  min-height:100vh;
  color:var(--ink);
  font-family:"Manrope",ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:var(--bg);
}
.wrap{max-width:1240px;margin:0 auto;padding:24px 24px 40px}
.page{display:grid;grid-template-columns:minmax(0,1fr);gap:20px}
.page > *, .page-top > *, .two-col > *, .metrics-grid > *, .insight-grid > *, .stack > *{min-width:0;max-width:100%}
.panel{
  background:var(--surface);
  backdrop-filter:blur(14px);
  border:1px solid rgba(223,217,207,.96);
  border-radius:var(--radius-xl);
  box-shadow:var(--shadow-soft);
  min-width:0;
}
.header-card{padding:22px 22px 20px;box-shadow:var(--shadow)}
.panel-pad{padding:20px}
.page-top{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:start}
.page-head{min-width:0}
.eyebrow{
  margin:0 0 8px;
  font-size:12px;
  line-height:1.2;
  font-weight:800;
  letter-spacing:.12em;
  text-transform:uppercase;
  color:var(--ink-faint);
}
.page-title{
  margin:0;
  font-size:clamp(32px,4vw,40px);
  line-height:1.02;
  letter-spacing:-.04em;
  color:var(--ink);
}
.page-subtitle{
  margin:10px 0 0;
  max-width:720px;
  color:var(--ink-soft);
  font-size:15px;
  line-height:1.55;
}
.header-meta,.top-actions,.chip-row{display:flex;gap:10px;flex-wrap:wrap}
.header-meta{margin-top:16px}
.top-actions{margin-top:18px}
.chip{
  display:inline-flex;
  align-items:center;
  gap:8px;
  min-height:36px;
  padding:0 12px;
  border-radius:999px;
  border:1px solid var(--border);
  background:rgba(255,255,255,.86);
  font-size:13px;
  font-weight:700;
  color:var(--ink-soft);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.72);
}
.action-link{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:8px;
  min-height:40px;
  padding:0 16px;
  border-radius:11px;
  border:1px solid var(--border);
  background:#fff;
  color:var(--ink);
  text-decoration:none;
  font-size:14px;
  font-weight:700;
  letter-spacing:-.01em;
  appearance:none;
  cursor:pointer;
  transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease, background .15s ease;
}
.action-link:hover{transform:translateY(-1px);box-shadow:var(--shadow-soft);border-color:var(--border-strong)}
.action-link.primary{background:#5B6AF9;border-color:#5B6AF9;color:#fff}
.action-link.primary:hover{background:#7B87FF;border-color:#7B87FF}
.action-link.secondary{background:var(--surface-muted);border-color:var(--border)}
.action-link.danger{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.action-inline{display:flex;gap:8px;flex-wrap:wrap}
.back-link{
  display:inline-flex;
  align-items:center;
  gap:8px;
  text-decoration:none;
  color:var(--ink-faint);
  font-size:13px;
  font-weight:700;
}
.back-link:hover{color:var(--ink)}
.lang-switch{
  display:inline-flex;
  align-self:flex-start;
  gap:3px;
  align-items:center;
  flex-wrap:nowrap;
  padding:3px;
  border-radius:10px;
  background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.09);
  margin-bottom:18px;
}
.lang-btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:44px;
  min-height:28px;
  padding:0 10px;
  border-radius:7px;
  text-decoration:none;
  font-size:11px;
  font-weight:800;
  letter-spacing:.04em;
  color:rgba(255,255,255,.4);
  transition:background .15s,color .15s;
}
.lang-btn.active{background:#5B6AF9;color:#fff}
.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.kpi{
  position:relative;
  overflow:hidden;
  padding:18px 18px 16px;
}
.kpi::after{
  content:'';
  position:absolute;
  inset:auto 0 0 0;
  height:3px;
  background:linear-gradient(90deg, rgba(79,90,104,.44), rgba(79,90,104,0));
  opacity:.22;
}
.kpi.good::after{background:linear-gradient(90deg, rgba(47,138,87,.90), rgba(47,138,87,0));opacity:.28}
.kpi.mid::after,.kpi.warn::after{background:linear-gradient(90deg, rgba(155,106,25,.90), rgba(155,106,25,0));opacity:.28}
.kpi.bad::after{background:linear-gradient(90deg, rgba(179,71,63,.90), rgba(179,71,63,0));opacity:.28}
.kpi-label{
  margin:0 0 10px;
  font-size:12px;
  font-weight:800;
  line-height:1.35;
  letter-spacing:.08em;
  color:var(--ink-faint);
  text-transform:uppercase;
}
.kpi-value{
  margin:0;
  font-size:clamp(34px,3vw,40px);
  line-height:.95;
  font-weight:900;
  letter-spacing:-.05em;
  color:var(--ink);
}
.kpi-note{margin:10px 0 0;color:var(--ink-soft);font-size:13px;line-height:1.45}
.kpi-subvalue{margin-top:8px;font-size:14px;font-weight:700;color:var(--ink-soft)}
.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:16px}
.panel-title{margin:0;font-size:24px;line-height:1.1;letter-spacing:-.03em;color:var(--ink)}
.panel-subtitle{margin:6px 0 0;color:var(--ink-soft);font-size:14px;line-height:1.5}
.two-col{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(320px,1fr);gap:18px;align-items:start}
.stack{display:grid;gap:18px}
.table-wrap,.hscroll{overflow:auto}
table{width:100%;border-collapse:separate;border-spacing:0}
th,td{padding:14px 12px;border-bottom:1px solid #ebe6de;text-align:left;vertical-align:top}
th{
  font-size:12px;
  font-weight:800;
  letter-spacing:.10em;
  text-transform:uppercase;
  color:var(--ink-faint);
  background:rgba(247,244,239,.92);
}
td{font-size:14px;line-height:1.5;color:var(--ink-soft)}
tbody tr:hover td{background:rgba(247,244,239,.82)}
.sub{font-size:12px;color:var(--ink-faint);margin-top:4px;line-height:1.35}
.score-pill{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:76px;
  min-height:32px;
  padding:0 10px;
  border-radius:999px;
  border:1px solid var(--border);
  background:#fff;
  color:var(--ink-soft);
  font-size:12px;
  font-weight:900;
}
.score-pill.good{background:var(--good-soft);border-color:#cde7d7;color:var(--good)}
.score-pill.mid{background:var(--warn-soft);border-color:#f1dfbb;color:var(--warn)}
.score-pill.bad{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.badge{
  display:inline-flex;
  align-items:center;
  gap:6px;
  min-height:30px;
  padding:0 10px;
  border-radius:999px;
  border:1px solid var(--border);
  background:#fff;
  font-size:12px;
  font-weight:800;
  color:var(--ink-soft);
}
.badge.good{background:var(--good-soft);border-color:#cde7d7;color:var(--good)}
.badge.warn{background:var(--warn-soft);border-color:#f1dfbb;color:var(--warn)}
.badge.bad{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.clickable{
  cursor:pointer;
  transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.clickable:hover{transform:translateY(-2px);box-shadow:var(--shadow);border-color:var(--border-strong)}
.clickable:focus-visible{outline:2px solid rgba(79,90,104,.24);outline-offset:2px}
[data-reveal]{
  opacity:0;
  transform:translateY(14px);
  animation:pageReveal .55s cubic-bezier(.2,.7,.2,1) forwards;
  animation-delay:calc(var(--reveal, 0) * 70ms);
}
ul{margin:0;padding-left:18px}
li{margin:6px 0}
@keyframes pageReveal{to{opacity:1;transform:translateY(0)}}
@media (prefers-reduced-motion: reduce){
  [data-reveal]{opacity:1;transform:none;animation:none}
  .action-link,.clickable{transition:none}
}
@media (max-width: 1040px){
  .kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .two-col{grid-template-columns:1fr}
}
@media (max-width: 720px){
  .wrap{padding:16px 16px 28px}
  .header-card,.panel-pad,.kpi{padding:16px}
  .page-top{grid-template-columns:1fr;gap:12px}
  .page-title{font-size:32px}
  .page-subtitle{font-size:14px}
  .page-title,.page-subtitle,.panel-title{overflow-wrap:anywhere;word-break:break-word}
  .header-meta,.top-actions{gap:8px}
  .chip{width:100%;justify-content:flex-start;padding:8px 12px;min-height:40px;overflow-wrap:anywhere;word-break:break-word}
  .top-actions{display:grid;grid-template-columns:1fr;gap:8px}
  .action-link{width:100%}
  .lang-switch{justify-self:start}
  .kpi-grid{grid-template-columns:1fr}
  .panel-head{display:grid;grid-template-columns:1fr;gap:8px}
  .panel-title{font-size:21px}
  th,td{padding:10px;font-size:13px}
}
.shell{display:flex;min-height:100vh}
.shell-grid{display:flex;width:100%;align-items:stretch}
.sidebar{
  width:248px;
  flex-shrink:0;
  min-height:100vh;
  position:sticky;
  top:0;
  height:100vh;
  overflow-y:auto;
  padding:20px 16px 24px;
  background:#0C0C14;
  border-right:1px solid rgba(255,255,255,.07);
  display:flex;
  flex-direction:column;
}
.sidebar-brand{display:flex;align-items:center;gap:10px;padding:0 4px;margin-bottom:24px}
.sidebar-logo-icon{width:30px;height:30px;background:#5B6AF9;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900;color:#fff;flex-shrink:0}
.sidebar-title{margin:0;font-size:15px;font-weight:800;line-height:1.1;letter-spacing:-.01em;color:#fff}
.sidebar-subtitle{margin:3px 0 0;font-size:11px;color:rgba(255,255,255,.35);line-height:1.3}
.sidebar-group{margin-top:22px}
.sidebar-group:first-of-type{margin-top:0}
.sidebar-label{margin:0 0 6px;padding:0 8px;font-size:10px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.28)}
.sidebar-nav{display:grid;gap:2px}
.sidebar-link{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  min-height:38px;padding:0 10px;border-radius:10px;
  color:rgba(255,255,255,.55);text-decoration:none;font-size:13px;font-weight:700;
  border:1px solid transparent;transition:background .15s,color .15s,border-color .15s;
}
.sidebar-link:hover{background:rgba(255,255,255,.07);color:rgba(255,255,255,.85)}
.sidebar-link.active{background:#5B6AF9;color:#fff;border-color:transparent}
.sidebar-link.minor{font-weight:600;font-size:12px;min-height:34px}
.sidebar-link.disabled{opacity:.28;cursor:default;pointer-events:none}
.sidebar-item-row{display:flex;align-items:center;gap:4px}
.sidebar-item-row .sidebar-link{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sidebar-delete-form{flex-shrink:0;margin:0}
.sidebar-delete-btn{display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:7px;border:1px solid transparent;background:transparent;color:rgba(255,255,255,.3);font-size:15px;line-height:1;cursor:pointer;transition:background .12s,color .12s,border-color .12s;padding:0}
.sidebar-delete-btn:hover{background:rgba(239,68,68,.15);border-color:rgba(239,68,68,.3);color:#f87171}
.sidebar-meta{margin-top:auto;padding-top:16px;border-top:1px solid rgba(255,255,255,.07)}
.sidebar-logout{
  display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:0 14px;
  border-radius:9px;border:1px solid rgba(255,255,255,.1);background:transparent;color:rgba(255,255,255,.45);
  font-family:inherit;font-size:12px;font-weight:700;cursor:pointer;transition:background .15s,color .15s,border-color .15s;
}
.sidebar-logout:hover{background:rgba(255,255,255,.08);color:rgba(255,255,255,.8);border-color:rgba(255,255,255,.2)}
.content-wrap{flex:1;min-width:0;overflow:auto}
.content-inner{padding:28px 28px 48px}
.auth-page{max-width:420px;margin:80px auto 0}
.auth-card{padding:24px}
.auth-form{display:grid;gap:12px;margin-top:18px}
.field-label{font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint)}
.field-input,.field-textarea,.field-select{
  width:100%;min-height:44px;padding:12px 14px;border-radius:14px;
  border:1px solid var(--border);background:#fff;color:var(--ink);font:inherit;
}
.field-textarea{min-height:120px;resize:vertical}
.form-error{padding:12px 14px;border-radius:14px;background:var(--bad-soft);border:1px solid #f0d2ce;color:var(--bad);font-size:14px;line-height:1.45}
.form-success{padding:12px 14px;border-radius:14px;background:var(--good-soft);border:1px solid #cde7d7;color:var(--good);font-size:14px;line-height:1.45}
.submit-btn{
  display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 16px;
  border:0;border-radius:12px;background:var(--ink);color:#fff;font:inherit;font-weight:800;cursor:pointer;
}
.submit-btn:hover{background:#2a313b}
.muted{color:var(--ink-soft)}
.dashboard-grid{display:grid;gap:18px}
.employee-table td strong{color:var(--ink)}
.employee-link{color:var(--ink);text-decoration:none}
.employee-link:hover{color:var(--ink);text-decoration:underline}
.split-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.status-list{display:grid;gap:10px}
.status-row{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr) auto;gap:12px;align-items:start;padding:14px;border:1px solid var(--border);border-radius:16px;background:#fff}
.status-row.compact{grid-template-columns:minmax(0,1fr)}
.status-name{font-size:14px;font-weight:800;color:var(--ink);line-height:1.4}
.status-copy{font-size:13px;color:var(--ink-soft);line-height:1.5}
.pill{display:inline-flex;align-items:center;justify-content:center;min-height:30px;padding:0 10px;border-radius:999px;border:1px solid var(--border);background:#fff;color:var(--ink-soft);font-size:12px;font-weight:800}
.pill.good{background:var(--good-soft);border-color:#cde7d7;color:var(--good)}
.pill.warn{background:var(--warn-soft);border-color:#f1dfbb;color:var(--warn)}
.pill.bad{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.quick-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.empty-note{padding:14px;border:1px dashed var(--border-strong);border-radius:16px;color:var(--ink-soft);background:rgba(255,255,255,.65)}
.modal-backdrop{
  position:fixed;
  inset:0;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:16px;
  background:rgba(20,25,34,.34);
  backdrop-filter:blur(10px);
  opacity:0;
  pointer-events:none;
  transition:opacity .18s ease;
  z-index:60;
}
.modal-backdrop.open{opacity:1;pointer-events:auto}
.modal-card{
  width:min(100%, 460px);
  padding:22px;
  border-radius:18px;
  background:rgba(255,255,255,.96);
  border:1px solid rgba(223,217,207,.96);
  box-shadow:var(--shadow);
}
.modal-title{margin:0;font-size:24px;line-height:1.1;letter-spacing:-.03em;color:var(--ink)}
.modal-copy{margin:10px 0 0;color:var(--ink-soft);font-size:15px;line-height:1.55}
.modal-actions{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;margin-top:18px}
.modal-actions .action-link{min-width:120px}
body.modal-open{overflow:hidden}
@media (max-width: 1040px){
  .sidebar{display:none}
  .split-two,.quick-grid{grid-template-columns:1fr}
}
@media (max-width: 720px){
  .content-inner{padding:16px 16px 32px}
  .modal-actions{display:grid;grid-template-columns:1fr}
}
"""


def render_confirm_modal(lang: str) -> str:
    return (
        "<div class='modal-backdrop' id='confirm-modal' hidden>"
        "<div class='modal-card panel' role='dialog' aria-modal='true' aria-labelledby='confirm-modal-title'>"
        f"<h2 class='modal-title' id='confirm-modal-title'>{html_escape(t(lang, 'delete_employee'))}</h2>"
        "<p class='modal-copy' id='confirm-modal-copy'></p>"
        "<div class='modal-actions'>"
        f"<button type='button' class='action-link secondary' id='confirm-modal-cancel'>{html_escape(t(lang, 'cancel_action'))}</button>"
        f"<button type='button' class='action-link danger' id='confirm-modal-submit'>{html_escape(t(lang, 'confirm_action'))}</button>"
        "</div>"
        "</div>"
        "</div>"
    )


def render_frame_script() -> str:
    return """<script>
(function(){
  const modal = document.getElementById('confirm-modal');
  if (!modal) return;
  const copy = document.getElementById('confirm-modal-copy');
  const cancelBtn = document.getElementById('confirm-modal-cancel');
  const submitBtn = document.getElementById('confirm-modal-submit');
  let pendingForm = null;

  function closeModal() {
    modal.classList.remove('open');
    modal.hidden = true;
    document.body.classList.remove('modal-open');
    pendingForm = null;
  }

  function openModal(form) {
    pendingForm = form;
    copy.textContent = form.getAttribute('data-confirm-message') || '';
    modal.hidden = false;
    requestAnimationFrame(function(){ modal.classList.add('open'); });
    document.body.classList.add('modal-open');
  }

  document.addEventListener('submit', function(event){
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.hasAttribute('data-confirm-message')) return;
    if (form.dataset.confirmed === '1') {
      delete form.dataset.confirmed;
      return;
    }
    event.preventDefault();
    openModal(form);
  }, true);

  cancelBtn.addEventListener('click', closeModal);
  submitBtn.addEventListener('click', function(){
    if (!pendingForm) return;
    pendingForm.dataset.confirmed = '1';
    pendingForm.submit();
    closeModal();
  });

  modal.addEventListener('click', function(event){
    if (event.target === modal) closeModal();
  });

  document.addEventListener('keydown', function(event){
    if (event.key === 'Escape' && !modal.hidden) closeModal();
  });
})();
</script>"""


def lang_query_href(path: str, params: dict | None, lang: str) -> str:
    qp = {}
    for key, values in (params or {}).items():
        if key == 'lang':
            continue
        qp[key] = list(values) if isinstance(values, list) else [values]
    qp['lang'] = [lang]
    query = urlencode(qp, doseq=True)
    return f"{path}?{query}" if query else path


def add_lang_to_href(href: str, lang: str) -> str:
    if not href:
        return href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    params['lang'] = [lang]
    query = urlencode(params, doseq=True)
    path = parsed.path or ''
    fragment = f"#{parsed.fragment}" if parsed.fragment else ''
    if query:
        return f"{path}?{query}{fragment}"
    return f"{path}{fragment}"


def add_query_to_href(href: str, **extra_params) -> str:
    if not href:
        return href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    for key, value in extra_params.items():
        if value is None:
            continue
        params[str(key)] = [str(value)]
    query = urlencode(params, doseq=True)
    path = parsed.path or ''
    fragment = f"#{parsed.fragment}" if parsed.fragment else ''
    if query:
        return f"{path}?{query}{fragment}"
    return f"{path}{fragment}"


def status_label(lang: str, status: str | None) -> str:
    key = f"status_{str(status or '').strip().lower()}"
    return t(lang, key)


def render_lang_switch(path: str, params: dict | None, lang: str) -> str:
    ru_href = lang_query_href(path, params, 'ru')
    kk_href = lang_query_href(path, params, 'kk')
    return (
        "<div class='lang-switch'>"
        f"<a class='lang-btn {'active' if lang == 'ru' else ''}' href='{html_escape(ru_href)}'>{html_escape(t(lang, 'lang_ru'))}</a>"
        f"<a class='lang-btn {'active' if lang == 'kk' else ''}' href='{html_escape(kk_href)}'>{html_escape(t(lang, 'lang_kk'))}</a>"
        "</div>"
    )


def render_sidebar_html(lang: str, shell: dict | None) -> str:
    shell = shell or {}
    groups = shell.get('groups') if isinstance(shell.get('groups'), list) else []
    lang_switch = shell.get('lang_switch') or ''
    logout_html = shell.get('logout_html') or ''
    sections = []
    for group in groups:
        label = str(group.get('label') or '').strip()
        items = group.get('items') if isinstance(group.get('items'), list) else []
        item_html = []
        for item in items:
            if not isinstance(item, dict) or not str(item.get('label') or '').strip():
                continue
            label_text = html_escape(str(item.get('label') or ''))
            if item.get('disabled'):
                item_html.append(f"<span class='sidebar-link minor disabled'>{label_text}</span>")
                continue
            href = str(item.get('href') or '').strip() or '#'
            cls = ['sidebar-link']
            if item.get('active'):
                cls.append('active')
            if item.get('minor'):
                cls.append('minor')
            delete_href = str(item.get('delete_href') or '').strip()
            delete_id = item.get('delete_id')
            if delete_href and delete_id:
                confirm_msg = html_escape(t(lang, 'crm_disconnect_confirm'))
                item_html.append(
                    f"<div class='sidebar-item-row'>"
                    f"<a class='{' '.join(cls)}' href='{html_escape(href)}'>{label_text}</a>"
                    f"<form method='post' action='{html_escape(delete_href)}' class='sidebar-delete-form'"
                    f" data-confirm-message='{confirm_msg}'>"
                    f"<input type='hidden' name='connection_id' value='{int(delete_id)}'/>"
                    f"<button type='submit' class='sidebar-delete-btn' title='Удалить'>×</button>"
                    f"</form>"
                    f"</div>"
                )
            else:
                item_html.append(f"<a class='{' '.join(cls)}' href='{html_escape(href)}'>{label_text}</a>")
        if not item_html:
            continue
        sections.append(
            "<section class='sidebar-group'>"
            f"<p class='sidebar-label'>{html_escape(label)}</p>"
            f"<nav class='sidebar-nav'>{''.join(item_html)}</nav>"
            "</section>"
        )
    return (
        "<aside class='sidebar'>"
        "<div class='sidebar-brand'>"
        "<div class='sidebar-logo-icon'>О</div>"
        "<div>"
        f"<h2 class='sidebar-title'>{html_escape(t(lang, 'product_title'))}</h2>"
        f"<p class='sidebar-subtitle'>{html_escape(t(lang, 'rop_dashboard_subtitle'))}</p>"
        "</div>"
        "</div>"
        f"{lang_switch}"
        f"{''.join(sections)}"
        f"<div class='sidebar-meta'>{logout_html}</div>"
        "</aside>"
    )


def render_page_frame(lang: str, title: str, body_html: str, extra_style: str = '', script: str = '', shell: dict | None = None) -> str:
    shell_html = ''
    if shell and shell.get('authenticated'):
        sidebar_html = render_sidebar_html(lang, shell)
        shell_html = f"<div class='shell'><div class='shell-grid'>{sidebar_html}<main class='content-wrap'><div class='content-inner'><div class='page'>{body_html}</div></div></main></div></div>"
    else:
        shell_html = f"<div class='wrap'><div class='page'>{body_html}</div></div>"
    return f"""<!doctype html>
<html lang="{html_escape(lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(title)}</title>
<style>{render_dashboard_base_styles()}{extra_style}</style></head><body>
{shell_html}
{render_confirm_modal(lang)}
{render_frame_script()}
{script}
</body></html>"""


def render_logout_button(lang: str, current_path: str) -> str:
    return (
        "<form method='post' action='/logout' style='margin:0'>"
        f"<input type='hidden' name='next' value='{html_escape(current_path or '/')}'/>"
        f"<button type='submit' class='sidebar-logout'>{html_escape(t(lang, 'logout'))}</button>"
        "</form>"
    )


def render_marketplace_app_page(lang: str, notice_text: str = '', error_text: str = '', values: dict | None = None) -> str:
    values = values or {}
    name_value = html_escape(str(values.get('name') or '').strip())
    email_value = html_escape(str(values.get('email') or '').strip())
    company_value = html_escape(str(values.get('company') or '').strip())
    message_value = html_escape(str(values.get('message') or '').strip())
    notice_html = f"<div class='form-success market-feedback' style='margin-bottom:16px'>{html_escape(notice_text)}</div>" if notice_text else ''
    error_html = f"<div class='form-error market-feedback' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    body_html = """
<section class="panel market-hero" data-reveal style="--reveal:0">
  <p class="eyebrow">Приложение для Bitrix24</p>
  <h1 class="page-title" style="font-size:clamp(28px,4vw,42px);margin-bottom:10px">Oko Systems</h1>
  <p class="page-subtitle market-subtitle">
    AI-приложение для Bitrix24, которое собирает коммуникации по сделке, расшифровывает звонки,
    строит хронологию касаний и формирует отчёт по качеству работы отдела продаж на демо- и рабочих данных портала.
  </p>
  <div class="market-hero-actions">
    <a class="action-link" href="mailto:support@salmetov.fun">Связаться с разработчиком</a>
    <a class="action-link secondary" href="mailto:support@salmetov.fun?subject=Запрос%20демонстрации%20Oko%20Systems">Запросить демонстрацию</a>
  </div>
</section>

<section class="market-grid">
  <article class="panel market-card" data-reveal style="--reveal:1">
    <div class="market-card-head">
      <p class="market-kicker">Что делает приложение</p>
    </div>
    <div class="market-card-body">
      <ul class="market-list">
      <li>Получает данные сделки, контакта, активностей и комментариев таймлайна Bitrix24.</li>
      <li>Находит звонки, загружает аудио и расшифровывает разговоры.</li>
      <li>Определяет сотрудника, который вёл коммуникацию, и собирает полную хронологию взаимодействия.</li>
      <li>Формирует AI-отчёт по скрипту, качеству обработки лида и точкам роста сотрудника.</li>
      </ul>
    </div>
  </article>

  <article class="panel market-card" data-reveal style="--reveal:2">
    <div class="market-card-head">
      <p class="market-kicker">Поддержка и обратная связь</p>
    </div>
    <div class="market-card-body">
      <div class="market-facts">
        <div class="market-fact"><span class="market-fact-label">Канал</span><span class="market-fact-value"><a href="mailto:support@salmetov.fun">support@salmetov.fun</a></span></div>
        <div class="market-fact"><span class="market-fact-label">Сайт</span><span class="market-fact-value"><a href="https://ai.salmetov.fun/app">ai.salmetov.fun/app</a></span></div>
        <div class="market-fact"><span class="market-fact-label">Часы работы</span><span class="market-fact-value">пн-пт, 10:00-19:00</span></div>
        <div class="market-fact"><span class="market-fact-label">Часовой пояс</span><span class="market-fact-value">UTC+5, Asia/Almaty</span></div>
        <div class="market-fact"><span class="market-fact-label">Время реакции</span><span class="market-fact-value">обычно до 4 рабочих часов, в сложных случаях до 1 рабочего дня</span></div>
      </div>
    </div>
  </article>

  <article class="panel market-card" data-reveal style="--reveal:3">
    <div class="market-card-head">
      <p class="market-kicker">Как проходит подключение</p>
    </div>
    <div class="market-card-body">
      <ol class="market-steps">
        <li>Пользователь устанавливает приложение из Маркета Bitrix24.</li>
        <li>После установки открывается экран с инструкцией по подключению портала.</li>
        <li>Администратор подтверждает доступ к Bitrix24 и возвращается в кабинет Oko Systems.</li>
        <li>После авторизации становятся доступны анализ сделок, хронология коммуникаций и AI-отчёты.</li>
      </ol>
    </div>
  </article>
  <article class="panel market-card" data-reveal style="--reveal:4">
    <div class="market-card-head">
      <p class="market-kicker">Контакты</p>
    </div>
    <div class="market-card-body">
      <p class="market-copy">
        Для вопросов по установке, демонстрации и технической поддержке используйте форму связи через email.
        При обращении укажите домен вашего Bitrix24 и кратко опишите задачу.
      </p>
      <div class="market-hero-actions market-hero-actions-compact">
        <a class="action-link" href="mailto:support@salmetov.fun?subject=Поддержка%20Oko%20Systems">Написать в поддержку</a>
      </div>
    </div>
  </article>

  <article class="panel market-card market-form-card" data-reveal style="--reveal:5">
    <div class="market-card-head">
      <p class="market-kicker">Форма связи</p>
    </div>
    <div class="market-card-body">
    """ + notice_html + error_html + f"""
    <form method="post" action="/app/contact" class="market-form">
      <input type="hidden" name="lang" value="{html_escape(lang)}" />
      <label>
        <span class="field-label">Ваше имя</span>
        <input class="field-input" type="text" name="name" maxlength="120" value="{name_value}" required />
      </label>
      <label>
        <span class="field-label">Email</span>
        <input class="field-input" type="email" name="email" maxlength="160" value="{email_value}" required />
      </label>
      <label>
        <span class="field-label">Компания / Bitrix24</span>
        <input class="field-input" type="text" name="company" maxlength="160" value="{company_value}" placeholder="Например: Ferrum / ferrum.bitrix24.kz" />
      </label>
      <label>
        <span class="field-label">Сообщение</span>
        <textarea class="field-textarea" name="message" maxlength="3000" required>{message_value}</textarea>
      </label>
      <button class="submit-btn" type="submit">Отправить запрос</button>
    </form>
    </div>
  </article>
</section>
"""
    extra_style = """
.market-hero{max-width:920px;width:min(920px,100%);margin:24px auto 18px;padding:32px;display:grid;gap:18px;box-sizing:border-box}
.market-subtitle{max-width:none}
.market-hero .page-subtitle{max-width:none}
.market-grid{max-width:920px;margin:0 auto;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.market-card{padding:24px;display:grid;grid-template-rows:auto 1fr;gap:16px;min-height:100%}
.market-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding-bottom:14px;border-bottom:1px solid rgba(33,35,43,.08)}
.market-card-body{display:grid;gap:16px;align-content:start}
.market-form-card{grid-column:1 / -1}
.market-kicker{margin:0;font-size:12px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-faint)}
.market-copy{margin:0;color:var(--ink-soft);line-height:1.65}
.market-list,.market-steps{margin:0;padding-left:18px;color:var(--ink-soft);line-height:1.65}
.market-list li+.market-list li,.market-steps li+.market-steps li{margin-top:8px}
.market-facts{display:grid;gap:12px}
.market-fact{display:grid;gap:4px;padding-bottom:12px;border-bottom:1px solid rgba(33,35,43,.06)}
.market-fact:last-child{padding-bottom:0;border-bottom:0}
.market-fact-label{font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint)}
.market-fact-value{color:var(--ink-soft);line-height:1.6}
.market-fact-value a{color:var(--ink-soft)}
.market-hero-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}
.market-hero-actions-compact{margin-top:2px}
.market-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.market-form label:last-of-type{grid-column:1 / -1}
.market-form .submit-btn{grid-column:1 / -1;justify-self:start}
.market-feedback{max-width:720px}
@media(max-width:720px){
  .market-hero{margin:16px auto;padding:22px 18px}
  .market-grid{grid-template-columns:1fr;gap:14px}
  .market-card{padding:18px}
  .market-hero-actions{display:grid;grid-template-columns:1fr}
  .market-form{grid-template-columns:1fr}
}
"""
    return render_page_frame(lang, 'Oko Systems для Bitrix24', body_html, extra_style=extra_style)


def render_marketplace_install_page(lang: str, title: str, subtitle: str, status: str = 'info', action_href: str = '/login', action_label: str = 'Открыть кабинет', next_steps: list[str] | None = None) -> str:
    status_cls = 'warn'
    if status == 'success':
        status_cls = 'good'
    elif status == 'error':
        status_cls = 'bad'
    steps = next_steps or []
    steps_html = ''.join(f"<li>{item}</li>" for item in steps)
    note_html = ''
    if steps_html:
        note_html = f"""
  <div class="install-note {status_cls}">
    <strong>Что делать дальше:</strong>
    <ul>
      {steps_html}
    </ul>
  </div>
"""
    body_html = f"""
<section class="panel install-page" data-reveal style="--reveal:0">
  <p class="eyebrow">Установка приложения Bitrix24</p>
  <h1 class="page-title" style="font-size:clamp(26px,3.5vw,38px);margin-bottom:10px">{html_escape(title)}</h1>
  <p class="page-subtitle install-subtitle">{html_escape(subtitle)}</p>

  {note_html}

  <div class="install-actions">
    <a class="action-link" href="{html_escape(action_href)}" target="_blank" rel="noopener noreferrer">{html_escape(action_label)}</a>
    <a class="action-link secondary" href="/app" target="_blank" rel="noopener noreferrer">Инструкция и контакты</a>
  </div>
</section>
"""
    extra_style = """
.install-page{max-width:720px;margin:40px auto;padding:32px}
.install-subtitle{max-width:620px}
.install-note{margin-top:22px;padding:18px 20px;border-radius:18px;border:1px solid var(--border);background:var(--surface-muted);color:var(--ink-soft);line-height:1.65}
.install-note.good{background:var(--good-soft);border-color:#cde7d7;color:var(--good)}
.install-note.warn{background:var(--warn-soft);border-color:#f1dfbb;color:#6f5318}
.install-note.bad{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.install-note strong{display:block;margin-bottom:10px;color:var(--ink)}
.install-note ul{margin:0;padding-left:18px}
.install-note a{color:inherit}
.install-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}
@media(max-width:600px){
  .install-page{margin:16px auto;padding:22px 18px}
  .install-actions{display:grid;grid-template-columns:1fr}
}
    """
    return render_page_frame(lang, 'Установка Oko Systems', body_html, extra_style=extra_style)


def render_bitrix_embedded_page(
    lang: str,
    auth_session: dict | None = None,
    domain: str = '',
    member_id: str = '',
    current_path: str = '/connect/bitrix',
    query_params: dict | None = None,
    install_token: str = '',
    error_text: str = '',
    register_values: dict | None = None,
    login_value: str = '',
) -> str:
    domain_value = str(domain or '').strip()
    member_value = str(member_id or '').strip()
    has_auth = bool(auth_session)
    install_token_value = str(install_token or '').strip()
    register_values = register_values or {}
    quick_name_value = html_escape(str(register_values.get('name') or '').strip())
    quick_email_value = html_escape(str(register_values.get('email') or '').strip())
    login_input_value = html_escape(str(login_value or '').strip())
    error_html = f"<div class='form-error embedded-error'>{html_escape(error_text)}</div>" if error_text else ''

    status_title = 'Oko Systems для Bitrix24'
    status_copy = 'Войдите по коду из письма или создайте аккаунт через email.'
    primary_href = '/login?lang=ru'
    primary_label = 'Войти'
    secondary_href = '/register?lang=ru'
    secondary_label = 'Создать аккаунт'

    if has_auth:
        status_title = 'Bitrix24 готов'
        status_copy = 'Профиль Oko Systems найден. Можно продолжить работу в кабинете.'
        primary_href = "/"
        primary_label = 'Открыть кабинет'
        secondary_href = "/connect/bitrix"
        secondary_label = 'Подключить Bitrix24'
    elif install_token_value:
        status_title = 'Быстрый вход в Oko Systems'
        status_copy = 'Один код на почту для входа или регистрации. После подтверждения продолжим прямо из Bitrix24.'
    elif member_value or domain_value:
        status_title = 'Приложение установлено в Bitrix24'
        status_copy = 'Войдите в Oko Systems, чтобы привязать портал и перейти в кабинет.'

    onboarding_html = ''
    top_actions_html = f"""
  <div class="top-actions">
    <a class="action-link primary" href="{html_escape(add_lang_to_href(primary_href, lang))}">{html_escape(primary_label)}</a>
    <a class="action-link secondary" href="{html_escape(add_lang_to_href(secondary_href, lang))}">{html_escape(secondary_label)}</a>
  </div>
"""
    page_script = ''
    if install_token_value and not has_auth:
        next_href = html_escape(add_lang_to_href(f"/connect/bitrix?install_token={install_token_value}", lang))
        top_actions_html = """
  <div class="top-actions">
    <button type="button" class="action-link primary embedded-top-toggle active" data-auth-mode="login">Войти</button>
    <button type="button" class="action-link secondary embedded-top-toggle" data-auth-mode="register">Создать аккаунт</button>
  </div>
"""
        onboarding_html = f"""
<div class="embedded-inline-auth" data-reveal style="--reveal:1">
  <div class="embedded-auth-panel active" data-auth-panel="login">
    <div class="embedded-inline-copy">
      <p class="embedded-kicker">Вход</p>
      <h2 class="embedded-card-title">Войти по коду</h2>
      <p class="embedded-card-copy">Введите email. Мы отправим одноразовый код и после подтверждения сразу продолжим из Bitrix24.</p>
      {error_html}
    </div>
    <form method="post" action="/login" class="auth-form embedded-inline-form">
      <input type="hidden" name="install_token" value="{html_escape(install_token_value)}" />
      <input type="hidden" name="next" value="{next_href}" />
      <label class="auth-label" for="embedded-login-email">Email</label>
      <input class="auth-input" id="embedded-login-email" name="email" type="email" autocomplete="email" value="{login_input_value}" required />
      <button class="auth-submit" type="submit">Отправить код</button>
    </form>
  </div>
  <div class="embedded-auth-panel" data-auth-panel="register">
    <div class="embedded-inline-copy">
      <p class="embedded-kicker">Регистрация</p>
      <h2 class="embedded-card-title">Создать аккаунт</h2>
      <p class="embedded-card-copy">Укажите имя и email. Мы отправим код подтверждения и после него сразу откроем кабинет.</p>
    </div>
    <form method="post" action="/register" class="auth-form embedded-inline-form">
      <input type="hidden" name="install_token" value="{html_escape(install_token_value)}" />
      <label class="auth-label" for="embedded-register-name">Имя</label>
      <input class="auth-input" id="embedded-register-name" name="name" type="text" autocomplete="name" value="{quick_name_value}" required />
      <label class="auth-label" for="embedded-register-email">Email</label>
      <input class="auth-input" id="embedded-register-email" name="email" type="email" autocomplete="email" value="{quick_email_value}" required />
      <button class="auth-submit" type="submit">Создать и получить код</button>
    </form>
  </div>
</div>
"""
        page_script = """
<script>
(function(){
  var toggles = Array.prototype.slice.call(document.querySelectorAll('[data-auth-mode]'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('[data-auth-panel]'));
  if (!toggles.length || !panels.length) return;
  function setMode(mode){
    toggles.forEach(function(btn){
      var active = btn.getAttribute('data-auth-mode') === mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    panels.forEach(function(panel){
      panel.classList.toggle('active', panel.getAttribute('data-auth-panel') === mode);
    });
  }
  toggles.forEach(function(btn){
    btn.addEventListener('click', function(){ setMode(btn.getAttribute('data-auth-mode')); });
  });
  setMode('login');
})();
</script>
"""

    body_html = f"""
<section class="panel embedded-hero" data-reveal style="--reveal:0">
  <p class="eyebrow">Приложение Bitrix24</p>
  <h1 class="page-title" style="font-size:clamp(28px,4vw,40px);margin-bottom:10px">{html_escape(status_title)}</h1>
  <p class="page-subtitle embedded-copy">{html_escape(status_copy)}</p>
  {top_actions_html}
  {onboarding_html}
</section>
"""
    extra_style = """
.embedded-hero{max-width:960px;margin:24px auto 18px;padding:28px}
.embedded-copy{max-width:760px}
.embedded-inline-auth{display:grid;gap:18px;margin-top:24px;padding:22px;border:1px solid var(--border);border-radius:22px;background:linear-gradient(180deg,#fffef8 0%,#fff 100%)}
.embedded-auth-panel{display:none;grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);gap:18px;align-items:end}
.embedded-auth-panel.active{display:grid}
.embedded-inline-copy{display:grid;align-content:start}
.embedded-inline-form{margin-top:0}
.embedded-top-toggle{appearance:none;border:none;cursor:pointer}
.embedded-top-toggle.active{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.embedded-kicker{margin:0 0 14px;font-size:12px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-faint)}
.embedded-card-title{margin:0 0 10px;font-size:clamp(20px,3vw,28px);line-height:1.15}
.embedded-card-copy{margin:0 0 18px;color:var(--ink-soft);line-height:1.6}
.embedded-error{margin-bottom:16px}
@media(max-width:720px){
  .embedded-hero{margin:16px auto;padding:20px 18px}
  .embedded-inline-auth{padding:18px}
  .embedded-auth-panel,.embedded-auth-panel.active{grid-template-columns:1fr}
}
"""
    return render_page_frame(lang, 'Oko Systems для Bitrix24', body_html, extra_style=extra_style, script=page_script)


def render_login_page(lang: str, error_text: str = '', login_value: str = '', current_path: str = '/login', query_params: dict | None = None, mode: str = 'password') -> str:
    login_input_value = html_escape(str(login_value or '').strip())
    next_value = ''
    install_token_value = ''
    if isinstance(query_params, dict):
        next_value = str((query_params.get('next') or [''])[0] or '').strip()
        install_token_value = str((query_params.get('install_token') or [''])[0] or '').strip()
    next_input = f"<input type='hidden' name='next' value='{html_escape(next_value)}' />" if next_value.startswith('/') else ''
    install_token_input = f"<input type='hidden' name='install_token' value='{html_escape(install_token_value)}' />" if install_token_value else ''
    error_html = f"<div class='a-error'>{html_escape(error_text)}</div>" if error_text else ''
    lang_ru_active = 'a-lang-btn active' if lang == 'ru' else 'a-lang-btn'
    lang_kk_active = 'a-lang-btn active' if lang == 'kk' else 'a-lang-btn'
    lang_ru_href = html_escape(lang_query_href(current_path, query_params, 'ru'))
    lang_kk_href = html_escape(lang_query_href(current_path, query_params, 'kk'))
    return f"""<!doctype html>
<html lang="{html_escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(t(lang, 'login_title'))} — Oko Systems</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg?v=2">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{font-family:'Manrope',system-ui,sans-serif;font-size:15px;font-weight:500;line-height:1.55;background:#08080E;color:#0C0C14;-webkit-font-smoothing:antialiased;display:flex;flex-direction:column;min-height:100vh}}
/* layout */
.a-wrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:24px 16px;position:relative;overflow:hidden}}
.a-wrap-install{{padding-top:88px;padding-bottom:28px;align-items:flex-start;overflow:auto}}
.a-glow{{position:absolute;top:-150px;left:50%;transform:translateX(-50%);width:700px;height:500px;background:radial-gradient(ellipse,rgba(91,106,249,.22) 0%,transparent 70%);pointer-events:none}}
/* top bar */
.a-topbar{{position:fixed;top:0;left:0;right:0;height:60px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;z-index:10}}
.a-logo{{display:flex;align-items:center;gap:9px;text-decoration:none;color:#fff;font-size:16px;font-weight:800}}
.a-logo-icon{{width:28px;height:28px;background:#5B6AF9;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900;color:#fff;flex-shrink:0}}
.a-topbar-right{{display:flex;align-items:center;gap:8px}}
.a-lang-btn{{height:30px;padding:0 12px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:transparent;color:rgba(255,255,255,.45);font-family:inherit;font-size:12px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;transition:all .2s}}
.a-lang-btn.active,.a-lang-btn:hover{{background:rgba(255,255,255,.08);color:#fff;border-color:rgba(255,255,255,.25)}}
/* card */
.a-card{{background:#fff;border-radius:24px;padding:36px;width:100%;max-width:400px;box-shadow:0 0 0 1px rgba(91,106,249,.15),0 24px 64px rgba(0,0,0,.45);position:relative;z-index:1;animation:cardIn .5s ease both}}
@keyframes cardIn{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:none}}}}
.a-card-eyebrow{{font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#5B6AF9;margin-bottom:8px}}
.a-card-title{{font-size:26px;font-weight:900;letter-spacing:-.02em;color:#0C0C14;margin-bottom:4px}}
.a-card-sub{{font-size:13px;color:#6B7280;margin-bottom:24px}}
/* form */
.a-form{{display:flex;flex-direction:column;gap:14px}}
.a-label{{font-size:12px;font-weight:700;color:#6B7280;display:block;margin-bottom:5px}}
.a-input{{width:100%;height:46px;padding:0 14px;border:1.5px solid #E5E7EB;border-radius:11px;font-family:inherit;font-size:15px;font-weight:500;color:#0C0C14;background:#fff;outline:none;transition:border-color .2s}}
.a-password-wrap{{position:relative}}
.a-input-password{{padding-right:56px}}
.a-password-toggle{{position:absolute;top:50%;right:8px;transform:translateY(-50%);width:36px;height:36px;padding:0;border:1px solid #E5E7EB;border-radius:10px;background:#F8FAFC;color:#6B7280;display:inline-flex;align-items:center;justify-content:center;appearance:none;-webkit-appearance:none;box-shadow:0 1px 2px rgba(12,12,20,.04);cursor:pointer;transition:border-color .2s,background .2s,color .2s,box-shadow .2s}}
.a-password-toggle:hover{{background:#EEF2FF;border-color:#D8DEFE;color:#334155}}
.a-password-toggle:focus-visible{{outline:none;border-color:#5B6AF9;box-shadow:0 0 0 3px rgba(91,106,249,.14)}}
.a-password-toggle svg{{width:18px;height:18px;display:block;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}}
.a-password-toggle .icon-eye-off{{display:none}}
.a-password-toggle[aria-pressed='true']{{background:#EEF2FF;border-color:#C7D2FE;color:#5B6AF9}}
.a-password-toggle[aria-pressed='true'] .icon-eye{{display:none}}
.a-password-toggle[aria-pressed='true'] .icon-eye-off{{display:block}}
.a-input:focus{{border-color:#5B6AF9;box-shadow:0 0 0 3px rgba(91,106,249,.1)}}
.a-submit{{width:100%;height:48px;background:#5B6AF9;color:#fff;border:none;border-radius:12px;font-family:inherit;font-size:15px;font-weight:800;cursor:pointer;transition:background .2s,transform .15s;margin-top:2px}}
.a-submit:hover{{background:#7B87FF;transform:translateY(-1px)}}
/* links */
.a-links{{display:flex;justify-content:space-between;gap:8px;margin-top:12px}}
.a-links a{{font-size:12px;color:#9CA3AF;text-decoration:none;transition:color .2s}}
.a-links a:hover{{color:#5B6AF9}}
/* error */
.a-error{{background:#FEF2F2;border:1px solid #FECACA;border-radius:10px;padding:10px 14px;font-size:13px;color:#DC2626;margin-bottom:4px}}
/* page footer */
.a-page-footer{{padding:20px 24px;text-align:center}}
.a-page-footer-copy{{font-size:12px;color:rgba(255,255,255,.2)}}
@media(max-width:480px){{.a-card{{padding:28px 20px 24px}}.a-topbar{{padding:0 16px}}}}
</style>
</head>
<body>

<div class="a-topbar">
  <a href="/" class="a-logo">
    <div class="a-logo-icon">О</div>
    Oko Systems
  </a>
  <div class="a-topbar-right">
    <a href="{lang_ru_href}" class="{lang_ru_active}">Рус</a>
    <a href="{lang_kk_href}" class="{lang_kk_active}">Қаз</a>
  </div>
</div>

<div class="a-wrap">
  <div class="a-glow"></div>
  <div class="a-card">
    <div class="a-card-eyebrow">AI-аналитика звонков</div>
    <div class="a-card-title">Войти в Oko Systems</div>
    <div class="a-card-sub">{html_escape(t(lang, 'login_page_subtitle'))}</div>

    {error_html}
    <form method="post" action="/login" class="a-form">
      <input type="hidden" name="method" value="password" />
      {next_input}{install_token_input}
      <div>
        <label class="a-label" for="pw-email">{html_escape(t(lang, 'login_field'))}</label>
        <input class="a-input" id="pw-email" name="email" type="email" autocomplete="email" value="{login_input_value}" placeholder="email@example.com" required />
      </div>
      <div>
        <label class="a-label" for="pw-password">{html_escape(t(lang, 'password'))}</label>
        <div class="a-password-wrap">
          <input class="a-input a-input-password" id="pw-password" name="password" type="password" autocomplete="current-password" placeholder="••••••••" required />
          <button class="a-password-toggle" type="button" data-toggle-password="pw-password" aria-label="Показать пароль" aria-pressed="false">
            <svg class="icon-eye" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <svg class="icon-eye-off" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 3l18 18"></path>
              <path d="M10.58 10.58A2 2 0 0 0 12 14a2 2 0 0 0 1.42-.58"></path>
              <path d="M6.71 6.7C4.63 8.06 3.19 10.06 2.5 12c1.5 3.37 4.94 6 9.5 6 1.96 0 3.72-.49 5.2-1.34"></path>
              <path d="M9.88 4.24A11.6 11.6 0 0 1 12 4c4.56 0 8 2.63 9.5 6-.5 1.13-1.22 2.19-2.12 3.08"></path>
            </svg>
          </button>
        </div>
      </div>
      <button class="a-submit" type="submit">{html_escape(t(lang, 'login_enter_password'))}</button>
    </form>
    <div class="a-links">
      <a href="/forgot-password">{html_escape(t(lang, 'forgot_password'))}</a>
      <a href="/register">{html_escape(t(lang, 'no_account'))} {html_escape(t(lang, 'register'))}</a>
    </div>

  </div>
</div>

<div class="a-page-footer">
  <div class="a-page-footer-copy">© 2026 Oko Systems</div>
</div>

<script>
(function(){{
  Array.prototype.forEach.call(document.querySelectorAll('[data-toggle-password]'), function(btn){{
    btn.addEventListener('click', function(){{
      var input=document.getElementById(btn.getAttribute('data-toggle-password'));
      if(!input) return;
      var isVisible=input.type==='text';
      input.type=isVisible?'password':'text';
      btn.setAttribute('aria-label', isVisible?'Показать пароль':'Скрыть пароль');
      btn.setAttribute('aria-pressed', isVisible?'false':'true');
    }});
  }});
}})();
</script>
</body>
</html>"""


def render_register_page(lang: str, error_text: str = '', values: dict | None = None, current_path: str = '/register', query_params: dict | None = None) -> str:
    values = values or {}
    error_html = f"<div class='a-error'>{html_escape(error_text)}</div>" if error_text else ''
    name_value = html_escape(str(values.get('name') or '').strip())
    email_value = html_escape(str(values.get('email') or '').strip())
    next_value = ''
    install_token_value = ''
    if isinstance(query_params, dict):
        next_value = str((query_params.get('next') or [''])[0] or '').strip()
        install_token_value = str((query_params.get('install_token') or [''])[0] or '').strip()
    next_input = f"<input type='hidden' name='next' value='{html_escape(next_value)}' />" if next_value.startswith('/') else ''
    install_token_input = f"<input type='hidden' name='install_token' value='{html_escape(install_token_value)}' />" if install_token_value else ''
    lang_ru_active = 'a-lang-btn active' if lang == 'ru' else 'a-lang-btn'
    lang_kk_active = 'a-lang-btn active' if lang == 'kk' else 'a-lang-btn'
    lang_ru_href = html_escape(lang_query_href(current_path, query_params, 'ru'))
    lang_kk_href = html_escape(lang_query_href(current_path, query_params, 'kk'))
    login_href = html_escape(lang_query_href('/login', query_params, lang))
    is_install_flow = bool(install_token_value)
    card_title = 'Создать аккаунт'
    card_subtitle = 'Создайте аккаунт по email. Придумайте надёжный пароль.'
    submit_label = html_escape(t(lang, 'register'))
    password_fields_html = f"""
      <div class="a-field">
        <label class="a-label" for="register-password">{html_escape(t(lang, 'password'))}</label>
        <div class="a-password-wrap">
          <input class="a-input a-input-password" id="register-password" name="password" type="password" autocomplete="new-password" placeholder="Минимум 8 символов" required />
          <button class="a-password-toggle" type="button" data-toggle-password="register-password" aria-label="Показать пароль" aria-pressed="false">
            <svg class="icon-eye" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <svg class="icon-eye-off" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 3l18 18"></path>
              <path d="M10.58 10.58A2 2 0 0 0 12 14a2 2 0 0 0 1.42-.58"></path>
              <path d="M6.71 6.7C4.63 8.06 3.19 10.06 2.5 12c1.5 3.37 4.94 6 9.5 6 1.96 0 3.72-.49 5.2-1.34"></path>
              <path d="M9.88 4.24A11.6 11.6 0 0 1 12 4c4.56 0 8 2.63 9.5 6-.5 1.13-1.22 2.19-2.12 3.08"></path>
            </svg>
          </button>
        </div>
      </div>
      <div class="a-field">
        <label class="a-label" for="register-password2">{html_escape(t(lang, 'password_confirm'))}</label>
        <div class="a-password-wrap">
          <input class="a-input a-input-password" id="register-password2" name="password2" type="password" autocomplete="new-password" placeholder="••••••••" required />
          <button class="a-password-toggle" type="button" data-toggle-password="register-password2" aria-label="Показать пароль" aria-pressed="false">
            <svg class="icon-eye" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <svg class="icon-eye-off" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 3l18 18"></path>
              <path d="M10.58 10.58A2 2 0 0 0 12 14a2 2 0 0 0 1.42-.58"></path>
              <path d="M6.71 6.7C4.63 8.06 3.19 10.06 2.5 12c1.5 3.37 4.94 6 9.5 6 1.96 0 3.72-.49 5.2-1.34"></path>
              <path d="M9.88 4.24A11.6 11.6 0 0 1 12 4c4.56 0 8 2.63 9.5 6-.5 1.13-1.22 2.19-2.12 3.08"></path>
            </svg>
          </button>
        </div>
      </div>
"""
    footer_html = ''
    page_footer_html = """
<div class="a-page-footer">
  <div class="a-page-footer-copy">© 2026 Oko Systems</div>
</div>
"""
    if is_install_flow:
        page_footer_html = ''
    return f"""<!doctype html>
<html lang="{html_escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(t(lang, 'register_title'))} — Oko Systems</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg?v=2">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{font-family:'Manrope',system-ui,sans-serif;font-size:15px;font-weight:500;line-height:1.55;background:#08080E;color:#0C0C14;-webkit-font-smoothing:antialiased;display:flex;flex-direction:column;min-height:100vh}}
.a-wrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:24px 16px;position:relative;overflow:hidden}}
.a-wrap-install{{padding-top:74px;padding-bottom:16px;align-items:flex-start;overflow:auto}}
.a-glow{{position:absolute;top:-150px;left:50%;transform:translateX(-50%);width:700px;height:500px;background:radial-gradient(ellipse,rgba(91,106,249,.22) 0%,transparent 70%);pointer-events:none}}
.a-topbar{{position:fixed;top:0;left:0;right:0;height:60px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;z-index:10}}
.a-logo{{display:flex;align-items:center;gap:9px;text-decoration:none;color:#fff;font-size:16px;font-weight:800}}
.a-logo-icon{{width:28px;height:28px;background:#5B6AF9;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900;color:#fff;flex-shrink:0}}
.a-topbar-right{{display:flex;align-items:center;gap:8px}}
.a-lang-btn{{height:30px;padding:0 12px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:transparent;color:rgba(255,255,255,.45);font-family:inherit;font-size:12px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;transition:all .2s}}
.a-lang-btn.active,.a-lang-btn:hover{{background:rgba(255,255,255,.08);color:#fff;border-color:rgba(255,255,255,.25)}}
.a-card{{background:#fff;border-radius:22px;padding:22px 22px 16px;width:100%;max-width:368px;box-shadow:0 0 0 1px rgba(91,106,249,.15),0 24px 64px rgba(0,0,0,.45);position:relative;z-index:1;animation:cardIn .5s ease both}}
@keyframes cardIn{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:none}}}}
.a-card-eyebrow{{font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#5B6AF9;margin-bottom:6px}}
.a-card-title{{font-size:21px;font-weight:900;letter-spacing:-.02em;color:#0C0C14;margin-bottom:4px;line-height:1.06}}
.a-card-sub{{font-size:12px;color:#6B7280;margin-bottom:14px;line-height:1.45}}
.a-form{{display:flex;flex-direction:column;gap:9px}}
.a-field{{display:flex;flex-direction:column;gap:4px}}
.a-label{{font-size:11px;font-weight:700;color:#6B7280;display:block}}
.a-input{{width:100%;height:39px;padding:0 12px;border:1.5px solid #E5E7EB;border-radius:11px;font-family:inherit;font-size:14px;font-weight:500;color:#0C0C14;background:#fff;outline:none;transition:border-color .2s}}
.a-password-wrap{{position:relative}}
.a-input-password{{padding-right:54px}}
.a-password-toggle{{position:absolute;top:50%;right:6px;transform:translateY(-50%);width:32px;height:32px;padding:0;border:1px solid #E5E7EB;border-radius:10px;background:#F8FAFC;color:#6B7280;display:inline-flex;align-items:center;justify-content:center;appearance:none;-webkit-appearance:none;box-shadow:0 1px 2px rgba(12,12,20,.04);cursor:pointer;transition:border-color .2s,background .2s,color .2s,box-shadow .2s}}
.a-password-toggle:hover{{background:#EEF2FF;border-color:#D8DEFE;color:#334155}}
.a-password-toggle:focus-visible{{outline:none;border-color:#5B6AF9;box-shadow:0 0 0 3px rgba(91,106,249,.14)}}
.a-password-toggle svg{{width:16px;height:16px;display:block;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}}
.a-password-toggle .icon-eye-off{{display:none}}
.a-password-toggle[aria-pressed='true']{{background:#EEF2FF;border-color:#C7D2FE;color:#5B6AF9}}
.a-password-toggle[aria-pressed='true'] .icon-eye{{display:none}}
.a-password-toggle[aria-pressed='true'] .icon-eye-off{{display:block}}
.a-input:focus{{border-color:#5B6AF9;box-shadow:0 0 0 3px rgba(91,106,249,.1)}}
.a-submit{{width:100%;height:41px;background:#5B6AF9;color:#fff;border:none;border-radius:12px;font-family:inherit;font-size:14px;font-weight:800;cursor:pointer;transition:background .2s,transform .15s;margin-top:2px}}
.a-submit:hover{{background:#7B87FF;transform:translateY(-1px)}}
.a-links{{display:flex;justify-content:flex-start;gap:8px;margin-top:8px}}
.a-links a{{font-size:12px;color:#9CA3AF;text-decoration:none;transition:color .2s}}
.a-links a:hover{{color:#5B6AF9}}
.a-error{{background:#FEF2F2;border:1px solid #FECACA;border-radius:10px;padding:8px 10px;font-size:12px;color:#DC2626;margin-bottom:2px}}
.a-page-footer{{padding:20px 24px;text-align:center}}
.a-page-footer-copy{{font-size:12px;color:rgba(255,255,255,.2)}}
@media(max-width:480px){{.a-card{{padding:18px 16px 14px;max-width:100%}}.a-topbar{{padding:0 16px}}.a-wrap-install{{padding-top:68px;padding-bottom:14px}}}}
</style>
</head>
<body>

<div class="a-topbar">
  <a href="/" class="a-logo">
    <div class="a-logo-icon">О</div>
    Oko Systems
  </a>
  <div class="a-topbar-right">
    <a href="{lang_ru_href}" class="{lang_ru_active}">Рус</a>
    <a href="{lang_kk_href}" class="{lang_kk_active}">Қаз</a>
  </div>
</div>

<div class="a-wrap{' a-wrap-install' if is_install_flow else ''}">
  <div class="a-glow"></div>
  <div class="a-card">
    <div class="a-card-eyebrow">AI-аналитика звонков</div>
    <div class="a-card-title">{card_title}</div>
    <div class="a-card-sub">{card_subtitle}</div>

    {error_html}

    <form method="post" action="/register" class="a-form">
      {next_input}
      {install_token_input}
      <div class="a-field">
        <label class="a-label" for="register-name">{html_escape(t(lang, 'name_field'))}</label>
        <input class="a-input" id="register-name" name="name" type="text" autocomplete="name" value="{name_value}" required />
      </div>
      <div class="a-field">
        <label class="a-label" for="register-email">{html_escape(t(lang, 'email'))}</label>
        <input class="a-input" id="register-email" name="email" type="email" autocomplete="email" value="{email_value}" placeholder="email@example.com" required />
      </div>
      {password_fields_html}
      <button class="a-submit" type="submit">{submit_label}</button>
    </form>

    <div class="a-links">
      <a href="{login_href}">{html_escape(t(lang, 'have_account'))} {html_escape(t(lang, 'login'))}</a>
    </div>

    {footer_html}
  </div>
</div>

{page_footer_html}
<script>
(function(){{
  Array.prototype.forEach.call(document.querySelectorAll('[data-toggle-password]'), function(btn){{
    btn.addEventListener('click', function(){{
      var input=document.getElementById(btn.getAttribute('data-toggle-password'));
      if(!input) return;
      var isVisible=input.type==='text';
      input.type=isVisible?'password':'text';
      btn.setAttribute('aria-label', isVisible?'Показать пароль':'Скрыть пароль');
      btn.setAttribute('aria-pressed', isVisible?'false':'true');
    }});
  }});
}})();
</script>
</body>
</html>"""


def render_email_code_page(lang: str, token: str, email: str, error_text: str = '', notice_text: str = '', current_path: str = '/verify-code', query_params: dict | None = None) -> str:
    error_html = f"<div class='form-error' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    notice_html = f"<div class='form-notice' style='margin-bottom:16px'>{html_escape(notice_text)}</div>" if notice_text else ''
    lang_switch = render_lang_switch(current_path, query_params, lang)
    subtitle = t(lang, 'auth_code_subtitle').replace('{email}', email)
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <div class="auth-topbar">{lang_switch}</div>
  <p class="eyebrow">AI Аналитика</p>
  <h1 class="page-title" style="font-size:clamp(26px,3.5vw,36px)">{html_escape(t(lang, 'auth_code_title'))}</h1>
  <p class="page-subtitle">{html_escape(subtitle)}</p>
  {notice_html}
  {error_html}

  <form method="post" action="/verify-code" class="auth-form" style="margin-top:28px">
    <input type="hidden" name="token" value="{html_escape(token)}" />
    <label class="auth-label" for="auth-code">{html_escape(t(lang, 'auth_code_field'))}</label>
    <input class="auth-input" id="auth-code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="123456" required />
    <button class="auth-submit" type="submit">{html_escape(t(lang, 'auth_code_submit'))}</button>
  </form>

  <div class="auth-links">
    <a href="/login">{html_escape(t(lang, 'login_title'))}</a>
    <a href="/register">{html_escape(t(lang, 'register_title'))}</a>
  </div>
</section>
"""
    return render_page_frame(lang, t(lang, 'auth_code_title'), body_html, extra_style="""
.auth-page{max-width:420px;margin:60px auto;padding:36px 32px 40px}
.auth-topbar{display:flex;justify-content:flex-end;margin-bottom:18px}
.auth-topbar .lang-switch{margin-bottom:0;background:#F3F4F6;border-color:#E5E7EB}
.auth-topbar .lang-btn{color:var(--ink-soft)}
.auth-topbar .lang-btn:hover{color:var(--ink)}
.auth-topbar .lang-btn.active{background:#5B6AF9;color:#fff}
.auth-form{display:flex;flex-direction:column;gap:14px}
.auth-label{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint)}
.auth-input{width:100%;height:46px;padding:0 14px;border-radius:12px;border:1px solid var(--border);background:var(--panel-soft);color:var(--ink);font:inherit;box-sizing:border-box}
.auth-input:focus{outline:none;border-color:var(--ink-faint);box-shadow:0 0 0 3px rgba(33,35,43,.08)}
.auth-submit{display:flex;align-items:center;justify-content:center;width:100%;height:46px;padding:0 20px;border:none;border-radius:12px;background:var(--ink);color:var(--surface);font-size:15px;font-weight:800;cursor:pointer;transition:opacity .15s}
.auth-submit:hover{opacity:.9}
.auth-links{display:flex;justify-content:space-between;gap:12px;margin-top:16px}
.auth-links a{font-size:12px;color:var(--ink-faint);text-decoration:none}
.auth-links a:hover{color:var(--ink-soft);text-decoration:underline}
@media(max-width:480px){.auth-page{margin:24px auto;padding:24px 20px 28px}}
""")


def render_forgot_password_page(lang: str, error_text: str = '', notice_text: str = '', email_value: str = '', current_path: str = '/forgot-password', query_params: dict | None = None) -> str:
    error_html = f"<div class='form-error' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    notice_html = f"<div class='form-notice' style='margin-bottom:16px'>{html_escape(notice_text)}</div>" if notice_text else ''
    email_input_value = html_escape(str(email_value or '').strip())
    lang_switch = render_lang_switch(current_path, query_params, lang)
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <div class="auth-topbar">{lang_switch}</div>
  <p class="eyebrow">AI Аналитика</p>
  <h1 class="page-title" style="font-size:clamp(26px,3.5vw,36px)">Oko Systems</h1>
  <p class="page-subtitle">{html_escape(t(lang, 'forgot_password_page_subtitle'))}</p>
  {error_html}
  {notice_html}

  <form method="post" action="/forgot-password" class="auth-form" style="margin-top:28px">
    <label class="auth-label" for="forgot-email">{html_escape(t(lang, 'email'))}</label>
    <input class="auth-input" id="forgot-email" name="email" type="email" autocomplete="email" value="{email_input_value}" required />
    <button class="auth-submit" type="submit">{html_escape(t(lang, 'forgot_password_submit'))}</button>
  </form>

  <div class="auth-links">
    <a href="/login">{html_escape(t(lang, 'login'))}</a>
    <a href="/register">{html_escape(t(lang, 'register'))}</a>
  </div>
</section>
"""
    return render_page_frame(lang, t(lang, 'forgot_password_title'), body_html, extra_style="""
.auth-page{max-width:420px;margin:60px auto;padding:36px 32px 40px}
.auth-topbar{display:flex;justify-content:flex-end;margin-bottom:18px}
.auth-topbar .lang-switch{margin-bottom:0;background:#F3F4F6;border-color:#E5E7EB}
.auth-topbar .lang-btn{color:var(--ink-soft)}
.auth-topbar .lang-btn:hover{color:var(--ink)}
.auth-topbar .lang-btn.active{background:#5B6AF9;color:#fff}
.auth-form{display:flex;flex-direction:column;gap:14px}
.auth-label{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint)}
.auth-input{width:100%;height:46px;padding:0 14px;border-radius:12px;border:1px solid var(--border);background:var(--panel-soft);color:var(--ink);font:inherit;box-sizing:border-box}
.auth-input:focus{outline:none;border-color:var(--ink-faint);box-shadow:0 0 0 3px rgba(33,35,43,.08)}
.auth-submit{display:flex;align-items:center;justify-content:center;width:100%;height:46px;padding:0 20px;border:none;border-radius:12px;background:var(--ink);color:var(--surface);font-size:15px;font-weight:800;cursor:pointer;transition:opacity .15s}
.auth-submit:hover{opacity:.9}
.auth-links{display:flex;justify-content:space-between;gap:12px;margin-top:16px}
.auth-links a{font-size:12px;color:var(--ink-faint);text-decoration:none}
.auth-links a:hover{color:var(--ink-soft);text-decoration:underline}
.form-notice{padding:12px 14px;border-radius:12px;background:#eef6ef;color:#30553a;font-size:13px;line-height:1.5}
@media(max-width:480px){.auth-page{margin:24px auto;padding:24px 20px 28px}}
""")


def render_reset_password_page(lang: str, token: str, error_text: str = '', notice_text: str = '', valid: bool = True, current_path: str = '/reset-password', query_params: dict | None = None) -> str:
    error_html = f"<div class='form-error' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    notice_html = f"<div class='form-notice' style='margin-bottom:16px'>{html_escape(notice_text)}</div>" if notice_text else ''
    token_value = html_escape(str(token or ''))
    lang_switch = render_lang_switch(current_path, query_params, lang)
    form_html = f"""
  <form method="post" action="/reset-password" class="auth-form" style="margin-top:28px">
    <input type="hidden" name="token" value="{token_value}" />
    <label class="auth-label" for="reset-password">{html_escape(t(lang, 'password'))}</label>
    <input class="auth-input" id="reset-password" name="password" type="password" autocomplete="new-password" required />
    <label class="auth-label" for="reset-password-confirm">{html_escape(t(lang, 'password_confirm'))}</label>
    <input class="auth-input" id="reset-password-confirm" name="password_confirm" type="password" autocomplete="new-password" required />
    <button class="auth-submit" type="submit">{html_escape(t(lang, 'reset_password_submit'))}</button>
  </form>
""" if valid else ''
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <div class="auth-topbar">{lang_switch}</div>
  <p class="eyebrow">AI Аналитика</p>
  <h1 class="page-title" style="font-size:clamp(26px,3.5vw,36px)">Oko Systems</h1>
  <p class="page-subtitle">{html_escape(t(lang, 'reset_password_page_subtitle'))}</p>
  {error_html}
  {notice_html}
  {form_html}
  <div class="auth-links">
    <a href="/login">{html_escape(t(lang, 'login'))}</a>
    <a href="/forgot-password">{html_escape(t(lang, 'forgot_password'))}</a>
  </div>
</section>
"""
    return render_page_frame(lang, t(lang, 'reset_password_title'), body_html, extra_style="""
.auth-page{max-width:420px;margin:60px auto;padding:36px 32px 40px}
.auth-topbar{display:flex;justify-content:flex-end;margin-bottom:18px}
.auth-topbar .lang-switch{margin-bottom:0;background:#F3F4F6;border-color:#E5E7EB}
.auth-topbar .lang-btn{color:var(--ink-soft)}
.auth-topbar .lang-btn:hover{color:var(--ink)}
.auth-topbar .lang-btn.active{background:#5B6AF9;color:#fff}
.auth-form{display:flex;flex-direction:column;gap:14px}
.auth-label{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint)}
.auth-input{width:100%;height:46px;padding:0 14px;border-radius:12px;border:1px solid var(--border);background:var(--panel-soft);color:var(--ink);font:inherit;box-sizing:border-box}
.auth-input:focus{outline:none;border-color:var(--ink-faint);box-shadow:0 0 0 3px rgba(33,35,43,.08)}
.auth-submit{display:flex;align-items:center;justify-content:center;width:100%;height:46px;padding:0 20px;border:none;border-radius:12px;background:var(--ink);color:var(--surface);font-size:15px;font-weight:800;cursor:pointer;transition:opacity .15s}
.auth-submit:hover{opacity:.9}
.auth-links{display:flex;justify-content:space-between;gap:12px;margin-top:16px}
.auth-links a{font-size:12px;color:var(--ink-faint);text-decoration:none}
.auth-links a:hover{color:var(--ink-soft);text-decoration:underline}
.form-notice{padding:12px 14px;border-radius:12px;background:#eef6ef;color:#30553a;font-size:13px;line-height:1.5}
@media(max-width:480px){.auth-page{margin:24px auto;padding:24px 20px 28px}}
""")


def render_connect_bitrix_page(lang: str, connect_token: str, rop_id: str, error_text: str = '') -> str:
    """Page shown before Bitrix24 OAuth redirect — explains what will happen."""
    oauth_url = (
        f"https://oauth.bitrix.info/oauth/authorize/"
        f"?client_id={MT_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={MT_REDIRECT_URI}"
        f"&state={connect_token}"
    )
    error_html = f"<div class='form-error' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    fallback_path = f"/{str(rop_id).lstrip('/')}" if rop_id else '/'
    public_connect_url = f"{APP_BASE_URL.rstrip('/')}/connect/bitrix/{connect_token}" if connect_token else f"{APP_BASE_URL.rstrip('/')}{fallback_path}"
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <p class="eyebrow">Подключение Bitrix24</p>
  <h1 class="page-title" style="font-size:clamp(24px,3vw,32px)">Авторизация в Bitrix24</h1>
  {error_html}
  <p class="page-subtitle">
    Нажмите кнопку ниже, чтобы перейти к авторизации в вашем Bitrix24.
    Вы будете перенаправлены на страницу Bitrix24 для подтверждения доступа.
  </p>
  <div class="info-box" style="margin:20px 0">
    <p class="info-box-title">Для загрузки аудиозаписей звонков</p>
    <p class="info-box-text">
      Необходим доступ администратора Bitrix24. Если вы не являетесь администратором —
      скопируйте эту ссылку и отправьте вашему администратору:
    </p>
    <div class="copy-link-row">
      <code class="copy-link-code" id="connect-url">{html_escape(public_connect_url)}</code>
      <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('connect-url').textContent)">Копировать</button>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:12px;margin-top:8px;flex-wrap:wrap">
    <a class="btn-primary" href="{html_escape(oauth_url)}">Авторизоваться в Bitrix24</a>
    <a class="btn-back" href="{html_escape(fallback_path)}">← Назад</a>
  </div>
</section>
"""
    extra_style = """
.auth-page{max-width:480px;margin:60px auto;padding:36px 32px 40px}
.info-box{background:var(--surface-muted);border:1px solid var(--border);border-radius:14px;padding:16px 18px}
.info-box-title{margin:0 0 6px;font-size:13px;font-weight:700;color:var(--ink)}
.info-box-text{margin:0 0 12px;font-size:13px;color:var(--ink-soft);line-height:1.5}
.copy-link-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.copy-link-code{font-size:11px;word-break:break-all;background:rgba(0,0,0,.04);border-radius:6px;padding:6px 8px;flex:1;min-width:0}
.copy-btn{flex-shrink:0;height:32px;padding:0 12px;border-radius:8px;border:1px solid var(--border-strong);background:var(--surface);font-size:12px;font-weight:700;cursor:pointer;font-family:inherit}
.copy-btn:hover{background:var(--surface-muted)}
.btn-primary{display:inline-flex;align-items:center;height:44px;padding:0 20px;border-radius:12px;background:var(--ink);color:#fff;font-size:15px;font-weight:700;text-decoration:none;transition:opacity .15s}
.btn-primary:hover{opacity:.85}
.btn-back{display:inline-flex;align-items:center;height:44px;padding:0 16px;border-radius:12px;border:1px solid var(--border-strong);background:var(--surface);color:var(--ink-soft);font-size:14px;font-weight:700;text-decoration:none;transition:background .15s}
.btn-back:hover{background:var(--surface-muted)}
@media(max-width:520px){.auth-page{margin:24px auto;padding:24px 18px 28px}}
"""
    return render_page_frame(lang, 'Подключение Bitrix24', body_html, extra_style=extra_style)


def render_oauth_success_page(lang: str, rop_id: str) -> str:
    """Shown after successful Bitrix24 OAuth."""
    rop_href = html_escape(f"/{str(rop_id or 'analysis').lstrip('/')}")
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <p class="eyebrow">Подключение завершено</p>
  <h1 class="page-title" style="font-size:clamp(24px,3vw,32px)">Bitrix24 подключен!</h1>
  <p class="page-subtitle">Авторизация прошла успешно. Теперь вы можете использовать платформу.</p>
  <div class="top-actions" style="margin-top:24px">
    <a class="btn-primary" href="{rop_href}">Перейти к анализу</a>
  </div>
</section>
"""
    extra_style = """
.auth-page{max-width:440px;margin:80px auto;padding:40px 32px}
.btn-primary{display:inline-flex;align-items:center;height:44px;padding:0 20px;border-radius:12px;background:var(--ink);color:#fff;font-size:15px;font-weight:700;text-decoration:none;transition:opacity .15s}
.btn-primary:hover{opacity:.85}
"""
    return render_page_frame(lang, 'Bitrix24 подключен', body_html, extra_style=extra_style)
