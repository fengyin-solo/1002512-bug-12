<template>
  <section class="page" data-module="trackcircuit">
    <header class="page-head">
      <div>
        <h2>轨道电路管理</h2>
        <p class="page-desc">围绕区段编号、载频类型、发送/接收电平和分路灵敏度做登记、调整与状态跟踪。</p>
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
      <label class="filter-item">
        <span>区段编号</span>
        <input v-model="keyword" placeholder="按区段编号检索" />
      </label>
      <label class="filter-item">
        <span>电路状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
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
            <span v-else>{{ formatCell(row[column], column) }}</span>
          </td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :disabled="isDisabled(row)"
              :title="isDisabled(row) ? '已停用区段不参与参数调整' : ''"
              @click="markOffset(row)"
            >
              记录偏移
            </button>
            <button
              class="link"
              type="button"
              :disabled="isDisabled(row)"
              :title="isDisabled(row) ? '已停用区段不参与参数调整' : ''"
              @click="openAdjust(row)"
            >
              调整参数
            </button>
            <button
              class="link"
              type="button"
              :disabled="isDisabled(row)"
              :title="isDisabled(row) ? '区段已停用' : ''"
              @click="disableRow(row)"
            >
              办理停用
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的轨道电路数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条轨道电路记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 调整参数弹窗：发送/接收电平分两个输入框，避免错位 -->
    <div v-if="adjustTarget" class="modal-mask" @click.self="closeAdjust">
      <div class="modal">
        <h3>调整参数 · {{ adjustTarget['区段编号'] }}</h3>
        <p class="modal-tip">
          当前发送电平 {{ formatLevel(adjustTarget['发送电平']) }}V，
          接收电平 {{ formatLevel(adjustTarget['接收电平']) }}V，
          分路灵敏度 {{ formatLevel(adjustTarget['分路灵敏度']) }}Ω（调整时保持不变）
        </p>
        <form @submit.prevent="submitAdjust">
          <label class="form-item">
            <span>发送电平（V，允许 40~160）</span>
            <input v-model.number="adjustForm['发送电平']" type="number" step="0.1" />
          </label>
          <label class="form-item">
            <span>接收电平（V，允许 0.2~5）</span>
            <input v-model.number="adjustForm['接收电平']" type="number" step="0.01" />
          </label>
          <p v-if="adjustError" class="error-text">{{ adjustError }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="closeAdjust">取消</button>
            <button class="btn primary" type="submit" :disabled="adjusting">
              {{ adjusting ? '提交中…' : '保存调整' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 单条详情：含调整台账，重复提交只显示最近一条 -->
    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <h3>轨道电路明细 · {{ detail['区段编号'] }}</h3>
        <table class="detail-table">
          <tbody>
            <tr v-for="column in columns" :key="column">
              <th>{{ column }}</th>
              <td>{{ formatCell(detail[column], column) }}</td>
            </tr>
          </tbody>
        </table>
        <h4>调整台账</h4>
        <table v-if="detail['调整台账']?.length" class="data-table">
          <thead>
            <tr><th>调整时间</th><th>发送电平(V)</th><th>接收电平(V)</th></tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in detail['调整台账']" :key="idx">
              <td>{{ item['时间'] }}</td>
              <td>{{ formatLevel(item['发送电平']) }}</td>
              <td>{{ formatLevel(item['接收电平']) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state">暂无调整记录</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type LedgerItem = { 时间: string; 发送电平: number; 接收电平: number }
type Detail = Row & { 调整台账?: LedgerItem[] }

const ENDPOINT = '/api/trackcircuit'
const columns = ["区段编号", "所属区间", "载频类型", "发送电平", "接收电平", "调整状态", "分路灵敏度", "电路状态"]
const statuses = ["调整良好", "参数偏移", "分路不良", "已停用"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const stats = computed(() => [
  { label: '良好区段', value: rows.value.filter(r => r['电路状态'] === '调整良好').length },
  { label: '偏移区段', value: rows.value.filter(r => r['电路状态'] === '参数偏移').length },
  { label: '分路不良区段', value: rows.value.filter(r => r['电路状态'] === '分路不良').length },
  { label: '已停用区段', value: rows.value.filter(r => isDisabled(r)).length },
])

const detail = ref<Detail | null>(null)
const adjustTarget = ref<Row | null>(null)
const adjustForm = reactive<{ 发送电平: number | ''; 接收电平: number | '' }>({ 发送电平: '', 接收电平: '' })
const adjustError = ref('')
const adjusting = ref(false)

function isDisabled(row: Row) {
  return row['电路状态'] === '已停用' || row['status'] === '已停用'
}

function formatLevel(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? String(num) : '—'
}

function formatCell(value: unknown, column: string): string {
  if (column === '发送电平' || column === '接收电平') return value === null || value === undefined ? '—' : `${formatLevel(value)}V`
  if (column === '分路灵敏度') return value === null || value === undefined ? '—' : `${formatLevel(value)}Ω`
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '轨道电路登记入口尚未接入审批流'
}

// 统一处理后端返回的失败原因（ActionResult.ok=false 时原因在 message 里）
async function readFailure(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string; message?: string }
    return payload.detail ?? payload.message ?? fallback
  } catch {
    return fallback
  }
}

async function markOffset(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: '记录偏移' } }),
    })
    const payload = (await response.json()) as { ok: boolean; message?: string }
    if (!response.ok || !payload.ok) {
      errorMessage.value = payload.message ?? '记录偏移未生效'
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '记录偏移失败'
  }
}

async function disableRow(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: '办理停用' } }),
    })
    const payload = (await response.json()) as { ok: boolean; message?: string }
    if (!response.ok || !payload.ok) {
      errorMessage.value = payload.message ?? '办理停用未生效'
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '办理停用失败'
  }
}

function openAdjust(row: Row) {
  adjustTarget.value = row
  adjustForm['发送电平'] = Number(row['发送电平']) || ''
  // 接收电平单独取数，不能和发送电平串位
  adjustForm['接收电平'] = Number(row['接收电平']) || ''
  adjustError.value = ''
}

function closeAdjust() {
  adjustTarget.value = null
  adjustError.value = ''
}

async function submitAdjust() {
  if (!adjustTarget.value) return
  adjustError.value = ''
  if (adjustForm['发送电平'] === '' || adjustForm['接收电平'] === '') {
    adjustError.value = '请先填写发送电平和接收电平'
    return
  }
  adjusting.value = true
  try {
    const response = await request(`${ENDPOINT}/${adjustTarget.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          action: '调整参数',
          发送电平: adjustForm['发送电平'],
          接收电平: adjustForm['接收电平'],
        },
      }),
    })
    const payload = (await response.json()) as { ok: boolean; message?: string }
    if (!response.ok || !payload.ok) {
      // 越界等原因由后端明确给出，直接展示是哪个电平不合法
      adjustError.value = payload.message ?? '调整参数未保存'
      return
    }
    closeAdjust()
    await reload()
  } catch (error) {
    adjustError.value = error instanceof Error ? error.message : '调整参数请求失败'
  } finally {
    adjusting.value = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      errorMessage.value = await readFailure(response, `轨道电路明细读取失败（${response.status}）`)
      return
    }
    detail.value = (await response.json()) as Detail
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '轨道电路明细读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      errorMessage.value = await readFailure(response, '轨道电路列表读取失败')
      return
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 分路灵敏度由后端持久化：调整参数不改这个字段，刷新重新拉取后仍是原值
  } catch (error) {
    // 接口读取失败（网络中断等）说明原因，并保留页面上已有的数据不清空
    errorMessage.value = error instanceof Error ? error.message : '轨道电路列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 8px;
  padding: 18px 20px;
  width: 480px;
  max-height: 80vh;
  overflow: auto;
}
.modal h3 { margin: 0 0 8px; font-size: 16px; }
.modal h4 { margin: 14px 0 6px; font-size: 14px; }
.modal-tip { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
.form-item { display: block; margin-bottom: 10px; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item input { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.detail-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.detail-table th, .detail-table td { border: 1px solid var(--border); padding: 6px 8px; text-align: left; }
.detail-table th { width: 110px; background: #f8fafc; color: var(--muted); font-weight: normal; }
.link:disabled { color: #94a3b8; cursor: not-allowed; }
select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
</style>
