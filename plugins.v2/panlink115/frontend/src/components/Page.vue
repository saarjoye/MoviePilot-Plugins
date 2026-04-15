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
const statusMessage = ref("准备就绪。");
const searching = ref(false);
const loadingVodId = ref("");
const queueLoading = ref(false);
const searchResults = ref([]);
const linkGroups = ref({});
const queueItems = ref([]);
const pluginState = ref({
  enabled: false,
  only_show_115: true,
  max_results: 10
});

const resultCountText = computed(() => `共 ${searchResults.value.length} 条候选结果`);
const queueCountText = computed(() => `队列中 ${queueItems.value.length} 条占位任务`);

function normalizePayload(response) {
  return response?.data ?? response ?? {};
}

function groupEntries(linkMap) {
  return Object.entries(linkMap || {});
}

async function fetchState() {
  try {
    const payload = normalizePayload(await props.api.get("plugin/Panlink115/state"));
    if (payload?.message) {
      statusMessage.value = payload.message;
    }
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
  statusMessage.value = `正在搜索“${trimmed}”...`;
  linkGroups.value = {};
  try {
    const payload = normalizePayload(
      await props.api.get("plugin/Panlink115/search", {
        params: { keyword: trimmed }
      })
    );
    searchResults.value = payload?.results || [];
    statusMessage.value = payload?.message || "搜索完成。";
    emit("action");
  } catch (error) {
    searchResults.value = [];
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
  statusMessage.value = `正在加载《${item.vod_name}》资源...`;
  try {
    const payload = normalizePayload(
      await props.api.get("plugin/Panlink115/load_links", {
        params: {
          vod_id: item.vod_id,
          keyword: item.vod_name
        }
      })
    );
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

async function queue115(entry) {
  if (!entry?.url || queueLoading.value) {
    return;
  }

  queueLoading.value = true;
  try {
    const payload = normalizePayload(
      await props.api.get("plugin/Panlink115/queue_115", {
        params: {
          title: entry.title,
          url: entry.url,
          password: entry.password,
          source: entry.source
        }
      })
    );
    queueItems.value = payload?.queue || queueItems.value;
    statusMessage.value = payload?.message || "已加入队列。";
    emit("action");
  } catch (error) {
    statusMessage.value = error?.message || "加入 115 队列失败。";
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
    statusMessage.value = payload?.message || "队列已清空。";
    emit("action");
  } catch (error) {
    statusMessage.value = error?.message || "清空队列失败。";
  } finally {
    queueLoading.value = false;
  }
}

function resultSubtitle(item) {
  return [item.type_name, item.vod_year, item.vod_area, item.vod_remarks].filter(Boolean).join(" / ");
}

function groupTitle(name) {
  return name === "115" ? "115 资源" : `${name} 资源`;
}

onMounted(fetchState);
</script>

<template>
  <div class="page-shell">
    <VCard class="mb-4" variant="tonal">
      <VCardTitle class="d-flex align-center justify-space-between flex-wrap ga-3">
        <span>盘链搜索</span>
        <VChip
          :color="pluginState.enabled ? 'success' : 'warning'"
          size="small"
          variant="tonal"
        >
          {{ pluginState.enabled ? "插件已启用" : "插件未启用" }}
        </VChip>
      </VCardTitle>
      <VCardText class="d-flex flex-column ga-4">
        <div class="text-body-2 text-medium-emphasis">
          手动搜索电影或电视剧，优先展示盘链中的 115 资源，并预留“加入 115”按钮接口。
        </div>
        <VAlert type="info" variant="tonal">
          {{ statusMessage }}
        </VAlert>
        <div class="d-flex flex-wrap ga-2">
          <VChip size="small" variant="outlined">
            {{ pluginState.only_show_115 ? "当前仅显示 115" : "当前显示全部网盘" }}
          </VChip>
          <VChip size="small" variant="outlined">
            最多展示 {{ pluginState.max_results }} 条搜索结果
          </VChip>
          <VChip size="small" variant="outlined">
            {{ queueCountText }}
          </VChip>
        </div>
        <VRow>
          <VCol cols="12" md="8">
            <VTextField
              v-model="keyword"
              clearable
              density="comfortable"
              hide-details="auto"
              label="影视名称"
              placeholder="例如：危险关系、流浪地球、庆余年"
              @keyup.enter="searchPanlink"
            />
          </VCol>
          <VCol cols="12" md="4">
            <VBtn
              block
              color="primary"
              :loading="searching"
              @click="searchPanlink"
            >
              搜索盘链
            </VBtn>
          </VCol>
        </VRow>
        <div class="d-flex flex-wrap ga-2">
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
      </VCardText>
    </VCard>

    <VCard class="mb-4">
      <VCardTitle class="d-flex align-center justify-space-between flex-wrap ga-3">
        <span>搜索结果</span>
        <span class="text-caption text-medium-emphasis">{{ resultCountText }}</span>
      </VCardTitle>
      <VCardText v-if="searchResults.length" class="d-flex flex-column ga-3">
        <VCard
          v-for="item in searchResults"
          :key="item.vod_id"
          variant="outlined"
        >
          <VCardTitle>{{ item.vod_name }}</VCardTitle>
          <VCardSubtitle>
            {{ resultSubtitle(item) || `vod_id=${item.vod_id}` }}
          </VCardSubtitle>
          <VCardText class="d-flex flex-wrap ga-2">
            <VChip size="small" variant="outlined">语言：{{ item.vod_lang || "未知" }}</VChip>
            <VChip size="small" variant="outlined">编号：{{ item.vod_id }}</VChip>
          </VCardText>
          <VCardActions>
            <VBtn
              color="primary"
              variant="flat"
              :loading="loadingVodId === item.vod_id"
              @click="loadLinks(item)"
            >
              加载资源
            </VBtn>
          </VCardActions>
        </VCard>
      </VCardText>
      <VCardText v-else>
        <VAlert type="info" variant="tonal">
          暂无搜索结果。输入关键词后点击“搜索盘链”即可开始查询。
        </VAlert>
      </VCardText>
    </VCard>

    <VCard class="mb-4">
      <VCardTitle>资源列表</VCardTitle>
      <VCardText v-if="groupEntries(linkGroups).length" class="d-flex flex-column ga-4">
        <div
          v-for="[groupName, entries] in groupEntries(linkGroups)"
          :key="groupName"
          class="d-flex flex-column ga-3"
        >
          <div class="text-subtitle-1 font-weight-medium">{{ groupTitle(groupName) }}</div>
          <VCard
            v-for="entry in entries"
            :key="`${groupName}-${entry.url}`"
            variant="outlined"
          >
            <VCardTitle>{{ entry.title || "未命名资源" }}</VCardTitle>
            <VCardSubtitle>
              来源：{{ entry.source || "未知" }} / 更新时间：{{ entry.time || "未知" }}
            </VCardSubtitle>
            <VCardText class="d-flex flex-column ga-2">
              <div class="text-body-2 break-all">{{ entry.url }}</div>
              <VChip size="small" variant="outlined">
                提取码：{{ entry.password || "无" }}
              </VChip>
            </VCardText>
            <VCardActions class="flex-wrap ga-2">
              <VBtn
                :href="entry.url"
                target="_blank"
                rel="noopener noreferrer"
                variant="text"
              >
                打开链接
              </VBtn>
              <VBtn
                v-if="groupName === '115'"
                color="primary"
                variant="flat"
                :loading="queueLoading"
                @click="queue115(entry)"
              >
                加入 115
              </VBtn>
            </VCardActions>
          </VCard>
        </div>
      </VCardText>
      <VCardText v-else>
        <VAlert type="info" variant="tonal">
          还没有加载任何资源。先搜索影视条目，再点击对应结果上的“加载资源”。
        </VAlert>
      </VCardText>
    </VCard>

    <VCard>
      <VCardTitle class="d-flex align-center justify-space-between flex-wrap ga-3">
        <span>待转存到 115</span>
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
      <VCardText v-if="queueItems.length" class="d-flex flex-column ga-3">
        <VAlert type="warning" variant="tonal">
          当前“加入 115”仍是占位接口，只会记录待处理队列，还不会自动转存到你的 115。
        </VAlert>
        <VCard
          v-for="item in queueItems"
          :key="item.url"
          variant="outlined"
        >
          <VCardTitle>{{ item.title }}</VCardTitle>
          <VCardSubtitle>
            加入时间：{{ item.queued_at }} / 状态：{{ item.status }}
          </VCardSubtitle>
          <VCardText class="d-flex flex-column ga-2">
            <div>来源：{{ item.source || "未知" }}</div>
            <div class="break-all">{{ item.url }}</div>
            <div>提取码：{{ item.password || "无" }}</div>
          </VCardText>
        </VCard>
      </VCardText>
      <VCardText v-else>
        <VAlert type="info" variant="tonal">
          待转存队列为空。加载到 115 资源后，可以先点“加入 115”做占位记录。
        </VAlert>
      </VCardText>
    </VCard>
  </div>
</template>

<style scoped>
.page-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px;
}

.break-all {
  word-break: break-all;
}
</style>
