import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { LayoutDashboard, Users, KeyRound, Globe, Bot } from 'lucide-react'
import clsx from 'clsx'
import Dashboard from './pages/Dashboard'
import Accounts from './pages/Accounts'
import Tokens from './pages/Tokens'
import Domains from './pages/Domains'
import CodexPage from './pages/CodexPage'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: '概览' },
  { to: '/accounts', icon: Users, label: '账号管理' },
  { to: '/tokens', icon: KeyRound, label: 'Token 管理' },
  { to: '/domains', icon: Globe, label: '域名邮箱' },
  { to: '/codex', icon: Bot, label: 'Codex 集成' },
]

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden">
        {/* Sidebar */}
        <aside className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
          <div className="px-4 py-5 border-b border-gray-800">
            <h1 className="text-lg font-bold text-green-400">AutoChatGPT</h1>
            <p className="text-xs text-gray-500 mt-0.5">账号管理系统</p>
          </div>
          <nav className="flex-1 py-4 space-y-0.5 px-2">
            {NAV.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                    isActive
                      ? 'bg-green-900/40 text-green-400'
                      : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                  )
                }
              >
                <Icon size={16} />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="px-4 py-3 border-t border-gray-800">
            <p className="text-xs text-gray-600">v1.1.0</p>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto bg-gray-950">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/tokens" element={<Tokens />} />
            <Route path="/domains" element={<Domains />} />
            <Route path="/codex" element={<CodexPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
