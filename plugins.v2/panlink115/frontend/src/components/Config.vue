<script setup>
import { reactive, watch } from "vue";

const emit = defineEmits(["save", "close"]);

const props = defineProps({
  initialConfig: {
    type: Object,
    default: () => ({})
  },
  saving: {
    type: Boolean,
    default: false
  }
});

const form = reactive({
  enabled: false,
  username: "",
  password: "",
  timeout: 20,
  max_results: 10,
  only_show_115: true,
  u115_cookie: ""
});

function applyConfig(config = {}) {
  form.enabled = Boolean(config.enabled);
  form.username = String(config.username || "");
  form.password = String(config.password || "");
  form.timeout = Number(config.timeout || 20);
  form.max_results = Number(config.max_results || 10);
  form.only_show_115 = config.only_show_115 !== false;
  form.u115_cookie = String(config.u115_cookie || "");
}

function saveConfig() {
  emit("save", {
    enabled: form.enabled,
    username: form.username.trim(),
    password: form.password,
    timeout: Number(form.timeout || 20),
    max_results: Number(form.max_results || 10),
    only_show_115: form.only_show_115,
    u115_cookie: form.u115_cookie.trim()
  });
}

watch(
  () => props.initialConfig,
  (value) => applyConfig(value),
  { immediate: true, deep: true }
);
</script>

<template>
  <VCard :loading="saving">
    <VCardTitle>盘链 115 插件配置</VCardTitle>
    <VCardText class="d-flex flex-column ga-4">
      <VAlert type="info" variant="tonal">
        插件已切换为直连 115 模式，不再依赖 CD2。目标目录会复用 MoviePilot 中已配置的 u115 存储路径。
      </VAlert>

      <VAlert type="warning" variant="outlined">
        分享转存使用 115 网页 Cookie 调用官方网页接口。MoviePilot 的 u115 OAuth 登录仍用于目录解析和目标目录创建。
      </VAlert>

      <VRow>
        <VCol cols="12" md="6">
          <VSwitch v-model="form.enabled" label="启用插件" />
        </VCol>
        <VCol cols="12" md="6">
          <VSwitch v-model="form.only_show_115" label="仅显示 115 资源" />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12" md="6">
          <VTextField v-model="form.username" label="盘链账号" />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField v-model="form.password" label="盘链密码" type="password" />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12" md="6">
          <VTextField v-model="form.timeout" label="请求超时秒数" type="number" />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField v-model="form.max_results" label="搜索结果数量" type="number" />
        </VCol>
      </VRow>

      <VTextarea
        v-model="form.u115_cookie"
        label="115 网页 Cookie"
        rows="5"
        auto-grow
        placeholder="粘贴已登录 115 网页后的完整 Cookie"
      />
    </VCardText>
    <VCardActions class="px-4 pb-4">
      <VBtn color="primary" :loading="saving" :disabled="saving" @click="saveConfig">保存配置</VBtn>
      <VBtn variant="text" :disabled="saving" @click="emit('close')">关闭</VBtn>
    </VCardActions>
  </VCard>
</template>
