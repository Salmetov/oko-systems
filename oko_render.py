"""Static / shared server-rendered HTML fragments for OKO.

Self-contained presentation pieces — the dashboard base stylesheet, the confirm-dialog
widget, and the page frame script. Depend only on stdlib html-escaping and oko_i18n.
"""
from html import escape as html_escape

from oko_i18n import t


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
