<script setup>
import { computed, onMounted, ref } from "vue";

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
const preferredCategoryHint = computed(() => {
  if (!selectedMedia.value) {
    return "";
  }
  return inferPreferredGroup(selectedMedia.value);
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
  return [
    item.vod_year,
    item.vod_area,
    item.type_name,
    item.vod_remarks
  ].filter(Boolean);
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

function inferPreferredGroup(item) {
  const text = [item?.type_name, item?.vod_name, item?.vod_remarks].filter(Boolean).join(" ");
  if (/剧|综艺|纪录|动漫|国漫|日番|番/.test(text)) {
    return "电视剧";
  }
  return "电影";
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
  const preferredGroup = inferPreferredGroup(selectedMedia.value);
  const exact = categoryOptions.value.find((item) => item.group === preferredGroup);
  return exact?.key || categoryOptions.value[0].key;
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
    if (!selectedCategoryKey.value) {
      selectedCategoryKey.value = pickDefaultCategoryKey();
    }
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
    statusMessage.value = payload?.message || "已创建下载任务。";
    downloadDialog.value = false;
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
    <section class="hero-panel">
      <div class="hero-copy">
        <div class="hero-kicker">PANLIAN x MOVIEPILOT</div>
        <h1 class="hero-title">盘链搜索与 115 下载任务面板</h1>
        <p class="hero-text">
          手动查询电视剧或电影，按盘链详情页方式查看资源，并把 115 链接投递到基于 MoviePilot 当前分类的下载任务里。
        </p>
        <div class="hero-chips">
          <VChip :color="pluginState.enabled ? 'success' : 'warning'" size="small" variant="flat">
            {{ pluginState.enabled ? "插件已启用" : "插件未启用" }}
          </VChip>
          <VChip size="small" variant="outlined">
            {{ pluginState.only_show_115 ? "当前仅显示 115" : "当前显示全部网盘" }}
          </VChip>
          <VChip size="small" variant="outlined">
            最多 {{ pluginState.max_results }} 条结果
          </VChip>
          <VChip size="small" variant="outlined">
            {{ queueCountText }}
          </VChip>
        </div>
      </div>

      <div class="hero-search">
        <VAlert class="mb-4" type="info" variant="tonal">
          {{ statusMessage }}
        </VAlert>
        <VTextField
          v-model="keyword"
          clearable
          density="comfortable"
          hide-details="auto"
          label="影视名称"
          placeholder="例如：危险关系、流浪地球、庆余年"
          @keyup.enter="searchPanlink"
        />
        <div class="hero-actions">
          <VBtn color="primary" size="large" :loading="searching" @click="searchPanlink">
            搜索盘链
          </VBtn>
          <VBtn variant="text" color="primary" @click="emit('switch')">
            打开插件配置
          </VBtn>
          <VBtn variant="text" color="default" @click="fetchState">
            刷新状态
          </VBtn>
          <VBtn variant="text" color="default" @click="emit('close')">
            关闭
          </VBtn>
        </div>
      </div>
    </section>

    <section class="content-grid">
      <VCard class="result-panel" rounded="xl">
        <VCardTitle class="d-flex align-center justify-space-between flex-wrap ga-3">
          <span>搜索结果</span>
          <span class="text-caption text-medium-emphasis">{{ resultCountText }}</span>
        </VCardTitle>
        <VCardText v-if="searchResults.length" class="result-list">
          <button
            v-for="item in searchResults"
            :key="item.vod_id"
            class="result-card"
            :class="{ active: selectedMedia?.vod_id === item.vod_id }"
            type="button"
            @click="loadLinks(item)"
          >
            <img class="result-thumb" :src="item.vod_pic || 'https://115.com/favicon.ico'" :alt="item.vod_name">
            <div class="result-body">
              <div class="result-name">{{ item.vod_name }}</div>
              <div class="result-subtitle">{{ resultSubtitle(item) || `vod_id=${item.vod_id}` }}</div>
              <div class="result-lang">语言：{{ item.vod_lang || "未知" }}</div>
            </div>
            <div class="result-tail">
              <VProgressCircular
                v-if="loadingVodId === item.vod_id"
                indeterminate
                size="18"
                width="2"
              />
              <span v-else>查看</span>
            </div>
          </button>
        </VCardText>
        <VCardText v-else>
          <VAlert type="info" variant="tonal">
            暂无搜索结果。输入关键词后点击“搜索盘链”即可开始查询。
          </VAlert>
        </VCardText>
      </VCard>

      <div class="detail-stack">
        <VCard v-if="selectedMedia" class="detail-panel" rounded="xl">
          <div class="detail-banner" :style="{ backgroundImage: `url(${selectedMedia.vod_pic || 'https://115.com/favicon.ico'})` }"></div>
          <VCardText class="detail-content">
            <div class="detail-header">
              <img class="detail-poster" :src="selectedMedia.vod_pic || 'https://115.com/favicon.ico'" :alt="selectedMedia.vod_name">
              <div class="detail-copy">
                <div class="detail-title-row">
                  <h2 class="detail-title">{{ selectedMedia.vod_name }}</h2>
                  <a
                    v-if="selectedMedia.detail_url"
                    class="detail-link"
                    :href="selectedMedia.detail_url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    盘链原页
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
          <VCardTitle class="d-flex align-center justify-space-between flex-wrap ga-3">
            <span>资源展示</span>
            <span v-if="preferredCategoryHint" class="text-caption text-medium-emphasis">
              默认推荐分类组：{{ preferredCategoryHint }}
            </span>
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
              <div class="resource-hint">
                {{ group.name === "115" ? "点击查看并创建下载任务" : "点击查看原始链接" }}
              </div>
            </button>
          </VCardText>
          <VCardText v-else>
            <VAlert type="info" variant="tonal">
              先从左侧选择一个搜索结果，这里就会展示对应的网盘资源分组。
            </VAlert>
          </VCardText>
        </VCard>

        <VCard class="queue-panel" rounded="xl">
          <VCardTitle class="d-flex align-center justify-space-between flex-wrap ga-3">
            <span>下载任务</span>
            <VBtn
              color="warning"
              variant="text"
              :disabled="!queueItems.length"
              :loading="queueLoading"
              @click="clearQueue"
            >
              清空队列
            </VBtn>
          </VCardTitle>
          <VCardText v-if="queueItems.length" class="queue-list">
            <VAlert type="warning" variant="tonal">
              当前“下载”仍是占位任务，只会记录你选择的 115 链接和 MoviePilot 分类。下一阶段再接真实 115 转存与 MP 整理入库。
            </VAlert>
            <article v-for="item in queueItems" :key="`${item.url}-${item.category_name}`" class="queue-card">
              <div class="queue-name">{{ item.vod_name || item.title }}</div>
              <div class="queue-path">{{ queueSubtitle(item) }}</div>
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
            <VAlert type="info" variant="tonal">
              还没有下载任务。打开 115 资源弹层后点击“下载”，并选择一个 MoviePilot 分类即可创建任务。
            </VAlert>
          </VCardText>
        </VCard>
      </div>
    </section>

    <VDialog v-model="groupDialog" max-width="920">
      <VCard rounded="xl">
        <VCardTitle class="d-flex align-center justify-space-between flex-wrap ga-3">
          <span>{{ diskLabel(activeGroupName) }}</span>
          <VChip size="small" variant="outlined">
            共 {{ activeEntries.length }} 条
          </VChip>
        </VCardTitle>
        <VCardText v-if="activeEntries.length" class="dialog-list">
          <article v-for="entry in activeEntries" :key="entry.url" class="dialog-entry">
            <div class="dialog-entry-title">{{ entry.title || "未命名资源" }}</div>
            <div class="dialog-entry-subtitle">{{ entrySubtitle(entry) }}</div>
            <div class="dialog-entry-url">{{ entry.url }}</div>
            <div class="dialog-entry-pass">提取码：{{ entry.password || "无" }}</div>
            <div class="dialog-actions">
              <VBtn
                v-if="activeGroupName === '115'"
                color="primary"
                variant="flat"
                @click="openDownloadDialog(entry)"
              >
                下载
              </VBtn>
              <VBtn
                :href="entry.url"
                target="_blank"
                rel="noopener noreferrer"
                variant="text"
              >
                打开链接
              </VBtn>
            </div>
          </article>
        </VCardText>
        <VCardText v-else>
          <VAlert type="info" variant="tonal">
            当前分组没有可展示的链接。
          </VAlert>
        </VCardText>
      </VCard>
    </VDialog>

    <VDialog v-model="downloadDialog" max-width="720">
      <VCard rounded="xl">
        <VCardTitle>创建 115 下载任务</VCardTitle>
        <VCardText class="dialog-list">
          <VAlert type="info" variant="tonal">
            分类直接读取 MoviePilot 当前配置，后续真实接入整理链路时会以这里选中的分类作为落库目标。
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
            <div class="download-row">
              <span class="download-label">推荐分类组</span>
              <span>{{ preferredCategoryHint || "未识别" }}</span>
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
          <VBtn color="primary" variant="flat" :loading="queueLoading" @click="queue115">
            创建任务
          </VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
:global(:root) {
  --panlink-bg: linear-gradient(160deg, #f4f7fb 0%, #e8eef8 100%);
  --panlink-card: rgba(255, 255, 255, 0.9);
  --panlink-border: rgba(60, 86, 138, 0.12);
  --panlink-ink: #10233d;
  --panlink-muted: #5c6f8a;
  --panlink-primary: #2164f3;
  --panlink-primary-soft: rgba(33, 100, 243, 0.12);
  --panlink-gold: #ffb347;
}

.page-shell {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 8px;
  color: var(--panlink-ink);
}

.hero-panel {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 18px;
  padding: 20px;
  border-radius: 28px;
  background:
    radial-gradient(circle at top right, rgba(255, 179, 71, 0.18), transparent 32%),
    radial-gradient(circle at left bottom, rgba(33, 100, 243, 0.18), transparent 34%),
    var(--panlink-bg);
  border: 1px solid var(--panlink-border);
}

.hero-kicker {
  font-size: 12px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--panlink-muted);
}

.hero-title {
  margin: 8px 0 10px;
  font-size: 32px;
  line-height: 1.1;
}

.hero-text {
  margin: 0;
  max-width: 720px;
  color: var(--panlink-muted);
  line-height: 1.7;
}

.hero-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}

.hero-search {
  padding: 18px;
  border-radius: 24px;
  background: var(--panlink-card);
  border: 1px solid rgba(255, 255, 255, 0.55);
  box-shadow: 0 18px 50px rgba(16, 35, 61, 0.08);
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.content-grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.result-panel,
.detail-panel,
.resource-panel,
.queue-panel {
  background: var(--panlink-card);
  border: 1px solid var(--panlink-border);
  backdrop-filter: blur(10px);
}

.detail-stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-card {
  display: grid;
  grid-template-columns: 62px 1fr auto;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 10px;
  border: 1px solid rgba(60, 86, 138, 0.12);
  border-radius: 18px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.result-card:hover,
.result-card.active {
  transform: translateY(-1px);
  border-color: rgba(33, 100, 243, 0.36);
  box-shadow: 0 12px 30px rgba(33, 100, 243, 0.12);
}

.result-thumb {
  width: 62px;
  height: 84px;
  border-radius: 14px;
  object-fit: cover;
  background: #d8e3f7;
}

.result-name {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.4;
}

.result-subtitle,
.result-lang,
.dialog-entry-subtitle,
.queue-meta,
.queue-path,
.selection-preview {
  color: var(--panlink-muted);
}

.result-subtitle,
.result-lang,
.dialog-entry-subtitle,
.queue-meta,
.queue-status,
.download-row {
  font-size: 12px;
}

.result-tail {
  min-width: 32px;
  text-align: right;
  color: var(--panlink-primary);
  font-size: 12px;
  font-weight: 700;
}

.detail-banner {
  height: 160px;
  background-size: cover;
  background-position: center;
  filter: saturate(1.08);
  position: relative;
}

.detail-banner::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(7, 18, 35, 0.12) 0%, rgba(7, 18, 35, 0.78) 100%);
}

.detail-content {
  margin-top: -72px;
  position: relative;
  z-index: 1;
}

.detail-header {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 22px;
  align-items: start;
}

.detail-poster {
  width: 100%;
  max-width: 180px;
  aspect-ratio: 2 / 3;
  object-fit: cover;
  border-radius: 20px;
  border: 4px solid rgba(255, 255, 255, 0.9);
  box-shadow: 0 18px 50px rgba(16, 35, 61, 0.24);
  background: #dde6f6;
}

.detail-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.detail-title {
  margin: 0;
  font-size: 32px;
  line-height: 1.12;
}

.detail-link {
  color: var(--panlink-primary);
  font-size: 13px;
  text-decoration: none;
}

.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}

.detail-tag {
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(60, 86, 138, 0.1);
  font-size: 12px;
}

.detail-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(60, 86, 138, 0.08);
}

.meta-item.full-width {
  grid-column: 1 / -1;
}

.meta-label,
.plot-title,
.resource-name,
.dialog-entry-title,
.queue-name,
.download-label {
  font-weight: 700;
}

.meta-value,
.plot-text,
.dialog-entry-url,
.queue-url {
  word-break: break-all;
  line-height: 1.7;
}

.plot-panel {
  margin-top: 18px;
  padding: 18px;
  border-radius: 22px;
  background: linear-gradient(135deg, rgba(33, 100, 243, 0.08) 0%, rgba(255, 179, 71, 0.08) 100%);
}

.plot-title {
  margin-bottom: 10px;
}

.plot-text {
  margin: 0;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}

.resource-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
  border-radius: 22px;
  background: #fff;
  border: 1px solid rgba(60, 86, 138, 0.12);
  cursor: pointer;
  text-align: left;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.resource-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 16px 30px rgba(16, 35, 61, 0.08);
}

.resource-card.primary {
  background: linear-gradient(135deg, rgba(33, 100, 243, 0.94) 0%, rgba(16, 119, 255, 0.88) 100%);
  color: #fff;
  border-color: transparent;
}

.resource-count {
  font-size: 28px;
  font-weight: 800;
}

.resource-hint {
  font-size: 12px;
  opacity: 0.82;
}

.queue-list,
.dialog-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.queue-card,
.dialog-entry,
.download-summary {
  padding: 16px;
  border-radius: 20px;
  background: #fff;
  border: 1px solid rgba(60, 86, 138, 0.12);
}

.queue-name {
  font-size: 16px;
}

.queue-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 10px 0 6px;
}

.queue-status {
  display: inline-flex;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 179, 71, 0.12);
  color: #8b5d12;
  margin-bottom: 10px;
}

.queue-url {
  margin-bottom: 8px;
}

.dialog-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.download-summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.download-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.selection-preview {
  padding: 12px 14px;
  border-radius: 16px;
  background: var(--panlink-primary-soft);
}

@media (max-width: 1100px) {
  .hero-panel,
  .content-grid,
  .detail-header {
    grid-template-columns: 1fr;
  }

  .detail-content {
    margin-top: -48px;
  }

  .detail-poster {
    max-width: 160px;
  }
}

@media (max-width: 720px) {
  .hero-title,
  .detail-title {
    font-size: 24px;
  }

  .hero-panel {
    padding: 16px;
  }

  .hero-search {
    padding: 14px;
  }

  .detail-meta-grid {
    grid-template-columns: 1fr;
  }

  .download-row {
    flex-direction: column;
  }
}
</style>
