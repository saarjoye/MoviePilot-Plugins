<template>
  <v-card flat class="task-center-page">
    <v-card-item class="px-0 pt-0">
      <v-card-title>DC助手 · 任务中心</v-card-title>
      <v-card-subtitle>源、容器、更新进度和日志</v-card-subtitle>
      <template #append>
        <div class="d-flex align-center gap-2">
          <v-btn icon color="primary" variant="text" :loading="loading" @click="loadState">
            <v-icon>mdi-refresh</v-icon>
          </v-btn>
          <v-btn v-if="showSettingsButton" icon color="primary" variant="text" @click="emit('switch')">
            <v-icon>mdi-cog</v-icon>
          </v-btn>
        </div>
      </template>
    </v-card-item>

    <v-card-text class="px-0">
      <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
        {{ error }}
      </v-alert>
      <v-alert v-if="message" :type="messageType" variant="tonal" class="mb-4">
        {{ message }}
      </v-alert>

      <v-row dense>
        <v-col v-for="metric in metrics" :key="metric.label" cols="6" sm="4" md="2">
          <v-card variant="outlined" class="metric-card">
            <v-card-text>
              <div :class="['text-h4', 'font-weight-bold', `text-${metric.color}`]">
                {{ metric.value }}
              </div>
              <div class="text-body-2 text-medium-emphasis">{{ metric.label }}</div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2" align="stretch">
        <v-col cols="12" md="2">
          <v-card variant="outlined" class="source-panel fill-height">
            <v-card-title>源概览</v-card-title>
            <v-card-subtitle>选中一个源后，右侧容器与日志同步联动</v-card-subtitle>
            <v-card-text>
              <div class="chip-row mb-3">
                <v-btn
                  v-for="filter in sourceFilters"
                  :key="filter.value"
                  size="small"
                  rounded="lg"
                  :color="sourceFilter === filter.value ? 'primary' : undefined"
                  :variant="sourceFilter === filter.value ? 'flat' : 'tonal'"
                  @click="sourceFilter = filter.value"
                >
                  {{ filter.title }}
                </v-btn>
              </div>

              <div class="table-shell table-shell-sm">
                <v-table density="compact" class="source-table">
                  <thead>
                    <tr>
                      <th>源</th>
                      <th>状态</th>
                      <th>容器</th>
                      <th>自动</th>
                      <th>可升级</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="source in filteredSourceStates"
                      :key="source.id"
                      :class="{ 'is-selected': activeSource === source.id }"
                      @click="setActiveSource(source.id)"
                    >
                      <td class="font-weight-medium text-truncate">{{ source.name || source.id }}</td>
                      <td>
                        <v-chip size="x-small" :color="sourceColor(source)" variant="tonal">
                          {{ source.state || (source.enabled === false ? '停用' : '未知') }}
                        </v-chip>
                      </td>
                      <td>{{ source.container_count || 0 }}</td>
                      <td>{{ source.selected_auto_count || 0 }}</td>
                      <td class="font-weight-bold">{{ source.auto_updatable_count || 0 }}</td>
                    </tr>
                    <tr v-if="!filteredSourceStates.length">
                      <td colspan="5" class="text-medium-emphasis">当前筛选下暂无源。</td>
                    </tr>
                  </tbody>
                </v-table>
              </div>

              <div class="current-source-box mt-5">
                <div class="text-caption text-medium-emphasis">当前源</div>
                <div class="text-h5 font-weight-bold">{{ currentSourceTitle }}</div>
                <div class="source-summary-line mt-3">
                  <span>更新通知容器</span>
                  <strong class="text-primary">{{ selectedSourceSummary.notify }}</strong>
                </div>
                <div class="source-summary-line">
                  <span>自动更新容器</span>
                  <strong class="text-success">{{ selectedSourceSummary.auto }}</strong>
                </div>
                <div class="source-summary-line">
                  <span>可自动升级</span>
                  <strong class="text-error">{{ selectedSourceSummary.updatable }}</strong>
                </div>
              </div>

            </v-card-text>
          </v-card>
        </v-col>

        <v-col cols="12" md="10">
          <v-card variant="outlined" class="ops-panel">
            <v-card-title>容器操作台</v-card-title>
            <v-card-subtitle>通知列 = 收到更新提醒；自动列 = 进入自动升级队列</v-card-subtitle>
            <v-card-text>
              <div class="chip-row mb-3">
                <v-btn
                  v-for="tab in sourceTabs"
                  :key="tab.value"
                  size="small"
                  rounded="lg"
                  :color="activeSource === tab.value ? 'primary' : undefined"
                  :variant="activeSource === tab.value ? 'flat' : 'tonal'"
                  @click="setActiveSource(tab.value)"
                >
                  {{ tab.title }}
                </v-btn>
              </div>

              <div class="ops-toolbar mb-3">
                <v-text-field
                  v-model="search"
                  density="compact"
                  variant="outlined"
                  hide-details
                  clearable
                  prepend-inner-icon="mdi-magnify"
                  placeholder="搜索容器 / 镜像"
                />
                <div class="ops-actions">
                  <v-btn variant="tonal" :loading="loading" @click="loadState">
                    <v-icon start>mdi-refresh</v-icon>
                    刷新容器
                  </v-btn>
                  <v-btn color="primary" :disabled="!actionableContainers.length" @click="openBatchDialog">
                    <v-icon start>mdi-upload</v-icon>
                    批量升级
                  </v-btn>
                  <v-btn v-if="showSettingsButton" variant="tonal" @click="emit('switch')">
                    <v-icon start>mdi-cog</v-icon>
                    同步源
                  </v-btn>
                </div>
              </div>

              <v-card variant="outlined" class="progress-panel mb-3">
                <v-card-title>更新进度</v-card-title>
                <v-card-subtitle>显示已提交和正在执行的 DockerCopilot 更新任务，失败时保留脱敏后的详细日志</v-card-subtitle>
                <v-card-text>
                  <div v-if="!visibleProgressTasks.length" class="empty-progress text-medium-emphasis">
                    暂无更新中的容器。点击“升级”或“批量升级”后会在这里显示任务进度。
                  </div>
                  <div v-else class="progress-list">
                    <div v-for="task in visibleProgressTasks" :key="task.task_id" class="progress-item">
                      <div class="progress-main">
                        <div class="progress-title">
                          <div class="font-weight-bold text-truncate max-container">{{ task.container }}</div>
                          <div class="text-caption text-medium-emphasis">
                            {{ task.source }} · {{ task.scene }} · {{ shortTime(task.updated_at) }}
                          </div>
                        </div>
                        <v-chip size="small" :color="progressColor(task)" variant="tonal">
                          {{ task.status || '-' }}
                        </v-chip>
                      </div>
                      <div class="text-caption text-medium-emphasis text-truncate max-progress-image">
                        {{ task.image || '-' }}
                      </div>
                      <v-progress-linear
                        class="mt-2"
                        :model-value="Number(task.percent || 0)"
                        :color="progressColor(task)"
                        height="8"
                        rounded
                      />
                      <div class="progress-message mt-2">
                        <span>{{ task.message || '-' }}</span>
                        <strong>{{ Number(task.percent || 0) }}%</strong>
                      </div>
                      <v-alert
                        v-if="isProgressFailed(task)"
                        type="error"
                        variant="tonal"
                        density="compact"
                        class="mt-2"
                      >
                        {{ task.reason || task.message || '更新失败，未返回详细原因' }}
                        <div v-if="Array.isArray(task.logs) && task.logs.length" class="progress-log-list mt-2">
                          <div v-for="log in task.logs.slice(0, 4)" :key="`${task.task_id}-${log.time}-${log.status}`">
                            {{ shortTime(log.time) }} · {{ log.status }} · {{ log.message || log.reason || '-' }}
                          </div>
                        </div>
                      </v-alert>
                    </div>
                  </div>
                </v-card-text>
              </v-card>

              <div class="table-shell table-shell-lg">
                <v-table density="comfortable" class="container-table">
                  <thead>
                    <tr>
                      <th>容器</th>
                      <th>镜像</th>
                      <th>更新通知</th>
                      <th>自动更新</th>
                      <th>最近结果</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="container in operationContainers" :key="container.key">
                      <td>
                        <div class="font-weight-bold text-truncate max-container">{{ container.name }}</div>
                        <div class="text-caption text-medium-emphasis">{{ container.source_name }}</div>
                      </td>
                      <td class="text-truncate max-image">{{ container.usingImage || '-' }}</td>
                      <td>
                        <v-chip size="small" :color="container.selected_notify ? 'primary' : undefined" variant="tonal">
                          {{ yesNo(container.selected_notify) }}
                        </v-chip>
                      </td>
                      <td>
                        <v-chip size="small" :color="container.selected_auto ? 'success' : undefined" variant="tonal">
                          {{ yesNo(container.selected_auto) }}
                        </v-chip>
                      </td>
                      <td>
                        <v-chip size="small" :color="lastResultColor(container)" variant="tonal">
                          {{ lastResultText(container) }}
                        </v-chip>
                      </td>
                      <td>
                        <v-btn
                          v-if="canManualUpgrade(container)"
                          color="primary"
                          size="small"
                          variant="flat"
                          @click="openManualDialog(container)"
                        >
                          升级
                        </v-btn>
                        <span v-else class="text-medium-emphasis">无需操作</span>
                      </td>
                    </tr>
                    <tr v-if="!operationContainers.length">
                      <td colspan="6" class="text-medium-emphasis">
                        暂无容器。请确认源已保存、DC 地址包含正确端口、服务可访问且 secretKey 正确。
                      </td>
                    </tr>
                  </tbody>
                </v-table>
              </div>
            </v-card-text>
          </v-card>

          <v-row class="mt-3">
            <v-col cols="12" md="7">
              <v-card variant="outlined" class="fill-height">
                <v-card-title>最近日志</v-card-title>
                <v-card-subtitle>更新、成功、失败按任务结果聚合</v-card-subtitle>
                <v-card-text>
                  <v-row dense>
                    <v-col v-for="item in filteredLogMetrics" :key="item.label" cols="4">
                      <div class="log-summary-box">
                        <div :class="['text-h5', 'font-weight-bold', `text-${item.color}`]">{{ item.value }}</div>
                        <div class="text-caption text-medium-emphasis">{{ item.label }}</div>
                      </div>
                    </v-col>
                  </v-row>

                  <div class="table-shell table-shell-md mt-3">
                    <v-table density="compact">
                      <thead>
                        <tr>
                          <th>时间</th>
                          <th>类型</th>
                          <th>源</th>
                          <th>容器</th>
                          <th>结果</th>
                          <th>说明/原因</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="item in visibleLogs" :key="`${item.time}-${item.type}-${item.source}-${item.container}`">
                          <td class="log-time">{{ shortTime(item.time) }}</td>
                          <td>{{ item.type }}</td>
                          <td>{{ item.source }}</td>
                          <td class="text-truncate max-container">{{ item.container }}</td>
                          <td>
                            <v-chip size="x-small" :color="logResultColor(item)" variant="tonal">
                              {{ displayLogResult(item) }}
                            </v-chip>
                          </td>
                          <td class="text-truncate max-message">{{ item.message }}</td>
                        </tr>
                        <tr v-if="!visibleLogs.length">
                          <td colspan="6" class="text-medium-emphasis">
                            暂无执行日志，触发更新通知、自动更新、手动升级或镜像清理后显示。
                          </td>
                        </tr>
                      </tbody>
                    </v-table>
                  </div>

                  <div class="text-body-2 text-medium-emphasis mt-3">
                    日志格式固定为 source / container / image / reason；映射不到容器时记录 container=unknown。
                  </div>
                </v-card-text>
              </v-card>
            </v-col>

            <v-col cols="12" md="5">
              <v-card variant="outlined" class="fill-height">
                <v-card-title>执行摘要</v-card-title>
                <v-card-subtitle>确认升级前先看当前源与日志结果</v-card-subtitle>
                <v-card-text>
                  <div class="summary-title">{{ currentSourceTitle }}</div>
                  <div class="summary-row">
                    <span>更新通知容器</span>
                    <strong class="text-primary">{{ selectedSourceSummary.notify }}</strong>
                  </div>
                  <div class="summary-row">
                    <span>自动更新容器</span>
                    <strong class="text-success">{{ selectedSourceSummary.auto }}</strong>
                  </div>
                  <div class="summary-row">
                    <span>可自动升级</span>
                    <strong class="text-error">{{ selectedSourceSummary.updatable }}</strong>
                  </div>
                  <div class="summary-row">
                    <span>上次结果</span>
                    <strong>{{ selectedSourceSummary.lastResult }}</strong>
                  </div>

                  <v-alert type="warning" variant="tonal" density="compact" class="mt-4">
                    手动升级更适合临时补救，平时优先依赖自动更新。
                  </v-alert>
                  <div class="text-body-2 text-medium-emphasis mt-3">
                    日志只保留脱敏后的 source/container/image/reason。
                  </div>

                  <div class="manual-preview mt-4">
                    <div class="text-subtitle-1 font-weight-bold">确认手动升级</div>
                    <div class="text-body-2 mt-2">
                      当前候选：{{ actionableContainers[0]?.name || '暂无可升级容器' }}
                    </div>
                    <div class="text-caption text-medium-emphasis mt-1">
                      手动升级任务会先提交，再通过日志查看最终结果。
                    </div>
                  </div>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </v-col>
      </v-row>
    </v-card-text>

    <v-dialog v-model="confirmDialog" max-width="480">
      <v-card>
        <v-card-title>确认手动升级</v-card-title>
        <v-card-text>
          <div class="dialog-line">源：{{ selectedContainer?.source_name || '-' }}</div>
          <div class="dialog-line">容器：{{ selectedContainer?.name || '-' }}</div>
          <div class="dialog-line text-medium-emphasis">当前镜像：{{ selectedContainer?.usingImage || '-' }}</div>
          <v-alert type="warning" variant="tonal" class="mt-4">
            手动升级只表示任务提交成功，不代表容器已经更新完成，请稍后看日志和结果。
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="tonal" :disabled="manualLoading" @click="confirmDialog = false">取消</v-btn>
          <v-btn color="primary" :loading="manualLoading" @click="confirmManualUpgrade">确认升级</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="batchDialog" max-width="520">
      <v-card>
        <v-card-title>确认批量升级</v-card-title>
        <v-card-text>
          <div class="text-body-2">
            将按当前筛选条件提交 {{ actionableContainers.length }} 个可更新容器的升级任务。
          </div>
          <div class="batch-list mt-3">
            <div v-for="container in actionableContainers" :key="`batch-${container.key}`" class="batch-row">
              <span>{{ container.source_name }}</span>
              <strong>{{ container.name }}</strong>
            </div>
          </div>
          <v-alert type="warning" variant="tonal" class="mt-4">
            批量升级会逐个提交现有手动升级接口，失败项会保留在执行日志中。
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="tonal" :disabled="batchLoading" @click="batchDialog = false">取消</v-btn>
          <v-btn color="primary" :loading="batchLoading" @click="confirmBatchUpgrade">确认批量升级</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-card>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  api: {
    type: Object,
    default: null,
  },
  showSwitch: {
    type: Boolean,
    default: true,
  },
  show_switch: {
    type: Boolean,
    default: undefined,
  },
})

const emit = defineEmits(['switch'])

const loading = ref(false)
const manualLoading = ref(false)
const batchLoading = ref(false)
const error = ref('')
const message = ref('')
const messageType = ref('info')
const search = ref('')
const activeSource = ref('all')
const sourceFilter = ref('all')
const confirmDialog = ref(false)
const batchDialog = ref(false)
const selectedContainer = ref(null)
const refreshTimer = ref(null)

const state = reactive({
  sources: [],
  source_states: [],
  containers: [],
  logs: [],
  progress_tasks: [],
  updatablelist: [],
  autoupdatelist: [],
  metrics: {},
})

const sourceFilters = [
  { title: '全部', value: 'all' },
  { title: '在线', value: 'online' },
  { title: '可升级', value: 'updatable' },
  { title: '有失败', value: 'failed' },
]

const sourceStates = computed(() => Array.isArray(state.source_states) ? state.source_states : [])
const containers = computed(() => Array.isArray(state.containers) ? state.containers : [])
const updateLogs = computed(() => Array.isArray(state.logs) ? state.logs : [])
const progressTasks = computed(() => Array.isArray(state.progress_tasks) ? state.progress_tasks : [])
const showSettingsButton = computed(() => props.show_switch ?? props.showSwitch)
const sourceTabs = computed(() => [
  { title: '全部', value: 'all' },
  ...sourceStates.value.map(source => ({
    title: source.name || source.id,
    value: source.id,
  })),
])
const metrics = computed(() => [
  { label: '已配置源', value: state.metrics?.sources || 0, color: 'primary' },
  { label: '已选自动更新', value: state.metrics?.auto_selected || 0, color: 'warning' },
  { label: '可自动升级', value: state.metrics?.auto_updatable || 0, color: 'error' },
  { label: '待处理容器', value: state.metrics?.updatable || pendingContainers.value.length, color: 'primary' },
  { label: '更新中', value: state.metrics?.progress_running || runningProgressTasks.value.length, color: 'primary' },
  { label: '失败', value: state.metrics?.logs_failed || 0, color: 'error' },
])
const currentSourceTitle = computed(() => tabLabel(activeSource.value))
const filteredLogs = computed(() => logsBySource(updateLogs.value, activeSource.value))
const visibleLogs = computed(() => filteredLogs.value.slice(0, 8))
const filteredProgressTasks = computed(() => bySource(progressTasks.value, activeSource.value))
const visibleProgressTasks = computed(() => filteredProgressTasks.value.slice(0, 8))
const runningProgressTasks = computed(() => progressTasks.value.filter(isProgressRunning))
const filteredLogMetrics = computed(() => [
  { label: '更新日志', value: filteredLogs.value.length, color: 'primary' },
  { label: '成功', value: filteredLogs.value.filter(item => displayLogResult(item) === '成功').length, color: 'success' },
  { label: '失败', value: filteredLogs.value.filter(item => !item.success).length, color: 'error' },
])
const filteredSourceStates = computed(() => sourceStates.value.filter(source => {
  if (sourceFilter.value === 'online')
    return source.state === '已连接'
  if (sourceFilter.value === 'updatable')
    return Number(source.auto_updatable_count || 0) > 0
  if (sourceFilter.value === 'failed')
    return source.state === '异常' || logsBySource(updateLogs.value, source.id).some(item => !item.success)
  return true
}))
const operationContainers = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return [...bySource(containers.value, activeSource.value)]
    .filter(container => {
      if (!keyword)
        return true
      return [container.name, container.source_name, container.usingImage]
        .filter(Boolean)
        .some(value => String(value).toLowerCase().includes(keyword))
    })
    .sort((left, right) => containerRank(left) - containerRank(right))
})
const pendingContainers = computed(() => containers.value.filter(container => container.haveUpdate))
const actionableContainers = computed(() => operationContainers.value.filter(canManualUpgrade))
const selectedSourceSummary = computed(() => {
  const scopedContainers = bySource(containers.value, activeSource.value)
  const scopedLogs = logsBySource(updateLogs.value, activeSource.value)
  const lastLog = scopedLogs[0]
  return {
    notify: scopedContainers.filter(item => item.selected_notify).length,
    auto: scopedContainers.filter(item => item.selected_auto).length,
    updatable: scopedContainers.filter(item => item.selected_auto && item.haveUpdate).length,
    lastResult: lastLog ? displayLogResult(lastLog) : '暂无日志',
  }
})

function setActiveSource(value) {
  activeSource.value = value || 'all'
}

function bySource(list, sourceId) {
  if (sourceId === 'all')
    return list
  return list.filter(item => item.source_id === sourceId)
}

function logsBySource(list, sourceId) {
  if (sourceId === 'all')
    return list
  const source = sourceStates.value.find(item => item.id === sourceId)
  return list.filter(item => item.source_id === sourceId || item.source === source?.name || item.source === sourceId)
}

function tabLabel(value) {
  return sourceTabs.value.find(item => item.value === value)?.title || '全部'
}

function ensureActiveSource() {
  const values = new Set(sourceTabs.value.map(item => item.value))
  if (!values.has(activeSource.value))
    activeSource.value = 'all'
}

function yesNo(value) {
  return value ? '是' : '否'
}

function shortTime(value) {
  if (!value)
    return '-'
  return String(value).replace(/^\d{4}-\d{2}-\d{2}\s*/, '')
}

function isSubmittedLog(item) {
  const text = `${item?.result || ''} ${item?.message || ''} ${item?.type || ''}`
  return /任务创建成功|已提交|提交成功/.test(text)
}

function isFailedLog(item) {
  const text = `${item?.result || ''} ${item?.message || ''} ${item?.type || ''}`
  return /失败/.test(text)
}

function displayLogResult(item) {
  if (isFailedLog(item))
    return '失败'
  if (isSubmittedLog(item))
    return '已提交'
  return item?.result || '-'
}

function logResultColor(item) {
  const text = displayLogResult(item)
  if (text === '失败')
    return 'error'
  if (text === '已提交')
    return 'primary'
  if (text === '成功')
    return 'success'
  return undefined
}

function isProgressRunning(task) {
  return ['已提交', '执行中'].includes(task?.status)
}

function isProgressFailed(task) {
  return task?.status === '更新失败'
}

function progressColor(task) {
  if (task?.status === '更新成功')
    return 'success'
  if (task?.status === '更新失败')
    return 'error'
  if (['超时待确认', '远程源无法确认'].includes(task?.status))
    return 'warning'
  return 'primary'
}

function sourceColor(source) {
  if (source.enabled === false || source.state === '停用')
    return 'grey'
  if (source.state === '已连接')
    return 'success'
  if (source.state === '异常')
    return 'error'
  return 'warning'
}

function containerRank(container) {
  if (container.haveUpdate)
    return 0
  if (String(container.last_result || '').includes('失败'))
    return 1
  if (container.selected_auto)
    return 2
  return 3
}

function canManualUpgrade(container) {
  return Boolean(container?.haveUpdate)
}

function lastResultText(container) {
  const combined = `${container?.last_result || ''} ${container?.last_message || ''}`
  if (/任务创建成功|已提交|提交成功/.test(combined))
    return '已提交'
  if (container.haveUpdate)
    return '可升级'
  return container.last_result || '无更新'
}

function lastResultColor(container) {
  const text = lastResultText(container)
  if (text === '已提交')
    return 'primary'
  if (container.haveUpdate)
    return 'error'
  if (text.includes('失败'))
    return 'warning'
  if (text.includes('成功'))
    return 'success'
  if (text.includes('最新'))
    return 'primary'
  return undefined
}

function openManualDialog(container) {
  if (!canManualUpgrade(container))
    return
  selectedContainer.value = container
  confirmDialog.value = true
}

function openBatchDialog() {
  error.value = ''
  message.value = ''
  messageType.value = 'info'
  if (!actionableContainers.value.length) {
    message.value = '当前筛选条件下没有可升级容器。'
    return
  }
  batchDialog.value = true
}

async function runManualUpgrade(container) {
  const result = await props.api.post('plugin/DockerCopilotHelperMulti/manual_update', {
    container_key: container.key,
  })
  return {
    container,
    success: Boolean(result?.success),
    message: result?.message || (result?.success ? '升级任务已提交' : '升级失败'),
  }
}

async function confirmManualUpgrade() {
  error.value = ''
  message.value = ''
  messageType.value = 'info'
  if (!selectedContainer.value?.key)
    return
  if (!props.api?.post) {
    error.value = '当前 MoviePilot 未注入插件 POST API，无法执行手动升级。'
    return
  }
  manualLoading.value = true
  try {
    const result = await runManualUpgrade(selectedContainer.value)
    if (result.success) {
      message.value = '手动升级任务已提交，实际完成后会刷新在日志里。'
      messageType.value = 'info'
      confirmDialog.value = false
      await loadState()
    } else {
      await loadState()
      error.value = result.message || '手动升级失败'
    }
  } catch (err) {
    error.value = `手动升级失败：${err?.message || err}`
  } finally {
    manualLoading.value = false
  }
}

async function confirmBatchUpgrade() {
  error.value = ''
  message.value = ''
  messageType.value = 'info'
  if (!props.api?.post) {
    error.value = '当前 MoviePilot 未注入插件 POST API，无法执行批量升级。'
    return
  }
  const targets = [...actionableContainers.value]
  if (!targets.length) {
    batchDialog.value = false
    return
  }
  batchLoading.value = true
  try {
    const results = []
    for (const container of targets) {
      results.push(await runManualUpgrade(container))
    }
    const successCount = results.filter(item => item.success).length
    const failedCount = results.length - successCount
    batchDialog.value = false
    await loadState()
    if (failedCount) {
      error.value = `批量升级完成：成功 ${successCount} 个，失败 ${failedCount} 个。`
    } else {
      message.value = `批量升级任务已提交：${successCount} 个容器。`
      messageType.value = 'info'
    }
  } catch (err) {
    error.value = `批量升级失败：${err?.message || err}`
  } finally {
    batchLoading.value = false
  }
}

async function loadState() {
  error.value = ''
  if (!props.api?.get) {
    error.value = '当前 MoviePilot 未注入插件 API，无法加载详情数据。'
    return
  }
  loading.value = true
  try {
    const result = await props.api.get('plugin/DockerCopilotHelperMulti/state')
    Object.assign(state, {
      sources: Array.isArray(result?.sources) ? result.sources : [],
      source_states: Array.isArray(result?.source_states) ? result.source_states : [],
      containers: Array.isArray(result?.containers) ? result.containers : [],
      logs: Array.isArray(result?.logs) ? result.logs : [],
      progress_tasks: Array.isArray(result?.progress_tasks) ? result.progress_tasks : [],
      updatablelist: Array.isArray(result?.updatablelist) ? result.updatablelist : [],
      autoupdatelist: Array.isArray(result?.autoupdatelist) ? result.autoupdatelist : [],
      metrics: result?.metrics || {},
    })
    ensureActiveSource()
  } catch (err) {
    error.value = `加载详情失败：${err?.message || err}`
  } finally {
    loading.value = false
  }
}

function startProgressAutoRefresh() {
  stopProgressAutoRefresh()
  refreshTimer.value = window.setInterval(() => {
    if (runningProgressTasks.value.length && !loading.value)
      loadState()
  }, 5000)
}

function stopProgressAutoRefresh() {
  if (refreshTimer.value) {
    window.clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

watch(runningProgressTasks, tasks => {
  if (tasks.length)
    startProgressAutoRefresh()
  else
    stopProgressAutoRefresh()
})

onMounted(loadState)
onBeforeUnmount(stopProgressAutoRefresh)
</script>

<style scoped>
.task-center-page {
  background: transparent;
}
.task-center-page :deep(.v-card-title) {
  font-size: 18px;
  line-height: 1.25;
  padding-bottom: 2px;
}
.task-center-page :deep(.v-card-subtitle) {
  font-size: 13px;
  line-height: 1.35;
  white-space: normal;
}
.task-center-page :deep(.v-card-text) {
  font-size: 14px;
}
.gap-2 {
  gap: 8px;
}
.metric-card {
  height: 100%;
}
.metric-card :deep(.v-card-text) {
  min-height: 72px;
  padding: 8px 14px;
}
.metric-card :deep(.text-h4) {
  font-size: 2rem !important;
  line-height: 1.05;
}
.source-panel,
.ops-panel,
.progress-panel {
  border-radius: 8px;
}
.source-panel :deep(.v-card-text),
.ops-panel :deep(.v-card-text),
.progress-panel :deep(.v-card-text) {
  padding: 12px 16px;
}
.table-shell {
  border: 1px solid rgba(var(--v-border-color), 0.12);
  border-radius: 8px;
  overflow: auto;
}
.source-table,
.container-table {
  min-width: 680px;
}
.container-table {
  min-width: 780px;
}
.table-shell-sm {
  max-height: 300px;
}
.table-shell-md {
  max-height: 220px;
}
.table-shell-lg {
  max-height: 300px;
}
.source-panel .source-table {
  font-size: 12px;
  min-width: 100%;
  table-layout: fixed;
  width: 100%;
}
.source-panel .source-table :deep(th),
.source-panel .source-table :deep(td) {
  height: 34px;
  padding: 0 5px !important;
  white-space: nowrap;
}
.source-panel .source-table :deep(th:nth-child(1)),
.source-panel .source-table :deep(td:nth-child(1)) {
  width: 34%;
}
.source-panel .source-table :deep(th:nth-child(2)),
.source-panel .source-table :deep(td:nth-child(2)) {
  width: 24%;
}
.source-panel .source-table :deep(th:nth-child(3)),
.source-panel .source-table :deep(td:nth-child(3)),
.source-panel .source-table :deep(th:nth-child(4)),
.source-panel .source-table :deep(td:nth-child(4)),
.source-panel .source-table :deep(th:nth-child(5)),
.source-panel .source-table :deep(td:nth-child(5)) {
  text-align: center;
  width: 14%;
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip-row :deep(.v-btn) {
  min-width: 0;
  padding: 0 12px;
}
.ops-toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.ops-toolbar .v-text-field {
  flex: 1 1 260px;
  min-width: 220px;
}
.ops-actions {
  align-items: center;
  display: flex;
  flex: 0 1 auto;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}
.ops-actions :deep(.v-btn) {
  min-width: 0;
}
.source-table tbody tr,
.container-table tbody tr {
  cursor: pointer;
}
.source-table tbody tr.is-selected {
  background: rgba(var(--v-theme-primary), 0.08);
  box-shadow: inset 4px 0 0 rgb(var(--v-theme-primary));
}
.current-source-box,
.manual-preview {
  background: rgba(var(--v-theme-surface-variant), 0.28);
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  padding: 10px 12px;
}
.current-source-box {
  margin-top: 12px !important;
}
.current-source-box :deep(.text-h5) {
  font-size: 18px !important;
  line-height: 1.2;
}
.source-summary-line,
.summary-row {
  align-items: center;
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  line-height: 1.65;
}
.summary-title {
  font-size: 1.5rem;
  font-weight: 800;
  line-height: 1.2;
  margin-bottom: 12px;
}
.log-summary-box {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  padding: 12px 14px;
}
.empty-progress {
  border: 1px dashed rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  padding: 16px;
}
.progress-list {
  display: grid;
  gap: 12px;
  max-height: 220px;
  overflow: auto;
}
.progress-item {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  padding: 10px 12px;
}
.progress-main,
.progress-message {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}
.progress-title {
  min-width: 0;
}
.progress-log-list {
  display: grid;
  gap: 4px;
  font-size: 12px;
  line-height: 1.5;
}
.batch-list {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  max-height: 240px;
  overflow-y: auto;
}
.batch-row {
  align-items: center;
  display: grid;
  gap: 12px;
  grid-template-columns: 120px minmax(0, 1fr);
  min-height: 34px;
  padding: 0 12px;
}
.batch-row + .batch-row {
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
.max-message {
  max-width: 240px;
}
.max-image {
  max-width: 300px;
}
.max-container {
  max-width: 150px;
}
.max-progress-image {
  max-width: 100%;
}
.log-time {
  white-space: nowrap;
}
.dialog-line {
  line-height: 1.9;
}
@media (max-width: 960px) {
  .task-center-page :deep(.v-card-title) {
    font-size: 17px;
  }
  .ops-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .ops-toolbar .v-text-field {
    max-width: none;
    width: 100%;
  }
  .ops-actions {
    justify-content: stretch;
    width: 100%;
  }
  .ops-actions .v-btn {
    flex: 1 1 auto;
  }
  .progress-main,
  .progress-message {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }
}
</style>
