<script setup>
import { computed, nextTick, onMounted, ref } from "vue";

const props = defineProps({
  api: {
    type: Object,
    default: () => ({})
  }
});

const keyword = ref("");
const statusMessage = ref("准备就绪，输入影视名称后开始搜索。");
const searching = ref(false);
const loadingVodId = ref("");
const queueLoading = ref(false);
const categoryLoading = ref(false);
const searchResults = ref([]);
const selectedMedia = ref(null);
const linkGroups = ref({});
const queueItems = ref([]);
const queueSectionRef = ref(null);
const latestQueueKey = ref("");
const categoryOptions = ref([]);
const selectedCategoryKey = ref("");
const groupDialog = ref(false);
const downloadDialog = ref(false);
const activeGroupName = ref("");
const activeEntries = ref([]);
const selectedEntry = ref(null);
const pluginState = ref({
  enabled: false,
  only_show_115: true,
  max_results: 10,
  submit_mode: "direct_115",
  u115_auth_label: "115 网页 Cookie",
  u115_cookie_configured: false,
  mp_u115_configured: false,
  mp_u115_ready: false,
  workflow_label: "直连 115",
  direct_target_hint: ""
});

const resultCountText = computed(() => `共 ${searchResults.value.length} 条候选结果`);
const queueCountText = computed(() => `任务队列 ${queueItems.value.length} 条`);
const authSummaryText = computed(() => {
  const parts = [];
  parts.push(pluginState.value.mp_u115_ready ? "MP u115 已就绪" : "MP u115 未就绪");
  parts.push(pluginState.value.u115_cookie_configured ? "115 Cookie 已配置" : "115 Cookie 未配置");
  return parts.join(" / ");
});
const submitButtonText = computed(() => "直连提交到 115");
const groupCards = computed(() =>
  Object.entries(linkGroups.value || {}).map(([name, entries]) => ({
    name,
    label: diskLabel(name),
    count: Array.isArray(entries) ? entries.length : 0
  }))
);
const selectedCategory = computed(() =>
  categoryOptions.value.find((item) => item.key === selectedCategoryKey.value) || null
);

function normalizePayload(response) {
  return response?.data ?? response ?? {};
}

function safeText(value) {
  return String(value || "").trim();
}

function diskLabel(name) {
  const mapping = {
    "115": "115 网盘",
    quark: "夸克网盘",
    aliyun: "阿里云盘",
    tianyi: "天翼云盘",
    pikpak: "PikPak",
    "123": "123 网盘",
    others: "其他资源"
  };
  return mapping[name] || `${name} 资源`;
}

function resultSubtitle(item) {
  return [item.type_name, item.vod_year, item.vod_area, item.vod_remarks].filter(Boolean).join(" / ");
}

function mediaFacts(item) {
  if (!item) {
    return [];
  }
  return [item.vod_year, item.vod_area, item.type_name, item.vod_remarks].filter(Boolean);
}

function mediaMeta(item) {
  if (!item) {
    return [];
  }
  return [
    { label: "别名", value: item.vod_alias },
    { label: "导演", value: item.vod_director },
    { label: "语言", value: item.vod_lang },
    { label: "更新时间", value: item.vod_update_time }
  ].filter((entry) => safeText(entry.value));
}

function entrySubtitle(entry) {
  return [entry.source || "未知来源", entry.time || "未知时间"].join(" / ");
}

function flattenCategories(payload) {
  const options = [];
  Object.entries(payload || {}).forEach(([group, names]) => {
    if (!Array.isArray(names)) {
      return;
    }
    names.forEach((name) => {
      const trimmed = safeText(name);
      if (!trimmed) {
        return;
      }
      options.push({
        key: `${group}::${trimmed}`,
        label: `${group} / ${trimmed}`,
        group,
        name: trimmed
      });
    });
  });
  return options;
}

function pickDefaultCategoryKey() {
  if (!categoryOptions.value.length) {
    return "";
  }
  return categoryOptions.value[0].key;
}

async function fetchMpApi(path, init = {}) {
  let auth = {};
  try {
    auth = JSON.parse(localStorage.getItem("auth") || "{}");
  } catch (error) {
    auth = {};
  }

  const token = auth?.token;
  const headers = {
    Accept: "application/json",
    ...(init.headers || {})
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`/api/v1/${path}`, {
    ...init,
    headers
  });
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    payload = { message: text };
  }
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.message || `请求失败 (${response.status})`);
  }
  return payload;
}

async function fetchCategories(force = false) {
  if (!force && categoryOptions.value.length) {
    return;
  }
  categoryLoading.value = true;
  try {
    const payload = await fetchMpApi("media/category");
    categoryOptions.value = flattenCategories(payload);
    selectedCategoryKey.value = pickDefaultCategoryKey();
  } catch (error) {
    statusMessage.value = error?.message || "读取 MoviePilot 分类失败。";
  } finally {
    categoryLoading.value = false;
  }
}

async function fetchState() {
  try {
    const payload = normalizePayload(await props.api.get("plugin/Panlink115/state"));
    if (payload?.message) {
      statusMessage.value = payload.message;
    }
    keyword.value = payload?.keyword || "";
    searchResults.value = payload?.results || [];
    selectedMedia.value = payload?.selected_media && Object.keys(payload.selected_media).length
      ? payload.selected_media
      : null;
    linkGroups.value = payload?.link_groups || {};
    queueItems.value = payload?.queue || [];
    pluginState.value = {
      enabled: Boolean(payload?.enabled),
      only_show_115: Boolean(payload?.only_show_115),
      max_results: Number(payload?.max_results || 10),
      submit_mode: payload?.submit_mode || "direct_115",
      u115_auth_label: payload?.u115_auth_label || "115 网页 Cookie",
      u115_cookie_configured: Boolean(payload?.u115_cookie_configured),
      mp_u115_configured: Boolean(payload?.mp_u115_configured),
      mp_u115_ready: Boolean(payload?.mp_u115_ready),
      workflow_label: payload?.workflow_label || "直连 115",
      direct_target_hint: payload?.direct_target_hint || ""
    };
  } catch (error) {
    statusMessage.value = error?.message || "读取插件状态失败。";
  }
}

async function searchPanlink() {
  const trimmed = keyword.value.trim();
  if (!trimmed || searching.value) {
    return;
  }
  searching.value = true;
  try {
    const payload = normalizePayload(await props.api.get("plugin/Panlink115/search", { keyword: trimmed }));
    statusMessage.value = payload?.message || "搜索完成。";
    searchResults.value = payload?.results || [];
    selectedMedia.value = payload?.selected_media && Object.keys(payload.selected_media).length
      ? payload.selected_media
      : null;
    linkGroups.value = payload?.link_groups || {};
    queueItems.value = payload?.queue || queueItems.value;
  } catch (error) {
    statusMessage.value = error?.message || "搜索失败。";
  } finally {
    searching.value = false;
  }
}

async function loadLinks(item) {
  if (!item?.vod_id || loadingVodId.value) {
    return;
  }
  loadingVodId.value = item.vod_id;
  try {
    const payload = normalizePayload(
      await props.api.get("plugin/Panlink115/load_links", {
        vod_id: item.vod_id,
        vod_name: item.vod_name || "",
        keyword: keyword.value.trim() || item.vod_name || ""
      })
    );
    statusMessage.value = payload?.message || "加载资源完成。";
    selectedMedia.value = payload?.selected_media || item;
    linkGroups.value = payload?.link_groups || {};
  } catch (error) {
    statusMessage.value = error?.message || "加载资源失败。";
  } finally {
    loadingVodId.value = "";
  }
}

function openGroup(groupName) {
  activeGroupName.value = groupName;
  activeEntries.value = Array.isArray(linkGroups.value?.[groupName]) ? linkGroups.value[groupName] : [];
  groupDialog.value = true;
}

async function chooseEntry(entry) {
  selectedEntry.value = entry;
  await fetchCategories();
  downloadDialog.value = true;
}

async function submitSelectedEntry() {
  if (!selectedEntry.value || !selectedCategory.value || queueLoading.value) {
    return;
  }
  queueLoading.value = true;
  try {
    const media = selectedMedia.value || {};
    const payload = normalizePayload(
      await props.api.get("plugin/Panlink115/queue_115", {
        title: selectedEntry.value.title || media.vod_name || keyword.value.trim(),
        url: selectedEntry.value.url || "",
        password: selectedEntry.value.password || "",
        source: selectedEntry.value.source || "",
        vod_id: media.vod_id || "",
        vod_name: media.vod_name || "",
        type_name: media.type_name || "",
        category_group: selectedCategory.value.group,
        category_name: selectedCategory.value.name
      })
    );
    statusMessage.value = payload?.message || "已提交到 115。";
    queueItems.value = payload?.queue || queueItems.value;
    latestQueueKey.value = payload?.item?.queued_at || "";
    downloadDialog.value = false;
    await nextTick();
    queueSectionRef.value?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    statusMessage.value = error?.message || "提交到 115 失败。";
  } finally {
    queueLoading.value = false;
  }
}

async function clearQueue() {
  if (queueLoading.value) {
    return;
  }
  queueLoading.value = true;
  try {
    const payload = normalizePayload(await props.api.get("plugin/Panlink115/clear_queue"));
    statusMessage.value = payload?.message || "任务队列已清空。";
    queueItems.value = payload?.queue || [];
  } catch (error) {
    statusMessage.value = error?.message || "清空任务队列失败。";
  } finally {
    queueLoading.value = false;
  }
}

onMounted(async () => {
  await fetchState();
  await fetchCategories();
});
</script>

<template>
  <div class="panlink-page">
    <div class="hero-card">
      <div class="hero-copy">
        <div class="eyebrow">Panlink115</div>
        <h1>直连 115 分享转存</h1>
        <p>{{ statusMessage }}</p>
      </div>
      <div class="hero-side">
        <VChip color="primary" variant="outlined">{{ pluginState.workflow_label }}</VChip>
        <div class="hero-meta">{{ authSummaryText }}</div>
      </div>
    </div>

    <VAlert type="info" variant="tonal" class="mb-4">
      当前模式：直连 115。目标目录复用 MoviePilot 的 u115 存储，分享转存使用 115 网页 Cookie。
    </VAlert>

    <VAlert
      :type="pluginState.mp_u115_ready && pluginState.u115_cookie_configured ? 'success' : 'warning'"
      variant="outlined"
      class="mb-6"
    >
      MP u115：{{ pluginState.mp_u115_ready ? "已就绪" : "未就绪" }}，
      115 Cookie：{{ pluginState.u115_cookie_configured ? "已配置" : "未配置" }}
    </VAlert>

    <div class="panel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title">搜索资源</div>
          <div class="panel-subtitle">{{ resultCountText }}</div>
        </div>
      </div>

      <div class="search-bar">
        <VTextField
          v-model="keyword"
          label="影视名称"
          placeholder="输入电影、剧集、综艺名称"
          hide-details
          density="comfortable"
          @keyup.enter="searchPanlink"
        />
        <VBtn color="primary" :loading="searching" @click="searchPanlink">搜索</VBtn>
      </div>

      <div v-if="searchResults.length" class="result-grid">
        <VCard v-for="item in searchResults" :key="item.vod_id" class="result-card" variant="outlined">
          <VImg v-if="item.vod_pic" :src="item.vod_pic" height="240" cover />
          <VCardText class="d-flex flex-column ga-3">
            <div>
              <div class="result-title">{{ item.vod_name }}</div>
              <div class="result-subtitle">{{ resultSubtitle(item) || "暂无附加信息" }}</div>
            </div>
            <div class="fact-list">
              <VChip v-for="fact in mediaFacts(item)" :key="fact" size="small" variant="tonal">{{ fact }}</VChip>
            </div>
            <VBtn
              color="primary"
              variant="flat"
              :loading="loadingVodId === item.vod_id"
              @click="loadLinks(item)"
            >
              查看网盘链接
            </VBtn>
          </VCardText>
        </VCard>
      </div>
    </div>

    <div v-if="selectedMedia" class="panel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title">资源详情</div>
          <div class="panel-subtitle">{{ selectedMedia.vod_name }}</div>
        </div>
      </div>

      <div class="media-overview">
        <VImg v-if="selectedMedia.vod_pic" :src="selectedMedia.vod_pic" class="media-poster" cover />
        <div class="media-copy">
          <div class="fact-list">
            <VChip v-for="fact in mediaFacts(selectedMedia)" :key="fact" size="small" variant="outlined">{{ fact }}</VChip>
          </div>
          <div class="meta-grid">
            <div v-for="entry in mediaMeta(selectedMedia)" :key="entry.label" class="meta-line">
              <span>{{ entry.label }}</span>
              <strong>{{ entry.value }}</strong>
            </div>
          </div>
          <p class="media-content">{{ selectedMedia.vod_content || "暂无剧情简介" }}</p>
        </div>
      </div>

      <div v-if="groupCards.length" class="group-grid">
        <VCard v-for="group in groupCards" :key="group.name" class="group-card" variant="outlined" @click="openGroup(group.name)">
          <VCardText>
            <div class="group-title">{{ group.label }}</div>
            <div class="group-subtitle">{{ group.count }} 条链接</div>
          </VCardText>
        </VCard>
      </div>
    </div>

    <div ref="queueSectionRef" class="panel-card">
      <div class="panel-head">
        <div>
          <div class="panel-title">任务队列</div>
          <div class="panel-subtitle">{{ queueCountText }}</div>
        </div>
        <VBtn variant="text" :loading="queueLoading" @click="clearQueue">清空队列</VBtn>
      </div>

      <div v-if="queueItems.length" class="queue-list">
        <VCard
          v-for="item in queueItems"
          :key="`${item.url}-${item.target_path}-${item.queued_at}`"
          class="queue-card"
          variant="outlined"
          :class="{ latest: latestQueueKey && item.queued_at === latestQueueKey }"
        >
          <VCardText class="d-flex flex-column ga-2">
            <div class="queue-title">{{ item.vod_name || item.title }}</div>
            <div class="queue-path">分类：{{ item.category_group }} / {{ item.category_name }}</div>
            <div class="queue-path">目标目录：{{ item.target_path }}</div>
            <div class="queue-path">目标 CID：{{ item.target_cid || "未知" }}</div>
            <div class="queue-path">认证：{{ item.auth_label || "115 网页 Cookie" }}</div>
            <div class="queue-status">{{ item.status }}</div>
          </VCardText>
        </VCard>
      </div>
      <VAlert v-else type="info" variant="outlined">暂无任务。</VAlert>
    </div>

    <VDialog v-model="groupDialog" max-width="880">
      <VCard>
        <VCardTitle>{{ diskLabel(activeGroupName) }}</VCardTitle>
        <VCardText class="dialog-list">
          <VCard v-for="entry in activeEntries" :key="`${entry.url}-${entry.password}`" class="dialog-card" variant="outlined">
            <VCardText class="d-flex flex-column ga-3">
              <div>
                <div class="dialog-title">{{ entry.title || "未命名资源" }}</div>
                <div class="dialog-subtitle">{{ entrySubtitle(entry) }}</div>
              </div>
              <div class="dialog-entry-url">{{ entry.url }}</div>
              <div class="dialog-entry-pass">提取码：{{ entry.password || "无" }}</div>
              <VBtn color="primary" :disabled="activeGroupName !== '115'" @click="chooseEntry(entry)"> {{ submitButtonText }} </VBtn>
            </VCardText>
          </VCard>
        </VCardText>
        <VCardActions>
          <VSpacer />
          <VBtn variant="text" @click="groupDialog = false">关闭</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>

    <VDialog v-model="downloadDialog" max-width="640">
      <VCard>
        <VCardTitle>提交到 115</VCardTitle>
        <VCardText class="d-flex flex-column ga-4">
          <VAlert type="info" variant="tonal">
            目标目录会根据 MoviePilot 当前分类对应的 u115 存储自动解析。
          </VAlert>

          <div v-if="selectedEntry" class="dialog-summary">
            <div class="dialog-title">{{ selectedEntry.title || "未命名资源" }}</div>
            <div class="dialog-entry-url">{{ selectedEntry.url }}</div>
            <div class="dialog-entry-pass">提取码：{{ selectedEntry.password || "无" }}</div>
          </div>

          <VSelect
            v-model="selectedCategoryKey"
            :items="categoryOptions"
            :loading="categoryLoading"
            item-title="label"
            item-value="key"
            label="MoviePilot 分类"
          />
        </VCardText>
        <VCardActions>
          <VSpacer />
          <VBtn variant="text" @click="downloadDialog = false">取消</VBtn>
          <VBtn color="primary" :loading="queueLoading" :disabled="!selectedCategory" @click="submitSelectedEntry">提交</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
.panlink-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 12px 4px 32px;
}

.hero-card,
.panel-card {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 28px;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.96), rgba(238, 244, 255, 0.94)),
    radial-gradient(circle at top right, rgba(47, 119, 255, 0.14), transparent 40%);
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 28px;
}

.eyebrow {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #2f77ff;
}

.hero-copy h1 {
  margin: 10px 0 8px;
  font-size: 32px;
  line-height: 1.1;
}

.hero-copy p,
.hero-meta {
  margin: 0;
  color: rgba(15, 23, 42, 0.68);
}

.hero-side {
  display: flex;
  min-width: 220px;
  flex-direction: column;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}

.panel-card {
  padding: 22px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-bottom: 18px;
}

.panel-title {
  font-size: 20px;
  font-weight: 700;
}

.panel-subtitle {
  color: rgba(15, 23, 42, 0.62);
}

.search-bar {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
}

.result-grid,
.group-grid,
.queue-list,
.dialog-list {
  display: grid;
  gap: 16px;
}

.result-grid {
  margin-top: 18px;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.result-card,
.group-card,
.queue-card,
.dialog-card {
  border-radius: 22px;
}

.result-title,
.group-title,
.queue-title,
.dialog-title {
  font-size: 18px;
  font-weight: 700;
}

.result-subtitle,
.group-subtitle,
.dialog-subtitle {
  color: rgba(15, 23, 42, 0.6);
}

.fact-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.media-overview {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 18px;
}

.media-poster {
  border-radius: 20px;
  overflow: hidden;
}

.media-copy {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.media-content,
.dialog-entry-url {
  color: rgba(15, 23, 42, 0.72);
  word-break: break-all;
}

.meta-grid {
  display: grid;
  gap: 8px;
}

.meta-line {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 8px;
  border-bottom: 1px dashed rgba(15, 23, 42, 0.12);
}

.queue-path,
.queue-status,
.dialog-entry-pass {
  color: rgba(15, 23, 42, 0.72);
}

.queue-card.latest {
  border-color: rgba(47, 119, 255, 0.48);
  box-shadow: 0 0 0 3px rgba(47, 119, 255, 0.08);
}

@media (max-width: 900px) {
  .hero-card,
  .media-overview {
    grid-template-columns: 1fr;
    display: grid;
  }

  .hero-side {
    min-width: 0;
    align-items: flex-start;
  }

  .search-bar {
    grid-template-columns: 1fr;
  }
}
</style>
