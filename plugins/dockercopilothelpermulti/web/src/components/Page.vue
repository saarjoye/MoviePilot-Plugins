<template>
  <v-card flat class="task-center-page">
    <v-card-item class="px-0 pt-0">
      <v-card-title>DC助手 · 任务中心增强</v-card-title>
      <v-card-subtitle>按源查看任务、容器、手动升级与执行日志</v-card-subtitle>
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
      <v-alert v-if="message" type="success" variant="tonal" class="mb-4">
        {{ message }}
      </v-alert>

      <v-row>
        <v-col cols="6" md="2" v-for="metric in metrics" :key="metric.label">
          <v-card variant="outlined" class="metric-card">
            <v-card-text>
              <div :class="['text-h4', 'font-weight-bold', `text-${metric.color}`]">{{ metric.value }}</div>
              <div class="text-body-2 text-medium-emphasis">{{ metric.label }}</div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2">
        <v-col cols="12">
          <v-card variant="outlined">
            <v-card-title>DockerCopilot 源状态</v-card-title>
            <v-card-subtitle>可自动升级仅统计已勾选自动更新且当前可更新的容器</v-card-subtitle>
            <v-table density="comfortable" class="mt-2">
              <thead>
                <tr>
                  <th>源名称</th>
                  <th>源ID</th>
                  <th>状态</th>
                  <th>容器</th>
                  <th>已选自动更新</th>
                  <th>可自动升级</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="source in sourceStates" :key="source.id">
                  <td>{{ source.name || source.id }}</td>
                  <td><code>{{ source.id }}</code></td>
                  <td>
                    <v-chip size="small" :color="sourceColor(source)" variant="tonal">
                      {{ source.state || (source.enabled === false ? '停用' : '未知') }}
                    </v-chip>
                  </td>
                  <td>{{ source.container_count || 0 }}</td>
                  <td>{{ source.selected_auto_count || 0 }}</td>
                  <td class="font-weight-medium">{{ source.auto_updatable_count || 0 }}</td>
                  <td class="text-truncate max-message">{{ source.message || '-' }}</td>
                </tr>
                <tr v-if="!sourceStates.length">
                  <td colspan="7" class="text-medium-emphasis">暂无源，请先进入配置页新增并保存 DC 源。</td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2">
        <v-col cols="12" md="6">
          <v-card variant="outlined" class="fill-height">
            <v-card-title>任务选择</v-card-title>
            <v-card-subtitle>点击源标签后，仅显示该源已配置容器</v-card-subtitle>
            <v-card-text>
              <v-tabs v-model="activeTaskSource" density="compact" show-arrows>
                <v-tab v-for="tab in sourceTabs" :key="`task-${tab.value}`" :value="tab.value">
                  {{ tab.title }}
                </v-tab>
              </v-tabs>
              <div class="text-body-2 text-medium-emphasis mt-3 mb-4">
                当前显示：{{ activeTaskSourceLabel }} 源已配置容器
              </div>

              <div class="task-group">
                <div class="section-label">更新通知容器</div>
                <div v-for="container in taskNotifyContainers" :key="`notify-${container.key}`" class="task-row">
                  <v-icon color="primary" size="18">mdi-checkbox-marked-circle</v-icon>
                  <span class="task-name">{{ container.name }}</span>
                  <v-chip size="x-small" :color="container.haveUpdate ? 'error' : 'success'" variant="tonal">
                    {{ container.haveUpdate ? '可升级' : '运行中' }}
                  </v-chip>
                </div>
                <div v-if="!taskNotifyContainers.length" class="empty-line">当前筛选范围未选择更新通知容器</div>
              </div>

              <div class="task-group mt-5">
                <div class="section-label">自动更新容器</div>
                <div v-for="container in taskAutoContainers" :key="`auto-${container.key}`" class="task-row">
                  <v-icon color="success" size="18">mdi-checkbox-marked-circle</v-icon>
                  <span class="task-name">{{ container.name }}</span>
                  <v-chip size="x-small" :color="container.haveUpdate ? 'error' : 'success'" variant="tonal">
                    {{ container.haveUpdate ? '可升级' : '运行中' }}
                  </v-chip>
                </div>
                <div v-if="!taskAutoContainers.length" class="empty-line">当前筛选范围未选择自动更新容器</div>
              </div>
            </v-card-text>
          </v-card>
        </v-col>

        <v-col cols="12" md="6">
          <v-card variant="outlined" class="fill-height">
            <v-card-title>更新统计</v-card-title>
            <v-card-subtitle>更新日志、成功日志、失败日志按任务结果聚合</v-card-subtitle>
            <v-card-text>
              <v-row dense>
                <v-col cols="4" v-for="item in logMetrics" :key="item.label">
                  <v-card variant="outlined" class="log-metric">
                    <v-card-text>
                      <div :class="['text-h5', 'font-weight-bold', `text-${item.color}`]">{{ item.value }}</div>
                      <div class="text-caption text-medium-emphasis">{{ item.label }}</div>
                    </v-card-text>
                  </v-card>
                </v-col>
              </v-row>
              <v-table density="compact" class="mt-3">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>类型</th>
                    <th>源</th>
                    <th>容器</th>
                    <th>镜像</th>
                    <th>结果</th>
                    <th>说明/失败原因</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in updateLogs" :key="`${item.time}-${item.type}-${item.source}-${item.container}`">
                    <td class="log-time">{{ shortTime(item.time) }}</td>
                    <td>{{ item.type }}</td>
                    <td>{{ item.source }}</td>
                    <td class="text-truncate max-container">{{ item.container }}</td>
                    <td class="text-truncate max-image">{{ item.image || '-' }}</td>
                    <td>
                      <v-chip size="x-small" :color="item.success ? 'success' : 'error'" variant="tonal">
                        {{ item.result }}
                      </v-chip>
                    </td>
                    <td class="text-truncate max-message">{{ item.message }}</td>
                  </tr>
                  <tr v-if="!updateLogs.length">
                    <td colspan="7" class="text-medium-emphasis">暂无执行日志，触发更新通知、自动更新、手动升级或镜像清理后显示。</td>
                  </tr>
                </tbody>
              </v-table>

              <v-alert type="info" variant="tonal" class="mt-4">
                日志需明确 source、container、image、reason；镜像清理无法映射容器时记录 container=unknown。
              </v-alert>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2">
        <v-col cols="12">
          <v-card variant="outlined">
            <v-card-title>容器列表</v-card-title>
            <v-card-subtitle>标签页名称来自已配置源名，当前只显示 {{ activeContainerSourceLabel }} 源容器</v-card-subtitle>
            <v-card-text>
              <v-tabs v-model="activeContainerSource" density="compact" show-arrows class="mb-3">
                <v-tab v-for="tab in sourceTabs" :key="`container-${tab.value}`" :value="tab.value">
                  {{ tab.title }}
                </v-tab>
              </v-tabs>
              <v-table density="comfortable">
                <thead>
                  <tr>
                    <th>容器</th>
                    <th>镜像</th>
                    <th>状态</th>
                    <th>可更新</th>
                    <th>已选自动更新</th>
                    <th>最近结果</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="container in filteredContainers" :key="container.key">
                    <td>{{ container.name }}</td>
                    <td class="text-truncate max-image">{{ container.usingImage || '-' }}</td>
                    <td>{{ container.status || '-' }}</td>
                    <td>{{ yesNo(container.haveUpdate) }}</td>
                    <td>{{ yesNo(container.selected_auto) }}</td>
                    <td>{{ container.last_result || '-' }}</td>
                    <td>
                      <v-btn
                        v-if="container.haveUpdate"
                        color="primary"
                        size="small"
                        variant="flat"
                        @click="openManualDialog(container)"
                      >
                        手动升级
                      </v-btn>
                      <span v-else class="text-medium-emphasis">无需操作</span>
                    </td>
                  </tr>
                  <tr v-if="!filteredContainers.length">
                    <td colspan="7" class="text-medium-emphasis">
                      暂无容器。请确认源已保存、DC 地址包含正确端口、服务可访问且 secretKey 正确。
                    </td>
                  </tr>
                </tbody>
              </v-table>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </v-card-text>

    <v-dialog v-model="confirmDialog" max-width="460">
      <v-card>
        <v-card-title>确认手动升级</v-card-title>
        <v-card-text>
          <div class="dialog-line">源：{{ selectedContainer?.source_name || '-' }}</div>
          <div class="dialog-line">容器：{{ selectedContainer?.name || '-' }}</div>
          <div class="dialog-line text-medium-emphasis">当前镜像：{{ selectedContainer?.usingImage || '-' }}</div>
          <v-alert type="warning" variant="tonal" class="mt-4">
            手动升级会立即调用当前源的 DockerCopilot 更新接口，请确认容器正在空闲状态。
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="tonal" :disabled="manualLoading" @click="confirmDialog = false">取消</v-btn>
          <v-btn color="primary" :loading="manualLoading" @click="confirmManualUpgrade">确认升级</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-card>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

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
const error = ref('')
const message = ref('')
const activeTaskSource = ref('all')
const activeContainerSource = ref('all')
const confirmDialog = ref(false)
const selectedContainer = ref(null)

const state = reactive({
  sources: [],
  source_states: [],
  containers: [],
  logs: [],
  updatablelist: [],
  autoupdatelist: [],
  metrics: {},
})

const sourceStates = computed(() => Array.isArray(state.source_states) ? state.source_states : [])
const containers = computed(() => Array.isArray(state.containers) ? state.containers : [])
const updateLogs = computed(() => Array.isArray(state.logs) ? state.logs : [])
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
  { label: '启用源', value: state.metrics?.enabled_sources || 0, color: 'success' },
  { label: '容器总数', value: state.metrics?.containers || 0, color: 'primary' },
  { label: '已选自动更新', value: state.metrics?.auto_selected || 0, color: 'warning' },
  { label: '可自动升级', value: state.metrics?.auto_updatable || 0, color: 'error' },
  { label: '异常/失败', value: state.metrics?.failed_sources || 0, color: 'error' },
])
const logMetrics = computed(() => [
  { label: '更新日志', value: state.metrics?.logs_total || 0, color: 'primary' },
  { label: '成功', value: state.metrics?.logs_success || 0, color: 'success' },
  { label: '失败', value: state.metrics?.logs_failed || 0, color: 'error' },
])
const taskNotifyContainers = computed(() => bySource(containers.value, activeTaskSource.value).filter(item => item.selected_notify))
const taskAutoContainers = computed(() => bySource(containers.value, activeTaskSource.value).filter(item => item.selected_auto))
const filteredContainers = computed(() => bySource(containers.value, activeContainerSource.value))
const activeTaskSourceLabel = computed(() => tabLabel(activeTaskSource.value))
const activeContainerSourceLabel = computed(() => tabLabel(activeContainerSource.value))

function bySource(list, sourceId) {
  if (sourceId === 'all')
    return list
  return list.filter(item => item.source_id === sourceId)
}

function tabLabel(value) {
  return sourceTabs.value.find(item => item.value === value)?.title || '全部'
}

function ensureActiveTabs() {
  const values = new Set(sourceTabs.value.map(item => item.value))
  if (!values.has(activeTaskSource.value))
    activeTaskSource.value = 'all'
  if (!values.has(activeContainerSource.value))
    activeContainerSource.value = 'all'
}

function yesNo(value) {
  return value ? '是' : '否'
}

function shortTime(value) {
  if (!value)
    return '-'
  return String(value).replace(/^\d{4}-\d{2}-\d{2}\s*/, '')
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

function openManualDialog(container) {
  if (!container?.haveUpdate)
    return
  selectedContainer.value = container
  confirmDialog.value = true
}

async function confirmManualUpgrade() {
  error.value = ''
  message.value = ''
  if (!selectedContainer.value?.key)
    return
  if (!props.api?.post) {
    error.value = '当前 MoviePilot 未注入插件 POST API，无法执行手动升级。'
    return
  }
  manualLoading.value = true
  try {
    const result = await props.api.post('plugin/DockerCopilotHelperMulti/manual_update', {
      container_key: selectedContainer.value.key,
    })
    if (result?.success) {
      message.value = result.message || '手动升级任务已创建'
      confirmDialog.value = false
      await loadState()
    } else {
      const failureMessage = result?.message || '手动升级失败'
      await loadState()
      error.value = failureMessage
    }
  } catch (err) {
    error.value = `手动升级失败：${err?.message || err}`
  } finally {
    manualLoading.value = false
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
      updatablelist: Array.isArray(result?.updatablelist) ? result.updatablelist : [],
      autoupdatelist: Array.isArray(result?.autoupdatelist) ? result.autoupdatelist : [],
      metrics: result?.metrics || {},
    })
    ensureActiveTabs()
  } catch (err) {
    error.value = `加载详情失败：${err?.message || err}`
  } finally {
    loading.value = false
  }
}

onMounted(loadState)
</script>

<style scoped>
.task-center-page {
  background: transparent;
}
.gap-2 {
  gap: 8px;
}
.metric-card,
.log-metric {
  height: 100%;
}
.section-label {
  color: rgba(var(--v-theme-on-surface), 0.88);
  font-size: 0.875rem;
  font-weight: 700;
  margin-bottom: 10px;
}
.task-row {
  align-items: center;
  display: grid;
  gap: 8px;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  min-height: 32px;
}
.task-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty-line {
  color: rgba(var(--v-theme-on-surface), 0.58);
  font-size: 0.875rem;
  padding: 8px 0;
}
.max-message {
  max-width: 360px;
}
.max-image {
  max-width: 420px;
}
.max-container {
  max-width: 180px;
}
.log-time {
  white-space: nowrap;
}
.dialog-line {
  line-height: 1.9;
}
code {
  background: rgba(var(--v-theme-primary), 0.08);
  border-radius: 6px;
  padding: 2px 6px;
}
</style>
