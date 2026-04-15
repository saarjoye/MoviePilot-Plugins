<script setup>
import { reactive, watch } from "vue";

const emit = defineEmits(["save", "close"]);

const props = defineProps({
  initialConfig: {
    type: Object,
    default: () => ({})
  }
});

const form = reactive({
  enabled: false,
  username: "",
  password: "",
  timeout: 20,
  max_results: 10,
  only_show_115: true
});

function applyConfig(config = {}) {
  form.enabled = Boolean(config.enabled);
  form.username = String(config.username || "");
  form.password = String(config.password || "");
  form.timeout = Number(config.timeout || 20);
  form.max_results = Number(config.max_results || 10);
  form.only_show_115 = config.only_show_115 !== false;
}

function saveConfig() {
  emit("save", {
    enabled: form.enabled,
    username: form.username.trim(),
    password: form.password,
    timeout: Number(form.timeout || 20),
    max_results: Number(form.max_results || 10),
    only_show_115: form.only_show_115
  });
}

watch(
  () => props.initialConfig,
  (value) => applyConfig(value),
  { immediate: true, deep: true }
);
</script>

<template>
  <VCard>
    <VCardTitle>盘链 115 搜索配置</VCardTitle>
    <VCardText class="d-flex flex-column ga-4">
      <VAlert type="info" variant="tonal">
        这里保存的是盘链登录账号和搜索显示策略。“加入 115”目前仍是占位接口，真实转存会在后续版本继续补齐。
      </VAlert>

      <VRow>
        <VCol cols="12" md="6">
          <VSwitch v-model="form.enabled" label="启用插件" />
        </VCol>
        <VCol cols="12" md="6">
          <VSwitch v-model="form.only_show_115" label="仅展示 115 资源" />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12" md="6">
          <VTextField
            v-model="form.username"
            label="盘链账号"
            placeholder="填写盘链用户名"
          />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField
            v-model="form.password"
            label="盘链密码"
            type="password"
            placeholder="填写盘链密码"
          />
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
    </VCardText>
    <VCardActions class="px-4 pb-4">
      <VBtn color="primary" @click="saveConfig">保存配置</VBtn>
      <VBtn variant="text" @click="emit('close')">关闭</VBtn>
    </VCardActions>
  </VCard>
</template>
