import { Fragment, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown, ChevronUp, Globe, Loader2, Mail, Plus, RefreshCw,
  Save, Server, Shield, Trash2, CheckCircle, XCircle, UserPlus, Settings, RotateCcw,
} from 'lucide-react'
import {
  getAliases, generateAliases, createCustomAlias, deleteAlias, verifyCFConfig,
  getSettings, updateSettings, testImap, testProxy,
  autoRegister, getRegistrationTasks, retryRegistrationTask,
} from '../api'

/* ─── 标签页类型 ─── */
type Tab = 'config' | 'emails' | 'register' | 'tasks'

/* ─── 小组件 ─── */
function TaskBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    queued: 'bg-gray-800 text-gray-400',
    running: 'bg-blue-900/50 text-blue-400 animate-pulse',
    done: 'bg-green-900/50 text-green-400',
    failed: 'bg-red-900/50 text-red-400',
  }
  return <span className={`text-xs px-2 py-0.5 rounded-full ${map[status] ?? 'bg-gray-800 text-gray-400'}`}>{status}</span>
}

export default function Domains() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('config')

  /* ═══ 系统配置 ═══ */
  const { data: cfg, isLoading: cfgLoading } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const [form, setForm] = useState<any>(null)
  const [testResult, setTestResult] = useState<{ type: string; msg: string; ok: boolean } | null>(null)

  // 初始化表单
  if (cfg && !form) setForm({ ...cfg })

  const saveMut = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['cf-verify'] })
      setTestResult({ type: 'save', msg: '配置已保存', ok: true })
    },
  })
  const testImapMut = useMutation({
    mutationFn: testImap,
    onSuccess: (r: any) => setTestResult({ type: 'imap', msg: r.message, ok: r.success }),
  })
  const testProxyMut = useMutation({
    mutationFn: testProxy,
    onSuccess: (r: any) => setTestResult({ type: 'proxy', msg: r.message, ok: r.success }),
  })

  /* ═══ 邮箱管理 ═══ */
  const [genCount, setGenCount] = useState(5)
  const [customAlias, setCustomAlias] = useState('')
  const { data: aliases = [], isLoading: aliasLoading } = useQuery({ queryKey: ['aliases'], queryFn: getAliases })
  const { data: cfStatus } = useQuery({ queryKey: ['cf-verify'], queryFn: verifyCFConfig })

  const genMut = useMutation({
    mutationFn: () => generateAliases(genCount),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['aliases'] }),
  })
  const customMut = useMutation({
    mutationFn: () => createCustomAlias(customAlias),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['aliases'] }); setCustomAlias('') },
  })
  const delMut = useMutation({
    mutationFn: deleteAlias,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['aliases'] }),
  })

  /* ═══ 批量注册 ═══ */
  const [regMode, setRegMode] = useState<'batch' | 'select'>('batch')
  const [regCount, setRegCount] = useState(1)
  const [selectedAliases, setSelectedAliases] = useState<number[]>([])
  const [regError, setRegError] = useState('')
  const [taskError, setTaskError] = useState('')
  const [expandedTasks, setExpandedTasks] = useState<number[]>([])

  const { data: tasks = [] } = useQuery({
    queryKey: ['tasks'],
    queryFn: getRegistrationTasks,
    refetchInterval: tab === 'tasks' ? 1000 : false,
  })

  const registerMut = useMutation({
    mutationFn: autoRegister,
    onSuccess: (createdTasks: any[]) => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      setRegError('')
      setTaskError('')
      setSelectedAliases([])
      setExpandedTasks(prev => Array.from(new Set([...prev, ...createdTasks.map((task: any) => task.id)])))
      setTab('tasks')
    },
    onError: (e: any) => setRegError(e?.response?.data?.detail ?? e?.message ?? '请求失败'),
  })
  const retryMut = useMutation({
    mutationFn: retryRegistrationTask,
    onSuccess: (task: any) => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      setTaskError('')
      setExpandedTasks(prev => Array.from(new Set([...prev, task.id])))
      setTab('tasks')
    },
    onError: (e: any) => setTaskError(e?.response?.data?.detail ?? e?.message ?? '重试失败'),
  })

  const usedCount = aliases.filter((a: any) => a.is_used).length
  const availableAliases = aliases.filter((a: any) => !a.is_used)
  const toggleTask = (taskId: number) => {
    setExpandedTasks(prev => (
      prev.includes(taskId) ? prev.filter(id => id !== taskId) : [...prev, taskId]
    ))
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">域名邮箱管理</h2>
      </div>

      {/* 标签页 */}
      <div className="flex gap-1 mb-6 border-b border-gray-800">
        {([
          { key: 'config' as Tab, label: '系统配置', icon: Settings },
          { key: 'emails' as Tab, label: '邮箱管理', icon: Mail },
          { key: 'register' as Tab, label: '批量注册', icon: UserPlus },
          { key: 'tasks' as Tab, label: '注册任务', icon: Loader2 },
        ]).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 transition-colors ${
              tab === key ? 'border-green-500 text-green-400' : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {/* ═══════════════════════════ 系统配置 ═══════════════════════════ */}
      {tab === 'config' && (
        <div className="space-y-6">
          {cfgLoading || !form ? (
            <div className="text-center py-10 text-gray-600">加载中...</div>
          ) : (
            <>
              {/* 域名配置 */}
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Globe size={16} className="text-cyan-400" />
                  <h3 className="font-medium text-sm">域名配置</h3>
                </div>
                <div className="grid grid-cols-1 gap-4">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">域名 (Cloudflare catch-all 转发)</label>
                    <input
                      value={form.domain_name}
                      onChange={e => setForm({ ...form, domain_name: e.target.value })}
                      placeholder="example.com"
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                    <p className="text-xs text-gray-600 mt-1">Cloudflare Email Routing 配置 catch-all 规则后，所有 *@domain 的邮件会转发到收件邮箱</p>
                  </div>
                </div>
              </div>

              {/* IMAP 配置 */}
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Mail size={16} className="text-blue-400" />
                  <h3 className="font-medium text-sm">收件邮箱 (IMAP)</h3>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">IMAP 服务器</label>
                    <input
                      value={form.imap_host}
                      onChange={e => setForm({ ...form, imap_host: e.target.value })}
                      placeholder="imap.163.com"
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">端口</label>
                    <input
                      type="number"
                      value={form.imap_port}
                      onChange={e => setForm({ ...form, imap_port: Number(e.target.value) })}
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">邮箱账号</label>
                    <input
                      value={form.imap_user}
                      onChange={e => setForm({ ...form, imap_user: e.target.value })}
                      placeholder="user@163.com"
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">密码 / 授权码</label>
                    <input
                      type="password"
                      value={form.imap_password}
                      onChange={e => setForm({ ...form, imap_password: e.target.value })}
                      placeholder="IMAP 授权码"
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                  </div>
                </div>
                <button
                  onClick={() => testImapMut.mutate(form)}
                  disabled={testImapMut.isPending}
                  className="mt-3 flex items-center gap-2 border border-gray-700 hover:bg-gray-800 px-3 py-1.5 rounded-lg text-xs transition-colors text-gray-400 disabled:opacity-50"
                >
                  {testImapMut.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                  测试连接
                </button>
              </div>

              {/* 代理配置 */}
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Shield size={16} className="text-amber-400" />
                  <h3 className="font-medium text-sm">代理配置 (可选)</h3>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">代理地址</label>
                    <input
                      value={form.proxy_host}
                      onChange={e => setForm({ ...form, proxy_host: e.target.value })}
                      placeholder="127.0.0.1"
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">端口</label>
                    <input
                      type="number"
                      value={form.proxy_port}
                      onChange={e => setForm({ ...form, proxy_port: Number(e.target.value) })}
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">用户名 (可选)</label>
                    <input
                      value={form.proxy_user}
                      onChange={e => setForm({ ...form, proxy_user: e.target.value })}
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">密码 (可选)</label>
                    <input
                      type="password"
                      value={form.proxy_pass}
                      onChange={e => setForm({ ...form, proxy_pass: e.target.value })}
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                    />
                  </div>
                </div>
                <button
                  onClick={() => testProxyMut.mutate(form)}
                  disabled={testProxyMut.isPending}
                  className="mt-3 flex items-center gap-2 border border-gray-700 hover:bg-gray-800 px-3 py-1.5 rounded-lg text-xs transition-colors text-gray-400 disabled:opacity-50"
                >
                  {testProxyMut.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                  测试代理
                </button>
              </div>

              {/* 测试结果 */}
              {testResult && (
                <div className={`rounded-xl border px-4 py-3 text-sm flex items-center gap-2 ${
                  testResult.ok ? 'bg-green-900/20 border-green-800 text-green-300' : 'bg-red-900/20 border-red-800 text-red-300'
                }`}>
                  {testResult.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
                  {testResult.msg}
                </div>
              )}

              {/* 保存 */}
              <button
                onClick={() => saveMut.mutate(form)}
                disabled={saveMut.isPending}
                className="flex items-center gap-2 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white px-5 py-2.5 rounded-lg text-sm transition-colors"
              >
                {saveMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                保存配置
              </button>
            </>
          )}
        </div>
      )}

      {/* ═══════════════════════════ 邮箱管理 ═══════════════════════════ */}
      {tab === 'emails' && (
        <div className="space-y-5">
          {/* 配置状态 */}
          {cfStatus && (
            <div className={`p-4 rounded-xl border text-sm ${cfStatus.ok ? 'bg-green-900/20 border-green-800' : 'bg-yellow-900/20 border-yellow-800'}`}>
              <div className="flex items-center gap-2 font-medium mb-1">
                {cfStatus.ok
                  ? <><CheckCircle size={14} className="text-green-400" /> 域名配置正常</>
                  : <><XCircle size={14} className="text-yellow-400" /> 请先在「系统配置」中配置域名和 IMAP</>
                }
              </div>
              {cfStatus.ok && (
                <div className="text-xs text-gray-400 flex gap-4">
                  <span>域名: <span className="font-mono text-gray-300">{cfStatus.domain}</span></span>
                  <span>转发到: <span className="font-mono text-gray-300">{cfStatus.forward_to}</span></span>
                </div>
              )}
            </div>
          )}

          {/* 统计 + 生成 */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <p className="text-2xl font-bold">{aliases.length}</p>
              <p className="text-sm text-gray-400">总邮箱数</p>
              <p className="text-xs text-gray-600 mt-1">已用 {usedCount} | 可用 {aliases.length - usedCount}</p>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <p className="text-sm text-gray-400 mb-3">批量生成随机邮箱</p>
              <div className="flex gap-2">
                <input
                  type="number" min={1} max={50} value={genCount}
                  onChange={e => setGenCount(Number(e.target.value))}
                  className="w-20 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-500"
                />
                <button
                  onClick={() => genMut.mutate()}
                  disabled={genMut.isPending}
                  className="flex items-center gap-2 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm transition-colors"
                >
                  {genMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                  生成
                </button>
              </div>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <p className="text-sm text-gray-400 mb-3">自定义邮箱</p>
              <div className="flex gap-2">
                <input
                  value={customAlias}
                  onChange={e => setCustomAlias(e.target.value)}
                  placeholder={`前缀 或 user@${cfg?.domain_name || 'domain'}`}
                  className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500"
                />
                <button
                  onClick={() => customMut.mutate()}
                  disabled={customMut.isPending || !customAlias.trim()}
                  className="flex items-center gap-2 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm transition-colors"
                >
                  <Plus size={14} /> 添加
                </button>
              </div>
            </div>
          </div>

          {/* 邮箱列表 */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800 bg-gray-800/30">
                  <th className="text-left px-4 py-2.5">邮箱别名</th>
                  <th className="text-left px-4 py-2.5">转发到</th>
                  <th className="text-left px-4 py-2.5">状态</th>
                  <th className="text-left px-4 py-2.5">创建时间</th>
                  <th className="text-left px-4 py-2.5">操作</th>
                </tr>
              </thead>
              <tbody>
                {aliasLoading && <tr><td colSpan={5} className="text-center py-8 text-gray-600">加载中...</td></tr>}
                {aliases.map((a: any) => (
                  <tr key={a.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs">{a.alias}</td>
                    <td className="px-4 py-3 text-xs text-gray-400">{a.forward_to}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${a.is_used ? 'bg-blue-900/50 text-blue-400' : 'bg-gray-800 text-gray-400'}`}>
                        {a.is_used ? '已使用' : '可用'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {new Date(a.created_at).toLocaleString('zh-CN')}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => { if (confirm('删除此别名记录？')) delMut.mutate(a.id) }}
                        className="text-gray-500 hover:text-red-400 transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
                {!aliasLoading && aliases.length === 0 && (
                  <tr><td colSpan={5} className="text-center py-10 text-gray-600">暂无邮箱，点击「生成」或「添加」创建</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ═══════════════════════════ 批量注册 ═══════════════════════════ */}
      {tab === 'register' && (
        <div className="max-w-2xl space-y-5">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="font-medium mb-5 text-gray-200">批量注册 ChatGPT 账号</h3>

            {/* 模式选择 */}
            <div className="flex gap-2 mb-5">
              <button
                onClick={() => setRegMode('batch')}
                className={`flex-1 py-2 rounded-lg text-sm transition-colors border ${
                  regMode === 'batch'
                    ? 'bg-green-900/40 border-green-700 text-green-400'
                    : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200'
                }`}
              >
                自动生成邮箱
              </button>
              <button
                onClick={() => setRegMode('select')}
                className={`flex-1 py-2 rounded-lg text-sm transition-colors border ${
                  regMode === 'select'
                    ? 'bg-green-900/40 border-green-700 text-green-400'
                    : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200'
                }`}
              >
                选择已有邮箱
              </button>
            </div>

            {regMode === 'batch' ? (
              <div className="mb-5">
                <label className="block text-xs text-gray-400 mb-1.5">注册数量</label>
                <input
                  type="number" min={1} max={20} value={regCount}
                  onChange={e => setRegCount(Math.max(1, Math.min(20, Number(e.target.value))))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-600"
                />
                <p className="text-xs text-gray-500 mt-1">
                  自动生成 {regCount} 个 <span className="font-mono text-gray-400">*@{cfg?.domain_name || '未配置域名'}</span> 邮箱并注册
                </p>
              </div>
            ) : (
              <div className="mb-5">
                <label className="block text-xs text-gray-400 mb-2">选择可用邮箱（可多选）</label>
                {availableAliases.length === 0 ? (
                  <div className="text-xs text-gray-500 bg-gray-800 rounded-lg px-4 py-6 text-center">
                    暂无可用邮箱，请先在「邮箱管理」中生成
                  </div>
                ) : (
                  <div className="max-h-48 overflow-y-auto bg-gray-800 rounded-lg border border-gray-700 divide-y divide-gray-700/50">
                    {availableAliases.map((a: any) => (
                      <label key={a.id} className="flex items-center gap-3 px-3 py-2 hover:bg-gray-700/30 cursor-pointer transition-colors">
                        <input
                          type="checkbox"
                          checked={selectedAliases.includes(a.id)}
                          onChange={e => {
                            if (e.target.checked) setSelectedAliases([...selectedAliases, a.id])
                            else setSelectedAliases(selectedAliases.filter(id => id !== a.id))
                          }}
                          className="rounded border-gray-600 bg-gray-900 text-green-500 focus:ring-green-500"
                        />
                        <span className="font-mono text-xs text-gray-300">{a.alias}</span>
                      </label>
                    ))}
                  </div>
                )}
                {selectedAliases.length > 0 && (
                  <p className="text-xs text-green-400 mt-2">已选 {selectedAliases.length} 个邮箱</p>
                )}
              </div>
            )}

            {regError && (
              <div className="mb-4 text-xs text-red-400 bg-red-900/20 border border-red-800/50 rounded-lg px-3 py-2">
                {regError}
              </div>
            )}

            <button
              disabled={
                registerMut.isPending ||
                (regMode === 'select' && selectedAliases.length === 0)
              }
              onClick={() => {
                setRegError('')
                if (regMode === 'batch') {
                  registerMut.mutate({ use_domain_email: true, count: regCount })
                } else {
                  const emails = selectedAliases.map(id => {
                    const a = aliases.find((x: any) => x.id === id)
                    return a?.alias
                  }).filter(Boolean)
                  registerMut.mutate({ emails, use_domain_email: false, count: emails.length })
                }
              }}
              className="w-full bg-green-700 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed text-white py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
            >
              {registerMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
              {registerMut.isPending ? '注册中...' : '开始注册'}
            </button>
          </div>

          <div className="bg-gray-900/60 border border-gray-800 rounded-xl px-4 py-3 text-xs text-gray-500 space-y-1">
            <p>• 注册前请确保在「系统配置」中已正确配置域名、IMAP 和代理</p>
            <p>• 注册任务在后台异步执行，提交后自动跳转到「注册任务」标签查看进度</p>
            <p>• 注册完成后，系统会自动获取 OAuth Token</p>
          </div>
        </div>
      )}

      {/* ═══════════════════════════ 注册任务 ═══════════════════════════ */}
      {tab === 'tasks' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          {taskError && (
            <div className="mx-4 mt-4 rounded-lg border border-red-800/50 bg-red-900/20 px-3 py-2 text-xs text-red-400">
              {taskError}
            </div>
          )}
          <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="text-gray-500 text-xs border-b border-gray-800 bg-gray-800/30">
                <th className="text-left px-4 py-2.5">ID</th>
                <th className="text-left px-4 py-2.5">邮箱</th>
                <th className="text-left px-4 py-2.5">状态</th>
                <th className="text-left px-4 py-2.5">创建时间</th>
                <th className="text-left px-4 py-2.5">日志</th>
                <th className="text-left px-4 py-2.5">操作</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task: any) => (
                <Fragment key={task.id}>
                  <tr className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                    <td className="px-4 py-3 text-gray-500">#{task.id}</td>
                    <td className="px-4 py-3 font-mono text-xs">{task.email}</td>
                    <td className="px-4 py-3"><TaskBadge status={task.status} /></td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {new Date(task.created_at).toLocaleString('zh-CN')}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => toggleTask(task.id)}
                        className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
                      >
                        {expandedTasks.includes(task.id) ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                        {expandedTasks.includes(task.id) ? '收起' : '查看'}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      {task.status === 'failed' && (
                        <button
                          onClick={() => retryMut.mutate(task.id)}
                          disabled={retryMut.isPending}
                          className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 disabled:opacity-50"
                        >
                          {retryMut.isPending ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                          重试
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedTasks.includes(task.id) && (
                    <tr className="border-b border-gray-800/50">
                      <td colSpan={6} className="px-4 py-3 max-w-0">
                        <pre className="w-full overflow-x-auto break-all bg-gray-950 rounded p-3 text-xs text-gray-400 font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
                          {task.log || '等待日志输出...'}
                        </pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {tasks.length === 0 && (
                <tr><td colSpan={6} className="text-center py-10 text-gray-600">暂无注册任务</td></tr>
              )}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  )
}
