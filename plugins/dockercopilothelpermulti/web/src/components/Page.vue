<template>
  <v-card flat>
    <v-card-item>
      <v-card-title>DC助手 · 执行与通知</v-card-title>
      <v-card-subtitle>多源状态、任务范围与失败源处理</v-card-subtitle>
      <template #append>
        <v-btn icon color="primary" variant="text" @click="emit('switch')">
          <v-icon>mdi-cog</v-icon>
        </v-btn>
      </template>
    </v-card-item>

    <v-card-text>
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
                  <th>地址</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="source in sources" :key="source.id">
                  <td>{{ source.name || source.id }}</td>
                  <td><code>{{ source.id }}</code></td>
                  <td>
                    <v-chip size="small" :color="source.enabled === false ? 'grey' : 'success'" variant="tonal">
                      {{ source.enabled === false ? '停用' : '启用' }}
                    </v-chip>
                  </td>
                  <td class="text-truncate max-host">{{ source.host }}</td>
                </tr>
                <tr v-if="!sources.length">
                  <td colspan="4" class="text-medium-emphasis">暂无源，请先进入配置页新增。</td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>

        <v-col cols="12" md="5">
          <v-card variant="outlined">
            <v-card-title>通知预览</v-card-title>
            <v-card-text>
              <v-alert type="info" variant="tonal">
                【DC助手-更新通知】<br>
                [源名称] 容器名 可更新<br>
                当前镜像：image:tag<br>
                说明：通知始终带源名称，避免排障混乱。
              </v-alert>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-2">
        <v-col cols="12" md="7">
          <v-card variant="outlined">
            <v-card-title>选择摘要</v-card-title>
            <v-card-text>
              <v-chip v-for="item in selectedItems" :key="item" color="primary" variant="tonal" class="ma-1">
                {{ item }}
              </v-chip>
              <div v-if="!selectedItems.length" class="text-medium-emphasis">暂无已选容器。</div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="12" md="5">
          <v-card variant="outlined">
            <v-card-title>失败源处理</v-card-title>
            <v-list density="compact">
              <v-list-item title="重试策略" subtitle="本轮跳过，下一次调度继续重试" />
              <v-list-item title="日志级别" subtitle="ERROR，不输出 secretKey 明文" />
              <v-list-item title="通知策略" subtitle="备份和更新结果按源名汇总推送" />
            </v-list>
          </v-card>
        </v-col>
      </v-row>
    </v-card-text>
  </v-card>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  model: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['switch'])

const sources = computed(() => Array.isArray(props.model?.sources) ? props.model.sources : [])
const enabledSources = computed(() => sources.value.filter(item => item.enabled !== false))
const selectedItems = computed(() => [
  ...(Array.isArray(props.model?.updatablelist) ? props.model.updatablelist : []),
  ...(Array.isArray(props.model?.autoupdatelist) ? props.model.autoupdatelist : []),
])
const metrics = computed(() => [
  { label: '已配置源', value: sources.value.length, color: 'primary' },
  { label: '启用源', value: enabledSources.value.length, color: 'success' },
  { label: '通知容器', value: Array.isArray(props.model?.updatablelist) ? props.model.updatablelist.length : 0, color: 'primary' },
  { label: '自动更新', value: Array.isArray(props.model?.autoupdatelist) ? props.model.autoupdatelist.length : 0, color: 'success' },
])
</script>

<style scoped>
.max-host {
  max-width: 360px;
}
code {
  background: rgba(var(--v-theme-primary), 0.08);
  border-radius: 6px;
  padding: 2px 6px;
}
</style>
