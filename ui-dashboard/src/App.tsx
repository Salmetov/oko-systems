import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle, ArrowLeft, ArrowUpRight, Bell, CheckCircle2, ChevronDown, ChevronRight,
  Check, ClipboardCheck, Download, ExternalLink, Loader2, LogOut, Pencil, Plus, RotateCcw, Send, Sparkles, Trash2, TrendingDown, TrendingUp, Users, BarChart3,
  X,
} from "lucide-react"

// ─── Types ────────────────────────────────────────────────────────────────────

type RouteState =
  | { kind: "home" }
  | { kind: "analyses"; statusFilter?: string }
  | { kind: "report"; id: string }
  | { kind: "chronology"; id: string }
  | { kind: "employee"; id: string; focus?: "problems" }
  | { kind: "standards" }
  | { kind: "standard"; id: string }

type MePayload = {
  user_id: number
  name: string
  email: string
  connections: { id: number; domain: string; title: string; is_primary: boolean }[]
}

type EmployeeCard = {
  employee_id: number
  employee_name: string
  analysis_count: number
  avg_score: number
  latest_score: number
  latest_public_id: string
  last_at: string
  problem_runs: number
  plan_status: "draft" | "sent" | null
}

type AnalysisItem = {
  batch_id: number
  status: string
  created_at: string
  deal_id: number | null
  entity_type: string
  bitrix_domain: string
  employee_name: string
  score: number | null
  public_id: string
  export_count: number
  done_count: number
  processing_stage: string
  error_kind?: string | null
  error_label?: string | null
}

type SelectionOption = { user_id: number; user_name: string; user_position: string; call_count: number }
type BatchExportDetail = { export_id: number; status: string; processing_stage?: string; selection_options: SelectionOption[] }

type ReportModule = {
  block_name: string
  block_weight_percent: number | null
  block_score_percent: number
  module_name: string
  module_weight_percent: number
  module_score_percent: number
  raw_coef: number
  module_observation: string
  module_task: string
}

type ReportPayload = {
  public_id: string
  run_id: number
  export_id: number
  standard_id: number | null
  card_fields_configured: boolean
  deal_id: number | null
  employee_id: number | null
  employee_name: string
  client_name?: string | null
  overall_score_percent: number
  final_summary: string
  touches_count: number
  missing_fields: string[]
  modules: ReportModule[]
  chronology_url: string
  employee_url: string
  deal_url: string
}

type ChronologyEvent = {
  event_id: number
  timestamp_utc?: string
  channel: string
  event_type: string
  creator_name: string
  creator_position?: string
  scope: "selected" | "other" | "system"
  scope_label: string
  title: string
  status?: string | null
  status_label?: string | null
  text: string
  transcript?: string
  phone?: string
  duration_seconds?: number
}

type ChronologyPayload = {
  public_id: string
  title: string
  deal_id: number
  deal_url: string
  client_name: string
  selected_operator_name: string
  events: ChronologyEvent[]
}

type EmployeeHistoryItem = {
  run_id: number
  public_id: string
  deal_id: number | null
  client_name: string
  overall_score_percent: number
  primary_call_at?: string | null
  sort_at?: string | null
  delta_from_prev?: number | null
  declined_modules: { module_name: string }[]
}

type EmployeeMatrixRow = {
  block_name: string
  module_name: string
  avg_ratio_percent: number
  values: ({ ratio_percent: number; raw_coef: number; comment?: string } | null)[]
}

type ProblemInstance = { date_label: string; comment: string }
type ProblemModule = {
  module_name: string
  block_name: string
  bad_count: number
  avg_ratio_percent: number
  instances: ProblemInstance[]
}

type RepeatedProblem = {
  module_name: string
  block_name: string
  bad_count: number
  avg_ratio_percent: number
}

type TaskFollowupItem = {
  module_name: string
  task: string
  status: "completed" | "partial" | "not_done"
}

type ScoreSeriesPoint = { run_id: number; public_id: string; score_percent: number; utc_iso: string; date_label: string }

type EmployeePayload = {
  employee_id: number
  employee_name: string
  employee_position: string
  analysis_count: number
  average_score_percent: number
  latest_score_percent: number
  latest_delta_percent?: number | null
  overall_trend_percent?: number | null
  score_series: ScoreSeriesPoint[]
  history: EmployeeHistoryItem[]
  module_matrix: EmployeeMatrixRow[]
  repeated_problems: RepeatedProblem[]
  task_followup: { completed: number; partial: number; not_done: number; items: TaskFollowupItem[] }
  best_module?: { module_name?: string }
  worst_module?: { module_name?: string }
}

type PlanTask = { title: string; description: string; deadline_days: number }

type DevelopmentPlan = {
  id: number
  employee_id: number
  run_ids: number[]
  tasks: PlanTask[]
  bitrix_task_ids: number[]
  status: "draft" | "sent"
}

type AppNotification = {
  id: number
  type: string
  payload: {
    cycle_id?: number
    plan_id?: number
    employee_id?: number
    employee_name?: string
    delta?: number
  }
  read: boolean
  created_at: string
}

// ─── Router ───────────────────────────────────────────────────────────────────

function resolveRoute(): RouteState {
  const p = window.location.pathname.replace(/\/+$/, "")
  const q = new URLSearchParams(window.location.search)
  const parts = p.split("/").filter(Boolean)
  const di = parts.findIndex((x) => x === "dash")
  if (di === -1) return { kind: "home" }
  const sec = parts[di + 1]
  const id = parts[di + 2]
  if (!sec || sec === "employees") return { kind: "home" }
  if (sec === "analyses") return { kind: "analyses", statusFilter: q.get("status") ?? undefined }
  if (sec === "report" && id) return { kind: "report", id }
  if (sec === "chronology" && id) return { kind: "chronology", id }
  if (sec === "employee" && id) {
    const focus = q.get("focus") === "problems" ? "problems" : undefined
    return { kind: "employee", id, focus }
  }
  if (sec === "standards") {
    return id ? { kind: "standard", id } : { kind: "standards" }
  }
  return { kind: "home" }
}

function toPath(r: RouteState): string {
  if (r.kind === "home") return "/dash"
  if (r.kind === "analyses") return r.statusFilter ? `/dash/analyses?status=${r.statusFilter}` : "/dash/analyses"
  if (r.kind === "report") return `/dash/report/${r.id}`
  if (r.kind === "chronology") return `/dash/chronology/${r.id}`
  if (r.kind === "employee") return r.focus ? `/dash/employee/${r.id}?focus=${r.focus}` : `/dash/employee/${r.id}`
  if (r.kind === "standards") return "/dash/standards"
  if (r.kind === "standard") return `/dash/standards/${r.id}`
  return "/dash"
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function initials(name: string) {
  return name.split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("")
}

function scoreColor(s: number) {
  if (s >= 80) return "text-green-400"
  if (s >= 60) return "text-amber-400"
  return "text-red-400"
}

function scoreBg(s: number) {
  if (s >= 80) return "bg-green-500"
  if (s >= 60) return "bg-amber-500"
  return "bg-red-500"
}

function scoreBorder(s: number) {
  if (s >= 80) return "border-green-500/20 bg-green-500/5"
  if (s >= 60) return "border-amber-500/20 bg-amber-500/5"
  return "border-red-500/20 bg-red-500/5"
}

function fmtDate(v?: string | null) {
  if (!v) return "—"
  const d = new Date(v)
  return isNaN(d.getTime()) ? "—" : new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }).format(d)
}

function fmtDur(s?: number) {
  const n = Number(s || 0)
  if (!n) return "—"
  const m = Math.floor(n / 60), ss = n % 60
  return m > 0 ? `${m} мин${ss > 0 ? ` ${ss} сек` : ""}` : `${ss} сек`
}

function moduleRatio(score: number, weight: number) {
  return weight ? Math.round((score / weight) * 10000) / 100 : 0
}

const MODULE_SHORT_NAME_RULES: Array<[RegExp, string]> = [
  [/^приветствие/i, 'Приветствие'],
  [/обратиться к клиенту по имени/i, 'Обращение по имени 2+ раз'],
  [/заполнение карточки/i, 'Заполнение карточки клиента'],
  [/активного слушания/i, 'Активное слушание'],
  [/критерии подбора двери/i, 'Критерии подбора двери'],
  [/воронки выявления потребности/i, 'Воронка вопросов'],
  [/презентацию о компании/i, 'Презентация компании и продуктов'],
  [/техники хпв/i, 'Техника ХПВ'],
  [/уделить внимание каждому вопросу и возражению/i, 'Внимание к вопросам и возражениям'],
  [/часто задаваемые вопросы/i, 'Отработка частых вопросов'],
  [/типовые возражения/i, 'Отработка типовых возражений'],
  [/предложить клиенту встречу/i, 'Предложение встречи'],
  [/о следующем шаге/i, 'Договорённость о следующем шаге'],
  [/резюмировать общее решение/i, 'Резюме встречи: дата, время'],
]

function shortenModuleName(raw: string): string {
  for (const [re, label] of MODULE_SHORT_NAME_RULES) if (re.test(raw)) return label
  return (raw || '').replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s{2,}/g, ' ').replace(/[.,;:*]+$/, '').trim() || raw
}

function displayStatus(status: string): { label: string; color: string } {
  if (status === "completed") return { label: "Готово", color: "bg-green-500/15 text-green-400" }
  if (status === "completed_with_errors") return { label: "С ошибками", color: "bg-amber-500/15 text-amber-400" }
  if (status === "failed") return { label: "Ошибка", color: "bg-red-500/15 text-red-400" }
  if (status === "awaiting_operator") return { label: "Выбор сотрудника", color: "bg-purple-500/15 text-purple-400" }
  return { label: "В работе", color: "bg-blue-500/15 text-blue-400" }
}

// ─── Primitives ───────────────────────────────────────────────────────────────

function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  const sz = size === "lg" ? "w-14 h-14 text-lg" : size === "sm" ? "w-8 h-8 text-xs" : "w-10 h-10 text-sm"
  return (
    <div className={`${sz} rounded-full bg-gradient-to-br from-blue-600 to-blue-800 flex items-center justify-center font-bold text-white shrink-0 select-none`}>
      {initials(name) || "?"}
    </div>
  )
}

function DeltaBadge({ value }: { value?: number | null }) {
  if (value == null) return <span className="text-neutral-600 text-xs">—</span>
  const c = value > 0 ? "text-green-400" : value < 0 ? "text-red-400" : "text-neutral-500"
  const I = value > 0 ? TrendingUp : value < 0 ? TrendingDown : null
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold ${c}`}>
      {I && <I size={12} />}{value > 0 ? "+" : ""}{value}%
    </span>
  )
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-neutral-800 bg-neutral-900 ${className}`}>{children}</div>
}

function SLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] font-semibold tracking-widest text-neutral-500 uppercase mb-3">{children}</p>
}

function ScorePill({ score }: { score: number }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${scoreBorder(score)}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${scoreBg(score)}`} />
      <span className={scoreColor(score)}>{score}%</span>
    </span>
  )
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

function NotificationBell({ navigate }: { navigate: (r: RouteState) => void }) {
  const [notifs, setNotifs] = useState<AppNotification[]>([])
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const fetchNotifs = useCallback(() => {
    fetch("/api/notifications").then(r => r.json()).then(d => {
      if (d.ok) setNotifs(d.result)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    fetchNotifs()
    const t = setInterval(fetchNotifs, 30000)
    return () => clearInterval(t)
  }, [fetchNotifs])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onClickOutside)
    return () => document.removeEventListener("mousedown", onClickOutside)
  }, [])

  const unread = notifs.filter(n => !n.read).length

  function markRead(id: number) {
    fetch(`/api/notifications/${id}/read`, { method: "POST" }).catch(() => {})
    setNotifs(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
  }

  function markAllRead() {
    fetch("/api/notifications/read-all", { method: "POST" }).catch(() => {})
    setNotifs(prev => prev.map(n => ({ ...n, read: true })))
  }

  function notifTitle(n: AppNotification) {
    const name = n.payload.employee_name || `Сотрудник ${n.payload.employee_id || ""}`
    if (n.type === "plan_ready") return `План развития готов — ${name}`
    if (n.type === "report_ready") {
      const d = n.payload.delta
      const dStr = d !== undefined ? ` (${d > 0 ? "+" : ""}${d}%)` : ""
      return `Отчёт о прогрессе — ${name}${dStr}`
    }
    return n.type
  }

  function handleNotifClick(n: AppNotification) {
    markRead(n.id)
    setOpen(false)
    if (n.payload.employee_id) {
      navigate({ kind: "employee", id: String(n.payload.employee_id) })
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="relative flex items-center justify-center w-8 h-8 rounded-xl text-neutral-400 hover:text-white hover:bg-neutral-800 transition-colors"
        title="Уведомления"
      >
        <Bell size={16} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex items-center justify-center min-w-[16px] h-4 rounded-full bg-blue-600 text-[10px] font-bold text-white px-1 leading-none">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 w-80 rounded-2xl border border-neutral-800 bg-neutral-900 shadow-xl z-50 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
            <span className="text-sm font-semibold text-white">Уведомления</span>
            <div className="flex items-center gap-2">
              {unread > 0 && (
                <button onClick={markAllRead} className="text-[11px] text-neutral-500 hover:text-white transition-colors">
                  Прочитать все
                </button>
              )}
              <button onClick={() => setOpen(false)} className="text-neutral-600 hover:text-white transition-colors">
                <X size={14} />
              </button>
            </div>
          </div>

          <div className="max-h-80 overflow-y-auto divide-y divide-neutral-800/60">
            {notifs.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-neutral-600">Нет уведомлений</div>
            ) : (
              notifs.map(n => (
                <button
                  key={n.id}
                  onClick={() => handleNotifClick(n)}
                  className={`w-full text-left px-4 py-3 transition-colors hover:bg-neutral-800/60 ${n.read ? "opacity-60" : ""}`}
                >
                  <div className="flex items-start gap-2">
                    <span className={`mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full ${n.read ? "bg-neutral-700" : "bg-blue-500"}`} />
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-neutral-200 leading-snug">{notifTitle(n)}</p>
                      <p className="text-[11px] text-neutral-600 mt-0.5">{fmtDate(n.created_at)}</p>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Sidebar({ me, route, navigate }: { me: MePayload; route: RouteState; navigate: (r: RouteState) => void }) {
  const navItems: { kind: RouteState["kind"]; label: string; icon: typeof Users; route: RouteState; matches: RouteState["kind"][] }[] = [
    { kind: "home", label: "Сотрудники", icon: Users, route: { kind: "home" }, matches: ["home", "employee"] },
    { kind: "analyses", label: "Анализы", icon: BarChart3, route: { kind: "analyses" }, matches: ["analyses", "report", "chronology"] },
    { kind: "standards", label: "Стандарты", icon: ClipboardCheck, route: { kind: "standards" }, matches: ["standards", "standard"] },
  ]
  return (
    <aside className="flex flex-col w-56 shrink-0 border-r border-neutral-800 bg-neutral-950 sticky top-0 h-screen overflow-y-auto">
      {/* Logo */}
      <div className="px-4 border-b border-neutral-800 h-[72px] flex items-center">
        <div className="flex items-center gap-2.5">
          <span className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-sm font-black text-white shrink-0">O</span>
          <div>
            <div className="text-sm font-bold text-white leading-none">Oko Systems</div>
            <div className="text-[11px] text-neutral-500 mt-0.5 leading-none">Контроль качества</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-0.5 overflow-y-auto">
        <p className="px-2 mb-2 text-[10px] font-semibold tracking-widest text-neutral-600 uppercase">Раздел</p>
        {navItems.map((item) => {
          const active = item.matches.includes(route.kind)
          return (
            <button
              key={item.kind}
              onClick={() => navigate(item.route)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-medium transition-colors ${
                active ? "bg-blue-600 text-white" : "text-neutral-400 hover:text-white hover:bg-neutral-800"
              }`}
            >
              <item.icon size={15} />
              {item.label}
            </button>
          )
        })}

        {/* Bitrix connections */}
        {me.connections.length > 0 && (
          <div className="pt-4">
            <p className="px-2 mb-2 text-[10px] font-semibold tracking-widest text-neutral-600 uppercase">Битрикс аккаунты</p>
            {me.connections.map((c) => (
              <div key={c.id} className="flex items-center gap-2 px-3 py-2 rounded-xl">
                <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                <span className="text-xs text-neutral-400 truncate">{c.domain || `Портал #${c.id}`}</span>
              </div>
            ))}
          </div>
        )}
      </nav>

      {/* User + logout */}
      <div className="px-3 py-4 border-t border-neutral-800">
        <div className="flex items-center gap-2 px-2">
          {me.name && <Avatar name={me.name} size="sm" />}
          <span className="text-xs text-neutral-400 truncate flex-1">{me.name}</span>
          <a
            href="/logout"
            title="Выйти"
            className="flex items-center justify-center w-7 h-7 rounded-lg text-neutral-500 hover:text-red-400 hover:bg-red-500/10 transition-colors shrink-0"
          >
            <LogOut size={14} />
          </a>
        </div>
      </div>
    </aside>
  )
}

// ─── SubmitBar ────────────────────────────────────────────────────────────────

function SubmitBar({ hasBitrix, onSubmitted }: { hasBitrix: boolean; onSubmitted?: () => void }) {
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  function submit() {
    const val = url.trim()
    if (!val || loading) return
    setLoading(true)
    setMsg(null)
    fetch("/api/analysis/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: val }),
    })
      .then(async (res) => {
        const d = await res.json()
        if (!d.ok) throw new Error(d.error || "Ошибка")
        return d
      })
      .then((d) => {
        setMsg({ text: `Анализ запущен (${d.deal_count} сделка)`, ok: true })
        setUrl("")
        onSubmitted?.()
      })
      .catch((e: unknown) => {
        const err = e instanceof Error ? e.message : "Ошибка"
        setMsg({
          text: err === "no_deal_link" ? "Не найдена ссылка на сделку Bitrix24" :
                err === "no_bitrix" ? "Битрикс24 не подключён" : err,
          ok: false,
        })
      })
      .finally(() => setLoading(false))
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          ref={inputRef}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          disabled={!hasBitrix || loading}
          placeholder={hasBitrix ? "https://портал.bitrix24.kz/crm/deal/details/1234/ или /crm/lead/details/1234/" : "Подключите Bitrix24 для запуска анализа"}
          className="flex-1 h-10 rounded-xl border border-neutral-700 bg-neutral-800/80 px-3 text-sm text-white placeholder:text-neutral-600 outline-none focus:border-blue-500 disabled:opacity-40 transition-colors"
        />
        <button
          onClick={submit}
          disabled={!hasBitrix || loading || !url.trim()}
          className="h-10 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-semibold text-white transition-colors flex items-center gap-2 shrink-0"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          Запустить
        </button>
      </div>
      {msg && (
        <p className={`text-xs px-1 ${msg.ok ? "text-green-400" : "text-red-400"}`}>{msg.text}</p>
      )}
    </div>
  )
}

// ─── HomeView (Employee Roster) ───────────────────────────────────────────────

function HomeView({ me, navigate }: { me: MePayload; navigate: (r: RouteState) => void }) {
  const [employees, setEmployees] = useState<EmployeeCard[]>([])
  const [archivedCount, setArchivedCount] = useState<number>(0)
  const [loading, setLoading] = useState(true)
  const [showArchived, setShowArchived] = useState<boolean>(false)
  const [unarchiving, setUnarchiving] = useState<number | null>(null)

  const fetchEmployees = useCallback(() => {
    setLoading(true)
    fetch(`/api/employees${showArchived ? "?archived=1" : ""}`)
      .then((r) => r.json())
      .then((d) => setEmployees(d.ok ? d.result : []))
      .catch(() => setEmployees([]))
      .finally(() => setLoading(false))
  }, [showArchived])

  // Independent of which tab is active, keep the archive count current for the tab badge.
  const fetchArchivedCount = useCallback(() => {
    fetch("/api/employees?archived=1")
      .then((r) => r.json())
      .then((d) => setArchivedCount(d.ok ? (d.result || []).length : 0))
      .catch(() => {})
  }, [])

  useEffect(() => { fetchEmployees() }, [fetchEmployees])
  useEffect(() => { fetchArchivedCount() }, [fetchArchivedCount])

  const unarchive = async (id: number) => {
    setUnarchiving(id)
    try {
      const r = await fetch(`/api/employee/${id}/unarchive`, { method: "POST" }).then(r => r.json())
      if (r.ok) {
        fetchEmployees()
        fetchArchivedCount()
      }
    } finally {
      setUnarchiving(null)
    }
  }

  return (
    <div className="space-y-6">
      <Card className="p-4">
        <p className="text-xs font-semibold text-neutral-500 mb-2">Новый анализ</p>
        <SubmitBar hasBitrix={me.connections.length > 0} onSubmitted={() => { fetchEmployees(); fetchArchivedCount() }} />
      </Card>

      <div className="flex gap-2">
        <button
          onClick={() => setShowArchived(false)}
          className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-colors ${!showArchived ? "bg-blue-500/15 text-blue-400" : "bg-neutral-900 text-neutral-500 hover:text-neutral-300"}`}
        >
          Активные
        </button>
        <button
          onClick={() => setShowArchived(true)}
          className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-colors ${showArchived ? "bg-blue-500/15 text-blue-400" : "bg-neutral-900 text-neutral-500 hover:text-neutral-300"}`}
        >
          Архив{archivedCount > 0 ? ` · ${archivedCount}` : ""}
        </button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={24} className="animate-spin text-neutral-600" />
        </div>
      )}

      {!loading && employees.length === 0 && (
        <Card className="p-10 text-center border-dashed">
          <Users size={32} className="text-neutral-700 mx-auto mb-3" />
          <p className="text-neutral-400 font-semibold">{showArchived ? "В архиве пусто" : "Сотрудников пока нет"}</p>
          <p className="text-sm text-neutral-600 mt-1">{showArchived ? "Архивированные сотрудники будут здесь" : "Запустите первый анализ звонка, чтобы сотрудники появились здесь"}</p>
        </Card>
      )}

      {!loading && employees.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {employees.map((op) => (
            <div
              key={op.employee_id}
              className={`relative text-left rounded-2xl border border-neutral-800 bg-neutral-900 p-5 transition-all ${showArchived ? "opacity-70" : "hover:border-neutral-700 hover:bg-neutral-800/60 cursor-pointer group"}`}
              onClick={!showArchived ? () => navigate({ kind: "employee", id: String(op.employee_id) }) : undefined}
            >
              <div className="flex items-start justify-between gap-3 mb-4">
                <div className="flex items-center gap-3">
                  <Avatar name={op.employee_name} />
                  <div>
                    <p className="text-sm font-semibold text-white leading-tight">{op.employee_name}</p>
                    <p className="text-xs text-neutral-500 mt-0.5">{op.analysis_count} анализов</p>
                  </div>
                </div>
                {!showArchived && <ChevronRight size={16} className="text-neutral-600 group-hover:text-neutral-400 transition-colors shrink-0 mt-0.5" />}
              </div>

              {/* Score — average is the hero */}
              <div className="mb-2">
                <p className="text-[10px] text-neutral-600 mb-0.5">Среднее</p>
                <p className={`text-3xl font-black ${scoreColor(op.avg_score)}`}>{op.avg_score}%</p>
              </div>

              {/* Score bar — reflects average */}
              <div className="h-1.5 rounded-full bg-neutral-800 overflow-hidden mb-2">
                <div
                  className={`h-full rounded-full ${scoreBg(op.avg_score)}`}
                  style={{ width: `${op.avg_score}%` }}
                />
              </div>

              {/* Last score — small line under the bar, with delta when non-zero */}
              {(() => {
                const delta = Math.round((op.latest_score - op.avg_score) * 10) / 10
                const Icon = delta > 0 ? TrendingUp : delta < 0 ? TrendingDown : null
                const deltaCls = delta > 0 ? "text-green-400" : "text-red-400"
                return (
                  <p className="text-xs text-neutral-500 mb-3 whitespace-nowrap">
                    Последний: <span className={scoreColor(op.latest_score)}>{op.latest_score}%</span>
                    {Icon && (
                      <span className={`inline-flex items-baseline gap-0.5 ml-1.5 ${deltaCls}`}>
                        <Icon size={11} className="self-center" />
                        {delta > 0 ? "+" : ""}{delta}
                      </span>
                    )}
                  </p>
                )
              })()}

              {/* Footer — badges on their own row, date below */}
              {(op.problem_runs > 0 || op.plan_status === "sent") && (
                <div className="flex flex-wrap gap-2 mb-2">
                  {op.problem_runs > 0 && (
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation()
                        navigate({ kind: "employee", id: String(op.employee_id), focus: "problems" })
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.stopPropagation()
                          e.preventDefault()
                          navigate({ kind: "employee", id: String(op.employee_id), focus: "problems" })
                        }
                      }}
                      className="inline-flex items-center gap-1 rounded-lg border border-amber-500/20 bg-amber-500/5 px-2 py-0.5 text-xs text-amber-400 whitespace-nowrap cursor-pointer hover:bg-amber-500/10 hover:border-amber-500/40 transition-colors"
                    >
                      <AlertTriangle size={10} /> {op.problem_runs} проблем
                    </span>
                  )}
                  {op.plan_status === "sent" && (
                    <span className="inline-flex items-center gap-1 rounded-lg border border-green-500/20 bg-green-500/5 px-2 py-0.5 text-xs text-green-400 whitespace-nowrap">
                      <CheckCircle2 size={10} /> план отправлен
                    </span>
                  )}
                </div>
              )}
              <div className="text-[10px] text-neutral-600">{fmtDate(op.last_at)}</div>

              {showArchived && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); unarchive(op.employee_id) }}
                  disabled={unarchiving === op.employee_id}
                  className="mt-3 w-full inline-flex items-center justify-center gap-1.5 h-8 rounded-xl border border-blue-500/20 bg-blue-500/5 text-xs text-blue-400 hover:bg-blue-500/10 hover:border-blue-500/40 transition-colors disabled:opacity-50"
                >
                  {unarchiving === op.employee_id ? <Loader2 size={12} className="animate-spin" /> : null}
                  Восстановить
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── LiveStatusCell ───────────────────────────────────────────────────────────

const TERMINAL = new Set(["completed", "completed_with_errors", "failed", "error"])

function stagePercent(exportStatus: string): number {
  const map: Record<string, number> = {
    received: 8, queued: 12, awaiting_operator: 12,
    bitrix_fetch: 28, bitrix_parsed: 42,
    stt_submit: 52, stt_skip: 55, stt_done: 65,
    claude_queue: 75, claude_processing: 88,
    completed: 100, completed_with_errors: 100,
  }
  return map[exportStatus] ?? 15
}

function LiveStatusCell({ status, pct }: { status: string; pct: number | null }) {
  const { label, color } = displayStatus(status)
  const isActive = !TERMINAL.has(status)
  const showFill = isActive && pct != null && pct > 0

  return (
    <span className={`relative overflow-hidden rounded-lg px-2.5 py-1 text-xs font-semibold inline-flex items-center gap-1.5 w-fit ${color}`}>
      {showFill && (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 bg-blue-500/35 transition-[width] duration-700 ease-out pointer-events-none"
          style={{ width: `${pct}%` }}
        />
      )}
      {isActive && <span className="relative w-1.5 h-1.5 rounded-full bg-current animate-pulse shrink-0" />}
      <span className="relative">{label}</span>
    </span>
  )
}

function rowProgressPct(status: string, liveExportStatus?: string): number | null {
  if (TERMINAL.has(status) || status === "awaiting_operator") return null
  // Cap non-terminal progress at 92%. Filling all the way to 100% while the row is still
  // "В работе" reads as "done" to users — but the actual transition to "Готово" can lag a
  // poll cycle behind. Keeping a visible gap until the row is truly terminal makes the
  // signal honest: full bar = done, partial bar = still working.
  const raw = stagePercent(liveExportStatus ?? status)
  return Math.min(raw, 92)
}

// ─── EmployeeSelector ─────────────────────────────────────────────────────────

function EmployeeSelector({ batchId, onAssigned }: { batchId: number; onAssigned: () => void }) {
  const [open, setOpen] = useState(false)
  const [fetching, setFetching] = useState(false)
  const [options, setOptions] = useState<(SelectionOption & { export_id: number })[]>([])
  const [assigning, setAssigning] = useState<number | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  const toggle = async () => {
    if (open) { setOpen(false); return }
    setFetching(true)
    try {
      const d = await fetch(`/api/analysis/batch/${batchId}`).then(r => r.json())
      if (d.ok) {
        const flat: (SelectionOption & { export_id: number })[] = []
        for (const exp of (d.result?.items ?? []) as BatchExportDetail[]) {
          if (exp.status === "awaiting_operator" && exp.selection_options?.length) {
            for (const o of exp.selection_options) {
              if (!flat.some(x => x.user_id === o.user_id)) flat.push({ ...o, export_id: exp.export_id })
            }
          }
        }
        setOptions(flat)
        setOpen(true)
      }
    } finally { setFetching(false) }
  }

  const assign = async (opt: SelectionOption & { export_id: number }) => {
    setAssigning(opt.user_id)
    try {
      const d = await fetch(`/api/analysis/export/${opt.export_id}/operator`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Endpoint key is operator_id — it's the Bitrix-side selected user_id, not our internal employee.id.
        body: JSON.stringify({ operator_id: opt.user_id }),
      }).then(r => r.json())
      if (d.ok) { setOpen(false); onAssigned() }
    } finally { setAssigning(null) }
  }

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={toggle}
        className="inline-flex items-center gap-1 text-xs font-medium text-purple-400 hover:text-purple-300 transition-colors"
      >
        {fetching ? <Loader2 size={11} className="animate-spin" /> : null}
        Выбрать <ChevronDown size={11} />
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-50 min-w-[190px] bg-neutral-900 border border-neutral-700 rounded-xl shadow-2xl py-1 overflow-hidden">
          {options.length === 0 ? (
            <p className="px-3 py-2 text-xs text-neutral-500">Нет кандидатов</p>
          ) : options.map((opt) => (
            <button
              key={opt.user_id}
              onClick={() => assign(opt)}
              disabled={assigning !== null}
              className="w-full text-left px-3 py-2 flex items-center gap-2.5 hover:bg-neutral-800 transition-colors disabled:opacity-50"
            >
              {assigning === opt.user_id
                ? <Loader2 size={14} className="animate-spin text-neutral-400 shrink-0" />
                : <Avatar name={opt.user_name} size="sm" />
              }
              <div className="min-w-0">
                <p className="text-sm text-white truncate">{opt.user_name}</p>
                {opt.call_count > 0 && (
                  <p className="text-[10px] text-neutral-500">{opt.call_count} {opt.call_count === 1 ? "звонок" : "звонка"}</p>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── AnalysesView ─────────────────────────────────────────────────────────────

function AnalysesView({ me, navigate }: { me: MePayload; navigate: (r: RouteState) => void }) {
  const [items, setItems] = useState<AnalysisItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState("all")
  const [loading, setLoading] = useState(true)
  const [liveStatus, setLiveStatus] = useState<Record<number, { export_status: string; processing_stage: string }>>({})
  const [retryingId, setRetryingId] = useState<number | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const confirmDeleteItem = useMemo(
    () => (confirmDeleteId == null ? null : items.find(i => i.batch_id === confirmDeleteId) || null),
    [confirmDeleteId, items],
  )

  const doDelete = useCallback(async () => {
    if (confirmDeleteId == null) return
    setDeletingId(confirmDeleteId)
    try {
      const r = await fetch(`/api/analysis/batch/${confirmDeleteId}/delete`, { method: "POST" })
      const d = await r.json().catch(() => ({}))
      if (d.ok) {
        setConfirmDeleteId(null)
        fetchAnalysesRef.current(true)
      } else {
        console.error("delete failed", d)
      }
    } catch (e) {
      console.error("delete network error", e)
    } finally {
      setDeletingId(null)
    }
  }, [confirmDeleteId])

  const retryBatch = useCallback(async (batchId: number) => {
    if (retryingId) return
    setRetryingId(batchId)
    try {
      const r = await fetch(`/api/analyses/${batchId}/retry`, { method: "POST" })
      const d = await r.json().catch(() => ({}))
      if (!d.ok) {
        console.error("retry failed", d)
      }
    } catch (e) {
      console.error("retry network error", e)
    } finally {
      setRetryingId(null)
      fetchAnalysesRef.current(true)
    }
  }, [retryingId])

  const activeIdsRef = useRef<Set<number>>(new Set())
  const lastSeenStatusRef = useRef<Map<number, string>>(new Map())
  const fetchAnalysesRef = useRef<(silent?: boolean) => void>(() => {})

  const fetchAnalyses = useCallback((silent = false) => {
    if (!silent) setLoading(true)
    const url = `/api/analyses?status=${status}&page=${page}`
    fetch(url).then((r) => r.json()).then((d) => {
      if (d.ok) { setItems(d.result.items); setTotal(d.result.total) }
    }).catch(() => {}).finally(() => { if (!silent) setLoading(false) })
  }, [status, page])

  fetchAnalysesRef.current = fetchAnalyses

  useEffect(() => { fetchAnalyses() }, [fetchAnalyses])
  useEffect(() => { setPage(1) }, [status])

  const poll = useCallback(async () => {
    const ids = [...activeIdsRef.current]
    if (!ids.length) return
    for (const batchId of ids) {
      try {
        const d = await fetch(`/api/analysis/batch/${batchId}`).then(r => r.json())
        if (!d.ok) continue
        const exps: BatchExportDetail[] = d.result?.items ?? []
        const active = exps.find(e => !TERMINAL.has(e.status)) ?? exps[0]
        if (active) {
          setLiveStatus(prev => ({
            ...prev,
            [batchId]: { export_status: active.status, processing_stage: active.processing_stage ?? "" }
          }))
        }
        const newStatus: string = d.status ?? ''
        const prevStatus = lastSeenStatusRef.current.get(batchId) ?? ''
        if (newStatus && newStatus !== prevStatus) {
          lastSeenStatusRef.current.set(batchId, newStatus)
          const becameAwaiting = newStatus === 'awaiting_operator'
          const leftAwaiting = prevStatus === 'awaiting_operator' && newStatus !== 'awaiting_operator'
          if (becameAwaiting || leftAwaiting || TERMINAL.has(newStatus)) {
            fetchAnalysesRef.current(true)
          }
        }
        if (TERMINAL.has(newStatus)) {
          activeIdsRef.current.delete(batchId)
        }
      } catch { /* ignore */ }
    }
  }, [])

  // Keep active IDs ref in sync; kick a fast poll for fresh active batches.
  useEffect(() => {
    activeIdsRef.current = new Set(
      items.filter(i => !TERMINAL.has(i.status)).map(i => i.batch_id)
    )
    for (const i of items) lastSeenStatusRef.current.set(i.batch_id, i.status)
    const hasFreshActive = items.some(i =>
      !TERMINAL.has(i.status) && i.status !== "awaiting_operator"
    )
    if (hasFreshActive) {
      const t = setTimeout(poll, 1200)
      return () => clearTimeout(t)
    }
  }, [items, poll])

  // Steady 5s polling
  useEffect(() => {
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [poll])

  const perPage = 20
  const totalPages = Math.max(1, Math.ceil(total / perPage))

  const filters = [
    { key: "all", label: "Все" },
    { key: "active", label: "В работе" },
    { key: "done", label: "Готово" },
    { key: "error", label: "Ошибки" },
  ]

  return (
    <div className="space-y-5">
      <Card className="p-4">
        <p className="text-xs font-semibold text-neutral-500 mb-2">Новый анализ</p>
        <SubmitBar hasBitrix={me.connections.length > 0} onSubmitted={fetchAnalyses} />
      </Card>

      {/* Filters */}
      <div className="flex gap-1.5">
        {filters.map((f) => (
          <button
            key={f.key}
            onClick={() => setStatus(f.key)}
            className={`h-8 px-4 rounded-xl text-sm font-medium transition-colors ${
              status === f.key ? "bg-blue-600 text-white" : "border border-neutral-800 text-neutral-400 hover:text-white hover:border-neutral-600"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={24} className="animate-spin text-neutral-600" />
        </div>
      )}

      {!loading && items.length === 0 && (
        <Card className="p-10 text-center border-dashed">
          <BarChart3 size={32} className="text-neutral-700 mx-auto mb-3" />
          <p className="text-neutral-400">Анализов нет</p>
        </Card>
      )}

      {!loading && items.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="border-b border-neutral-800">
                  {["Дата", "Сделка", "Сотрудник", "Оценка", "Статус", "", ""].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800">
                {items.map((item) => {
                  const entityPath = item.entity_type === "lead" ? "lead" : "deal"
                  const dealUrl = item.bitrix_domain && item.deal_id
                    ? `https://${item.bitrix_domain}/crm/${entityPath}/details/${item.deal_id}/`
                    : null
                  const live = liveStatus[item.batch_id]
                  const pct = rowProgressPct(item.status, live?.export_status)
                  return (
                    <tr key={item.batch_id} className="hover:bg-neutral-800/30 transition-colors">
                      <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">{fmtDate(item.created_at)}</td>
                      <td className="px-4 py-3">
                        {item.deal_id ? (
                          <a
                            href={dealUrl ?? "#"}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 font-mono text-sm"
                            onClick={(e) => e.stopPropagation()}
                          >
                            #{item.deal_id} <ArrowUpRight size={12} />
                          </a>
                        ) : <span className="text-neutral-600">—</span>}
                      </td>
                      <td className="px-4 py-3 text-neutral-300">
                        {item.status === "awaiting_operator"
                          ? <EmployeeSelector batchId={item.batch_id} onAssigned={fetchAnalyses} />
                          : (item.employee_name || <span className="text-neutral-600">—</span>)
                        }
                      </td>
                      <td className="px-4 py-3">
                        {item.score != null ? <ScorePill score={Math.round(item.score)} /> : <span className="text-neutral-600">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <LiveStatusCell status={item.status} pct={pct} />
                      </td>
                      <td className="px-4 py-3">
                        {item.public_id ? (
                          <button
                            onClick={() => navigate({ kind: "report", id: item.public_id })}
                            className="inline-flex items-center gap-1 text-xs text-neutral-400 hover:text-white transition-colors"
                          >
                            Открыть <ChevronRight size={12} />
                          </button>
                        ) : (item.status === "completed_with_errors" || item.status === "failed") ? (
                          <button
                            onClick={() => retryBatch(item.batch_id)}
                            disabled={retryingId === item.batch_id}
                            title={item.error_label ? `${item.error_label}. Нажмите, чтобы повторить.` : "Повторить анализ"}
                            className="inline-flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                          >
                            {retryingId === item.batch_id ? (
                              <><Loader2 size={12} className="animate-spin" /> Запускается…</>
                            ) : (
                              <><RotateCcw size={12} /> Повторить</>
                            )}
                          </button>
                        ) : <span className="text-neutral-700 text-xs">—</span>}
                      </td>
                      <td className="px-3 py-3 w-10">
                        {TERMINAL.has(item.status) && (
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(item.batch_id)}
                            disabled={deletingId === item.batch_id}
                            title="Удалить анализ"
                            className="inline-flex items-center justify-center w-7 h-7 rounded-lg text-neutral-600 hover:text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                          >
                            {deletingId === item.batch_id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-neutral-800">
              <span className="text-xs text-neutral-500">{total} записей</span>
              <div className="flex gap-1.5">
                <button disabled={page <= 1} onClick={() => setPage(page - 1)}
                  className="h-7 px-3 rounded-lg border border-neutral-700 text-xs text-neutral-400 disabled:opacity-30 hover:border-neutral-500 hover:text-white transition-colors">
                  ←
                </button>
                <span className="h-7 px-3 flex items-center text-xs text-neutral-400">{page} / {totalPages}</span>
                <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}
                  className="h-7 px-3 rounded-lg border border-neutral-700 text-xs text-neutral-400 disabled:opacity-30 hover:border-neutral-500 hover:text-white transition-colors">
                  →
                </button>
              </div>
            </div>
          )}
        </Card>
      )}

      {confirmDeleteId !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => deletingId == null && setConfirmDeleteId(null)}
        >
          <div
            className="w-full max-w-md mx-4 rounded-2xl border border-neutral-800 bg-neutral-900 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white mb-2">Удалить анализ?</h3>
            <p className="text-sm text-neutral-400 leading-6 mb-5">
              {confirmDeleteItem?.deal_id ? (
                <>
                  Анализ сделки <span className="text-white font-semibold">#{confirmDeleteItem.deal_id}</span>
                  {confirmDeleteItem.employee_name ? <> ({confirmDeleteItem.employee_name})</> : null} будет удалён вместе с отчётом и оценками модулей.
                </>
              ) : "Этот анализ будет удалён вместе с отчётом и оценками модулей."}
              {" "}Расшифровки звонков останутся — анализ можно запустить заново на той же сделке.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmDeleteId(null)}
                disabled={deletingId != null}
                className="h-9 px-4 rounded-xl border border-neutral-700 text-sm text-neutral-300 hover:border-neutral-500 hover:text-white transition-colors disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={doDelete}
                disabled={deletingId != null}
                className="h-9 px-4 rounded-xl bg-red-500/15 border border-red-500/30 text-sm font-semibold text-red-400 hover:bg-red-500/25 hover:border-red-500/50 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                {deletingId != null ? <Loader2 size={14} className="animate-spin" /> : null}
                Удалить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── ReportView ───────────────────────────────────────────────────────────────

const CARD_FIELDS_MODULE_RE = /карточ.*(?:клиент|crm|б24|b24)|(?:клиент|crm|б24|b24).*карточ/i

function ReportView({ report, navigate }: { report: ReportPayload; navigate: (r: RouteState) => void }) {
  const failing = useMemo(() => report.modules.filter((m) => m.raw_coef < 1), [report])
  const passing = useMemo(() => report.modules.filter((m) => m.raw_coef >= 1), [report])
  const cardModule = useMemo(
    () => report.modules.find((m) => CARD_FIELDS_MODULE_RE.test(m.module_name)) ?? null,
    [report]
  )
  const showCardFieldsHint = !!cardModule && !report.card_fields_configured

  const failingByBlock = useMemo(() => {
    const map = new Map<string, ReportModule[]>()
    for (const m of failing) {
      const arr = map.get(m.block_name) ?? []; arr.push(m); map.set(m.block_name, arr)
    }
    return map
  }, [failing])

  const blockSummary = useMemo(() => {
    const map = new Map<string, { score: number; weight: number | null }>()
    for (const m of report.modules) {
      const cur = map.get(m.block_name) ?? { score: 0, weight: m.block_weight_percent }
      cur.score += m.module_score_percent; map.set(m.block_name, cur)
    }
    return map
  }, [report])

  return (
    <div className="space-y-4">
      {/* Hero */}
      <Card className="p-6 bg-gradient-to-br from-neutral-900 via-neutral-900 to-blue-950/30">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-4">
            <Avatar name={report.employee_name} size="lg" />
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs text-neutral-500">Анализ завершён</span>
                <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
              </div>
              <h2 className="text-xl font-bold text-white">{report.employee_name || "—"}</h2>
              {(report.deal_id || report.client_name) && (
                report.deal_url ? (
                  <a href={report.deal_url} target="_blank" rel="noreferrer"
                    className="inline-flex flex-wrap gap-x-3 mt-1 text-sm text-neutral-400 hover:text-white transition-colors">
                    {report.deal_id && <span>Сделка #{report.deal_id}</span>}
                    {report.client_name && <span>· {report.client_name}</span>}
                    <ExternalLink size={12} className="self-center" />
                  </a>
                ) : (
                  <div className="flex flex-wrap gap-x-3 mt-1 text-sm text-neutral-400">
                    {report.deal_id && <span>Сделка #{report.deal_id}</span>}
                    {report.client_name && <span>· {report.client_name}</span>}
                  </div>
                )
              )}
            </div>
          </div>

          <div className="flex flex-col items-end gap-3 sm:w-80 sm:shrink-0">
            <div className="text-right">
              <div className={`text-5xl font-black ${scoreColor(report.overall_score_percent)}`}>{report.overall_score_percent}</div>
              <div className="text-sm text-neutral-500 mt-0.5">из 100</div>
            </div>
            <div className="w-full space-y-1.5">
              {Array.from(blockSummary.entries()).map(([block, { score, weight }]) => {
                const r = weight ? Math.min(100, (score / weight) * 100) : 0
                return (
                  <div key={block} className="flex items-center gap-2">
                    <span className="text-[10px] text-neutral-500 flex-1 min-w-0 text-right leading-tight">{block}</span>
                    <div className="w-24 shrink-0 h-1 rounded-full bg-neutral-800 overflow-hidden">
                      <div className={`h-full rounded-full ${scoreBg(r)}`} style={{ width: `${r}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {report.final_summary && (
          <p className="mt-4 text-sm text-neutral-400 leading-6 border-t border-neutral-800 pt-4">{report.final_summary}</p>
        )}

        <div className="flex flex-wrap gap-2 mt-4">
          {report.employee_id && (
            <button onClick={() => navigate({ kind: "employee", id: String(report.employee_id) })}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-xl border border-neutral-700 text-xs text-neutral-300 hover:border-neutral-500 hover:text-white transition-colors">
              <ChevronRight size={12} /> Прогресс сотрудника
            </button>
          )}
          <button onClick={() => navigate({ kind: "chronology", id: report.public_id })}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-xl border border-neutral-700 text-xs text-neutral-300 hover:border-neutral-500 hover:text-white transition-colors">
            <ChevronRight size={12} /> Хронология
          </button>
          <a href={`/r/${report.public_id}.pdf`} download
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-xl border border-neutral-700 text-xs text-neutral-300 hover:border-neutral-500 hover:text-white transition-colors">
            <Download size={12} /> Скачать PDF
          </a>
        </div>
      </Card>

      {/* Failing */}
      {failing.length > 0 && (
        <div>
          <SLabel>Проблемные зоны — {failing.length} из {report.modules.length} модулей</SLabel>
          <div className="space-y-2">
            {Array.from(failingByBlock.entries()).map(([block, mods]) => (
              <Card key={block} className="overflow-hidden">
                <div className="px-5 py-2.5 border-b border-neutral-800 bg-neutral-800/30">
                  <span className="text-[11px] font-semibold text-neutral-500 uppercase tracking-wider">{block}</span>
                </div>
                <div className="divide-y divide-neutral-800">
                  {mods.map((m) => {
                    const ratio = moduleRatio(m.module_score_percent, m.module_weight_percent)
                    return (
                      <div key={m.module_name} className="px-5 py-4">
                        <div className="flex items-start gap-3">
                          <AlertTriangle size={14} className={`mt-0.5 shrink-0 ${ratio === 0 ? "text-red-400" : "text-amber-400"}`} />
                          <div className="flex-1">
                            <div className="flex items-center justify-between gap-3 mb-1.5">
                              <p className="text-sm font-semibold text-white">{m.module_name}</p>
                              <ScorePill score={ratio} />
                            </div>
                            {m.module_observation && m.module_observation !== "—" && (
                              <p className="text-xs text-neutral-400 leading-5">{m.module_observation}</p>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Passing */}
      {passing.length > 0 && (
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 size={14} className="text-green-400" />
            <SLabel>Выполнено — {passing.length} модулей</SLabel>
          </div>
          <div className="flex flex-wrap gap-2">
            {passing.map((m) => {
              const isUnconfiguredCardModule = showCardFieldsHint && CARD_FIELDS_MODULE_RE.test(m.module_name)
              return (
                <span
                  key={m.module_name}
                  className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs ${
                    isUnconfiguredCardModule
                      ? "border-amber-500/30 bg-amber-500/5 text-amber-300"
                      : "border-neutral-800 bg-neutral-800/40 text-neutral-500"
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${isUnconfiguredCardModule ? "bg-amber-400/70" : "bg-green-500/60"}`} />
                  {m.module_name}
                </span>
              )
            })}
          </div>
          {showCardFieldsHint && (
            <div className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
              <p className="text-xs text-amber-200/90 leading-5">
                Модуль <span className="font-semibold">«{cardModule!.module_name}»</span> сейчас оценивается без штрафа — обязательные поля карточки клиента в Bitrix не настроены.{" "}
                {report.standard_id != null ? (
                  <a
                    href={`/dash/standards/${report.standard_id}`}
                    onClick={(e) => { e.preventDefault(); navigate({ kind: "standard", id: String(report.standard_id) }) }}
                    className="underline hover:text-amber-200"
                  >
                    Укажите поля в стандарте
                  </a>
                ) : (
                  <span className="underline">Укажите поля в стандарте</span>
                )}
                {" "}— ИИ начнёт штрафовать менеджеров за незаполненную карточку.
              </p>
            </div>
          )}
        </Card>
      )}

      {/* Missing fields */}
      {report.missing_fields.length > 0 && (
        <Card className="p-5">
          <SLabel>Не заполнены поля карточки</SLabel>
          <div className="flex flex-wrap gap-2">
            {report.missing_fields.map((f) => (
              <span key={f} className="rounded-lg border border-red-500/20 bg-red-500/5 px-2.5 py-1 text-xs text-red-300">{f}</span>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

// ─── ChronologyView ───────────────────────────────────────────────────────────

function ChronologyView({ chronology, navigate }: { chronology: ChronologyPayload; navigate: (r: RouteState) => void }) {
  return (
    <div className="space-y-4">
      <Card className="p-5 bg-gradient-to-br from-neutral-900 to-blue-950/20">
        <div className="flex flex-wrap gap-2 mb-3">
          <button onClick={() => navigate({ kind: "report", id: chronology.public_id })}
            className="inline-flex items-center gap-1.5 h-7 px-3 rounded-lg border border-neutral-700 text-xs text-neutral-400 hover:text-white hover:border-neutral-500 transition-colors">
            <ArrowLeft size={11} /> К отчёту
          </button>
          {chronology.deal_url && (
            <a href={chronology.deal_url} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1.5 h-7 px-3 rounded-lg border border-neutral-700 text-xs text-neutral-400 hover:text-white hover:border-neutral-500 transition-colors">
              <ExternalLink size={11} /> Сделка
            </a>
          )}
        </div>
        <h2 className="text-lg font-bold text-white mb-1">{chronology.title}</h2>
        <p className="text-sm text-neutral-500">Сделка #{chronology.deal_id} · {chronology.client_name} · {chronology.selected_operator_name}</p>
      </Card>

      <div className="space-y-2">
        {chronology.events.map((ev) => {
          const sel = ev.scope === "selected"
          const sys = ev.scope === "system"

          // "Отправлено Файл" / "Отправлено Аудиосообщение" → suffix to title, no body box.
          const sentMatch = ev.text?.match(/^Отправлено\s+(.{1,30})$/)
          const sentLabel = sentMatch ? sentMatch[1].trim() : ""
          const bodyText = sentLabel ? "" : ev.text

          // Hide creator line when it's a system source / placeholder. Keep when there's a real person.
          const isPlaceholder = (s?: string) => !s || !s.trim() || /^<.*>$/.test(s.trim()) || /^не\s*(указан|задан|доступ)/i.test(s.trim())
          const showCreator = !sys && !isPlaceholder(ev.creator_name)
          const creatorPos = isPlaceholder(ev.creator_position) ? "" : ev.creator_position

          const cardCls = sel
            ? "p-4 border-blue-500/20 bg-blue-500/5"
            : sys
            ? "p-3 border-neutral-800/50 bg-neutral-900/50"
            : "p-3.5"
          const titleCls = sel
            ? "text-sm font-semibold text-white"
            : sys
            ? "text-xs font-medium text-neutral-400"
            : "text-sm font-semibold text-neutral-200"
          const headerHasItems = ev.status_label || ev.duration_seconds

          return (
            <Card key={ev.event_id} className={cardCls}>
              <div className={`flex flex-wrap items-center gap-2 ${headerHasItems ? "mb-2" : "mb-1.5"}`}>
                <span className="text-[10px] text-neutral-600">{fmtDate(ev.timestamp_utc)}</span>
                {ev.status_label && (
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${ev.status === "handled" ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400"}`}>
                    {ev.status_label}
                  </span>
                )}
                {ev.duration_seconds ? <span className="text-[10px] text-neutral-600">{fmtDur(ev.duration_seconds)}</span> : null}
              </div>
              <h3 className={`${titleCls} ${showCreator || bodyText || ev.transcript ? "mb-2" : ""}`}>
                {ev.title}
                {sentLabel && <span className="text-neutral-500 font-normal"> · {sentLabel}</span>}
              </h3>
              {showCreator && (
                <p className="text-xs text-neutral-600 mb-2">
                  {ev.creator_name}{creatorPos ? ` · ${creatorPos}` : ""}
                </p>
              )}
              {bodyText && (
                <p className={`leading-6 rounded-xl bg-neutral-800/40 px-3 py-2 ${ev.transcript ? "mb-2" : ""} ${sys ? "text-xs text-neutral-400 leading-5" : "text-sm text-neutral-300"}`}>
                  {bodyText}
                </p>
              )}
              {ev.transcript && (
                <div className="rounded-xl border border-blue-500/15 bg-blue-500/5 px-3 py-2">
                  <p className="text-[10px] font-semibold text-blue-400 mb-2">Транскрипт</p>
                  <div className="flex flex-col gap-1.5 text-xs leading-5">
                    {ev.transcript.split('\n').map((line, i) => {
                      const m = /^(Спикер\s*\S+):\s*(.*)$/.exec(line)
                      if (m) {
                        return (
                          <div key={i} className="flex gap-2">
                            <span className="text-blue-400/80 font-medium shrink-0 min-w-[60px]">{m[1]}</span>
                            <span className="text-neutral-300">{m[2]}</span>
                          </div>
                        )
                      }
                      return <div key={i} className="text-neutral-300">{line}</div>
                    })}
                  </div>
                </div>
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}

// ─── DevelopmentPlanSection ───────────────────────────────────────────────────

function DevelopmentPlanSection({ employeeId }: { employeeId: number }) {
  const [plan, setPlan] = useState<DevelopmentPlan | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [sending, setSending] = useState(false)
  const [genError, setGenError] = useState("")
  const [sendResult, setSendResult] = useState<{ count: number } | null>(null)

  const fetchPlan = useCallback(() => {
    fetch(`/api/employee/${employeeId}/plan`).then(async (r) => {
      if (r.status === 404) return null
      const d = await r.json(); return d.ok ? d.result : null
    }).then((p) => { setPlan(p); setLoaded(true) }).catch(() => setLoaded(true))
  }, [employeeId])

  useEffect(() => { fetchPlan() }, [fetchPlan])

  function generate() {
    setGenerating(true); setGenError(""); setSendResult(null)
    fetch(`/api/employee/${employeeId}/plan/generate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ calls_count: 5 }) })
      .then(async (r) => { const d = await r.json(); if (!d.ok) throw new Error(d.error); return d.result })
      .then((p) => setPlan(p))
      .catch((e: unknown) => setGenError(e instanceof Error ? e.message : "Ошибка"))
      .finally(() => setGenerating(false))
  }

  function sendBitrix() {
    if (!plan) return
    setSending(true)
    fetch(`/api/employee/${employeeId}/plan/${plan.id}/send-bitrix`, { method: "POST" })
      .then(async (r) => { const d = await r.json(); if (!d.ok) throw new Error(d.error); return d.result })
      .then((r) => { setSendResult({ count: r.created_count }); fetchPlan() })
      .catch((e: unknown) => setGenError(e instanceof Error ? e.message : "Ошибка отправки"))
      .finally(() => setSending(false))
  }

  const errMsg: Record<string, string> = {
    no_completed_runs: "Нет завершённых анализов для этого сотрудника",
    not_enough_runs: "Нужно минимум 2 анализа",
    no_problem_modules: "Системных проблем не обнаружено — отличный результат!",
    claude_returned_no_tasks: "Не удалось сформировать задачи, попробуйте позже",
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <SLabel>План развития</SLabel>
        <button onClick={generate} disabled={generating}
          className="inline-flex items-center gap-1.5 h-7 px-3 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-xs font-semibold text-white transition-colors">
          {generating ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
          {plan ? "Обновить" : "Сгенерировать"}
        </button>
      </div>

      {genError && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-xs text-red-400 mb-3">
          {errMsg[genError] ?? genError}
        </div>
      )}

      {!plan && loaded && !genError && (
        <Card className="p-6 text-center border-dashed">
          <Sparkles size={20} className="text-neutral-700 mx-auto mb-2" />
          <p className="text-sm text-neutral-500">Нет активного плана</p>
          <p className="text-xs text-neutral-600 mt-1">Claude проанализирует последние 5 звонков и сформирует задачи</p>
        </Card>
      )}

      {plan && (
        <Card className="overflow-hidden">
          <div className="px-5 py-3 border-b border-neutral-800 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${plan.status === "sent" ? "bg-green-500/15 text-green-400" : "bg-amber-500/15 text-amber-400"}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${plan.status === "sent" ? "bg-green-500" : "bg-amber-500"}`} />
                {plan.status === "sent" ? "Отправлен в Б24" : "Черновик"}
              </span>
              <span className="text-xs text-neutral-600">{plan.run_ids.length} звонков</span>
            </div>
            {plan.status !== "sent" && (
              <button onClick={sendBitrix} disabled={sending}
                className="inline-flex items-center gap-1.5 h-7 px-3 rounded-xl bg-green-700 hover:bg-green-600 disabled:opacity-50 text-xs font-semibold text-white transition-colors">
                {sending ? <Loader2 size={11} className="animate-spin" /> : <Send size={11} />}
                Отправить в Б24
              </button>
            )}
          </div>
          <div className="divide-y divide-neutral-800">
            {plan.tasks.map((t, i) => (
              <div key={i} className="px-5 py-4 flex items-start gap-3">
                <span className="w-5 h-5 rounded-full bg-blue-500/15 text-blue-400 text-xs font-bold flex items-center justify-center shrink-0 mt-0.5">{i + 1}</span>
                <div>
                  <p className="text-sm font-semibold text-white mb-1">{t.title}</p>
                  <p className="text-xs text-neutral-400 leading-5">{t.description}</p>
                  <p className="text-xs text-neutral-600 mt-1.5">Срок: {t.deadline_days} дн.</p>
                </div>
              </div>
            ))}
          </div>
          {sendResult && (
            <div className="px-5 py-3 border-t border-neutral-800 bg-green-500/5">
              <p className="text-sm text-green-400">✓ Создано {sendResult.count} задач в Битрикс24</p>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

// ─── Sparkline ────────────────────────────────────────────────────────────────

function Sparkline({ series }: { series: ScoreSeriesPoint[] }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(800)

  useEffect(() => {
    if (!wrapRef.current) return
    const ro = new ResizeObserver(entries => {
      const w = entries[0].contentRect.width
      if (w > 0) setW(Math.round(w))
    })
    ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [])

  if (series.length < 2) return (
    <div className="flex items-center justify-center h-[110px] text-xs text-neutral-600">Недостаточно данных</div>
  )

  const H = 110
  const padT = 24, padB = 24, padL = 14, padR = 14
  const innerW = W - padL - padR
  const innerH = H - padT - padB

  const scores = series.map(p => p.score_percent)
  const yMin = Math.max(0, Math.min(...scores) - 8)
  const yMax = Math.min(100, Math.max(...scores) + 8)
  const yRange = yMax - yMin || 1

  const cx = (i: number) => padL + (i / (series.length - 1)) * innerW
  const cy = (v: number) => padT + innerH - ((v - yMin) / yRange) * innerH

  const first = scores[0]
  const last = scores[scores.length - 1]
  const diff = last - first
  const lineColor = diff > 1.5 ? '#4ade80' : diff < -1.5 ? '#f87171' : '#818cf8'
  const gradId = `spark-grad-${diff > 1.5 ? 'up' : diff < -1.5 ? 'down' : 'flat'}`

  const points = series.map((p, i) => [cx(i), cy(p.score_percent)] as const)
  const tension = 0.35
  let path = `M ${points[0][0]},${points[0][1]}`
  for (let i = 0; i < points.length - 1; i++) {
    const [x0, y0] = points[i]
    const [x1, y1] = points[i + 1]
    const cp1x = x0 + (x1 - x0) * tension
    const cp2x = x1 - (x1 - x0) * tension
    path += ` C ${cp1x},${y0} ${cp2x},${y1} ${x1},${y1}`
  }
  const areaPath = `${path} L ${points[points.length - 1][0]},${padT + innerH} L ${padL},${padT + innerH} Z`

  const showLabel = (i: number) => i === 0 || i === series.length - 1 || series.length <= 7

  return (
    <div ref={wrapRef} className="w-full">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.28" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
          <filter id={`glow-${gradId}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        {[25, 50, 75].map(v => {
          const yg = cy(v)
          return yg > padT && yg < padT + innerH
            ? <line key={v} x1={padL} x2={padL + innerW} y1={yg} y2={yg} stroke="#262626" strokeWidth="1" />
            : null
        })}
        <path d={areaPath} fill={`url(#${gradId})`} />
        <path d={path} fill="none" stroke={lineColor} strokeWidth="2.5"
          strokeLinejoin="round" strokeLinecap="round" filter={`url(#glow-${gradId})`} />
        {series.map((p, i) => {
          const inner = (
            <g>
              <title>{p.date_label}: {p.score_percent}%{p.public_id ? " — открыть отчёт" : ""}</title>
              {showLabel(i) && (
                <text x={cx(i)} y={cy(p.score_percent) - 8} textAnchor="middle"
                  fontSize="11" fontWeight="600" fill="#d4d4d4" fontFamily="sans-serif">
                  {p.score_percent}%
                </text>
              )}
              {showLabel(i) && (
                <circle cx={cx(i)} cy={cy(p.score_percent)} r="6" fill={lineColor} fillOpacity="0.18" />
              )}
              <circle cx={cx(i)} cy={cy(p.score_percent)} r={showLabel(i) ? 3.5 : 2.5}
                fill={showLabel(i) ? lineColor : '#404040'} />
              {/* Invisible larger hit target for easier clicking */}
              <circle cx={cx(i)} cy={cy(p.score_percent)} r="12" fill="transparent"
                style={p.public_id ? { cursor: "pointer" } : undefined} />
              {showLabel(i) && (
                <text x={cx(i)} y={H - 6} textAnchor="middle"
                  fontSize="10" fill="#737373" fontFamily="sans-serif">
                  {p.date_label}
                </text>
              )}
            </g>
          )
          return p.public_id ? (
            <a key={i} href={`/dash/report/${p.public_id}`} target="_blank" rel="noopener noreferrer">
              {inner}
            </a>
          ) : (
            <g key={i}>{inner}</g>
          )
        })}
      </svg>
    </div>
  )
}

// ─── EmployeeView ─────────────────────────────────────────────────────────────

function EmployeeView({ operator, navigate, focus }: { operator: EmployeePayload; navigate: (r: RouteState) => void; focus?: "problems" }) {
  const [archiving, setArchiving] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)
  const doArchive = async () => {
    setArchiving(true)
    try {
      const r = await fetch(`/api/employee/${operator.employee_id}/archive`, { method: "POST" }).then(r => r.json())
      if (r.ok) navigate({ kind: "home" })
    } finally {
      setArchiving(false)
      setConfirmArchive(false)
    }
  }

  const [showMatrix, setShowMatrix] = useState(false)
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set())
  const problemsRef = useRef<HTMLDivElement | null>(null)

  // Build problem modules with per-call instances. Includes any module that failed at least once,
  // unless there exist modules failing ≥2 times — in which case only those (the "systemic" ones) are shown.
  const { problemModules, problemsTitle } = useMemo(() => {
    const all: ProblemModule[] = operator.module_matrix
      .map((row) => {
        const instances: ProblemInstance[] = []
        row.values.forEach((v, i) => {
          if (v && v.raw_coef < 1) {
            instances.push({
              date_label: operator.score_series[i]?.date_label ?? "—",
              comment: (v.comment ?? "").trim(),
            })
          }
        })
        return instances.length > 0
          ? {
              module_name: row.module_name,
              block_name: row.block_name,
              bad_count: instances.length,
              avg_ratio_percent: row.avg_ratio_percent,
              instances,
            }
          : null
      })
      .filter((x): x is ProblemModule => x !== null)

    const repeated = all.filter((m) => m.bad_count >= 2)
    const items = repeated.length > 0 ? repeated : all
    items.sort((a, b) => b.bad_count - a.bad_count || a.avg_ratio_percent - b.avg_ratio_percent)
    return {
      problemModules: items,
      problemsTitle: repeated.length > 0 ? "Системные проблемы" : "Проблемные модули",
    }
  }, [operator.module_matrix, operator.score_series])

  const toggleModule = (name: string) => {
    setExpandedModules((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  useEffect(() => {
    if (focus === "problems" && problemsRef.current) {
      problemsRef.current.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [focus, operator.employee_id])

  return (
    <div className="space-y-5">
      <Card className="p-6 bg-gradient-to-br from-neutral-900 via-neutral-900 to-blue-950/30">
        <div className="flex items-start gap-4">
          <Avatar name={operator.employee_name} size="lg" />
          <div className="flex-1 min-w-0">
            <h2 className="text-xl font-bold text-white">{operator.employee_name}</h2>
            <p className="text-sm text-neutral-500">
              {operator.employee_position || "—"}
              <span className="text-neutral-700"> · ID {operator.employee_id}</span>
            </p>
          </div>
          <div className="text-right shrink-0">
            <div className={`text-4xl font-black ${scoreColor(operator.average_score_percent)}`}>{operator.average_score_percent}%</div>
            <div className="text-xs text-neutral-600 mt-1">среднее за {operator.analysis_count} {operator.analysis_count === 1 ? "анализ" : "анализов"}</div>
          </div>
        </div>
        <div className="flex justify-end mt-4 pt-3 border-t border-neutral-800/60">
          <button
            type="button"
            onClick={() => setConfirmArchive(true)}
            disabled={archiving}
            className="inline-flex items-center gap-1.5 text-xs text-neutral-500 hover:text-red-400 transition-colors disabled:opacity-50"
          >
            {archiving ? <Loader2 size={12} className="animate-spin" /> : null}
            Архивировать сотрудника
          </button>
        </div>
      </Card>

      {operator.score_series.length > 0 && (
        <Card className="p-4">
          <div className="flex items-center justify-between text-xs text-neutral-500 mb-2 px-1">
            <span>Динамика оценок</span>
            <span className="flex items-center gap-2">
              <span className="text-neutral-600">{operator.score_series[operator.score_series.length - 1].date_label}</span>
              {operator.overall_trend_percent != null && <DeltaBadge value={operator.overall_trend_percent} />}
            </span>
          </div>
          <Sparkline series={operator.score_series} />
        </Card>
      )}

      <DevelopmentPlanSection employeeId={operator.employee_id} />

      {problemModules.length > 0 && (
        <div ref={problemsRef} className="scroll-mt-24">
          <SLabel>{problemsTitle}</SLabel>
          <div className="space-y-4">
            {Object.entries(
              problemModules.reduce<Record<string, ProblemModule[]>>((acc, p) => {
                (acc[p.block_name] ||= []).push(p)
                return acc
              }, {})
            ).map(([blockName, items]) => (
              <div key={blockName} className="space-y-2">
                <div className="px-1 text-[11px] font-semibold tracking-wider uppercase text-neutral-500">
                  {blockName}
                </div>
                {items.map((item) => {
                  const isExpanded = expandedModules.has(item.module_name)
                  return (
                    <Card key={item.module_name} className="overflow-hidden">
                      <button
                        type="button"
                        onClick={() => toggleModule(item.module_name)}
                        className="w-full text-left px-4 py-3 hover:bg-neutral-800/40 transition-colors"
                      >
                        <div className="flex items-center gap-3 mb-2">
                          <p className="flex-1 min-w-0 text-sm text-neutral-200 truncate" title={item.module_name}>
                            {shortenModuleName(item.module_name)}
                          </p>
                          <span className="shrink-0 text-xs text-neutral-600">{item.bad_count}×</span>
                          <span className={`shrink-0 text-base font-black w-12 text-right ${scoreColor(item.avg_ratio_percent)}`}>
                            {item.avg_ratio_percent}%
                          </span>
                          <ChevronDown
                            size={16}
                            className={`shrink-0 text-neutral-500 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                          />
                        </div>
                        <div className="h-1.5 rounded-full bg-neutral-800 overflow-hidden">
                          <div
                            className={`h-full rounded-full ${scoreBg(item.avg_ratio_percent)}`}
                            style={{ width: `${item.avg_ratio_percent}%` }}
                          />
                        </div>
                      </button>
                      {isExpanded && (
                        <div className="border-t border-neutral-800/60 px-4 py-3 space-y-2.5 bg-neutral-950/40">
                          {item.instances.map((inst, idx) => (
                            <div key={idx} className="flex gap-3 text-sm">
                              <span className="shrink-0 w-12 text-xs text-neutral-600 pt-0.5">{inst.date_label}</span>
                              <p className="flex-1 min-w-0 text-neutral-300 leading-relaxed">
                                {inst.comment || <span className="text-neutral-600 italic">без комментария</span>}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </Card>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      )}

      {operator.task_followup.items.length > 0 && (
        <div>
          <SLabel>Контроль задач</SLabel>
          <div className="flex gap-2 mb-3">
            {[
              { label: "Выполнено", value: operator.task_followup.completed, c: "text-green-400 border-green-500/20 bg-green-500/5" },
              { label: "Частично", value: operator.task_followup.partial, c: "text-amber-400 border-amber-500/20 bg-amber-500/5" },
              { label: "Не выполнено", value: operator.task_followup.not_done, c: "text-red-400 border-red-500/20 bg-red-500/5" },
            ].map((s) => (
              <div key={s.label} className={`flex-1 rounded-xl border px-3 py-3 text-center ${s.c}`}>
                <div className="text-[10px] text-neutral-500 mb-1">{s.label}</div>
                <div className="text-2xl font-black">{s.value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <SLabel>История звонков</SLabel>
        <div className="space-y-2">
          {[...operator.history].reverse().map((item) => (
            <Card key={item.run_id} className="p-4 flex items-center gap-3">
              <div className="text-xs text-neutral-600 w-24 shrink-0">{fmtDate(item.primary_call_at || item.sort_at)}</div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{item.client_name || "—"}</p>
                {item.declined_modules.length > 0 && (
                  <p className="text-xs text-neutral-600 truncate mt-0.5">↓ {item.declined_modules.map((m) => m.module_name).join(", ")}</p>
                )}
              </div>
              <div className={`text-lg font-black shrink-0 ${scoreColor(item.overall_score_percent)}`}>{item.overall_score_percent}%</div>
              <DeltaBadge value={item.delta_from_prev} />
              <button onClick={() => navigate({ kind: "report", id: item.public_id })}
                className="shrink-0 h-7 px-3 rounded-lg border border-neutral-700 hover:border-neutral-500 text-xs text-neutral-500 hover:text-white transition-colors">
                Отчёт
              </button>
            </Card>
          ))}
        </div>
      </div>

      <div>
        <button onClick={() => setShowMatrix((v) => !v)}
          className="flex items-center gap-2 text-[11px] font-semibold tracking-widest text-neutral-600 uppercase mb-3 hover:text-neutral-400 transition-colors">
          <ChevronRight size={12} className={`transition-transform ${showMatrix ? "rotate-90" : ""}`} />
          Динамика по модулям
        </button>
        {showMatrix && (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="border-b border-neutral-800">
                  <th className="text-left px-4 py-3 text-[11px] text-neutral-500 font-semibold">Модуль</th>
                  {operator.history.map((h) => (
                    <th key={h.run_id} className="px-3 py-3 text-[11px] text-neutral-500 font-semibold whitespace-nowrap">
                      {h.deal_id ? `#${h.deal_id}` : "—"}
                    </th>
                  ))}
                  <th className="px-4 py-3 text-[11px] text-neutral-500 font-semibold">Среднее</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800">
                {operator.module_matrix.map((row, i) => (
                  <tr key={i} className="hover:bg-neutral-800/20">
                    <td className="px-4 py-2.5 text-xs text-neutral-400 max-w-[180px]">{row.module_name}</td>
                    {row.values.map((v, vi) => (
                      <td key={vi} className="px-3 py-2.5 text-center">
                        {v ? (
                          <span className={`inline-block rounded-md px-1.5 py-0.5 text-xs font-semibold ${v.ratio_percent >= 80 ? "bg-green-500/15 text-green-400" : v.ratio_percent >= 50 ? "bg-amber-500/15 text-amber-400" : "bg-red-500/15 text-red-400"}`}>
                            {v.ratio_percent}%
                          </span>
                        ) : <span className="text-neutral-700">—</span>}
                      </td>
                    ))}
                    <td className="px-4 py-2.5 text-center">
                      <span className={`text-sm font-bold ${scoreColor(row.avg_ratio_percent)}`}>{row.avg_ratio_percent}%</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>

      {confirmArchive && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => !archiving && setConfirmArchive(false)}
        >
          <div
            className="w-full max-w-md mx-4 rounded-2xl border border-neutral-800 bg-neutral-900 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white mb-2">Архивировать сотрудника?</h3>
            <p className="text-sm text-neutral-400 leading-6 mb-5">
              <span className="text-white font-semibold">{operator.employee_name}</span> будет скрыт из списка активных. Вся история анализов сохранится — сотрудника можно восстановить в любой момент со вкладки «Архив».
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmArchive(false)}
                disabled={archiving}
                className="h-9 px-4 rounded-xl border border-neutral-700 text-sm text-neutral-300 hover:border-neutral-500 hover:text-white transition-colors disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={doArchive}
                disabled={archiving}
                className="h-9 px-4 rounded-xl bg-red-500/15 border border-red-500/30 text-sm font-semibold text-red-400 hover:bg-red-500/25 hover:border-red-500/50 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                {archiving ? <Loader2 size={14} className="animate-spin" /> : null}
                Архивировать
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Standards ────────────────────────────────────────────────────────────────

type StandardSummary = {
  id: number
  name: string
  status: string
  source_type: string
  source_file_name: string
  imported_at: string
  archived_at: string
  block_count: number
  module_count: number
  is_default: boolean
}

type StandardModule = {
  id: number
  name: string
  details: string
  weight_percent: number
  scoring_rules: string
  is_scored: boolean
  sort_order: number
}

type StandardBlock = {
  id: number
  name: string
  weight_percent: number
  sort_order: number
  modules: StandardModule[]
}

type CardField = {
  label: string
  entity_type: string
  field_code: string
}

type StandardPayload = {
  id: number
  name: string
  status: string
  source_type: string
  source_file_name: string
  imported_at: string
  archived_at: string
  blocks: StandardBlock[]
  total_modules: number
  is_default: boolean
  card_fields: CardField[]
}

function StandardsView({ navigate }: { navigate: (r: RouteState) => void }) {
  const [items, setItems] = useState<StandardSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [settingDefault, setSettingDefault] = useState<number | null>(null)
  const reload = () => {
    setLoading(true)
    fetch("/api/standards")
      .then((r) => r.json())
      .then((d) => setItems(d.ok ? d.result : []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }
  useEffect(() => { reload() }, [])

  const setAsDefault = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation()
    setSettingDefault(id)
    try {
      const r = await fetch(`/api/standards/${id}/set-default`, { method: "POST" }).then(r => r.json())
      if (r.ok) reload()
    } finally {
      setSettingDefault(null)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 size={24} className="animate-spin text-neutral-600" /></div>
  }
  if (items.length === 0) {
    return (
      <Card className="p-10 text-center border-dashed">
        <ClipboardCheck size={32} className="text-neutral-700 mx-auto mb-3" />
        <p className="text-neutral-400 font-semibold">Стандартов пока нет</p>
        <p className="text-sm text-neutral-600 mt-1">Импортируйте CSV-стандарт через админ-сценарий — появится здесь</p>
      </Card>
    )
  }
  return (
    <div className="space-y-3">
      {items.map((s) => (
        <div
          key={s.id}
          onClick={() => navigate({ kind: "standard", id: String(s.id) })}
          className="w-full text-left rounded-2xl border border-neutral-800 bg-neutral-900 p-5 hover:border-neutral-700 hover:bg-neutral-800/60 transition-all group cursor-pointer"
        >
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <h3 className="text-base font-semibold text-white truncate">{s.name}</h3>
                {s.is_default && (
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold bg-blue-500/15 text-blue-400">
                    По умолчанию
                  </span>
                )}
                {s.status === "archived" && (
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold bg-neutral-800 text-neutral-500">
                    Архив
                  </span>
                )}
              </div>
              {s.source_file_name && (
                <p className="text-xs text-neutral-500 truncate" title={s.source_file_name}>
                  Источник: {s.source_file_name}
                </p>
              )}
            </div>
            <ChevronRight size={16} className="text-neutral-600 group-hover:text-neutral-400 transition-colors shrink-0 mt-1" />
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs text-neutral-500">
            <span><span className="text-neutral-300 font-semibold">{s.block_count}</span> блоков</span>
            <span><span className="text-neutral-300 font-semibold">{s.module_count}</span> модулей</span>
            <span className="text-neutral-600">импортирован {fmtDate(s.imported_at)}</span>
            {s.status === "active" && !s.is_default && (
              <button
                onClick={(e) => setAsDefault(s.id, e)}
                disabled={settingDefault === s.id}
                className="ml-auto text-xs px-3 py-1 rounded-lg border border-neutral-700 text-neutral-300 hover:bg-neutral-800 hover:border-neutral-600 disabled:opacity-50"
              >
                {settingDefault === s.id ? "..." : "Сделать по умолчанию"}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function StandardDetailView({ id, navigate }: { id: string; navigate: (r: RouteState) => void }) {
  const [data, setData] = useState<StandardPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [openBlocks, setOpenBlocks] = useState<Set<number>>(new Set())
  const [editingName, setEditingName] = useState(false)
  const [draftName, setDraftName] = useState("")
  const [savingName, setSavingName] = useState(false)
  const [nameError, setNameError] = useState("")
  const [settingDefault, setSettingDefault] = useState(false)

  const setAsDefault = async () => {
    if (!data) return
    setSettingDefault(true)
    try {
      const r = await fetch(`/api/standards/${data.id}/set-default`, { method: "POST" }).then(r => r.json())
      if (r.ok) setData({ ...data, is_default: true })
    } finally {
      setSettingDefault(false)
    }
  }

  const startEditName = () => {
    setDraftName(data?.name || "")
    setNameError("")
    setEditingName(true)
  }

  const saveName = async () => {
    if (!data) return
    const trimmed = draftName.trim()
    if (!trimmed) { setNameError("Имя не может быть пустым"); return }
    if (trimmed === data.name) { setEditingName(false); return }
    setSavingName(true)
    setNameError("")
    try {
      const r = await fetch(`/api/standards/${data.id}/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmed }),
      }).then(r => r.json())
      if (r.ok) {
        setData({ ...data, name: trimmed })
        setEditingName(false)
      } else {
        setNameError(r.error || "save_failed")
      }
    } catch (e) {
      setNameError(String(e))
    } finally {
      setSavingName(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    setError("")
    fetch(`/api/standards/${id}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) {
          setData(d.result)
          // Open all blocks by default
          setOpenBlocks(new Set((d.result.blocks || []).map((b: StandardBlock) => b.id)))
        } else {
          setError(d.error || "load_failed")
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [id])

  const toggleBlock = (bid: number) => {
    setOpenBlocks((prev) => {
      const next = new Set(prev)
      if (next.has(bid)) next.delete(bid)
      else next.add(bid)
      return next
    })
  }

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 size={24} className="animate-spin text-neutral-600" /></div>
  }
  if (error || !data) {
    return (
      <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-8 text-center">
        <p className="text-red-400 font-semibold mb-1">Стандарт не найден</p>
        <button onClick={() => navigate({ kind: "standards" })} className="text-sm text-neutral-400 hover:text-white">Вернуться к списку</button>
      </div>
    )
  }

  const totalBlockWeight = data.blocks.reduce((s, b) => s + b.weight_percent, 0)

  return (
    <div className="space-y-5">
      <Card className="p-6 bg-gradient-to-br from-neutral-900 via-neutral-900 to-blue-950/30">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex-1 min-w-0">
            {editingName ? (
              <div className="flex flex-col gap-2 mb-1.5">
                <div className="flex items-center gap-2">
                  <input
                    autoFocus
                    type="text"
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveName()
                      if (e.key === "Escape") { setEditingName(false); setNameError("") }
                    }}
                    disabled={savingName}
                    maxLength={200}
                    className="flex-1 rounded-xl border border-neutral-700 bg-neutral-950 px-3 py-2 text-xl font-bold text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
                  />
                  <button
                    type="button"
                    onClick={saveName}
                    disabled={savingName}
                    title="Сохранить"
                    className="h-10 w-10 inline-flex items-center justify-center rounded-xl bg-green-500/15 border border-green-500/30 text-green-400 hover:bg-green-500/25 transition-colors disabled:opacity-50"
                  >
                    {savingName ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setEditingName(false); setNameError("") }}
                    disabled={savingName}
                    title="Отмена"
                    className="h-10 w-10 inline-flex items-center justify-center rounded-xl border border-neutral-700 text-neutral-400 hover:border-neutral-500 hover:text-white transition-colors disabled:opacity-50"
                  >
                    <X size={16} />
                  </button>
                </div>
                {nameError && <p className="text-xs text-red-400">{nameError}</p>}
              </div>
            ) : (
              <div className="flex items-center gap-2 mb-1.5 group flex-wrap">
                <h2 className="text-xl font-bold text-white">{data.name}</h2>
                {data.is_default && (
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold bg-blue-500/15 text-blue-400">
                    По умолчанию
                  </span>
                )}
                {data.status === "archived" && (
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold bg-neutral-800 text-neutral-500">
                    Архив
                  </span>
                )}
                <button
                  type="button"
                  onClick={startEditName}
                  title="Изменить имя"
                  className="ml-1 inline-flex items-center justify-center w-7 h-7 rounded-lg text-neutral-600 hover:text-white hover:bg-neutral-800 transition-colors opacity-0 group-hover:opacity-100"
                >
                  <Pencil size={13} />
                </button>
              </div>
            )}
            {data.source_file_name && (
              <p className="text-sm text-neutral-500">Источник: {data.source_file_name}</p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-neutral-500 pt-3 border-t border-neutral-800/60">
          <span><span className="text-neutral-300 font-semibold">{data.blocks.length}</span> блоков</span>
          <span><span className="text-neutral-300 font-semibold">{data.total_modules}</span> модулей</span>
          <span><span className="text-neutral-300 font-semibold">{Math.round(totalBlockWeight * 10) / 10}%</span> суммарный вес</span>
          <span className="text-neutral-600">импортирован {fmtDate(data.imported_at)}</span>
          {data.status === "active" && !data.is_default && (
            <button
              type="button"
              onClick={setAsDefault}
              disabled={settingDefault}
              className="ml-auto text-xs px-3 py-1.5 rounded-lg border border-neutral-700 text-neutral-200 hover:bg-neutral-800 hover:border-neutral-600 disabled:opacity-50"
            >
              {settingDefault ? "..." : "Сделать стандартом по умолчанию"}
            </button>
          )}
        </div>
      </Card>

      <div className="space-y-3">
        {data.blocks.map((block) => {
          const isOpen = openBlocks.has(block.id)
          const moduleSum = block.modules.reduce((s, m) => s + m.weight_percent, 0)
          return (
            <Card key={block.id} className="overflow-hidden">
              <button
                type="button"
                onClick={() => toggleBlock(block.id)}
                className="w-full text-left px-5 py-4 hover:bg-neutral-800/30 transition-colors"
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-[10px] font-semibold text-neutral-600 tabular-nums w-6">{block.sort_order}</span>
                  <h3 className="flex-1 min-w-0 text-base font-semibold text-white">{block.name}</h3>
                  <span className="text-xs text-neutral-500">{block.modules.length} модулей</span>
                  <span className="text-base font-black w-14 text-right text-blue-400">{block.weight_percent}%</span>
                  <ChevronDown size={16} className={`text-neutral-500 transition-transform ${isOpen ? "rotate-180" : ""}`} />
                </div>
                <div className="h-1.5 rounded-full bg-neutral-800 overflow-hidden ml-9">
                  <div className="h-full rounded-full bg-blue-500/60" style={{ width: `${block.weight_percent}%` }} />
                </div>
              </button>
              {isOpen && (
                <div className="border-t border-neutral-800/60 divide-y divide-neutral-800/40">
                  {block.modules.map((m) => (
                    <div key={m.id} className="px-5 py-3 flex items-start gap-3">
                      <span className="text-[10px] font-semibold text-neutral-600 tabular-nums w-6 mt-0.5">{m.sort_order}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-neutral-200 leading-snug">{m.name}</p>
                        {m.details && (
                          <p className="text-xs text-neutral-500 mt-1 leading-relaxed">{m.details}</p>
                        )}
                        {!m.is_scored && (
                          <span className="inline-block mt-1.5 text-[10px] text-neutral-600 italic">не оценивается</span>
                        )}
                      </div>
                      <span className="text-sm font-semibold text-neutral-300 w-14 text-right shrink-0">{m.weight_percent}%</span>
                    </div>
                  ))}
                  {Math.abs(moduleSum - block.weight_percent) > 0.01 && (
                    <div className="px-5 py-2 text-[11px] text-amber-400/80 bg-amber-500/5">
                      ⚠ Сумма модулей {Math.round(moduleSum * 10) / 10}% не совпадает с весом блока {block.weight_percent}%
                    </div>
                  )}
                </div>
              )}
            </Card>
          )
        })}
      </div>

      <CardFieldsSection
        standardId={data.id}
        fields={data.card_fields}
        onUpdate={(updated) => setData({ ...data, card_fields: updated })}
      />
    </div>
  )
}

// ─── CardFieldsSection ────────────────────────────────────────────────────────

function CardFieldsSection({ standardId, fields, onUpdate }: {
  standardId: number
  fields: CardField[]
  onUpdate: (next: CardField[]) => void
}) {
  const [importerOpen, setImporterOpen] = useState(false)
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-base font-semibold text-white mb-1">Поля карточки клиента</h3>
          <p className="text-xs text-neutral-500">Перечень полей в Bitrix24, которые менеджер обязан заполнить. Если список пуст — блок «Заполненность карточки» в отчёте не показывается.</p>
        </div>
        <button
          type="button"
          onClick={() => setImporterOpen(true)}
          className="text-xs px-3 py-1.5 rounded-lg border border-neutral-700 text-neutral-200 hover:bg-neutral-800 hover:border-neutral-600 shrink-0"
        >
          Импортировать из Bitrix24
        </button>
      </div>
      {fields.length === 0 ? (
        <p className="text-xs text-neutral-600 italic">Не настроено</p>
      ) : (
        <div className="space-y-1">
          {fields.map((f, idx) => (
            <div key={`${f.entity_type}:${f.field_code}:${idx}`} className="flex items-center gap-3 text-xs text-neutral-300">
              <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold bg-neutral-800 text-neutral-400 uppercase tracking-wide">{f.entity_type}</span>
              <span className="flex-1 truncate">{f.label}</span>
              <code className="text-[10px] text-neutral-600 font-mono">{f.field_code}</code>
            </div>
          ))}
        </div>
      )}
      {importerOpen && (
        <CardFieldsImporter
          standardId={standardId}
          currentFields={fields}
          onClose={() => setImporterOpen(false)}
          onSaved={(saved) => { onUpdate(saved); setImporterOpen(false) }}
        />
      )}
    </Card>
  )
}

function CardFieldsImporter({ standardId, currentFields, onClose, onSaved }: {
  standardId: number
  currentFields: CardField[]
  onClose: () => void
  onSaved: (fields: CardField[]) => void
}) {
  const [entityType, setEntityType] = useState<"deal" | "lead">("deal")
  const [bitrixFields, setBitrixFields] = useState<CardField[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [saving, setSaving] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(() => new Set(
    currentFields.map((f) => `${f.entity_type}:${f.field_code}`)
  ))

  useEffect(() => {
    setLoading(true)
    setError("")
    fetch(`/api/standards/${standardId}/bitrix-fields?entity_type=${entityType}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) setBitrixFields(d.result.fields || [])
        else setError(d.message || d.error || "load_failed")
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [entityType, standardId])

  const toggle = (field: CardField) => {
    const key = `${field.entity_type}:${field.field_code}`
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const save = async () => {
    setSaving(true)
    try {
      // Build the saved set: keep current fields whose key is in `selected`,
      // and add newly checked fields from bitrixFields.
      const keep: CardField[] = currentFields.filter((f) => selected.has(`${f.entity_type}:${f.field_code}`))
      const keepKeys = new Set(keep.map((f) => `${f.entity_type}:${f.field_code}`))
      for (const f of bitrixFields) {
        const k = `${f.entity_type}:${f.field_code}`
        if (selected.has(k) && !keepKeys.has(k)) {
          keep.push({ label: f.label, entity_type: f.entity_type, field_code: f.field_code })
          keepKeys.add(k)
        }
      }
      const r = await fetch(`/api/standards/${standardId}/card-fields`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: keep }),
      }).then((r) => r.json())
      if (r.ok) onSaved(r.result.fields || [])
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl max-h-[80vh] rounded-2xl border border-neutral-800 bg-neutral-900 flex flex-col">
        <div className="px-5 py-4 border-b border-neutral-800 flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">Поля Bitrix24</h3>
          <button onClick={onClose} className="text-neutral-500 hover:text-white"><X size={16} /></button>
        </div>
        <div className="px-5 py-3 border-b border-neutral-800 flex gap-2">
          <button
            type="button"
            onClick={() => setEntityType("deal")}
            className={`text-xs px-3 py-1.5 rounded-lg border ${entityType === "deal" ? "bg-blue-500/15 border-blue-500/40 text-blue-300" : "border-neutral-700 text-neutral-400 hover:bg-neutral-800"}`}
          >Сделки</button>
          <button
            type="button"
            onClick={() => setEntityType("lead")}
            className={`text-xs px-3 py-1.5 rounded-lg border ${entityType === "lead" ? "bg-blue-500/15 border-blue-500/40 text-blue-300" : "border-neutral-700 text-neutral-400 hover:bg-neutral-800"}`}
          >Лиды</button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-3">
          {loading ? (
            <div className="flex justify-center py-10"><Loader2 size={20} className="animate-spin text-neutral-600" /></div>
          ) : error ? (
            <div className="text-xs text-red-400">Ошибка: {error}</div>
          ) : bitrixFields.length === 0 ? (
            <p className="text-xs text-neutral-500 italic">В этом портале нет пользовательских полей для {entityType === "deal" ? "сделок" : "лидов"}.</p>
          ) : (
            <div className="space-y-1">
              {bitrixFields.map((f) => {
                const key = `${f.entity_type}:${f.field_code}`
                const checked = selected.has(key)
                return (
                  <label key={key} className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-neutral-800/40 cursor-pointer">
                    <input type="checkbox" checked={checked} onChange={() => toggle(f)} className="accent-blue-500" />
                    <span className="flex-1 text-sm text-neutral-200 truncate">{f.label}</span>
                    <code className="text-[10px] text-neutral-600 font-mono">{f.field_code}</code>
                  </label>
                )
              })}
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-neutral-800 flex justify-end gap-2">
          <button onClick={onClose} className="text-xs px-3 py-1.5 rounded-lg border border-neutral-700 text-neutral-300 hover:bg-neutral-800">Отмена</button>
          <button onClick={save} disabled={saving} className="text-xs px-3 py-1.5 rounded-lg bg-blue-500/20 border border-blue-500/40 text-blue-200 hover:bg-blue-500/30 disabled:opacity-50">
            {saving ? "..." : "Сохранить"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [route, setRoute] = useState<RouteState>(resolveRoute())
  const [me, setMe] = useState<MePayload | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [report, setReport] = useState<ReportPayload | null>(null)
  const [chronology, setChronology] = useState<ChronologyPayload | null>(null)
  const [operator, setOperator] = useState<EmployeePayload | null>(null)

  // Auth check
  useEffect(() => {
    fetch("/api/me").then(async (r) => {
      if (r.status === 401) { window.location.href = "/login"; return }
      const d = await r.json()
      if (d.ok) setMe(d.result)
      setAuthChecked(true)
    }).catch(() => setAuthChecked(true))
  }, [])

  // Route sync
  useEffect(() => {
    const sync = () => setRoute(resolveRoute())
    window.addEventListener("popstate", sync)
    return () => window.removeEventListener("popstate", sync)
  }, [])

  // Data fetch for report/chronology/operator
  useEffect(() => {
    if (!authChecked) return
    const ep =
      route.kind === "report" ? `/api/report/${encodeURIComponent(route.id)}` :
      route.kind === "chronology" ? `/api/chronology/${encodeURIComponent(route.id)}` :
      route.kind === "employee" ? `/api/employee/${encodeURIComponent(route.id)}` : null
    if (!ep) return

    let mounted = true
    setLoading(true); setError(""); setReport(null); setChronology(null); setOperator(null)
    fetch(ep).then(async (r) => {
      const d = await r.json()
      if (!d.ok) throw new Error(d.error || `HTTP ${r.status}`)
      return d.result
    }).then((data) => {
      if (!mounted) return
      if (route.kind === "report") setReport(data)
      if (route.kind === "chronology") setChronology(data)
      if (route.kind === "employee") setOperator(data)
    }).catch((e: unknown) => {
      if (mounted) setError(e instanceof Error ? e.message : "Ошибка")
    }).finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [route, authChecked])

  function navigate(next: RouteState) {
    window.history.pushState({}, "", toPath(next))
    setRoute(next)
  }

  if (!authChecked) {
    return (
      <div className="min-h-screen bg-neutral-950 flex items-center justify-center">
        <Loader2 size={24} className="animate-spin text-neutral-600" />
      </div>
    )
  }

  if (!me) return null

  const isSubPage = route.kind === "report" || route.kind === "chronology" || route.kind === "employee" || route.kind === "standard"

  return (
    <div className="flex min-h-screen bg-neutral-950 text-neutral-100">
      <Sidebar me={me} route={route} navigate={navigate} />

      <div className="flex-1 min-w-0">
        {/* Page top bar — always visible */}
        <div className="sticky top-0 z-10 border-b border-neutral-800 bg-neutral-950/90 backdrop-blur-sm px-6 h-[72px] flex items-center gap-3">
          {isSubPage ? (
            <>
              <button onClick={() => navigate(route.kind === "standard" ? { kind: "standards" } : { kind: "home" })}
                className="inline-flex items-center gap-1.5 text-xs text-neutral-500 hover:text-white transition-colors shrink-0">
                <ArrowLeft size={13} /> Назад
              </button>
              <span className="text-neutral-700">/</span>
              <span className="text-sm font-semibold text-white truncate">
                {route.kind === "report" && report ? report.employee_name :
                 route.kind === "chronology" && chronology ? chronology.title :
                 route.kind === "employee" && operator ? operator.employee_name :
                 route.kind === "standard" ? "Стандарт" : "…"}
              </span>
            </>
          ) : (
            <div>
              <div className="text-sm font-bold text-white leading-tight">
                {route.kind === "home" ? "Сотрудники" : route.kind === "standards" ? "Стандарты" : "Анализы"}
              </div>
              <div className="text-xs text-neutral-500 leading-tight mt-0.5">
                {route.kind === "home" ? "Последние результаты и системные проблемы" :
                 route.kind === "standards" ? "Чек-листы и критерии оценки" :
                 "История запущенных анализов"}
              </div>
            </div>
          )}
          <div className="ml-auto">
            <NotificationBell navigate={navigate} />
          </div>
        </div>

        <main className="px-6 py-8 max-w-4xl">
          {loading && (
            <div className="flex items-center justify-center py-20">
              <Loader2 size={24} className="animate-spin text-neutral-600" />
            </div>
          )}
          {!loading && error && (
            <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-8 text-center">
              <p className="text-red-400 font-semibold mb-1">Не удалось загрузить данные</p>
              <p className="text-sm text-neutral-500">{error}</p>
            </div>
          )}
          {!loading && !error && (
            <>
              {route.kind === "home" && <HomeView me={me} navigate={navigate} />}
              {route.kind === "analyses" && <AnalysesView me={me} navigate={navigate} />}
              {route.kind === "report" && report && <ReportView report={report} navigate={navigate} />}
              {route.kind === "chronology" && chronology && <ChronologyView chronology={chronology} navigate={navigate} />}
              {route.kind === "employee" && operator && <EmployeeView operator={operator} navigate={navigate} focus={route.focus} />}
              {route.kind === "standards" && <StandardsView navigate={navigate} />}
              {route.kind === "standard" && <StandardDetailView id={route.id} navigate={navigate} />}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
