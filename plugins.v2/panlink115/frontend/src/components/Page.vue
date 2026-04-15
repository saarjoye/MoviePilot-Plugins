<script setup>
import { computed, nextTick, onMounted, ref } from "vue";

const emit = defineEmits(["action", "switch", "close"]);

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
const pluginState = ref({
  enabled: false,
  only_show_115: true,
  max_results: 10
});
const groupDialog = ref(false);
const downloadDialog = ref(false);
const activeGroupName = ref("");
const activeEntries = ref([]);
const selectedEntry = ref(null);
const categoryOptions = ref([]);
const selectedCategoryKey = ref("");
const queueSectionRef = ref(null);
const latestQueueKey = ref("");

const resultCountText = computed(() => `共 ${searchResults.value.length} 条候选结果`);
const queueCountText = computed(() => `任务队列 ${queueItems.value.length} 条`);
const groupCards = computed(() =>
  Object.entries(linkGroups.value || {}).map(([name, entries]) => ({
    name,
    label: diskLabel(name),
    count: Array.isArray(entries) ? entries.length : 0
  }))
);
const selectedCategoryLabel = computed(() => {
  const matched = categoryOptions.value.find((item) => item.key === selectedCategoryKey.value);
  return matched ? matched.label : "";
});

function normalizePayload(response) {
  return response?.data ?? response ?? {};
}

function safeText(value) {
  return String(value || "").trim();
}

function resultSubtitle(item) {
  return [item.type_name, item.vod_year, item.vod_area, item.vod_remarks].filter(Boolean).join(" / ");
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

function openGroupDialog(name) {
  activeGroupName.value = name;
  activeEntries.value = Array.isArray(linkGroups.value?.[name]) ? linkGroups.value[name] : [];
  groupDialog.value = true;
}

function entrySubtitle(entry) {
  return [entry.source || "未知来源", entry.time || "未知时间"].join(" / ");
}

function queueSubtitle(item) {
  return `${item.category_group} / ${item.category_name}`;
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
  const current = categoryOptions.value.find((item) => item.key === selectedCategoryKey.value);
  return current?.key || categoryOptions.value[0].key;
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
      max_results: Number(payload?.max_results || 10)
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
  statusMessage.value = `正在搜索“${trimmed}”…`;
  linkGroups.value = {};
  selectedMedia.value = null;
  try {
    const payload = normalizePayload(
      await props.api.get("plugin/Panlink115/search", {
        params: { keyword: trimmed }
      })
    );
    searchResults.value = payload?.results || [];
    selectedMedia.value = payload?.selected_media?.vod_id ? payload.selected_media : searchResults.value[0] || null;
    linkGroups.value = payload?.link_groups || {};
    statusMessage.value = payload?.message || "搜索完成。";
    if (searchResults.value.length) {
      await loadLinks(searchResults.value[0]);
    }
    emit("action");
  } catch (error) {
    searchResults.value = [];
    selectedMedia.value = null;
    statusMessage.value = error?.message || "搜索失败。";
  } finally {
    searching.value = false;
  }
}

async function loadLinks(item) {
  if (!item?.vod_id || loadingVodId.value) {
    return;
  }

  selectedMedia.value = { ...item };
  loadingVodId.value = item.vod_id;
  statusMessage.value = `正在加载《${item.vod_name}》的盘链资源…`;
  try {
    const payload = normalizePayload(
      await props.api.get("plugin/Panlink115/load_links", {
        params: {
          vod_id: item.vod_id,
          keyword: item.vod_name
        }
      })
    );
    selectedMedia.value = payload?.detail || selectedMedia.value;
    linkGroups.value = payload?.links || {};
    statusMessage.value = payload?.message || "资源加载完成。";
    emit("action");
  } catch (error) {
    linkGroups.value = {};
    statusMessage.value = error?.message || "资源加载失败。";
  } finally {
    loadingVodId.value = "";
  }
}

async function openDownloadDialog(entry) {
  selectedEntry.value = entry;
  await fetchCategories();
  selectedCategoryKey.value = pickDefaultCategoryKey();
  downloadDialog.value = true;
}

async function queue115() {
  if (!selectedEntry.value?.url || !selectedCategoryKey.value || queueLoading.value) {
    return;
  }

  const selectedCategory = categoryOptions.value.find((item) => item.key === selectedCategoryKey.value);
  if (!selectedCategory) {
    statusMessage.value = "请先选择 MoviePilot 分类。";
    return;
  }

  queueLoading.value = true;
  try {
    const payload = normalizePayload(
      await props.api.get("plugin/Panlink115/queue_115", {
        params: {
          title: selectedEntry.value.title,
          url: selectedEntry.value.url,
          password: selectedEntry.value.password,
          source: selectedEntry.value.source,
          vod_id: selectedMedia.value?.vod_id,
          vod_name: selectedMedia.value?.vod_name,
          type_name: selectedMedia.value?.type_name,
          category_group: selectedCategory.group,
          category_name: selectedCategory.name
        }
      })
    );
    queueItems.value = payload?.queue || queueItems.value;
    const queuedItem = payload?.item || queueItems.value?.[0];
    latestQueueKey.value = queuedItem ? `${queuedItem.url}-${queuedItem.category_name}` : "";
    statusMessage.value = payload?.message || "已创建下载任务。";
    downloadDialog.value = false;
    await nextTick();
    queueSectionRef.value?.scrollIntoView({ behavior: "smooth", block: "start" });
    emit("action");
  } catch (error) {
    statusMessage.value = error?.message || "创建下载任务失败。";
  } finally {
    queueLoading.value = false;
  }
}

async function clearQueue() {
  if (!queueItems.value.length || queueLoading.value) {
    return;
  }

  queueLoading.value = true;
  try {
    const payload = normalizePayload(await props.api.get("plugin/Panlink115/clear_queue"));
    queueItems.value = payload?.queue || [];
    statusMessage.value = payload?.message || "任务队列已清空。";
    emit("action");
  } catch (error) {
    statusMessage.value = error?.message || "清空队列失败。";
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
  <div class="page-shell">
    <VCard class="hero-panel" rounded="xl">
      <VCardText class="hero-content">
        <div class="hero-head">
          <div>
            <div class="hero-kicker">PANLIAN x MOVIEPILOT</div>
            <h1 class="hero-title">盘链搜索与 115 提交</h1>
            <p class="hero-text">搜索盘链资源，查看 115 链接，并优先按 MoviePilot 的“存储 & 目录”映射结果提交到 CD2。</p>
          </div>
          <div class="hero-chips">
            <VChip :color="pluginState.enabled ? 'success' : 'warning'" size="small" variant="flat">
              {{ pluginState.enabled ? "插件已启用" : "插件未启用" }}
            </VChip>
            <VChip size="small" variant="outlined">
              {{ pluginState.only_show_115 ? "当前仅显示 115" : "当前显示全部网盘" }}
            </VChip>
            <VChip size="small" variant="outlined">
              最大 {{ pluginState.max_results }} 条结果
            </VChip>
            <VChip size="small" variant="outlined">
              {{ queueCountText }}
            </VChip>
          </div>
        </div>

        <VAlert type="info" variant="tonal" class="mb-4">
          {{ statusMessage }}
        </VAlert>

        <div class="hero-actions">
          <VTextField
            v-model="keyword"
            clearable
            density="comfortable"
            hide-details="auto"
            label="影视名称"
            placeholder="例如：流浪地球、危险关系、庆余年"
            @keyup.enter="searchPanlink"
          />
          <div class="hero-buttons">
            <VBtn color="primary" :loading="searching" @click="searchPanlink">搜索盘链</VBtn>
            <VBtn variant="text" color="primary" @click="emit('switch')">打开插件配置</VBtn>
            <VBtn variant="text" color="default" @click="fetchState">刷新状态</VBtn>
            <VBtn variant="text" color="default" @click="emit('close')">关闭</VBtn>
          </div>
        </div>
      </VCardText>
    </VCard>

    <div class="content-grid">
      <VCard class="result-panel" rounded="xl">
        <VCardTitle class="panel-title">
          <span>搜索结果</span>
          <span class="panel-subtitle">{{ resultCountText }}</span>
        </VCardTitle>
        <VCardText v-if="searchResults.length" class="result-list">
          <button
            v-for="item in searchResults"
            :key="item.vod_id"
            type="button"
            class="result-card"
            :class="{ active: selectedMedia?.vod_id === item.vod_id }"
            @click="loadLinks(item)"
          >
            <img class="result-thumb" :src="item.vod_pic || 'https://115.com/favicon.ico'" :alt="item.vod_name">
            <div class="result-body">
              <div class="result-name">{{ item.vod_name }}</div>
              <div class="result-subtitle">{{ resultSubtitle(item) || `vod_id=${item.vod_id}` }}</div>
              <div class="result-subtitle">语言：{{ item.vod_lang || "未知" }}</div>
            </div>
            <div class="result-tail">
              <VProgressCircular v-if="loadingVodId === item.vod_id" indeterminate size="18" width="2" />
              <span v-else>查看</span>
            </div>
          </button>
        </VCardText>
        <VCardText v-else>
          <VAlert type="info" variant="tonal">暂无搜索结果。输入关键词后点击“搜索盘链”即可开始查询。</VAlert>
        </VCardText>
      </VCard>

      <div class="detail-stack">
        <VCard v-if="selectedMedia" class="detail-panel" rounded="xl">
          <VCardText>
            <div class="detail-header">
              <img class="detail-poster" :src="selectedMedia.vod_pic || 'https://115.com/favicon.ico'" :alt="selectedMedia.vod_name">
              <div class="detail-copy">
                <div class="detail-title-row">
                  <div>
                    <div class="detail-eyebrow">盘链详情</div>
                    <h2 class="detail-title">{{ selectedMedia.vod_name }}</h2>
                  </div>
                  <a
                    v-if="selectedMedia.detail_url"
                    class="detail-link"
                    :href="selectedMedia.detail_url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    打开盘链原页
                  </a>
                </div>
                <div class="detail-tags">
                  <span v-for="fact in mediaFacts(selectedMedia)" :key="fact" class="detail-tag">{{ fact }}</span>
                </div>
                <div class="detail-meta-grid">
                  <div v-for="meta in mediaMeta(selectedMedia)" :key="meta.label" class="meta-item">
                    <span class="meta-label">{{ meta.label }}</span>
                    <span class="meta-value">{{ meta.value }}</span>
                  </div>
                  <div v-if="selectedMedia.vod_actor" class="meta-item full-width">
                    <span class="meta-label">主演</span>
                    <span class="meta-value">{{ selectedMedia.vod_actor }}</span>
                  </div>
                </div>
                <div v-if="selectedMedia.vod_content" class="plot-panel">
                  <div class="plot-title">剧情简介</div>
                  <p class="plot-text">{{ selectedMedia.vod_content }}</p>
                </div>
              </div>
            </div>
          </VCardText>
        </VCard>

        <VCard class="resource-panel" rounded="xl">
          <VCardTitle class="panel-title">
            <span>资源展示</span>
            <span class="panel-subtitle">分类由你手动选择</span>
          </VCardTitle>
          <VCardText v-if="groupCards.length" class="resource-grid">
            <button
              v-for="group in groupCards"
              :key="group.name"
              type="button"
              class="resource-card"
              :class="{ primary: group.name === '115' }"
              @click="openGroupDialog(group.name)"
            >
              <div class="resource-name">{{ group.label }}</div>
              <div class="resource-count">{{ group.count }} 条</div>
              <div class="resource-hint">{{ group.name === "115" ? "点击查看并创建下载任务" : "点击查看原始链接" }}</div>
            </button>
          </VCardText>
          <VCardText v-else>
            <VAlert type="info" variant="tonal">先从左侧选择一个搜索结果，这里就会展示对应的网盘资源分组。</VAlert>
          </VCardText>
        </VCard>

        <VCard ref="queueSectionRef" class="queue-panel" rounded="xl">
          <VCardTitle class="panel-title">
            <span>下载任务</span>
            <VBtn color="warning" variant="text" :disabled="!queueItems.length" :loading="queueLoading" @click="clearQueue">清空队列</VBtn>
          </VCardTitle>
          <VCardText v-if="queueItems.length" class="queue-list">
            <VAlert type="success" variant="tonal">当前“下载”会真实调用 CD2，并优先按 MoviePilot 的目录映射把盘链 115 链接提交到目标目录中。</VAlert>
            <article
              v-for="item in queueItems"
              :key="`${item.url}-${item.category_name}`"
              class="queue-card"
              :class="{ latest: latestQueueKey === `${item.url}-${item.category_name}` }"
            >
              <div class="queue-name">{{ item.vod_name || item.title }}</div>
              <div class="queue-path">分类：{{ queueSubtitle(item) }}</div>
              <div v-if="item.target_path" class="queue-path">CD2 目录：{{ item.target_path }}</div>
              <div v-if="item.created_path" class="queue-path">检测到新目录：{{ item.created_path }}</div>
              <div class="queue-meta">
                <span>来源：{{ item.source || "未知" }}</span>
                <span>创建时间：{{ item.queued_at }}</span>
              </div>
              <div class="queue-status">{{ item.status }}</div>
              <div class="queue-url">{{ item.url }}</div>
              <div class="queue-pass">提取码：{{ item.password || "无" }}</div>
            </article>
          </VCardText>
          <VCardText v-else>
            <VAlert type="info" variant="tonal">还没有下载任务。打开 115 资源弹层后点击“下载”，并选择一个 MoviePilot 分类即可提交到 115。</VAlert>
          </VCardText>
        </VCard>
      </div>
    </div>

    <VDialog v-model="groupDialog" max-width="920">
      <VCard rounded="xl">
        <VCardTitle class="panel-title">
          <span>{{ diskLabel(activeGroupName) }}</span>
          <VChip size="small" variant="outlined">共 {{ activeEntries.length }} 条</VChip>
        </VCardTitle>
        <VCardText v-if="activeEntries.length" class="dialog-list">
          <article v-for="entry in activeEntries" :key="entry.url" class="dialog-entry">
            <div class="dialog-entry-title">{{ entry.title || "未命名资源" }}</div>
            <div class="dialog-entry-subtitle">{{ entrySubtitle(entry) }}</div>
            <div class="dialog-entry-url">{{ entry.url }}</div>
            <div class="dialog-entry-pass">提取码：{{ entry.password || "无" }}</div>
            <div class="dialog-actions">
              <VBtn v-if="activeGroupName === '115'" color="primary" variant="flat" @click="openDownloadDialog(entry)">下载</VBtn>
              <VBtn :href="entry.url" target="_blank" rel="noopener noreferrer" variant="text">打开链接</VBtn>
            </div>
          </article>
        </VCardText>
        <VCardText v-else>
          <VAlert type="info" variant="tonal">当前分组没有可展示的链接。</VAlert>
        </VCardText>
      </VCard>
    </VDialog>

    <VDialog v-model="downloadDialog" max-width="720">
      <VCard rounded="xl">
        <VCardTitle>创建 115 下载任务</VCardTitle>
        <VCardText class="dialog-list">
          <VAlert type="info" variant="tonal">
            分类直接读取 MoviePilot 当前配置；提交时会先匹配 MoviePilot 的“存储 & 目录”，再按“CD2 MP目录映射”换算目标路径，最后才回退到分类映射和默认根目录。
          </VAlert>

          <div class="download-summary">
            <div class="download-row">
              <span class="download-label">影视条目</span>
              <span>{{ selectedMedia?.vod_name || "未选择" }}</span>
            </div>
            <div class="download-row">
              <span class="download-label">资源标题</span>
              <span>{{ selectedEntry?.title || "未选择" }}</span>
            </div>
          </div>

          <VSelect
            v-model="selectedCategoryKey"
            :items="categoryOptions"
            item-title="label"
            item-value="key"
            label="MoviePilot 分类"
            placeholder="请选择分类"
            :loading="categoryLoading"
            hide-details="auto"
          />

          <div v-if="selectedCategoryLabel" class="selection-preview">
            当前任务将写入：{{ selectedCategoryLabel }}
          </div>
        </VCardText>
        <VCardActions class="px-6 pb-5">
          <VSpacer />
          <VBtn variant="text" @click="downloadDialog = false">取消</VBtn>
          <VBtn color="primary" variant="flat" :loading="queueLoading" @click="queue115">提交到 115</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
:global(:root) {
  --panlink-bg: linear-gradient(180deg, #f5f7fb 0%, #edf2fb 100%);
  --panlink-card: rgba(255, 255, 255, 0.92);
  --panlink-border: rgba(34, 76, 138, 0.12);
  --panlink-ink: #18314f;
  --panlink-muted: #62748c;
  --panlink-primary: #2164f3;
}

.page-shell {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 8px;
  color: var(--panlink-ink);
}

.hero-panel,
.result-panel,
.detail-panel,
.resource-panel,
.queue-panel {
  background: var(--panlink-card);
  border: 1px solid var(--panlink-border);
}

.hero-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hero-head {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hero-kicker {
  font-size: 12px;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: var(--panlink-muted);
}

.hero-title {
  margin: 6px 0 8px;
  font-size: 30px;
  line-height: 1.1;
}

.hero-text {
  margin: 0;
  color: var(--panlink-muted);
  line-height: 1.7;
}

.hero-chips,
.hero-buttons,
.detail-tags,
.queue-meta,
.dialog-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hero-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.content-grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.detail-stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-subtitle {
  font-size: 12px;
  color: var(--panlink-muted);
}

.result-list,
.queue-list,
.dialog-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-card,
.resource-card {
  width: 100%;
  border: 1px solid var(--panlink-border);
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  padding: 12px;
  text-align: left;
  cursor: pointer;
}

.result-card {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.result-card.active {
  border-color: rgba(33, 100, 243, 0.4);
  box-shadow: 0 0 0 3px rgba(33, 100, 243, 0.1);
}

.result-thumb,
.detail-poster {
  object-fit: cover;
  border-radius: 12px;
  background: #dbe5f4;
}

.result-thumb {
  width: 64px;
  height: 92px;
}

.result-name,
.queue-name,
.dialog-entry-title,
.resource-name {
  font-weight: 700;
}

.result-subtitle,
.resource-hint,
.queue-path,
.dialog-entry-subtitle,
.dialog-entry-pass,
.queue-url,
.queue-pass {
  color: var(--panlink-muted);
  font-size: 13px;
  line-height: 1.5;
}

.result-tail {
  font-size: 13px;
  color: var(--panlink-primary);
}

.detail-header {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 18px;
}

.detail-poster {
  width: 100%;
  aspect-ratio: 2 / 3;
}

.detail-copy {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.detail-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.detail-eyebrow,
.meta-label,
.download-label {
  font-size: 12px;
  color: var(--panlink-muted);
}

.detail-title {
  margin: 6px 0 0;
  font-size: 28px;
  line-height: 1.2;
}

.detail-link {
  color: var(--panlink-primary);
  text-decoration: none;
}

.detail-tag {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(33, 100, 243, 0.08);
  color: var(--panlink-primary);
  font-size: 12px;
}

.detail-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-item.full-width {
  grid-column: 1 / -1;
}

.plot-panel {
  padding: 14px;
  border-radius: 14px;
  background: rgba(24, 49, 79, 0.04);
}

.plot-title {
  font-weight: 700;
  margin-bottom: 8px;
}

.plot-text {
  margin: 0;
  color: var(--panlink-muted);
  line-height: 1.7;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.resource-card.primary {
  border-color: rgba(33, 100, 243, 0.35);
}

.resource-count,
.queue-status,
.selection-preview {
  font-size: 13px;
  font-weight: 600;
  color: var(--panlink-primary);
}

.queue-card,
.dialog-entry,
.download-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--panlink-border);
  background: rgba(255, 255, 255, 0.96);
}

.queue-card.latest {
  border-color: rgba(33, 100, 243, 0.4);
  box-shadow: 0 0 0 3px rgba(33, 100, 243, 0.08);
}

.download-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

@media (max-width: 960px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .detail-header {
    grid-template-columns: 1fr;
  }

  .detail-poster {
    max-width: 220px;
  }
}
</style>
