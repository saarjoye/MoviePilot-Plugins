<template>
  <v-app>
    <v-main>
      <v-container>
        <v-tabs v-model="tab" class="mb-4">
          <v-tab value="config">配置</v-tab>
          <v-tab value="page">详情</v-tab>
        </v-tabs>
        <v-window v-model="tab">
          <v-window-item value="config">
            <Config :initial-config="demoConfig" @save="demoConfig = $event" />
          </v-window-item>
          <v-window-item value="page">
            <Page :model="demoConfig" />
          </v-window-item>
        </v-window>
      </v-container>
    </v-main>
  </v-app>
</template>

<script setup>
import { ref } from 'vue'
import Config from './components/Config.vue'
import Page from './components/Page.vue'

const tab = ref('config')
const demoConfig = ref({
  enabled: true,
  interval: 10,
  intervallimit: 6,
  sources: [],
  updatablelist: [],
  autoupdatelist: [],
  backup_sources: [],
  container_items: [],
})
</script>
