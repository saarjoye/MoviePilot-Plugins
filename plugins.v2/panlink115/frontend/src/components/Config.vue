<script setup>
import { reactive, watch } from "vue";

const emit = defineEmits(["save", "close"]);

const props = defineProps({
  initialConfig: {
    type: Object,
    default: () => ({})
  }
});

const authModeItems = [
  { title: "API Token", value: "api_token" },
  { title: "网页登录 Token", value: "web_token" }
];

const form = reactive({
  enabled: false,
  username: "",
  password: "",
  timeout: 20,
  max_results: 10,
  only_show_115: true,
  cd2_url: "",
  cd2_auth_mode: "api_token",
  cd2_token: "",
  cd2_web_token: "",
  cd2_default_root: "",
  cd2_pending_root: "",
  cd2_directory_roots: "",
  cd2_category_roots: "",
  cd2_detect_delay: 1.2
});

function applyConfig(config = {}) {
  form.enabled = Boolean(config.enabled);
  form.username = String(config.username || "");
  form.password = String(config.password || "");
  form.timeout = Number(config.timeout || 20);
  form.max_results = Number(config.max_results || 10);
  form.only_show_115 = config.only_show_115 !== false;
  form.cd2_url = String(config.cd2_url || "");
  form.cd2_auth_mode = String(config.cd2_auth_mode || "api_token") === "web_token" ? "web_token" : "api_token";
  form.cd2_token = String(config.cd2_token || "");
  form.cd2_web_token = String(config.cd2_web_token || "");
  form.cd2_default_root = String(config.cd2_default_root || "");
  form.cd2_pending_root = String(config.cd2_pending_root || "");
  form.cd2_directory_roots = String(config.cd2_directory_roots || "");
  form.cd2_category_roots = String(config.cd2_category_roots || "");
  form.cd2_detect_delay = Number(config.cd2_detect_delay || 1.2);
}

function saveConfig() {
  emit("save", {
    enabled: form.enabled,
    username: form.username.trim(),
    password: form.password,
    timeout: Number(form.timeout || 20),
    max_results: Number(form.max_results || 10),
    only_show_115: form.only_show_115,
    cd2_url: form.cd2_url.trim(),
    cd2_auth_mode: form.cd2_auth_mode,
    cd2_token: form.cd2_token.trim(),
    cd2_web_token: form.cd2_web_token.trim(),
    cd2_default_root: form.cd2_default_root.trim(),
    cd2_pending_root: form.cd2_pending_root.trim(),
    cd2_directory_roots: form.cd2_directory_roots,
    cd2_category_roots: form.cd2_category_roots,
    cd2_detect_delay: Number(form.cd2_detect_delay || 1.2)
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
        提交到 115 时会优先读取 MoviePilot 的“存储 & 目录”配置，再结合本插件的 MP 目录映射、分类映射和默认根目录，解析出最终 CD2 路径。
      </VAlert>

      <VAlert type="warning" variant="tonal">
        当前环境已验证：CD2 API Token 的“读写”不等于具备“离线下载”权限。如果真实提交报离线权限不足，请改用“网页登录 Token”模式。
      </VAlert>

      <VAlert type="warning" variant="outlined">
        配置“115 待整理目录”后，插件会先把资源统一提交到该目录；页面里选择的 MoviePilot 分类只作为后续整理入库意图，不再直接作为下载落点。
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

      <VRow>
        <VCol cols="12">
          <VTextField
            v-model="form.cd2_url"
            label="CD2 地址"
            placeholder="例如：https://cd2.example.com:5555"
          />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12" md="6">
          <VSelect
            v-model="form.cd2_auth_mode"
            :items="authModeItems"
            item-title="title"
            item-value="value"
            label="CD2 鉴权模式"
          />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField v-model="form.cd2_detect_delay" label="CD2 检测等待秒数" type="number" />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12">
          <VTextField
            v-model="form.cd2_token"
            label="CD2 API Token"
            type="password"
            placeholder="填写 API 令牌页里的 Token"
          />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12">
          <VTextField
            v-model="form.cd2_web_token"
            label="CD2 网页登录 Token"
            type="password"
            placeholder="填写浏览器 localStorage.token"
          />
        </VCol>
      </VRow>

      <VAlert type="info" variant="outlined">
        网页登录 Token 的获取方式：先登录 CD2 网页，再在浏览器开发者工具里读取 `localStorage.token`。当前插件不会自动抓浏览器会话，需手动粘贴一次。
      </VAlert>

      <VRow>
        <VCol cols="12">
          <VTextField
            v-model="form.cd2_default_root"
            label="CD2 默认根目录"
            placeholder="例如：/115open/媒体库"
          />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12">
          <VTextField
            v-model="form.cd2_pending_root"
            label="115 待整理目录"
            placeholder="例如：/115open/待整理/Panlink115"
          />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12">
          <VTextarea
            v-model="form.cd2_directory_roots"
            label="CD2 MP目录映射"
            rows="5"
            auto-grow
            placeholder="每行一个映射，例如：&#10;local:D:/115挂载/媒体库=/115open/媒体库&#10;local:D:/115挂载/媒体库/电影=/115open/媒体库/电影"
          />
        </VCol>
      </VRow>

      <VRow>
        <VCol cols="12">
          <VTextarea
            v-model="form.cd2_category_roots"
            label="CD2 分类目录映射"
            rows="5"
            auto-grow
            placeholder="每行一个映射，例如：&#10;电影/华语电影=/115open/媒体库/电影/华语电影&#10;剧集/国产剧=/115open/媒体库/剧集/国产剧&#10;*=/115open/媒体库"
          />
        </VCol>
      </VRow>
    </VCardText>
    <VCardActions class="px-4 pb-4">
      <VBtn color="primary" @click="saveConfig">保存配置</VBtn>
      <VBtn variant="text" @click="emit('close')">关闭</VBtn>
    </VCardActions>
  </VCard>
</template>
