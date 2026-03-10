import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, Copy, RefreshCw, Link, ChevronDown, Terminal } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { getAccounts, startOpenClawOAuth, getOpenClawResult } from '../api'

type TaskStatus = 'idle' | 'running' | 'done' | 'error'

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-xs transition-colors"
    >
      {copied ? <CheckCircle size={13} className="text-green-400" /> : <Copy size={13} />}
      {copied ? '已复制' : '复制'}
    </button>
  )
}

export default function OAuthCapture() {
  const [authUrl, setAuthUrl] = useState('')
  const [accountId, setAccountId] = useState<number | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskStatus, setTaskStatus] = useState<TaskStatus>('idle')
  const [callbackUrl, setCallbackUrl] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [log, setLog] = useState<string[]>([])
  const [showLog, setShowLog] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: getAccounts })

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }
  useEffect(() => () => stopPolling(), [])

  // 自动滚动日志到底部
  useEffect(() => {
    if (showLog) logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [log, showLog])

  const startMut = useMutation({
    mutationFn: () => {
      if (!authUrl.trim() || accountId === null) throw new Error('请填写 URL 并选择账号')
      return startOpenClawOAuth(authUrl.trim(), accountId)
    },
    onSuccess: (data) => {
      setTaskId(data.task_id)
      setTaskStatus('running')
      setCallbackUrl(null)
      setErrorMsg(null)
      setLog([])
      // 开始轮询
      pollRef.current = setInterval(async () => {
        try {
          const res = await getOpenClawResult(data.task_id)
          if (res.log) setLog(res.log)
          if (res.status === 'done') {
            setCallbackUrl(res.callback_url)
            setTaskStatus('done')
            stopPolling()
          } else if (res.status === 'error') {
            setErrorMsg(res.error ?? '未知错误')
            setTaskStatus('error')
            stopPolling()
          }
        } catch { /* 网络抖动继续轮询 */ }
      }, 1500)
    },
    onError: (e: any) => {
      setErrorMsg(e?.response?.data?.detail ?? e?.message ?? '启动失败')
      setTaskStatus('error')
    },
  })

  const handleReset = () => {
    stopPolling()
    setTaskId(null)
    setTaskStatus('idle')
    setCallbackUrl(null)
    setErrorMsg(null)
    setLog([])
  }

  const activeAccounts = accounts.filter((a: any) => a.status === 'active' || a.status === 'pending')
  const isReady = authUrl.trim().startsWith('http') && accountId !== null

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Link size={20} className="text-blue-400" />
        <h2 className="text-xl font-semibold">OpenClaw OAuth 鉴权</h2>
      </div>

      {/* 说明 */}
      <div className="bg-blue-900/10 border border-blue-800/40 rounded-xl p-4 mb-6 text-sm text-gray-300">
        <p className="font-medium text-blue-300 mb-1">使用说明</p>
        <ol className="list-decimal list-inside space-y-1 text-gray-400 text-xs">
          <li>将 OpenClaw 提供的授权 URL 粘贴到下方输入框</li>
          <li>选择用于登录的账号（需已注册并有密码）</li>
          <li>点击「开始鉴权」，系统自动使用 HTTP 接口完成 OAuth 登录流程</li>
          <li>获取到回调 URL 后，复制并粘贴回 OpenClaw 完成鉴权</li>
        </ol>
      </div>

      {/* 输入区域 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-4 space-y-4">
        {/* URL 输入 */}
        <div>
          <label className="block text-sm text-gray-400 mb-1.5">OpenClaw 授权 URL</label>
          <textarea
            value={authUrl}
            onChange={e => setAuthUrl(e.target.value)}
            disabled={taskStatus === 'running'}
            placeholder="https://auth.openai.com/oauth/authorize?response_type=code&client_id=app_EMoamEEZ73f0CkXaXp7hrann&redirect_uri=..."
            rows={3}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-xs font-mono
                       text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-600
                       resize-none disabled:opacity-50 transition-colors"
          />
        </div>

        {/* 账号选择 */}
        <div>
          <label className="block text-sm text-gray-400 mb-1.5">使用账号</label>
          <div className="relative">
            <select
              value={accountId ?? ''}
              onChange={e => setAccountId(e.target.value ? Number(e.target.value) : null)}
              disabled={taskStatus === 'running'}
              className="w-full appearance-none bg-gray-800 border border-gray-700 rounded-lg
                         px-3 py-2.5 pr-8 text-sm text-gray-200 focus:outline-none focus:border-blue-600
                         disabled:opacity-50 transition-colors"
            >
              <option value="">-- 选择账号 --</option>
              {accounts.map((acc: any) => (
                <option key={acc.id} value={acc.id}>
                  {acc.email}  [{acc.status}]
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
          </div>
          {accounts.length === 0 && (
            <p className="text-xs text-gray-500 mt-1">暂无账号，请先在「账号管理」中添加</p>
          )}
        </div>

        {/* 操作按钮 */}
        <div className="flex items-center gap-3">
          {taskStatus !== 'running' ? (
            <button
              onClick={() => startMut.mutate()}
              disabled={!isReady || startMut.isPending}
              className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40
                         disabled:cursor-not-allowed text-sm font-medium transition-colors"
            >
              {startMut.isPending ? '启动中...' : '开始鉴权'}
            </button>
          ) : (
            <button
              onClick={handleReset}
              className="px-5 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-sm font-medium transition-colors"
            >
              取消
            </button>
          )}
          {(taskStatus === 'done' || taskStatus === 'error') && (
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-700
                         hover:border-gray-600 text-sm text-gray-400 transition-colors"
            >
              <RefreshCw size={13} />
              重新开始
            </button>
          )}
        </div>
      </div>

      {/* 状态面板 */}
      {taskStatus !== 'idle' && (
        <div className={`rounded-xl border p-5 ${
          taskStatus === 'done'
            ? 'bg-green-900/10 border-green-800/60'
            : taskStatus === 'running'
            ? 'bg-blue-900/10 border-blue-800/40'
            : 'bg-red-900/10 border-red-800/60'
        }`}>
          {/* 状态头 */}
          <div className="flex items-center gap-2 mb-3">
            {taskStatus === 'running' && (
              <>
                <RefreshCw size={15} className="text-blue-400 animate-spin" />
                <span className="text-sm font-medium text-blue-300">正在执行 HTTP OAuth 登录...</span>
              </>
            )}
            {taskStatus === 'done' && (
              <>
                <CheckCircle size={15} className="text-green-400" />
                <span className="text-sm font-medium text-green-300">鉴权成功！已获取回调 URL</span>
              </>
            )}
            {taskStatus === 'error' && (
              <>
                <XCircle size={15} className="text-red-400" />
                <span className="text-sm font-medium text-red-300">鉴权失败</span>
              </>
            )}
            {/* 日志折叠按钮 */}
            {log.length > 0 && (
              <button
                onClick={() => setShowLog(v => !v)}
                className="ml-auto flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
              >
                <Terminal size={12} />
                {showLog ? '隐藏日志' : `查看日志 (${log.length})`}
              </button>
            )}
          </div>

          {/* 错误信息 */}
          {errorMsg && (
            <div className="bg-red-900/20 rounded-lg px-4 py-2.5 text-xs text-red-300 font-mono mb-3">
              {errorMsg}
            </div>
          )}

          {/* 回调 URL */}
          {callbackUrl && (
            <div className="mt-1">
              <p className="text-xs text-gray-400 mb-1.5">回调 URL（复制后粘贴到 OpenClaw）：</p>
              <div className="bg-gray-900/80 border border-green-800/40 rounded-lg px-4 py-3">
                <p className="font-mono text-xs text-green-300 break-all leading-relaxed mb-3">
                  {callbackUrl}
                </p>
                <CopyButton text={callbackUrl} />
              </div>
            </div>
          )}

          {/* 日志 */}
          {showLog && log.length > 0 && (
            <div className="mt-3 bg-black/40 rounded-lg p-3 max-h-64 overflow-y-auto">
              {log.map((line, i) => (
                <p key={i} className="font-mono text-xs text-gray-400 leading-relaxed whitespace-pre-wrap">
                  {line}
                </p>
              ))}
              <div ref={logEndRef} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
