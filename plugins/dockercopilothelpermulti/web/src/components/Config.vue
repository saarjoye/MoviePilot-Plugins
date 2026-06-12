<template>
  <v-card class="dc-config" flat>
    <v-card-item>
      <v-card-title>DC助手 · 多 DockerCopilot 源</v-card-title>
      <v-card-subtitle>点击“新增源”后只新增 1 个 DC 源设置；支持任意数量，不再固定 5 个槽位。</v-card-subtitle>
      <template #append>
        <v-btn icon color="primary" variant="text" @click="emit('close')">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </template>
    </v-card-item>

    <v-card-text class="config-body">
      <v-alert type="warning" variant="tonal" class="mb-4">
        DC 地址与 secretKey 属于敏感配置；secretKey 仅保存到 MP 插件配置，页面摘要、通知和日志不显示明文。
      </v-alert>

      <div class="section-title">
        <div class="text-h6 font-weight-bold">基础开关</div>
        <div class="text-body-2 text-medium-emphasis">保存后定时任务按新配置生效</div>
      </div>
      <v-row>
        <v-col cols="12" sm="6" md="3">
          <v-switch v-model="config.enabled" label="启用插件" color="primary" inset />
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-switch v-model="config.onlyonce" label="立即运行一次" color="primary" inset />
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-switch v-model="config.schedulereport" label="进度汇报" color="primary" inset />
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-switch v-model="config.deleteimages" label="镜像清理" color="primary" inset />
        </v-col>
      </v-row>

      <v-row>
        <v-col cols="12" md="3">
          <v-text-field v-model="config.interval" label="检查间隔（秒）" variant="outlined" density="comfortable" />
        </v-col>
        <v-col cols="12" md="3">
          <v-text-field v-model="config.intervallimit" label="检查次数" variant="outlined" density="comfortable" />
        </v-col>
        <v-col cols="12" md="3">
          <v-text-field v-model="config.updatecron" label="更新通知 Cron" variant="outlined" density="comfortable" placeholder="15 8-23/2 * * *" />
        </v-col>
        <v-col cols="12" md="3">
          <v-text-field v-model="config.autoupdatecron" label="自动更新 Cron" variant="outlined" density="comfortable" placeholder="15 2 * * *" />
        </v-col>
      </v-row>

      <v-row>
        <v-col cols="12" md="4">
          <v-text-field v-model="config.backupcron" label="自动备份 Cron" variant="outlined" density="comfortable" placeholder="0 7 * * *" />
        </v-col>
        <v-col cols="12" md="4">
          <v-switch v-model="config.updatablenotify" label="更新通知开关" color="primary" inset />
        </v-col>
        <v-col cols="12" md="4">
          <v-switch v-model="config.autoupdatenotify" label="自动更新通知" color="primary" inset />
        </v-col>
      </v-row>

      <div class="section-title d-flex flex-wrap align-center justify-space-between gap-2">
        <div>
          <div class="text-h6 font-weight-bold">DockerCopilot 源</div>
          <div class="text-body-2 text-medium-emphasis">已配置 {{ config.sources.length }} 个源，启用 {{ enabledSourceCount }} 个</div>
        </div>
        <v-btn color="primary" prepend-icon="mdi-plus" @click="addSource">新增源</v-btn>
      </div>

      <v-alert v-if="!config.sources.length" type="info" variant="tonal" class="mb-4">
        暂无 DC 源。点击“新增源”后，页面会出现 1 个 DC 源设置卡片；继续点击可继续增加。
      </v-alert>

      <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
        {{ error }}
      </v-alert>

      <v-card
        v-for="(source, index) in config.sources"
        :key="source._key || index"
        class="source-card mb-4"
        variant="outlined"
      >
        <v-card-item>
          <v-card-title class="d-flex align-center gap-2">
            <v-icon color="primary">mdi-server-network</v-icon>
            <span>DC 源设置 {{ index + 1 }}</span>
            <v-chip size="small" :color="source.enabled === false ? 'grey' : 'success'" variant="tonal">
              {{ source.enabled === false ? '停用' : '启用' }}
            </v-chip>
          </v-card-title>
          <template #append>
            <v-btn icon variant="text" color="error" @click="removeSource(index)">
              <v-icon>mdi-delete-outline</v-icon>
            </v-btn>
          </template>
        </v-card-item>
        <v-divider />
        <v-card-text>
          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="source.enabled" label="启用此源" color="primary" inset />
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field
                v-model.trim="source.id"
                label="源ID"
                variant="outlined"
                density="comfortable"
                hint="英文、数字、下划线、短横线"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field v-model.trim="source.name" label="显示名称" variant="outlined" density="comfortable" />
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field
                v-model="source.secretKey"
                label="secretKey"
                variant="outlined"
                density="comfortable"
                :type="visibleSecrets[source._key] ? 'text' : 'password'"
                :append-inner-icon="visibleSecrets[source._key] ? 'mdi-eye-off' : 'mdi-eye'"
                @click:append-inner="toggleSecret(source._key)"
              />
            </v-col>
            <v-col cols="12">
              <v-text-field
                v-model.trim="source.host"
                label="服务地址"
                variant="outlined"
                density="comfortable"
                placeholder="http://dc-lxc-01:12712"
                hint="必须以 http:// 或 https:// 开头，末尾不需要 /"
                persistent-hint
              />
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <div class="d-flex align-center gap-2 mb-3">
        <v-chip color="primary" variant="tonal">容器值：source_id::container_name</v-chip>
        <v-chip color="success" variant="tonal">防同名冲突</v-chip>
      </div>

      <div class="section-title">
        <div class="text-h6 font-weight-bold">任务范围</div>
        <div class="text-body-2 text-medium-emphasis">保存源配置后点击刷新，容器选项会按源名称 / 容器名加载</div>
      </div>
      <div class="d-flex flex-wrap align-center gap-2 mb-4">
        <v-btn
          color="primary"
          variant="tonal"
          prepend-icon="mdi-refresh"
          :loading="loadingContainers"
          @click="loadContainerItems"
        >
          刷新容器列表
        </v-btn>
        <span class="text-body-2 text-medium-emphasis">当前 {{ containerItems.length }} 个容器选项</span>
      </div>
      <v-alert v-if="containerMessage" type="info" variant="tonal" class="mb-4">
        {{ containerMessage }}
      </v-alert>
      <v-alert v-if="sourceErrors.length" type="warning" variant="tonal" class="mb-4">
        <div v-for="item in sourceErrors" :key="item.id || item.name">
          {{ item.name || item.id }}：{{ item.message }}
        </div>
      </v-alert>
      <v-row>
        <v-col cols="12" md="6">
          <v-select
            v-model="config.updatablelist"
            label="更新通知容器"
            :items="containerItems"
            chips
            multiple
            variant="outlined"
            density="comfortable"
            hint="选项保存为 source_id::container_name"
            persistent-hint
          />
        </v-col>
        <v-col cols="12" md="6">
          <v-select
            v-model="config.autoupdatelist"
            label="自动更新容器"
            :items="containerItems"
            chips
            multiple
            variant="outlined"
            density="comfortable"
            hint="只自动更新选中的容器"
            persistent-hint
          />
        </v-col>
        <v-col cols="12" md="6">
          <v-select
            v-model="config.backup_sources"
            label="自动备份源范围"
            :items="sourceItems"
            chips
            multiple
            variant="outlined"
            density="comfortable"
            hint="留空表示备份全部启用源"
            persistent-hint
          />
        </v-col>
        <v-col cols="12" md="6">
          <v-switch v-model="config.backupsnotify" label="备份结果通知" color="primary" inset />
        </v-col>
      </v-row>
    </v-card-text>

    <v-card-actions class="config-actions">
      <v-btn variant="text" color="secondary" @click="resetConfig">重置</v-btn>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-content-save" :loading="saving" @click="saveConfig">保存配置</v-btn>
    </v-card-actions>
  </v-card>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
  api: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['save', 'close'])

const defaultConfig = {
  enabled: false,
  onlyonce: false,
  schedulereport: false,
  deleteimages: false,
  updatablenotify: false,
  autoupdatenotify: false,
  backupsnotify: false,
  updatecron: '',
  autoupdatecron: '',
  backupcron: '',
  interval: 10,
  intervallimit: 6,
  sources: [],
  updatablelist: [],
  autoupdatelist: [],
  backup_sources: [],
  container_items: [],
}

const config = reactive(cloneConfig(defaultConfig))
const error = ref('')
const saving = ref(false)
const loadingContainers = ref(false)
const containerMessage = ref('')
const sourceErrors = ref([])
const visibleSecrets = reactive({})

const enabledSourceCount = computed(() => config.sources.filter(item => item.enabled !== false).length)
const sourceItems = computed(() => config.sources
  .filter(item => item.id)
  .map(item => ({ title: `${item.name || item.id} · ${item.id}`, value: item.id })))
const containerItems = computed(() => Array.isArray(config.container_items) ? config.container_items : [])

watch(
  () => props.initialConfig,
  value => applyInitialConfig(value || {}),
  { immediate: true, deep: true },
)

function cloneConfig(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function createKey() {
  return `source_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function normalizeSources(value) {
  if (Array.isArray(value))
    return value.map(normalizeSource).filter(item => item.id || item.host || item.secretKey)
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return normalizeSources(parsed)
    } catch {
      return []
    }
  }
  return []
}

function normalizeSource(source) {
  return {
    _key: source?._key || createKey(),
    id: String(source?.id || source?.name || '').trim(),
    name: String(source?.name || source?.id || '').trim(),
    host: String(source?.host || '').trim().replace(/\/+$/, ''),
    secretKey: String(source?.secretKey || source?.secret_key || '').trim(),
    enabled: source?.enabled !== false,
  }
}

function serializeSource(source) {
  const normalized = normalizeSource(source)
  return {
    id: normalized.id,
    name: normalized.name,
    host: normalized.host,
    secretKey: normalized.secretKey,
    enabled: normalized.enabled,
  }
}

function applyInitialConfig(initial) {
  Object.assign(config, cloneConfig(defaultConfig), cloneConfig(initial))
  config.sources = normalizeSources(initial.sources?.length ? initial.sources : initial.sources_text)
  if (!config.sources.length)
    config.sources = normalizeLegacySlots(initial)
  config.updatablelist = Array.isArray(initial.updatablelist) ? initial.updatablelist : []
  config.autoupdatelist = Array.isArray(initial.autoupdatelist) ? initial.autoupdatelist : []
  config.backup_sources = Array.isArray(initial.backup_sources) ? initial.backup_sources : []
  config.container_items = Array.isArray(initial.container_items) ? initial.container_items : []
  error.value = ''
  containerMessage.value = ''
  sourceErrors.value = []
}

function normalizeLegacySlots(initial) {
  const sources = []
  for (let index = 1; index <= 100; index++) {
    const prefix = `source${index}`
    if (!initial[`${prefix}_host`] && !initial[`${prefix}_secretKey`])
      continue
    sources.push(normalizeSource({
      id: initial[`${prefix}_id`],
      name: initial[`${prefix}_name`],
      host: initial[`${prefix}_host`],
      secretKey: initial[`${prefix}_secretKey`],
      enabled: initial[`${prefix}_enabled`],
    }))
  }
  if (!sources.length && initial.host && initial.secretKey) {
    sources.push(normalizeSource({
      id: 'default',
      name: '默认源',
      host: initial.host,
      secretKey: initial.secretKey,
      enabled: true,
    }))
  }
  return sources
}

function emptySource() {
  return { _key: createKey(), id: '', name: '', host: '', secretKey: '', enabled: true }
}

function addSource() {
  error.value = ''
  config.sources.push(emptySource())
}

function removeSource(index) {
  const source = config.sources[index]
  config.sources.splice(index, 1)
  if (source?._key)
    delete visibleSecrets[source._key]
  if (source?.id) {
    config.backup_sources = config.backup_sources.filter(item => item !== source.id)
    config.updatablelist = config.updatablelist.filter(item => !String(item).startsWith(`${source.id}::`))
    config.autoupdatelist = config.autoupdatelist.filter(item => !String(item).startsWith(`${source.id}::`))
  }
}

function toggleSecret(key) {
  visibleSecrets[key] = !visibleSecrets[key]
}

function resetConfig() {
  applyInitialConfig(props.initialConfig || {})
}

function validateSources(sources) {
  const ids = new Set()
  for (let index = 0; index < sources.length; index += 1) {
    const source = sources[index]
    const label = `DC 源设置 ${index + 1}`
    if (!source.id)
      return `${label}：源ID不能为空`
    if (!/^[a-zA-Z0-9_-]+$/.test(source.id))
      return `${label}：源ID只能包含英文、数字、下划线或短横线`
    if (ids.has(source.id))
      return `${label}：源ID ${source.id} 已存在`
    ids.add(source.id)
    if (!source.name)
      return `${label}：显示名称不能为空`
    if (!/^https?:\/\//.test(source.host))
      return `${label}：服务地址必须以 http:// 或 https:// 开头`
    if (!source.secretKey)
      return `${label}：secretKey不能为空`
  }
  return ''
}

async function saveConfig() {
  saving.value = true
  try {
    const payload = cloneConfig(config)
    payload.sources = config.sources.map(serializeSource)
    const validationError = validateSources(payload.sources)
    if (validationError) {
      error.value = validationError
      return
    }
    payload.sources_text = JSON.stringify(payload.sources, null, 2)
    emit('save', payload)
  } finally {
    saving.value = false
  }
}

async function loadContainerItems() {
  error.value = ''
  containerMessage.value = ''
  sourceErrors.value = []
  if (!props.api?.get) {
    containerMessage.value = '当前 MoviePilot 未注入插件 API，请保存后重新打开配置页。'
    return
  }
  loadingContainers.value = true
  try {
    const state = await props.api.get('plugin/DockerCopilotHelperMulti/state')
    config.container_items = Array.isArray(state?.container_items) ? state.container_items : []
    if (Array.isArray(state?.updatablelist))
      config.updatablelist = state.updatablelist
    if (Array.isArray(state?.autoupdatelist))
      config.autoupdatelist = state.autoupdatelist
    sourceErrors.value = Array.isArray(state?.source_states)
      ? state.source_states.filter(item => item.state === '异常' || (item.enabled !== false && !item.container_count))
      : []
    if (!config.container_items.length)
      containerMessage.value = state?.metrics?.sources
        ? '没有获取到容器。请检查 DC 服务地址是否包含端口、服务是否可访问，以及 secretKey 是否正确。'
        : '还没有保存可用 DC 源。请先保存配置，再刷新容器列表。'
  } catch (err) {
    error.value = `刷新容器列表失败：${err?.message || err}`
  } finally {
    loadingContainers.value = false
  }
}
</script>

<style scoped>
.dc-config {
  height: min(82vh, 760px);
  max-height: calc(100vh - 96px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.config-body {
  flex: 1 1 auto;
  height: 100%;
  min-height: 0;
  max-height: 100%;
  overflow-y: auto;
  padding-bottom: 24px;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}
.config-actions {
  flex: 0 0 auto;
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  background: rgb(var(--v-theme-surface));
}
.section-title {
  margin-top: 20px;
  margin-bottom: 12px;
}
.gap-2 {
  gap: 8px;
}
.source-card {
  border-radius: 14px;
}
code {
  background: rgba(var(--v-theme-primary), 0.08);
  border-radius: 6px;
  padding: 2px 6px;
}
</style>
