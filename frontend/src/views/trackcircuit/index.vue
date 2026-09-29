<template>
  <section class="page" data-module="trackcircuit">
    <header class="page-head">
      <div>
        <h2>轨道电路管理</h2>
        <p class="page-desc">维护轨道电路，围绕区段编号、所属区间、载频类型、发送/接收电平做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记轨道电路</button>
        <button class="btn" type="button" @click="exportRows">导出轨道电路清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>电路状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="st in statuses" :key="st" :value="st">{{ st }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '区段编号'" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ formatCell(column, row[column]) }}</template>
          </td>
          <td class="row-actions">
            <template v-if="isDisabled(row)">
              <span class="muted-text">已停用，不可调整</span>
            </template>
            <template v-else>
              <button class="link" type="button" @click="runAction('记录偏移', row)">记录偏移</button>
              <button class="link" type="button" @click="openAdjust(row)">调整参数</button>
              <button class="link danger" type="button" @click="runAction('办理停用', row)">办理停用</button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无轨道电路数据，可先登记轨道电路</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条轨道电路记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>

    <!-- 调整参数弹窗：发送/接收电平分开填写，分路灵敏度只读且原样保留 -->
    <div v-if="adjust.open" class="modal-mask" @click.self="closeAdjust">
      <div class="modal">
        <h3>调整参数 · {{ adjust.section }}</h3>
        <p class="page-desc">允许范围：发送电平 100~140 V；接收电平 240~1000 mV。分路灵敏度不随本次调整改动。</p>
        <div class="form-grid">
          <label>
            <span>发送电平（V）</span>
            <input v-model="adjust.sendLevel" type="number" step="0.1" />
          </label>
          <label>
            <span>接收电平（mV）</span>
            <input v-model="adjust.receiveLevel" type="number" step="1" />
          </label>
          <label>
            <span>分路灵敏度（Ω，保留原值）</span>
            <input :value="formatCell('分路灵敏度', adjust.sensitivity)" disabled />
          </label>
        </div>
        <p v-if="adjust.error" class="error-text">{{ adjust.error }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" :disabled="adjust.loading" @click="closeAdjust">取消</button>
          <button class="btn primary" type="button" :disabled="adjust.loading" @click="submitAdjust">
            {{ adjust.loading ? '保存中…' : '保存调整' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 区段详情：结论与列表同源，并附最近一次调整台账记录 -->
    <div v-if="detail.open" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <h3>区段详情 · {{ detail.row?.['区段编号'] }}</h3>
        <table class="detail-table">
          <tbody>
            <tr v-for="column in columns" :key="column">
              <th>{{ column }}</th>
              <td>{{ formatCell(column, detail.row?.[column]) }}</td>
            </tr>
          </tbody>
        </table>
        <h4>最近一次调整台账</h4>
        <p v-if="detail.loading" class="page-desc">正在读取调整记录…</p>
        <p v-else-if="detail.error" class="error-text">{{ detail.error }}</p>
        <p v-else-if="!detail.adjustment" class="page-desc">该区段暂无调整记录</p>
        <table v-else class="detail-table">
          <tbody>
            <tr><th>发送电平（V）</th><td>{{ detail.adjustment['发送电平'] }}</td></tr>
            <tr><th>接收电平（mV）</th><td>{{ detail.adjustment['接收电平'] }}</td></tr>
            <tr><th>分路灵敏度（Ω）</th><td>{{ detail.adjustment['分路灵敏度'] }}</td></tr>
            <tr><th>调整时间</th><td>{{ detail.adjustment['调整时间'] }}</td></tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null | boolean>

interface ApiResult {
  ok: boolean
  message: string
  entry: Row | null
}

const ENDPOINT = '/api/trackcircuit'
const columns = ['区段编号', '所属区间', '载频类型', '发送电平', '接收电平', '调整状态', '分路灵敏度', '电路状态']
const statuses = ['调整良好', '参数偏移', '分路不良', '已停用']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})
const statusFilter = ref('')
const filterFields = columns.slice(0, 3)

// 统计卡片随列表数据实时计算，和表格里的电路状态保持同一口径
const stats = computed(() => [
  { label: '良好区段', value: rows.value.filter((row) => row['电路状态'] === '调整良好').length },
  { label: '偏移区段', value: rows.value.filter((row) => row['电路状态'] === '参数偏移').length },
  { label: '分路不良区段', value: rows.value.filter((row) => row['电路状态'] === '分路不良').length },
])

let messageTimer: ReturnType<typeof setTimeout> | undefined
function flashSuccess(message: string) {
  successMessage.value = message
  clearTimeout(messageTimer)
  messageTimer = setTimeout(() => {
    successMessage.value = ''
  }, 4000)
}

function isDisabled(row: Row) {
  return row['电路状态'] === '已停用'
}

function formatCell(column: string, value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  if (column === '发送电平') return `${Number(value)} V`
  if (column === '接收电平') return `${Number(value)} mV`
  if (column === '分路灵敏度') return `${Number(value)} Ω`
  return String(value)
}

function resetFilters() {
  filters.value = {}
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '轨道电路登记入口尚未接入审批流'
}

/** 统一解析动作接口：HTTP 失败和后端 ok=false 都要把原因带出来，不能只报“操作失败”。 */
async function postAction(id: number | string, values: Record<string, unknown>): Promise<ApiResult> {
  let response: Response
  try {
    response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : '接口请求未送达', entry: null }
  }
  try {
    const payload = (await response.json()) as ApiResult
    if (!response.ok || payload.ok === false) {
      return { ok: false, message: payload.message || `接口返回 ${response.status}，操作未生效`, entry: null }
    }
    return payload
  } catch {
    return { ok: false, message: `接口返回 ${response.status}，响应内容无法解析`, entry: null }
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const result = await postAction(String(row.id), { action })
  if (!result.ok) {
    errorMessage.value = result.message
    return
  }
  flashSuccess(result.message)
  await reload()
}

// ---------------------------------------------------------------- 调整参数弹窗
const adjust = reactive({
  open: false,
  loading: false,
  error: '',
  id: 0,
  section: '',
  sendLevel: '',
  receiveLevel: '',
  sensitivity: '' as string | number,
})

function openAdjust(row: Row) {
  adjust.open = true
  adjust.error = ''
  adjust.id = Number(row.id)
  adjust.section = String(row['区段编号'])
  // 回填当前电平；分路灵敏度仅展示，提交时不带，保证刷新后仍是原值
  adjust.sendLevel = String(row['发送电平'] ?? '')
  adjust.receiveLevel = String(row['接收电平'] ?? '')
  adjust.sensitivity = (row['分路灵敏度'] ?? '') as string | number
}

function closeAdjust() {
  adjust.open = false
  adjust.error = ''
}

async function submitAdjust() {
  adjust.error = ''
  adjust.loading = true
  try {
    const result = await postAction(adjust.id, {
      action: '调整参数',
      发送电平: adjust.sendLevel,
      接收电平: adjust.receiveLevel,
    })
    if (!result.ok) {
      adjust.error = result.message
      return
    }
    closeAdjust()
    flashSuccess(result.message)
    await reload()
  } finally {
    adjust.loading = false
  }
}

// ---------------------------------------------------------------- 区段详情弹窗
const detail = reactive<{
  open: boolean
  loading: boolean
  error: string
  row: Row | null
  adjustment: Record<string, unknown> | null
}>({
  open: false,
  loading: false,
  error: '',
  row: null,
  adjustment: null,
})

async function openDetail(row: Row) {
  detail.open = true
  detail.loading = true
  detail.error = ''
  detail.row = row
  detail.adjustment = null
  try {
    const response = await request(`${ENDPOINT}/${row.id}/adjustment`)
    if (!response.ok) {
      let reason = `接口返回 ${response.status}`
      try {
        const payload = (await response.json()) as { detail?: string }
        reason = payload.detail || reason
      } catch {
        /* 保留状态码原因 */
      }
      detail.error = `调整记录读取失败：${reason}`
      return
    }
    const payload = (await response.json()) as { item: Record<string, unknown> | null; message?: string }
    detail.adjustment = payload.item
  } catch (error) {
    detail.error = `调整记录读取失败：${error instanceof Error ? error.message : '接口请求未送达'}`
  } finally {
    detail.loading = false
  }
}

function closeDetail() {
  detail.open = false
  detail.row = null
  detail.adjustment = null
  detail.error = ''
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  Object.entries(filters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      let reason = `接口返回 ${response.status}`
      try {
        const payload = (await response.json()) as { detail?: string }
        reason = payload.detail || reason
      } catch {
        /* 保留状态码原因 */
      }
      throw new Error(`轨道电路列表读取失败：${reason}`)
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '轨道电路列表读取失败：接口请求未送达'
  }
}

onMounted(reload)
</script>

<style scoped>
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.success-text {
  color: #15803d;
}
.link.danger {
  color: #b42318;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgb(16 24 40 / 45%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 520px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal h3 {
  margin: 0 0 6px;
}
.modal h4 {
  margin: 14px 0 6px;
  font-size: 14px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 12px;
  margin: 12px 0;
}
.form-grid label:last-child {
  grid-column: 1 / -1;
}
.form-grid span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.form-grid input,
.filter-item select {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.form-grid input:disabled {
  background: #f1f5f9;
  color: var(--muted);
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.detail-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 6px;
}
.detail-table th,
.detail-table td {
  border: 1px solid var(--border);
  padding: 6px 10px;
  font-size: 13px;
  text-align: left;
}
.detail-table th {
  width: 42%;
  background: #f8fafc;
  color: var(--muted);
  font-weight: normal;
}
</style>
