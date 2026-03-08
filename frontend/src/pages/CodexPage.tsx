import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAccounts, getCodexStatus, codexSwitch, codexReload } from '../api'
import { Bot, CheckCircle, XCircle, RefreshCw, Zap, Copy } from 'lucide-react'
import { useState } from 'react'

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button onClick={copy} className="text-gray-500 hover:text-gray-300 transition-colors">
      {copied ? <CheckCircle size={14} className="text-green-400" /> : <Copy size={14} />}
    </button>
  )
}

export default function CodexPage() {
  const qc = useQueryClient()
  const { data: status } = useQuery({
    queryKey: ['codex-status'],
    queryFn: getCodexStatus,
    refetchInterval: 5000,
  })
  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: getAccounts })

  const switchMut = useMutation({
    mutationFn: codexSwitch,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['codex-status'] })
      qc.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
  const reloadMut = useMutation({
    mutationFn: codexReload,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['codex-status'] }),
  })

  const proxyUrl = status?.proxy_url ?? 'http://127.0.0.1:8000/v1'

  const setupCommands = [
    { label: 'Linux / macOS', cmd: `export OPENAI_API_BASE="${proxyUrl}"` },
    { label: 'Windows CMD', cmd: `set OPENAI_API_BASE=${proxyUrl}` },
    { label: 'Windows PowerShell', cmd: `$env:OPENAI_API_BASE="${proxyUrl}"` },
    { label: 'Python', cmd: `import openai\nopenai.api_base = "${proxyUrl}"` },
  ]

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Bot size={20} className="text-green-400" />
        <h2 className="text-xl font-semibold">Codex 本地代理集成</h2>
        <button
          onClick={() => reloadMut.mutate()}
          title="重新加载"
          className="ml-auto text-gray-500 hover:text-gray-300 transition-colors"
        >
          <RefreshCw size={16} className={reloadMut.isPending ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* 当前状态 */}
      <div className={`rounded-xl border p-5 mb-6 ${status?.token_valid ? 'bg-green-900/10 border-green-800/60' : 'bg-red-900/10 border-red-800/60'}`}>
        <div className="flex items-center gap-2 mb-4">
          {status?.token_valid
            ? <CheckCircle size={16} className="text-green-400" />
            : <XCircle size={16} className="text-red-400" />
          }
          <span className="font-medium">
            {status?.token_valid ? '代理运行中' : '未配置激活账号'}
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
          <div className="bg-gray-900/60 rounded-lg px-4 py-3">
            <p className="text-xs text-gray-400 mb-1">激活账号</p>
            <p className="font-mono text-xs truncate">{status?.active_email ?? '未设置'}</p>
          </div>
          <div className="bg-gray-900/60 rounded-lg px-4 py-3">
            <p className="text-xs text-gray-400 mb-1">代理地址</p>
            <div className="flex items-center gap-2">
              <p className="font-mono text-xs text-green-400 truncate">{proxyUrl}</p>
              <CopyButton text={proxyUrl} />
            </div>
          </div>
          <div className="bg-gray-900/60 rounded-lg px-4 py-3">
            <p className="text-xs text-gray-400 mb-1">API Key</p>
            <p className="font-mono text-xs text-gray-400">
              {status?.api_key_preview ?? '未配置可用于 Codex 的 API 凭证'}
            </p>
          </div>
        </div>
      </div>

      {/* 切换账号 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
        <h3 className="font-medium mb-4 flex items-center gap-2">
          <Zap size={15} className="text-yellow-400" />
          切换激活账号
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {accounts.map((acc: any) => (
            <button
              key={acc.id}
              onClick={() => switchMut.mutate(acc.id)}
              disabled={switchMut.isPending}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg border text-sm transition-all ${
                acc.is_active
                  ? 'border-green-600 bg-green-900/20 text-green-300'
                  : 'border-gray-700 hover:border-gray-600 hover:bg-gray-800 text-gray-300'
              }`}
            >
              <div className="flex-1 text-left">
                <p className="font-mono text-xs truncate">{acc.email}</p>
                <p className={`text-xs mt-0.5 ${acc.status === 'active' ? 'text-green-500' : 'text-gray-500'}`}>
                  {acc.status} {acc.has_api_key ? '· API Key ✓' : '· 需添加 API key / access token'}
                </p>
              </div>
              {acc.is_active && <CheckCircle size={14} className="text-green-400 flex-shrink-0" />}
            </button>
          ))}
          {accounts.length === 0 && (
            <p className="col-span-2 text-gray-600 text-sm py-4 text-center">暂无账号，请先注册</p>
          )}
        </div>
      </div>

      {/* 配置命令 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="font-medium mb-4">Codex 环境配置</h3>
        <p className="text-xs text-gray-400 mb-4">
          将以下环境变量配置到你的终端或项目 .env 文件，Codex 将无感使用当前激活账号：
        </p>
        <div className="space-y-3">
          {setupCommands.map(({ label, cmd }) => (
            <div key={label} className="bg-gray-950 rounded-lg overflow-hidden">
              <div className="px-3 py-1.5 text-xs text-gray-500 border-b border-gray-800 flex items-center justify-between">
                <span>{label}</span>
                <CopyButton text={cmd} />
              </div>
              <pre className="px-4 py-3 text-xs font-mono text-green-400 overflow-x-auto">{cmd}</pre>
            </div>
          ))}
        </div>
        <div className="mt-4 p-3 bg-blue-900/20 border border-blue-800/50 rounded-lg text-xs text-blue-300">
          切换账号后无需重启 Codex。代理会实时使用新激活账号的 API key 或 access token。
        </div>
      </div>
    </div>
  )
}
