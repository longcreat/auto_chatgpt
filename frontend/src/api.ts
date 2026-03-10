import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// ─── 账号 ─────────────────────────────────────────────────────

export const getAccounts = () => api.get('/accounts').then(r => r.data)
export const getAccount = (id: number) => api.get(`/accounts/${id}`).then(r => r.data)
export const createAccount = (data: any) => api.post('/accounts', data).then(r => r.data)
export const updateAccount = (id: number, data: any) => api.patch(`/accounts/${id}`, data).then(r => r.data)
export const deleteAccount = (id: number) => api.delete(`/accounts/${id}`).then(r => r.data)
export const switchAccount = (id: number) => api.post('/accounts/switch', { account_id: id }).then(r => r.data)
export const refreshToken = (id: number) => api.post(`/accounts/${id}/refresh-token`).then(r => r.data)
export const fetchAccountToken = (id: number) => api.post(`/accounts/${id}/fetch-token`).then(r => r.data)
export const autoRegister = (data: any) => api.post('/accounts/register', data).then(r => r.data)
export const getRegistrationTasks = () => api.get('/accounts/tasks').then(r => r.data)
export const getTask = (id: number) => api.get(`/accounts/tasks/${id}`).then(r => r.data)
export const retryRegistrationTask = (id: number) => api.post(`/accounts/tasks/${id}/retry`).then(r => r.data)

// ─── Token ────────────────────────────────────────────────────

export const getTokens = (accountId?: number) =>
  api.get('/tokens', { params: accountId ? { account_id: accountId } : {} }).then(r => r.data)
export const createToken = (data: any) => api.post('/tokens', data).then(r => r.data)
export const updateToken = (id: number, data: any) => api.patch(`/tokens/${id}`, data).then(r => r.data)
export const deleteToken = (id: number) => api.delete(`/tokens/${id}`).then(r => r.data)
export const invalidateExpiredTokens = () => api.post('/tokens/invalidate-expired').then(r => r.data)

// ─── 域名邮箱 ─────────────────────────────────────────────────

export const verifyCFConfig = () => api.get('/domains/verify').then(r => r.data)
export const getAliases = () => api.get('/domains/aliases').then(r => r.data)
export const generateAliases = (count: number) =>
  api.post('/domains/aliases/generate', { count }).then(r => r.data)
export const createCustomAlias = (alias: string) =>
  api.post(`/domains/aliases/custom?alias=${encodeURIComponent(alias)}`).then(r => r.data)
export const deleteAlias = (id: number) => api.delete(`/domains/aliases/${id}`).then(r => r.data)

// ─── 系统配置 ─────────────────────────────────────────────────

export const getSettings = () => api.get('/settings').then(r => r.data)
export const updateSettings = (data: any) => api.put('/settings', data).then(r => r.data)
export const testImap = (data: any) => api.post('/settings/test-imap', data).then(r => r.data)
export const testProxy = (data: any) => api.post('/settings/test-proxy', data).then(r => r.data)

// ─── Codex ─────────────────────────────────────────────────────

export const getCodexStatus = () => api.get('/codex/status').then(r => r.data)
export const codexSwitch = (id: number) => api.post('/codex/switch', { account_id: id }).then(r => r.data)
export const codexReload = () => api.post('/codex/reload').then(r => r.data)
export const getCodexPluginStatus = () => api.get('/codex/plugin-status').then(r => r.data)
export const switchCodexPluginAccount = (id: number) =>
  api.post('/codex/plugin-switch', { account_id: id }).then(r => r.data)

// ─── OAuth 回调捕获 ────────────────────────────────────────────

export const startOpenClawOAuth = (auth_url: string, account_id: number) =>
  api.post('/oauth/openclaw', { auth_url, account_id }).then(r => r.data)
export const getOpenClawResult = (taskId: string) =>
  api.get(`/oauth/openclaw/${taskId}`).then(r => r.data)
