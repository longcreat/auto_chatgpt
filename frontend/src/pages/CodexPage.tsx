import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  CheckCircle,
  Copy,
  RefreshCw,
  XCircle,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import {
  codexReload,
  codexSwitch,
  getAccounts,
  getCodexPluginStatus,
  getCodexStatus,
  getTokens,
  switchCodexPluginAccount,
} from '../api'

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
  const [pluginFeedback, setPluginFeedback] = useState<{ ok: boolean; message: string } | null>(null)

  const { data: status } = useQuery({
    queryKey: ['codex-status'],
    queryFn: getCodexStatus,
    refetchInterval: 5000,
  })
  const { data: pluginStatus } = useQuery({
    queryKey: ['codex-plugin-status'],
    queryFn: getCodexPluginStatus,
    refetchInterval: 5000,
  })
  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: getAccounts })
  const { data: tokens = [] } = useQuery({ queryKey: ['tokens'], queryFn: () => getTokens() })

  const switchMut = useMutation({
    mutationFn: codexSwitch,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['codex-status'] })
      qc.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
  const reloadMut = useMutation({
    mutationFn: codexReload,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['codex-status'] })
      qc.invalidateQueries({ queryKey: ['codex-plugin-status'] })
    },
  })
  const pluginSwitchMut = useMutation({
    mutationFn: switchCodexPluginAccount,
    onSuccess: (result: any) => {
      qc.invalidateQueries({ queryKey: ['codex-plugin-status'] })
      setPluginFeedback({
        ok: true,
        message: result.warning ? `${result.message} ${result.warning}` : result.message,
      })
    },
    onError: (error: any) => {
      setPluginFeedback({
        ok: false,
        message: error?.response?.data?.detail ?? error?.message ?? '切换插件登录态失败',
      })
    },
  })

  const tokenTypesByAccount = new Map<number, Set<string>>()
  for (const token of tokens as any[]) {
    if (!token.is_valid) continue
    const bucket = tokenTypesByAccount.get(token.account_id) ?? new Set<string>()
    bucket.add(token.token_type)
    tokenTypesByAccount.set(token.account_id, bucket)
  }

  const proxyUrl = status?.proxy_url ?? 'http://127.0.0.1:8000/v1'
  const pluginAuthReady = Boolean(pluginStatus?.has_access_token && pluginStatus?.has_refresh_token)

  const setupCommands = [
    { label: 'Linux / macOS', cmd: `export OPENAI_API_BASE="${proxyUrl}"` },
    { label: 'Windows CMD', cmd: `set OPENAI_API_BASE=${proxyUrl}` },
    { label: 'Windows PowerShell', cmd: `$env:OPENAI_API_BASE="${proxyUrl}"` },
    { label: 'Python', cmd: `import openai\nopenai.api_base = "${proxyUrl}"` },
  ]

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Bot size={20} className="text-green-400" />
        <h2 className="text-xl font-semibold">Codex 集成</h2>
        <button
          onClick={() => reloadMut.mutate()}
          title="重新加载"
          className="ml-auto text-gray-500 hover:text-gray-300 transition-colors"
        >
          <RefreshCw size={16} className={reloadMut.isPending ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className={`rounded-xl border p-5 mb-6 ${status?.token_valid ? 'bg-green-900/10 border-green-800/60' : 'bg-red-900/10 border-red-800/60'}`}>
        <div className="flex items-center gap-2 mb-4">
          {status?.token_valid
            ? <CheckCircle size={16} className="text-green-400" />
            : <XCircle size={16} className="text-red-400" />
          }
          <span className="font-medium">
            {status?.token_valid ? '本地代理运行中' : '未配置代理激活账号'}
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
          <div className="bg-gray-900/60 rounded-lg px-4 py-3">
            <p className="text-xs text-gray-400 mb-1">代理激活账号</p>
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
            <p className="text-xs text-gray-400 mb-1">代理凭证</p>
            <p className="font-mono text-xs text-gray-400">
              {status?.api_key_preview ?? '未配置可用于代理的 API 凭证'}
            </p>
          </div>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
        <h3 className="font-medium mb-4 flex items-center gap-2">
          <Zap size={15} className="text-yellow-400" />
          切换代理激活账号
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
                  {acc.status} {acc.has_api_key ? '· API Key ✓' : '· 使用 access token / api key'}
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

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
        <h3 className="font-medium mb-4">切换插件登录账号</h3>
        <div className={`rounded-xl border p-4 mb-4 ${pluginAuthReady ? 'bg-blue-900/10 border-blue-800/60' : 'bg-yellow-900/10 border-yellow-800/60'}`}>
          <div className="flex items-center gap-2 mb-3">
            {pluginAuthReady
              ? <CheckCircle size={16} className="text-blue-400" />
              : <XCircle size={16} className="text-yellow-400" />
            }
            <span className="font-medium">
              {pluginStatus?.email ? `当前插件账号: ${pluginStatus.email}` : '未识别插件登录账号'}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
            <div className="bg-gray-900/60 rounded-lg px-4 py-3">
              <p className="text-xs text-gray-400 mb-1">登录模式</p>
              <p className="font-mono text-xs">{pluginStatus?.auth_mode ?? '未知'}</p>
            </div>
            <div className="bg-gray-900/60 rounded-lg px-4 py-3">
              <p className="text-xs text-gray-400 mb-1">插件账号 ID</p>
              <p className="font-mono text-xs truncate">{pluginStatus?.plugin_account_id ?? '—'}</p>
            </div>
            <div className="bg-gray-900/60 rounded-lg px-4 py-3">
              <p className="text-xs text-gray-400 mb-1">套餐</p>
              <p className="font-mono text-xs">{pluginStatus?.plan_type ?? '—'}</p>
            </div>
            <div className="bg-gray-900/60 rounded-lg px-4 py-3">
              <p className="text-xs text-gray-400 mb-1">最近刷新</p>
              <p className="font-mono text-xs">
                {pluginStatus?.last_refresh ? new Date(pluginStatus.last_refresh).toLocaleString('zh-CN') : '—'}
              </p>
            </div>
          </div>
          <div className="mt-3 bg-gray-900/60 rounded-lg px-4 py-3">
            <div className="flex items-center gap-2">
              <p className="text-xs text-gray-400">认证文件</p>
              {pluginStatus?.auth_file && <CopyButton text={pluginStatus.auth_file} />}
            </div>
            <p className="font-mono text-xs text-gray-300 break-all mt-1">{pluginStatus?.auth_file ?? '—'}</p>
          </div>
          {pluginStatus?.warning && (
            <div className="mt-3 text-xs text-yellow-300 bg-yellow-900/20 border border-yellow-800/60 rounded-lg px-3 py-2">
              {pluginStatus.warning}
            </div>
          )}
          {pluginFeedback && (
            <div className={`mt-3 text-xs rounded-lg px-3 py-2 border ${
              pluginFeedback.ok
                ? 'text-green-300 bg-green-900/20 border-green-800/60'
                : 'text-red-300 bg-red-900/20 border-red-800/60'
            }`}>
              {pluginFeedback.message}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {accounts.map((acc: any) => {
            const tokenTypes = tokenTypesByAccount.get(acc.id) ?? new Set<string>()
            const ready = tokenTypes.has('access_token') && tokenTypes.has('refresh_token')
            const isCurrentPluginAccount = pluginStatus?.email === acc.email

            return (
              <button
                key={`plugin-${acc.id}`}
                disabled={!ready || pluginSwitchMut.isPending}
                onClick={() => {
                  if (confirm(`将覆盖 ${pluginStatus?.auth_file ?? '~/.codex/auth.json'}，切换 Codex 插件登录账号为 ${acc.email}，继续吗？`)) {
                    pluginSwitchMut.mutate(acc.id)
                  }
                }}
                className={`flex items-center gap-3 px-4 py-3 rounded-lg border text-sm transition-all ${
                  isCurrentPluginAccount
                    ? 'border-blue-600 bg-blue-900/20 text-blue-200'
                    : ready
                      ? 'border-gray-700 hover:border-gray-600 hover:bg-gray-800 text-gray-300'
                      : 'border-gray-800 bg-gray-950 text-gray-600 cursor-not-allowed'
                }`}
              >
                <div className="flex-1 text-left">
                  <p className="font-mono text-xs truncate">{acc.email}</p>
                  <p className={`text-xs mt-0.5 ${ready ? 'text-green-500' : 'text-gray-500'}`}>
                    {ready ? 'access_token + refresh_token ✓' : '缺少 access_token 或 refresh_token'}
                  </p>
                </div>
                {isCurrentPluginAccount && <CheckCircle size={14} className="text-blue-400 flex-shrink-0" />}
              </button>
            )
          })}
          {accounts.length === 0 && (
            <p className="col-span-2 text-gray-600 text-sm py-4 text-center">暂无账号</p>
          )}
        </div>

        <div className="mt-4 p-3 bg-amber-900/20 border border-amber-800/50 rounded-lg text-xs text-amber-200">
          这里切的是 VS Code Codex 插件本地登录态，会直接写入 <span className="font-mono">~/.codex/auth.json</span>。
          如果侧边栏没有立刻刷新，执行 VS Code 的 <span className="font-mono">Developer: Reload Window</span>。
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="font-medium mb-4">本地代理环境配置</h3>
        <p className="text-xs text-gray-400 mb-4">
          这部分仍然只影响 <span className="font-mono">OPENAI_API_BASE</span> 代理，不会修改插件登录态：
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
          代理切号和插件登录态切号是两套独立机制。前者改 <span className="font-mono">/v1</span> 请求身份，后者改 <span className="font-mono">~/.codex/auth.json</span>。
        </div>
      </div>
    </div>
  )
}
