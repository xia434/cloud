<template>
  <div class="chat-container">
    <el-container class="app-shell">
      <el-aside width="260px" class="sidebar">
        <div class="sidebar-header">
          <div class="brand">
            <div class="brand-logo">CA</div>
            <h2>Cloud Agent</h2>
          </div>
          <el-button type="primary" :icon="Plus" circle @click="createNewSession" />
        </div>
        <div class="session-list">
          <div 
            v-for="session in sessions" 
            :key="session.id"
            :class="['session-item', { active: currentSessionId === session.id }]"
            @click="switchSession(session.id)"
          >
            <el-icon><ChatDotRound /></el-icon>
            <span class="session-name">{{ session.name }}</span>
          </div>
        </div>
        <div class="user-info">
          <div class="mini-avatar user-avatar">{{ currentUser ? currentUser.username.charAt(0).toUpperCase() : '?' }}</div>
          <span class="username">{{ currentUser ? currentUser.display_name : '未登录' }}</span>
          <el-button
            v-if="currentUser"
            size="small"
            text
            class="logout-btn"
            @click="logout"
          >退出</el-button>
          <el-button
            v-else
            size="small"
            text
            class="logout-btn"
            @click="showLoginDialog = true"
          >登录</el-button>
        </div>
      </el-aside>

      <el-main class="chat-main">
        <div class="chat-header">
          <div class="header-title-row">
            <div class="header-title">企业云智能客服</div>
            <div
              v-if="systemStatus === 'degraded'"
              class="status-badge status-degraded"
              title="部分组件不可用，但不影响对话"
            >⚠ 降级</div>
            <div
              v-else-if="systemStatus === 'error'"
              class="status-badge status-error"
              title="Agent 编排未就绪，可能无法正常对话"
            >● 异常</div>
          </div>
          <div class="header-subtitle">Multi-Agent · Billing · Promotion · FinOps</div>
        </div>
        <div class="message-list" ref="messageListRef">
          <div v-if="messages.length === 0" class="empty-state">
            <el-icon size="64" color="#409EFC"><Service /></el-icon>
            <h3 class="welcome-title">欢迎使用云平台智能客服</h3>
            <p class="welcome-desc">我是您的专属 AI 助手，您可以直接向我提问，或者尝试以下典型场景：</p>
            
            <div class="scenario-container">
              <el-row :gutter="20">
                <el-col :span="12">
                  <div class="scenario-card">
                    <div class="card-header">
                      <el-icon><Monitor /></el-icon>
                      <span>产品咨询与推荐</span>
                    </div>
                    <div class="scenario-list">
                      <div class="scenario-item" @click="sendQuery('云服务器ECS有哪些基本属性？')">云服务器ECS有哪些基本属性？</div>
                      <div class="scenario-item" @click="sendQuery('我是Java接口服务+MySQL，8核16G够吗？推荐具体实例型号。')">Java服务+MySQL，推荐具体实例型号</div>
                    </div>
                  </div>
                </el-col>
                <el-col :span="12">
                  <div class="scenario-card">
                    <div class="card-header">
                      <el-icon><List /></el-icon>
                      <span>账单与实例查询</span>
                    </div>
                    <div class="scenario-list">
                      <div class="scenario-item" @click="sendQuery('帮我查一下我最近的订单记录')">帮我查一下我最近的订单记录</div>
                      <div class="scenario-item" @click="sendQuery('查询我名下的所有运行中的实例')">查询我名下的所有运行中的实例</div>
                    </div>
                  </div>
                </el-col>
              </el-row>
              <el-row :gutter="20" style="margin-top: 20px;">
                <el-col :span="12">
                  <div class="scenario-card">
                    <div class="card-header">
                      <el-icon><DataLine /></el-icon>
                      <span>资源优化与降本</span>
                    </div>
                    <div class="scenario-list">
                      <div class="scenario-item" @click="sendQuery('获取近7天CPU/内存/带宽数据并做降本建议')">获取近7天资源监控并做降本建议</div>
                      <div class="scenario-item" @click="sendQuery('服务器利用率低，怎么省钱？')">服务器利用率低，怎么省钱？</div>
                    </div>
                  </div>
                </el-col>
                <el-col :span="12">
                  <div class="scenario-card">
                    <div class="card-header">
                      <el-icon><Share /></el-icon>
                      <span>产品推广活动</span>
                    </div>
                    <div class="scenario-list">
                      <div class="scenario-item" @click="sendQuery('我想推广云服务器ECS，有海报吗？')">我想推广云服务器ECS，有海报吗？</div>
                      <div class="scenario-item" @click="sendQuery('帮我生成一张 c7 计算型的推广海报')">帮我生成一张 c7 计算型的推广海报</div>
                    </div>
                  </div>
                </el-col>
              </el-row>
            </div>
          </div>

          <div 
            v-for="(msg, index) in messages" 
            :key="index"
            :class="['message-row', msg.role]"
          >
            <div :class="['msg-avatar', msg.role === 'user' ? 'user-avatar' : 'ai-avatar']">
              {{ msg.role === 'user' ? 'U' : 'AI' }}
            </div>
            <div class="message-bubble" v-html="renderMarkdown(msg.content)"></div>
          </div>
          
          <div v-if="isLoading" class="message-row assistant">
             <div class="msg-avatar ai-avatar">AI</div>
             <div class="message-bubble loading">
               <div v-if="thinkingSteps.length === 0" class="loading-text">
                 <el-icon class="is-loading"><Loading /></el-icon> 正在思考与调用工具中...
               </div>
               <div v-else class="thinking-trace">
                 <div v-for="(step, idx) in thinkingSteps" :key="idx" class="trace-step">
                   <span v-if="step.type === 'route'" class="trace-route">
                     🧭 路由至 <strong>{{ resolveAgentName(step.agent) }}</strong>
                   </span>
                   <span v-else-if="step.type === 'tool_start'" class="trace-tool">
                     🔧 调用工具 <strong>{{ step.name }}</strong>
                     <span v-if="step.args && Object.keys(step.args).length" class="trace-args">
                       ({{ formatArgs(step.args) }})
                     </span>
                   </span>
                   <span v-else-if="step.type === 'tool_end'" class="trace-tool-end">
                     ✅ {{ step.name }} 完成
                   </span>
                   <span v-else-if="step.type === 'cache_hit'" class="trace-cache">
                     ⚡ 缓存命中 ({{ step.level }})
                   </span>
                 </div>
                 <div class="loading-text">
                   <el-icon class="is-loading"><Loading /></el-icon> 生成回答中...
                 </div>
               </div>
             </div>
          </div>
        </div>

        <div class="input-area">
          <el-input
            v-model="inputQuery"
            type="textarea"
            :rows="3"
            placeholder="请输入您的问题，Shift + Enter 换行，Enter 发送"
            @keydown.enter.prevent="handleEnter"
            :disabled="isLoading"
          />
          <el-button 
            type="primary" 
            class="send-btn" 
            :icon="Position" 
            :loading="isLoading"
            @click="sendQuery(inputQuery)"
            :disabled="!inputQuery.trim()"
          >
            发送
          </el-button>
        </div>
      </el-main>
    </el-container>

    <!-- P3 安全认证体系改造：登录弹窗 -->
    <el-dialog
      v-model="showLoginDialog"
      title="登录到 Cloud Agent"
      width="400px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      align-center
    >
      <el-form :model="loginForm" @submit.prevent="login" label-width="0">
        <el-form-item>
          <el-input
            v-model="loginForm.username"
            placeholder="用户名（alice / bob / admin）"
            :prefix-icon="User"
            autocomplete="username"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="loginForm.password"
            type="password"
            placeholder="密码（cloud@2024）"
            :prefix-icon="Lock"
            show-password
            autocomplete="current-password"
            @keyup.enter="login"
          />
        </el-form-item>
        <div v-if="loginError" class="login-error">{{ loginError }}</div>
        <div class="login-tip">
          测试账号：alice / bob / admin，密码统一 <code>cloud@2024</code>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="showLoginDialog = false" :disabled="isLoggingIn">取消</el-button>
        <el-button type="primary" @click="login" :loading="isLoggingIn">登录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, computed } from 'vue'
import { Plus, ChatDotRound, Service, Position, Loading, Monitor, List, DataLine, Share, User, Lock } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { ElMessage } from 'element-plus'

// ============ P3 安全认证体系：token 管理 ============
interface CurrentUser {
  user_id: string
  username: string
  display_name: string
  role: string
}

const TOKEN_KEY = 'cloud_agent_token'
const USER_KEY = 'cloud_agent_user'

const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
const currentUser = ref<CurrentUser | null>(
  (() => {
    try {
      const raw = localStorage.getItem(USER_KEY)
      return raw ? JSON.parse(raw) as CurrentUser : null
    } catch {
      return null
    }
  })()
)
const showLoginDialog = ref(false)
const isLoggingIn = ref(false)
const loginError = ref('')
const loginForm = ref({ username: '', password: '' })

/** 拉取当前用户信息（用于校验 token 是否仍有效） */
const fetchCurrentUser = async (): Promise<CurrentUser | null> => {
  if (!token.value) return null
  try {
    const resp = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${token.value}` }
    })
    if (!resp.ok) return null
    const data = await resp.json()
    return data as CurrentUser
  } catch {
    return null
  }
}

const login = async () => {
  loginError.value = ''
  if (!loginForm.value.username || !loginForm.value.password) {
    loginError.value = '请输入用户名和密码'
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(loginForm.value)
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '登录失败' }))
      loginError.value = err.detail || `登录失败 (HTTP ${resp.status})`
      return
    }
    const data = await resp.json()
    token.value = data.access_token
    currentUser.value = {
      user_id: data.user_id,
      username: data.username,
      display_name: data.display_name,
      role: data.role
    }
    localStorage.setItem(TOKEN_KEY, token.value!)
    localStorage.setItem(USER_KEY, JSON.stringify(currentUser.value))
    showLoginDialog.value = false
    loginForm.value = { username: '', password: '' }
    ElMessage.success(`欢迎回来，${currentUser.value.display_name}`)
  } catch (e) {
    loginError.value = '网络错误，请检查后端服务是否启动'
  } finally {
    isLoggingIn.value = false
  }
}

const logout = () => {
  token.value = null
  currentUser.value = null
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  messages.value = []
  ElMessage.info('已退出登录')
  showLoginDialog.value = true
}

/** 401 处理：清空 token 并弹登录窗 */
const handleUnauthorized = () => {
  token.value = null
  currentUser.value = null
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  showLoginDialog.value = true
  ElMessage.warning('登录已过期，请重新登录')
}

/** 构造带 Authorization header 的请求头 */
const authHeaders = (): HeadersInit => {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token.value) {
    h['Authorization'] = `Bearer ${token.value}`
  }
  return h
}

// ============ 原有聊天状态 ============
// 状态定义
const inputQuery = ref('')
const isLoading = ref(false)
const messageListRef = ref<HTMLElement | null>(null)
const currentSessionId = ref('session_default_1')

// 系统健康状态：'ok' | 'degraded' | 'error' | 'unknown'
const systemStatus = ref<'ok' | 'degraded' | 'error' | 'unknown'>('unknown')

/** 拉取后端 /api/health，更新顶部状态徽标 */
const fetchHealth = async (): Promise<void> => {
  try {
    const resp = await fetch('/api/health')
    if (!resp.ok) {
      systemStatus.value = 'error'
      return
    }
    const data = await resp.json()
    systemStatus.value = (data.status as typeof systemStatus.value) || 'unknown'
  } catch {
    // 后端未启动时静默处理，onMounted 已有登录流程提示
    systemStatus.value = 'unknown'
  }
}

// Agent 思考过程（路由、工具调用等元数据事件）
interface ThinkingStep {
  type: 'route' | 'tool_start' | 'tool_end' | 'cache_hit'
  agent?: string
  name?: string
  args?: Record<string, unknown>
  level?: string
}
const thinkingSteps = ref<ThinkingStep[]>([])

// Agent 名称中文映射
const agentNameMap: Record<string, string> = {
  product_agent: '产品咨询 Agent',
  billing_agent: '账单查询 Agent',
  promotion_agent: '推广营销 Agent',
  recommendation_agent: '选型推荐 Agent',
  finops_agent: 'FinOps 成本优化 Agent'
}

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const messages = ref<Message[]>([])

const sessions = ref([
  { id: 'session_default_1', name: '新对话' }
])

// 初始化
onMounted(async () => {
  // P3 改造：启动时校验 token，无效则弹登录窗
  if (token.value) {
    const user = await fetchCurrentUser()
    if (user) {
      currentUser.value = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    } else {
      // token 过期或无效
      token.value = null
      currentUser.value = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      showLoginDialog.value = true
    }
  } else {
    showLoginDialog.value = true
  }
  // 拉取系统健康状态（不阻塞登录流程）
  fetchHealth()
})

const createNewSession = () => {
  const newId = `session_${Date.now()}`
  sessions.value.unshift({ id: newId, name: '新对话' })
  currentSessionId.value = newId
  messages.value = []
}

const switchSession = async (id: string) => {
  if (currentSessionId.value === id) return
  currentSessionId.value = id

  // P1-7 改造：从后端拉取该 session 的历史消息，而不是清空
  // P3 改造：user_id 由后端从 JWT 解析，不再通过 Query 传递
  // 失败时降级为空列表（不阻塞用户继续对话）
  messages.value = []
  try {
    const resp = await fetch(
      `/api/history?session_id=${encodeURIComponent(id)}`,
      {
        method: 'GET',
        headers: authHeaders()
      }
    )
    if (resp.status === 401) {
      handleUnauthorized()
      return
    }
    if (resp.ok) {
      const data = await resp.json()
      if (Array.isArray(data.messages)) {
        messages.value = data.messages.map((m: { role: string; content: string }) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content
        }))
      }
      // degraded：后端记忆后端不可用，仅警告不阻塞
      if (data.status === 'degraded') {
        ElMessage.warning('历史记录暂时不可用，已为您开启新对话')
      }
    }
  } catch (e) {
    console.warn('拉取历史失败，降级为空会话:', e)
    ElMessage.warning('历史记录拉取失败，已开启新对话')
  }
  scrollToBottom()
}

const renderMarkdown = (text: string): string => {
  const rendered = marked.parse(text, { async: false }) as string
  return DOMPurify.sanitize(rendered, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'form'],
  })
}

const scrollToBottom = async () => {
  await nextTick()
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

const handleEnter = (e: KeyboardEvent) => {
  if (e.shiftKey) return
  if (inputQuery.value.trim() && !isLoading.value) {
    sendQuery(inputQuery.value)
  }
}

const sendQuery = async (query: string) => {
  if (!query.trim()) return

  // P3 改造：未登录不允许发送
  if (!token.value) {
    showLoginDialog.value = true
    ElMessage.warning('请先登录')
    return
  }

  const text = query.trim()
  inputQuery.value = ''

  // 添加用户消息
  messages.value.push({ role: 'user', content: text })
  scrollToBottom()

  isLoading.value = true
  thinkingSteps.value = [] // 清空上一次的思考步骤

  // 预先创建一个空的助手消息，用于接收流式数据
  const assistantMessage: Message = { role: 'assistant', content: '' }
  messages.value.push(assistantMessage)
  const currentMsgIndex = messages.value.length - 1

  try {
    // P3 改造：调用 FastAPI 后端接口，移除 body 中的 user_id，由后端从 JWT 解析
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        query: text,
        session_id: currentSessionId.value
      })
    })

    if (response.status === 401) {
      handleUnauthorized()
      messages.value.pop() // 移除空助手消息
      isLoading.value = false
      return
    }

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder('utf-8')
    // 注意：isLoading 在收到第一个 content token 后才关闭，让思考过程展示完整

    if (reader) {
      let buffer = ''
      let hasContentStarted = false
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // 将不完整的一行保留到下一次循环

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim()
            if (dataStr === '[DONE]') continue
            if (!dataStr) continue

            try {
              const data = JSON.parse(dataStr)

              // 元数据事件：路由 / 工具调用 / 缓存命中
              if (data.type === 'route') {
                thinkingSteps.value.push({ type: 'route', agent: data.agent })
                scrollToBottom()
              } else if (data.type === 'tool_start') {
                thinkingSteps.value.push({ type: 'tool_start', name: data.name, args: data.args })
                scrollToBottom()
              } else if (data.type === 'tool_end') {
                thinkingSteps.value.push({ type: 'tool_end', name: data.name })
                scrollToBottom()
              } else if (data.type === 'cache_hit') {
                thinkingSteps.value.push({ type: 'cache_hit', level: data.level })
                scrollToBottom()
              }

              // 内容流：累加到助手消息
              if (data.content && messages.value[currentMsgIndex]) {
                if (!hasContentStarted) {
                  hasContentStarted = true
                  isLoading.value = false // 开始输出内容，关闭 loading
                }
                messages.value[currentMsgIndex].content += data.content
                scrollToBottom()
              }
              if (data.done) {
                // 流传输完成
              }
            } catch (e) {
              console.error('Error parsing SSE data:', e, dataStr)
            }
          }
        }
      }
      // 兜底：如果一直没有 content，也要关闭 loading
      if (!hasContentStarted) {
        isLoading.value = false
      }
    }
  } catch (error) {
    console.error('API Error:', error)
    if (messages.value[currentMsgIndex]) {
      messages.value[currentMsgIndex].content = '❌ 请求失败，请检查后端服务是否启动 (FastAPI port 5000)。'
    }
  } finally {
    isLoading.value = false
    // 保留思考步骤 3 秒后清空，避免下一条消息干扰
    setTimeout(() => { thinkingSteps.value = [] }, 3000)
    scrollToBottom()
  }
}

// 格式化工具参数展示
const formatArgs = (args: Record<string, unknown>): string => {
  const entries = Object.entries(args)
  if (entries.length === 0) return ''
  return entries.map(([k, v]) => {
    const val = typeof v === 'string' ? (v.length > 50 ? v.slice(0, 50) + '...' : v) : String(v)
    return `${k}=${val}`
  }).join(', ')
}

const resolveAgentName = (agent?: string): string => {
  if (!agent) return '未知 Agent'
  return agentNameMap[agent] || agent
}
</script>

<style scoped>
.chat-container {
  height: 100vh;
  width: 100vw;
  background: radial-gradient(circle at 10% 20%, #e6f0ff 0%, #eef5ff 35%, #f6f8fc 100%);
  overflow: hidden;
  padding: 16px;
  box-sizing: border-box;
}
.app-shell {
  height: 100%;
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid #e7ebf3;
  box-shadow: 0 20px 50px rgba(15, 35, 95, 0.08);
  background: #fff;
}
.sidebar {
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  padding: 18px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-logo {
  width: 30px;
  height: 30px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #60a5fa, #2563eb);
}
.sidebar-header h2 {
  margin: 0;
  font-size: 16px;
  color: #f8fafc;
  letter-spacing: 0.4px;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.session-item {
  padding: 12px;
  margin-bottom: 8px;
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  color: #dbeafe;
  transition: all 0.3s;
  border: 1px solid transparent;
}
.session-item:hover {
  background-color: rgba(96, 165, 250, 0.18);
}
.session-item.active {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.24), rgba(37, 99, 235, 0.22));
  color: #eff6ff;
  font-weight: 500;
  border-color: rgba(96, 165, 250, 0.35);
}
.user-info {
  padding: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  display: flex;
  align-items: center;
  gap: 10px;
}
.username {
  font-weight: 600;
  color: #e2e8f0;
}

.chat-main {
  display: flex;
  flex-direction: column;
  padding: 0;
  background: linear-gradient(180deg, #f8fbff 0%, #f6f8fc 100%);
}
.chat-header {
  padding: 16px 28px 12px;
  border-bottom: 1px solid #e7edf7;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
}
.header-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}
.status-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  line-height: 1.4;
  white-space: nowrap;
}
.status-degraded {
  background: #fef3c7;
  color: #b45309;
  border: 1px solid #fde68a;
}
.status-error {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}
.header-subtitle {
  margin-top: 4px;
  color: #64748b;
  font-size: 13px;
}
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  scroll-behavior: smooth;
}
.empty-state {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: #64748b;
  background: #ffffff;
  border: 1px solid #e7edf7;
  border-radius: 16px;
  padding: 40px;
}
.welcome-title {
  margin-top: 16px;
  margin-bottom: 8px;
  color: #1e293b;
  font-size: 24px;
  font-weight: 600;
}
.welcome-desc {
  margin-bottom: 32px;
  color: #64748b;
  font-size: 15px;
}
.scenario-container {
  width: 100%;
  max-width: 800px;
}
.scenario-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  height: 100%;
  transition: all 0.3s ease;
}
.scenario-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  border-color: #cbd5e1;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 16px;
}
.card-header .el-icon {
  color: #3b82f6;
  font-size: 20px;
}
.scenario-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.scenario-item {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 14px;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s ease;
}
.scenario-item:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
  transform: translateY(-2px);
}

.message-row {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
  max-width: 86%;
  align-items: flex-start;
}
.message-row.user {
  flex-direction: row-reverse;
  margin-left: auto;
}
.msg-avatar {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}
.user-avatar {
  color: #eff6ff;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
}
.ai-avatar {
  color: #f8fafc;
  background: linear-gradient(135deg, #0ea5e9, #22c55e);
}
.mini-avatar {
  width: 28px;
  height: 28px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
}
.message-bubble {
  background: #ffffff;
  padding: 13px 16px;
  border-radius: 14px;
  border: 1px solid #e7edf7;
  box-shadow: 0 8px 24px rgba(15, 35, 95, 0.05);
  line-height: 1.6;
  color: #1e293b;
  font-size: 15px;
}
.message-row.user .message-bubble {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #ffffff;
  border-color: rgba(59, 130, 246, 0.35);
}
.message-row.assistant .message-bubble {
  border-top-left-radius: 0;
}
.message-row.user .message-bubble {
  border-top-right-radius: 0;
}
.message-bubble :deep(p) { margin: 0 0 10px 0; }
.message-bubble :deep(p:last-child) { margin: 0; }
.message-bubble :deep(img) { max-width: 100%; border-radius: 8px; margin-top: 10px; }
.message-bubble :deep(pre) { background: #f4f4f5; padding: 10px; border-radius: 6px; overflow-x: auto; }
.message-bubble :deep(code) { font-family: monospace; }
.message-bubble.loading {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  color: #64748b;
  min-width: 220px;
}
.loading-text {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.thinking-trace {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  margin-bottom: 4px;
}
.trace-step {
  font-size: 12.5px;
  padding: 5px 10px;
  border-radius: 8px;
  background: #f1f5f9;
  color: #475569;
  border-left: 3px solid #93c5fd;
  animation: trace-in 0.3s ease;
}
.trace-route { border-left-color: #60a5fa; }
.trace-tool { border-left-color: #fbbf24; }
.trace-tool-end { border-left-color: #34d399; }
.trace-cache { border-left-color: #a78bfa; }
.trace-args {
  color: #94a3b8;
  font-size: 11.5px;
  margin-left: 4px;
}
@keyframes trace-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.input-area {
  padding: 16px 28px 20px;
  background: #ffffff;
  border-top: 1px solid #e7edf7;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.send-btn {
  align-self: flex-end;
  width: 110px;
  border-radius: 10px;
}

/* P3 安全认证体系：登录弹窗 + 用户信息区样式 */
.logout-btn {
  margin-left: auto;
  color: #94a3b8;
}
.logout-btn:hover {
  color: #f8fafc;
}
.login-error {
  color: #ef4444;
  font-size: 13px;
  margin-bottom: 8px;
  padding: 6px 10px;
  background: #fef2f2;
  border-radius: 6px;
  border: 1px solid #fecaca;
}
.login-tip {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
  padding: 8px 10px;
  background: #f1f5f9;
  border-radius: 6px;
  line-height: 1.6;
}
.login-tip code {
  background: #e2e8f0;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: #0f172a;
}
</style>
