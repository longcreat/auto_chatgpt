import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Trash2, Zap } from 'lucide-react'
import { deleteAccount, fetchAccountToken, getAccounts, switchAccount } from '../api'

function Badge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: 'bg-green-900/50 text-green-400',
    pending: 'bg-yellow-900/50 text-yellow-400',
    suspended: 'bg-orange-900/50 text-orange-400',
    banned: 'bg-red-900/50 text-red-400',
  }
  return <span className={`text-xs px-2 py-0.5 rounded-full ${map[status] ?? 'bg-gray-800 text-gray-400'}`}>{status}</span>
}

export default function Accounts() {
  const qc = useQueryClient()

  const { data: accounts = [], isLoading } = useQuery({ queryKey: ['accounts'], queryFn: getAccounts })

  const switchMut = useMutation({
    mutationFn: switchAccount,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['accounts'] })
      qc.invalidateQueries({ queryKey: ['codex-status'] })
    },
  })
  const deleteMut = useMutation({
    mutationFn: deleteAccount,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['accounts'] })
      qc.invalidateQueries({ queryKey: ['codex-status'] })
    },
  })
  const fetchTokenMut = useMutation({
    mutationFn: fetchAccountToken,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['accounts'] })
      qc.invalidateQueries({ queryKey: ['tokens'] })
      qc.invalidateQueries({ queryKey: ['codex-status'] })
    },
  })

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">账号管理</h2>
        <p className="text-xs text-gray-500">注册新账号请前往「域名邮箱 → 批量注册」</p>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800 bg-gray-800/30">
              <th className="text-left px-4 py-2.5">邮箱</th>
              <th className="text-left px-4 py-2.5">状态</th>
              <th className="text-left px-4 py-2.5">API 凭证</th>
              <th className="text-left px-4 py-2.5">激活</th>
              <th className="text-left px-4 py-2.5">操作</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={5} className="text-center py-10 text-gray-600">加载中...</td></tr>
            )}
            {accounts.map((account: any) => (
              <tr key={account.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="px-4 py-3 font-mono text-xs">
                  <div>{account.email}</div>
                  {account.cf_email_alias && <div className="text-gray-500 text-xs mt-0.5">{account.cf_email_alias}</div>}
                </td>
                <td className="px-4 py-3"><Badge status={account.status} /></td>
                <td className="px-4 py-3 font-mono text-xs text-gray-400">
                  {account.has_access_token
                    ? <span className="text-green-400">Token ✓</span>
                    : account.has_api_key ? account.api_key_preview ?? '已配置' : '—'}
                </td>
                <td className="px-4 py-3">
                  {account.is_active
                    ? <span className="text-xs text-green-400 font-medium">● 当前</span>
                    : (
                      <button
                        onClick={() => switchMut.mutate(account.id)}
                        className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        切换
                      </button>
                    )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => switchMut.mutate(account.id)}
                      title="设为激活"
                      className="text-gray-500 hover:text-green-400 transition-colors"
                    >
                      <Zap size={14} />
                    </button>
                    {!account.has_access_token && (
                      <button
                        onClick={() => fetchTokenMut.mutate(account.id)}
                        disabled={fetchTokenMut.isPending}
                        title="获取 Token"
                        className="text-gray-500 hover:text-blue-400 transition-colors disabled:opacity-50 disabled:cursor-wait"
                      >
                        <KeyRound size={14} />
                      </button>
                    )}
                    <button
                      onClick={() => { if (confirm('确认删除？')) deleteMut.mutate(account.id) }}
                      title="删除账号"
                      className="text-gray-500 hover:text-red-400 transition-colors"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!isLoading && accounts.length === 0 && (
              <tr><td colSpan={5} className="text-center py-10 text-gray-600">暂无账号，请前往「域名邮箱」注册</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
