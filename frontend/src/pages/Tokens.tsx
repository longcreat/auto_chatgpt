import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ChevronDown, ChevronUp, KeyRound, Plus, Trash2 } from 'lucide-react'
import { createToken, deleteToken, fetchAccountToken, getAccounts, getTokens, invalidateExpiredTokens } from '../api'

const TOKEN_TYPES = ['access_token', 'refresh_token', 'api_key', 'session_token']

/** 每种 token 对应的样式 */
const TOKEN_COLORS: Record<string, string> = {
  access_token:  'bg-blue-900/50 text-blue-300',
  refresh_token: 'bg-purple-900/50 text-purple-300',
  session_token: 'bg-cyan-900/50 text-cyan-300',
  api_key:       'bg-amber-900/50 text-amber-300',
}

function hasValidToken(tokens: any[], type: string) {
  return tokens.some((t: any) => t.token_type === type && t.is_valid)
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${ok ? 'bg-green-900/40 text-green-400' : 'bg-gray-800 text-gray-600'}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-green-400' : 'bg-gray-600'}`} />
      {label}
    </span>
  )
}

export default function Tokens() {
  const qc = useQueryClient()
  const [expandedAccount, setExpandedAccount] = useState<number | null>(null)
  const [addingFor, setAddingFor] = useState<number | null>(null)
  const [form, setForm] = useState({ token_type: 'access_token', token_value: '', expires_at: '' })
  const [showGlobalAdd, setShowGlobalAdd] = useState(false)
  const [globalForm, setGlobalForm] = useState({ account_id: 0, token_type: 'access_token', token_value: '', expires_at: '' })

  const { data: accounts = [], isLoading } = useQuery({ queryKey: ['accounts'], queryFn: getAccounts })
  const { data: allTokens = [] } = useQuery({ queryKey: ['tokens'], queryFn: () => getTokens() })

  const invalidateMut = useMutation({
    mutationFn: invalidateExpiredTokens,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tokens'] }); qc.invalidateQueries({ queryKey: ['accounts'] }) },
  })
  const deleteMut = useMutation({
    mutationFn: deleteToken,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tokens'] })
      qc.invalidateQueries({ queryKey: ['accounts'] })
      qc.invalidateQueries({ queryKey: ['codex-status'] })
    },
  })
  const createMut = useMutation({
    mutationFn: createToken,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tokens'] })
      qc.invalidateQueries({ queryKey: ['accounts'] })
      qc.invalidateQueries({ queryKey: ['codex-status'] })
      setAddingFor(null)
      setShowGlobalAdd(false)
      setForm({ token_type: 'access_token', token_value: '', expires_at: '' })
      setGlobalForm({ account_id: 0, token_type: 'access_token', token_value: '', expires_at: '' })
    },
  })
  const fetchTokenMut = useMutation({
    mutationFn: fetchAccountToken,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tokens'] })
      qc.invalidateQueries({ queryKey: ['accounts'] })
      qc.invalidateQueries({ queryKey: ['codex-status'] })
    },
  })

  const accountTokens = (accountId: number) =>
    (allTokens as any[])
      .filter((t: any) => t.account_id === accountId)
      .sort((a: any, b: any) => {
        const order = ['access_token', 'refresh_token', 'session_token', 'api_key']
        return order.indexOf(a.token_type) - order.indexOf(b.token_type)
      })

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Token 管理</h2>
        <div className="flex gap-2">
          <button
            onClick={() => invalidateMut.mutate()}
            disabled={invalidateMut.isPending}
            className="flex items-center gap-2 border border-gray-700 hover:bg-gray-800 px-3 py-2 rounded-lg text-sm transition-colors text-gray-400 disabled:opacity-50"
          >
            <AlertTriangle size={14} /> 清理过期
          </button>
          <button
            onClick={() => setShowGlobalAdd(!showGlobalAdd)}
            className="flex items-center gap-2 bg-green-700 hover:bg-green-600 text-white px-4 py-2 rounded-lg text-sm transition-colors"
          >
            <Plus size={16} /> 添加 Token
          </button>
        </div>
      </div>

      {/* 提示 */}
      <div className="mb-5 rounded-xl border border-blue-900/50 bg-blue-950/30 px-4 py-3 text-xs text-blue-200 space-y-1">
        <p>Codex 代理仅使用激活账号的 <span className="font-mono">api_key</span> 或 <span className="font-mono">access_token</span>。</p>
        <p className="text-blue-300/50">注：当前注册流程走 Codex OAuth，不经过 chatgpt.com，故不产生 <span className="font-mono">session_token</span>，这是正常现象，不影响 Codex 使用。</p>
      </div>

      {/* 全局添加 Token 面板 */}
      {showGlobalAdd && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
          <h3 className="font-medium mb-4 text-sm">添加 Token</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">关联账号</label>
              <select
                value={globalForm.account_id}
                onChange={e => setGlobalForm({ ...globalForm, account_id: Number(e.target.value) })}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-500"
              >
                <option value={0}>选择账号</option>
                {(accounts as any[]).map((a: any) => <option key={a.id} value={a.id}>{a.email}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Token 类型</label>
              <select
                value={globalForm.token_type}
                onChange={e => setGlobalForm({ ...globalForm, token_type: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-500"
              >
                {TOKEN_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-gray-400 mb-1">Token 值</label>
              <textarea rows={3} value={globalForm.token_value}
                onChange={e => setGlobalForm({ ...globalForm, token_value: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-500 resize-none"
                placeholder="粘贴 token 值..."
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">过期时间（可选）</label>
              <input type="datetime-local" value={globalForm.expires_at}
                onChange={e => setGlobalForm({ ...globalForm, expires_at: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-500"
              />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button
              onClick={() => createMut.mutate({ ...globalForm, expires_at: globalForm.expires_at || undefined })}
              disabled={!globalForm.account_id || !globalForm.token_value || createMut.isPending}
              className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm transition-colors"
            >
              {createMut.isPending ? '保存中...' : '保存'}
            </button>
            <button onClick={() => setShowGlobalAdd(false)}
              className="border border-gray-700 px-4 py-2 rounded-lg text-sm text-gray-400 hover:bg-gray-800 transition-colors"
            >取消</button>
          </div>
        </div>
      )}

      {/* 主表格：以账号为行 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800 bg-gray-800/30">
              <th className="text-left px-4 py-2.5 w-8" />
              <th className="text-left px-4 py-2.5">邮箱</th>
              <th className="text-left px-4 py-2.5">access_token</th>
              <th className="text-left px-4 py-2.5">refresh_token</th>
              <th className="text-left px-4 py-2.5">session_token</th>
              <th className="text-left px-4 py-2.5">api_key</th>
              <th className="text-left px-4 py-2.5">有效/总计</th>
              <th className="text-left px-4 py-2.5">操作</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={8} className="text-center py-10 text-gray-600">加载中...</td></tr>
            )}
            {(accounts as any[]).map((account: any) => {
              const tokens = accountTokens(account.id)
              const isExpanded = expandedAccount === account.id
              const isAddingHere = addingFor === account.id

              return (
                <Fragment key={account.id}>
                  {/* 账号汇总行 */}
                  <tr className={`border-b border-gray-800/50 transition-colors cursor-pointer ${isExpanded ? 'bg-gray-800/40' : 'hover:bg-gray-800/20'}`}
                    onClick={() => setExpandedAccount(isExpanded ? null : account.id)}
                  >
                    <td className="px-4 py-3 text-center text-gray-500">
                      {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs text-gray-200">{account.email}</div>
                      {account.is_active && <div className="text-xs text-green-400 mt-0.5">● 当前激活</div>}
                    </td>
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      <StatusDot ok={hasValidToken(tokens, 'access_token')} label="access" />
                    </td>
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      <StatusDot ok={hasValidToken(tokens, 'refresh_token')} label="refresh" />
                    </td>
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      <StatusDot ok={hasValidToken(tokens, 'session_token')} label="session" />
                    </td>
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      <StatusDot ok={hasValidToken(tokens, 'api_key')} label="api_key" />
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500" onClick={e => e.stopPropagation()}>
                      {tokens.filter((t: any) => t.is_valid).length} / {tokens.length}
                    </td>
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      <div className="flex items-center gap-2">
                        {!hasValidToken(tokens, 'access_token') && (
                          <button
                            onClick={() => fetchTokenMut.mutate(account.id)}
                            disabled={fetchTokenMut.isPending}
                            title="自动获取 OAuth Token"
                            className="text-gray-500 hover:text-blue-400 transition-colors disabled:opacity-50 disabled:cursor-wait"
                          >
                            <KeyRound size={14} />
                          </button>
                        )}
                        <button
                          onClick={() => {
                            setAddingFor(isAddingHere ? null : account.id)
                            setExpandedAccount(account.id)
                            setForm({ token_type: 'access_token', token_value: '', expires_at: '' })
                          }}
                          title="手动添加 Token"
                          className="text-gray-500 hover:text-green-400 transition-colors"
                        >
                          <Plus size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>

                  {/* 展开：手动添加表单 */}
                  {isExpanded && isAddingHere && (
                    <tr className="border-b border-gray-800/30 bg-gray-900/80">
                      <td colSpan={8} className="px-6 py-4">
                        <div className="bg-gray-800/60 rounded-xl p-4">
                          <p className="text-xs text-gray-400 mb-3 font-medium">
                            为 <span className="text-green-400 font-mono">{account.email}</span> 添加 Token
                          </p>
                          <div className="grid grid-cols-3 gap-3 mb-2">
                            <div>
                              <label className="block text-xs text-gray-500 mb-1">类型</label>
                              <select value={form.token_type} onChange={e => setForm({ ...form, token_type: e.target.value })}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:border-green-500"
                              >
                                {TOKEN_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                              </select>
                            </div>
                            <div>
                              <label className="block text-xs text-gray-500 mb-1">过期时间（可选）</label>
                              <input type="datetime-local" value={form.expires_at}
                                onChange={e => setForm({ ...form, expires_at: e.target.value })}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:border-green-500"
                              />
                            </div>
                            <div className="flex items-end gap-2">
                              <button
                                onClick={() => createMut.mutate({ account_id: account.id, ...form, expires_at: form.expires_at || undefined })}
                                disabled={!form.token_value || createMut.isPending}
                                className="bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg text-xs transition-colors"
                              >{createMut.isPending ? '保存...' : '保存'}</button>
                              <button onClick={() => setAddingFor(null)}
                                className="border border-gray-700 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:bg-gray-800 transition-colors"
                              >取消</button>
                            </div>
                          </div>
                          <div>
                            <label className="block text-xs text-gray-500 mb-1">Token 值</label>
                            <textarea rows={2} value={form.token_value}
                              onChange={e => setForm({ ...form, token_value: e.target.value })}
                              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:border-green-500 resize-none"
                              placeholder="粘贴 token 值..."
                            />
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}

                  {/* 展开：Token 明细表 */}
                  {isExpanded && tokens.length > 0 && (
                    <tr className="border-b border-gray-800/50">
                      <td colSpan={8} className="px-6 pb-4 pt-1">
                        <div className="rounded-xl border border-gray-800 overflow-hidden">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-gray-600 border-b border-gray-800 bg-gray-800/20">
                                <th className="text-left px-3 py-2">类型</th>
                                <th className="text-left px-3 py-2">Token 预览</th>
                                <th className="text-left px-3 py-2">状态</th>
                                <th className="text-left px-3 py-2">过期时间</th>
                                <th className="text-left px-3 py-2">创建时间</th>
                                <th className="text-left px-3 py-2">操作</th>
                              </tr>
                            </thead>
                            <tbody>
                              {tokens.map((token: any) => (
                                <tr key={token.id} className="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors">
                                  <td className="px-3 py-2">
                                    <span className={`px-2 py-0.5 rounded font-mono ${TOKEN_COLORS[token.token_type] ?? 'bg-gray-800 text-gray-300'}`}>
                                      {token.token_type}
                                    </span>
                                  </td>
                                  <td className="px-3 py-2 font-mono text-gray-400 max-w-xs truncate">
                                    {token.token_preview ?? '—'}
                                  </td>
                                  <td className="px-3 py-2">
                                    <span className={`px-2 py-0.5 rounded-full ${token.is_valid ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
                                      {token.is_valid ? '有效' : '失效'}
                                    </span>
                                  </td>
                                  <td className="px-3 py-2 text-gray-500">
                                    {token.expires_at ? new Date(token.expires_at).toLocaleString('zh-CN') : '永不过期'}
                                  </td>
                                  <td className="px-3 py-2 text-gray-600">
                                    {new Date(token.created_at).toLocaleString('zh-CN')}
                                  </td>
                                  <td className="px-3 py-2">
                                    <button
                                      onClick={() => { if (confirm('确认删除此 Token？')) deleteMut.mutate(token.id) }}
                                      className="text-gray-600 hover:text-red-400 transition-colors"
                                    >
                                      <Trash2 size={12} />
                                    </button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}

                  {/* 展开但无 token */}
                  {isExpanded && tokens.length === 0 && !isAddingHere && (
                    <tr className="border-b border-gray-800/30">
                      <td colSpan={8} className="text-center py-4 text-gray-600 text-xs">
                        此账号暂无 Token — 点击 <KeyRound size={11} className="inline mx-1" /> 自动获取或 <Plus size={11} className="inline mx-1" /> 手动添加
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {!isLoading && (accounts as any[]).length === 0 && (
              <tr><td colSpan={8} className="text-center py-10 text-gray-600">暂无账号</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
