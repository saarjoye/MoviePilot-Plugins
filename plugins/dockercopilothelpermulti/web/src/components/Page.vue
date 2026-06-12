<template>
  <v-card flat>
    <v-card-item>
      <v-card-title>DC助手 · 执行与通知</v-card-title>
      <v-card-subtitle>多源状态、容器列表与任务范围</v-card-subtitle>
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

    <v-card-text>
      <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
        {{ error }}
      </v-alert>

      <v-row>
        <v-col cols="6" md="3" v-for="metric in metrics" :key="metric.label">
          <v-card variant="outlined">
            <v-card-text>
              <div :class="['text-h4', 'font-weight-bold', `text-${metric.color}`]">{{ metric.value }}</div>
              <div class="text-body-2 text-medium-emphasis">{{ metric.label }}</div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2">
        <v-col cols="12" md="7">
          <v-card variant="outlined">
            <v-card-title>DockerCopilot 源</v-card-title>
            <v-table density="comfortable">
              <thead>
                <tr>
                  <th>源名称</th>
                  <th>源ID</th>
                  <th>状态</th>
                  <th>容器</th>
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
                  <td class="text-truncate max-message">{{ source.message || '-' }}</td>
                </tr>
                <tr v-if="!sourceStates.length">
                  <td colspan="5" class="text-medium-emphasis">暂无源，请先进入配置页新增并保存 DC 源。</td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>

        <v-col cols="12" md="5">
          <v-card variant="outlined">
            <v-card-title>任务选择</v-card-title>
            <v-card-text>
              <div class="text-body-2 text-medium-emphasis mb-2">更新通知容器</div>
              <div class="mb-4">
                <v-chip v-for="item in state.updatablelist" :key="`notify-${item}`" color="primary" variant="tonal" class="ma-1">
                  {{ item }}
                </v-chip>
                <span v-if="!state.updatablelist?.length" class="text-medium-emphasis">未选择</span>
              </div>
              <div class="text-body-2 text-medium-emphasis mb-2">自动更新容器</div>
              <div>
                <v-chip v-for="item in state.autoupdatelist" :key="`auto-${item}`" color="success" variant="tonal" class="ma-1">
                  {{ item }}
                </v-chip>
                <span v-if="!state.autoupdatelist?.length" class="text-medium-emphasis">未选择</span>
              </div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2">
        <v-col cols="12">
          <v-card variant="outlined">
            <v-card-title>容器列表</v-card-title>
            <v-table density="comfortable">
              <thead>
                <tr>
                  <th>源</th>
                  <th>容器</th>
                  <th>镜像</th>
                  <th>状态</th>
                  <th>可更新</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="container in containers" :key="container.key">
                  <td>{{ container.source_name }}</td>
                  <td>{{ container.name }}</td>
                  <td class="text-truncate max-image">{{ container.usingImage || '-' }}</td>
                  <td>{{ container.status || '-' }}</td>
                  <td>
                    <v-chip size="small" :color="container.haveUpdate ? 'primary' : 'grey'" variant="tonal">
                      {{ container.haveUpdate ? '是' : '否' }}
                    </v-chip>
                  </td>
                </tr>
                <tr v-if="!containers.length">
                  <td colspan="5" class="text-medium-emphasis">
                    暂无容器。请确认源已保存、DC 地址包含正确端口、服务可访问且 secretKey 正确。
                  </td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>
      </v-row>
    </v-card-text>
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
const error = ref('')
const state = reactive({
  sources: [],
  source_states: [],
  containers: [],
  updatablelist: [],
  autoupdatelist: [],
  metrics: {},
})

const sourceStates = computed(() => Array.isArray(state.source_states) ? state.source_states : [])
const containers = computed(() => Array.isArray(state.containers) ? state.containers : [])
const showSettingsButton = computed(() => props.show_switch ?? props.showSwitch)
const metrics = computed(() => [
  { label: '已配置源', value: state.metrics?.sources || 0, color: 'primary' },
  { label: '启用源', value: state.metrics?.enabled_sources || 0, color: 'success' },
  { label: '容器总数', value: state.metrics?.containers || 0, color: 'primary' },
  { label: '异常源', value: state.metrics?.failed_sources || 0, color: 'error' },
])

function sourceColor(source) {
  if (source.enabled === false || source.state === '停用')
    return 'grey'
  if (source.state === '已连接')
    return 'success'
  if (source.state === '异常')
    return 'error'
  return 'warning'
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
      updatablelist: Array.isArray(result?.updatablelist) ? result.updatablelist : [],
      autoupdatelist: Array.isArray(result?.autoupdatelist) ? result.autoupdatelist : [],
      metrics: result?.metrics || {},
    })
  } catch (err) {
    error.value = `加载详情失败：${err?.message || err}`
  } finally {
    loading.value = false
  }
}

onMounted(loadState)
</script>

<style scoped>
.gap-2 {
  gap: 8px;
}
.max-message {
  max-width: 360px;
}
.max-image {
  max-width: 420px;
}
code {
  background: rgba(var(--v-theme-primary), 0.08);
  border-radius: 6px;
  padding: 2px 6px;
}
</style>
