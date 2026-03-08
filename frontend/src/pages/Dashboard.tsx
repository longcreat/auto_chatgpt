import { useQuery } from '@tanstack/react-query'
import { Users, KeyRound, Globe, Bot, CheckCircle, XCircle } from 'lucide-react'
import { getAccounts, getTokens, getAliases, getCodexStatus } from '../api'

function StatCard({ icon: Icon, label, value, color }: any) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex items-start gap-4">
      <div className={`p-2 rounded-lg ${color}`}>
        <Icon size={20} />
      </div>
      <div>
        <p className="text-2xl font-bold">{value ?? '—'}</p>
        <p className="text-sm text-gray-400 mt-0.5">{label}</p>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: 'bg-green-900/50 text-green-400',
    pending: 'bg-yellow-900/50 text-yellow-400',
    suspended: 'bg-orange-900/50 text-orange-400',
    banned: 'bg-red-900/50 text-red-400',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${map[status] ?? 'bg-gray-800 text-gray-400'}`}>
      {status}
    </span>
  )
}

export default function Dashboard() {
  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: getAccounts })
  const { data: tokens = [] } = useQuery({ queryKey: ['tokens'], queryFn: () => getTokens() })
  const { data: aliases = [] } = useQuery({ queryKey: ['aliases'], queryFn: getAliases })
  const { data: codex } = useQuery({ queryKey: ['codex-status'], queryFn: getCodexStatus, refetchInterval: 10000 })

  const activeCount = accounts.filter((a: any) => a.status === 'active').length
  const validTokens = tokens.filter((t: any) => t.is_valid).length

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h2 className="text-xl font-semibold mb-6">系统概览</h2>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={Users} label="账号总数" value={accounts.length} color="bg-blue-900/50 text-blue-400" />
        <StatCard icon={CheckCircle} label="活跃账号" value={activeCount} color="bg-green-900/50 text-green-400" />
        <StatCard icon={KeyRound} label="有效 Token" value={validTokens} color="bg-purple-900/50 text-purple-400" />
        <StatCard icon={Globe} label="邮箱别名" value={aliases.length} color="bg-cyan-900/50 text-cyan-400" />
      </div>

      {/* Codex 状态 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-8">
        <div className="flex items-center gap-2 mb-3">
          <Bot size={16} className="text-green-400" />
          <h3 className="font-medium">Codex 代理状态</h3>
          {codex?.token_valid ? (
            <span className="ml-auto flex items-center gap-1 text-xs text-green-400">
              <CheckCircle size={12} /> 正常运行
            </span>
          ) : (
            <span className="ml-auto flex items-center gap-1 text-xs text-red-400">
              <XCircle size={12} /> 未配置
            </span>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
          <div className="bg-gray-800/50 rounded-lg px-3 py-2">
            <p className="text-gray-400 text-xs mb-0.5">激活账号</p>
            <p className="font-mono truncate">{codex?.active_email ?? '未设置'}</p>
          </div>
          <div className="bg-gray-800/50 rounded-lg px-3 py-2">
            <p className="text-gray-400 text-xs mb-0.5">代理地址</p>
            <p className="font-mono text-green-400">{codex?.proxy_url ?? '—'}</p>
          </div>
          <div className="bg-gray-800/50 rounded-lg px-3 py-2">
            <p className="text-gray-400 text-xs mb-0.5">Codex 配置</p>
            <p className="font-mono text-xs text-yellow-400">
              OPENAI_API_BASE={codex?.proxy_url ?? 'http://127.0.0.1:8000/v1'}
            </p>
          </div>
        </div>
      </div>

      {/* 最近账号 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-800 flex items-center justify-between">
          <h3 className="font-medium">最近账号</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800">
              <th className="text-left px-5 py-2">邮箱</th>
              <th className="text-left px-5 py-2">状态</th>
              <th className="text-left px-5 py-2">激活</th>
              <th className="text-left px-5 py-2">创建时间</th>
            </tr>
          </thead>
          <tbody>
            {accounts.slice(0, 8).map((acc: any) => (
              <tr key={acc.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="px-5 py-2.5 font-mono text-xs">{acc.email}</td>
                <td className="px-5 py-2.5"><StatusBadge status={acc.status} /></td>
                <td className="px-5 py-2.5">
                  {acc.is_active && <span className="text-xs text-green-400">● 当前</span>}
                </td>
                <td className="px-5 py-2.5 text-gray-500 text-xs">
                  {new Date(acc.created_at).toLocaleString('zh-CN')}
                </td>
              </tr>
            ))}
            {accounts.length === 0 && (
              <tr>
                <td colSpan={4} className="px-5 py-8 text-center text-gray-600">暂无账号</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
