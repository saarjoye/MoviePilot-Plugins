import { importShared } from "./__federation_fn_import.js";

const { computed, defineComponent, h, onMounted, reactive, ref, resolveComponent } = await importShared("vue");

const FIELD_DEFS = [
  { key: "watch_dir", label: "下载监听目录", icon: "mdi-download", storage: "local", accent: "primary", hint: "听书系统下载整理完成后的监听目录。" },
  { key: "target_115_dir", label: "115 目标目录", icon: "mdi-cloud-upload-outline", storage: "u115", accent: "warning", locked: true, hint: "固定使用 MP 的 115 网盘存储，避免误选本地目录。" },
  { key: "strm_output_dir", label: "STRM 生成目录", icon: "mdi-link-variant", storage: "local", accent: "success", hint: "插件会按下载目录下的分类子目录自动新建分类文件夹。" },
];

const LOG_TABS = [
  { key: "all", label: "全部" },
  { key: "error", label: "错误" },
  { key: "upload", label: "上传" },
  { key: "strm", label: "STRM" },
  { key: "scan", label: "扫描" },
];

const DEFAULT_CONFIG = {
  enabled: false,
  watch_dir: "",
  strm_output_dir: "",
  target_115_dir: "/Audiobooks",
  scan_interval: 300,
  move_completed: true,
  overwrite_strm: false,
  min_file_count: 1,
  auto_adopt_loose_audio: true,
  scrape_metadata: false,
  public_base_url: "",
  ads_enabled: false,
  ads_base_url: "",
  ads_token: "",
  ads_library_id: "",
};

function buildQuery(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    const text = String(value ?? "").trim();
    if (text) search.set(key, text);
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

async function request(path, init = {}) {
  let auth = {};
  try {
    auth = JSON.parse(localStorage.getItem("auth") || "{}");
  } catch {
    auth = {};
  }
  const headers = { Accept: "application/json", ...(init.headers || {}) };
  if (auth?.token) headers.Authorization = `Bearer ${auth.token}`;
  const response = await fetch(`/api/v1/${path}`, { ...init, headers });
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { message: text };
  }
  if (!response.ok) throw new Error(payload?.detail || payload?.message || `请求失败 (${response.status})`);
  return payload?.data ?? payload ?? {};
}

function itemPath(item) {
  return String(item?.path || item?.name || "/");
}

function parentPath(path) {
  const normalized = String(path || "/").replace(/\\/g, "/").replace(/\/+/g, "/");
  if (!normalized || normalized === "/") return "/";
  const trimmed = normalized.replace(/\/$/, "");
  const index = trimmed.lastIndexOf("/");
  return index <= 0 ? "/" : trimmed.slice(0, index);
}

function formatStoragePath(storage, path) {
  return `${storage || "local"}:${path || "/"}`;
}

function levelColor(level) {
  if (level === "error") return "error";
  if (level === "warning" || level === "warn") return "warning";
  return "info";
}

function levelIcon(level) {
  if (level === "error") return "mdi-alert-circle-outline";
  if (level === "warning" || level === "warn") return "mdi-alert-outline";
  return "mdi-information-outline";
}

function compactTime(value) {
  const text = String(value || "");
  const match = text.match(/T(\d{2}:\d{2}:\d{2})/);
  return match ? match[1] : text;
}

export default defineComponent({
  name: "TingBookSyncPage",
  props: {
    api: { type: Object, default: () => ({}) },
    pluginId: { type: String, default: "TingBookSync" },
  },
  setup() {
    const config = reactive({ ...DEFAULT_CONFIG });
    const storages = ref([{ title: "本地", value: "local" }, { title: "115 网盘", value: "u115" }]);
    const storage = ref("local");
    const currentPath = ref("/");
    const items = ref([]);
    const logs = ref([]);
    const results = ref([]);
    const records = ref([]);
    const activeTab = ref("config");
    const pickerOpen = ref(false);
    const activeField = ref("watch_dir");
    const activeLogTab = ref("all");
    const expandedLogKey = ref("");
    const advancedOpen = ref(false);
    const loading = ref(false);
    const saving = ref(false);
    const logLoading = ref(false);
    const recordLoading = ref(false);
    const recordQuery = ref("");
    const message = ref("请选择目录并保存配置。");
    const error = ref("");
    const c = (name) => resolveComponent(name);

    const dirs = computed(() => items.value.filter((item) => item.type === "dir" || item.isDir));
    const activeFieldDef = computed(() => FIELD_DEFS.find((item) => item.key === activeField.value) || FIELD_DEFS[0]);
    const activeStorage = computed(() => activeFieldDef.value.storage || storage.value || "local");
    const storageItems = computed(() => {
      const value = activeStorage.value;
      if (activeFieldDef.value.storage) return storages.value.filter((item) => item.value === value);
      return storages.value;
    });
    const enabledText = computed(() => config.enabled ? "已启用" : "未启用");
    const lastResult = computed(() => results.value[0] || null);
    const lastResultText = computed(() => {
      const status = lastResult.value?.status || "";
      if (status === "strm_generated") return "STRM 已生成";
      if (status === "uploaded") return "上传完成";
      if (status === "failed") return "处理失败";
      if (status === "scanning") return "待处理";
      return logs.value[0]?.message || "暂无结果";
    });
    const filteredLogs = computed(() => {
      if (activeLogTab.value === "all") return logs.value;
      return logs.value.filter((item) => String(item.level || "").includes(activeLogTab.value) || String(item.stage || "").includes(activeLogTab.value));
    });
    const recentTasks = computed(() => {
      const mapped = results.value.map((item) => ({
        title: String(item.bookDir || "").split(/[\\/]/).pop() || item.taskId || "听书任务",
        subtitle: item.message || item.status || "",
        status: item.status || "pending",
      }));
      if (mapped.length) return mapped.slice(0, 4);
      return [
        { title: "等待扫描", subtitle: "保存配置后由 MP 定时任务执行", status: "pending" },
        { title: "真实 115 上传", subtitle: "拿到 pickcode 后才生成 STRM", status: "uploaded" },
      ];
    });
    const filteredRecords = computed(() => {
      const query = recordQuery.value.trim().toLowerCase();
      if (!query) return records.value;
      return records.value.filter((item) => JSON.stringify(item).toLowerCase().includes(query));
    });

    async function loadConfig() {
      const payload = await request("plugin/TingBookSync");
      Object.assign(config, { ...DEFAULT_CONFIG, ...payload });
      results.value = Array.isArray(payload?.last_results) ? payload.last_results.slice().reverse() : [];
    }

    async function loadStorages() {
      try {
        const payload = await request("plugin/TingBookSync/storages");
        if (Array.isArray(payload?.items) && payload.items.length) {
          const merged = [...payload.items];
          if (!merged.some((item) => item.value === "u115")) merged.push({ title: "115 网盘", value: "u115" });
          if (!merged.some((item) => item.value === "local")) merged.unshift({ title: "本地", value: "local" });
          storages.value = merged;
        }
      } catch {
        storages.value = [{ title: "本地", value: "local" }, { title: "115 网盘", value: "u115" }];
      }
    }

    async function browse(path = currentPath.value) {
      loading.value = true;
      error.value = "";
      try {
        const requestStorage = activeStorage.value;
        const payload = await request(`plugin/TingBookSync/browse${buildQuery({ storage: requestStorage, path, dirs_only: true })}`);
        if (!payload?.success) throw new Error(payload?.message || "目录读取失败");
        currentPath.value = payload.path || path || "/";
        items.value = Array.isArray(payload.items) ? payload.items : [];
        storage.value = requestStorage;
        message.value = `当前位置：${formatStoragePath(requestStorage, currentPath.value)}`;
      } catch (err) {
        items.value = [];
        error.value = err?.message || "目录读取失败";
      } finally {
        loading.value = false;
      }
    }

    async function openPicker(fieldKey) {
      activeField.value = fieldKey;
      storage.value = activeStorage.value;
      currentPath.value = config[fieldKey] || "/";
      pickerOpen.value = true;
      await browse(currentPath.value || "/");
    }

    function selectCurrentPath() {
      config[activeField.value] = currentPath.value || "/";
      message.value = `${activeFieldDef.value.label} 已选择：${formatStoragePath(activeStorage.value, config[activeField.value])}`;
      pickerOpen.value = false;
    }

    async function fetchLogs() {
      logLoading.value = true;
      try {
        const payload = await request("plugin/TingBookSync/logs?limit=100");
        logs.value = Array.isArray(payload?.items) ? payload.items.slice().reverse() : [];
      } catch (err) {
        error.value = err?.message || "读取日志失败";
      } finally {
        logLoading.value = false;
      }
    }

    async function fetchRecords() {
      recordLoading.value = true;
      try {
        const payload = await request("plugin/TingBookSync/records?limit=300");
        records.value = Array.isArray(payload?.items) ? payload.items : [];
      } catch (err) {
        error.value = err?.message || "读取整理记录失败";
      } finally {
        recordLoading.value = false;
      }
    }

    async function resetRecord(item, mode = "strm") {
      if (!item?.bookDir) return;
      const title = item.title || item.bookName || item.bookDir;
      const messageText = mode === "reupload"
        ? `确认重新上传《${title}》并生成 STRM？\n会重新上传本地音频到 115，拿到新的 pickcode 后生成 STRM。`
        : `确认重新生成《${title}》的 STRM？\n会优先使用本地 pickcode；没有时从 115 已有文件补齐 pickcode，不会主动重新上传。`;
      if (!window.confirm(messageText)) return;
      recordLoading.value = true;
      try {
        const payload = await request(`plugin/TingBookSync/records/reset${buildQuery({ bookDir: item.bookDir, mode })}`, { method: "POST" });
        message.value = payload?.message || "整理记录处理完成";
        await fetchRecords();
        await fetchLogs();
      } catch (err) {
        error.value = err?.message || "重置整理记录失败";
      } finally {
        recordLoading.value = false;
      }
    }

    async function clearLogs() {
      logLoading.value = true;
      try {
        await request("plugin/TingBookSync/logs/clear", { method: "POST" });
        await fetchLogs();
      } catch (err) {
        error.value = err?.message || "清空日志失败";
      } finally {
        logLoading.value = false;
      }
    }

    async function resetSyncState() {
      saving.value = true;
      error.value = "";
      try {
        const payload = await request("plugin/TingBookSync/sync/reset", { method: "POST" });
        message.value = payload?.message || "同步状态已重置。";
        await loadConfig();
        await fetchRecords();
        await fetchLogs();
      } catch (err) {
        error.value = err?.message || "重置同步状态失败";
      } finally {
        saving.value = false;
      }
    }

    async function saveConfig() {
      saving.value = true;
      error.value = "";
      try {
        const payload = { ...config };
        payload.scan_interval = Number(payload.scan_interval || 300);
        payload.min_file_count = Number(payload.min_file_count || 1);
        await request("plugin/TingBookSync", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        message.value = "配置已保存。";
        await loadConfig();
      } catch (err) {
        error.value = err?.message || "保存配置失败";
      } finally {
        saving.value = false;
      }
    }

    onMounted(async () => {
      try {
        await loadConfig();
        await loadStorages();
        await fetchRecords();
        await fetchLogs();
      } catch (err) {
        error.value = err?.message || "初始化失败";
      }
    });

    function renderMetric(title, value, subtitle, icon, color) {
      return h(c("VCard"), { variant: "outlined", rounded: "lg", class: "h-100" }, () => h(c("VCardText"), { class: "d-flex align-center ga-3" }, () => [
        h(c("VAvatar"), { color, variant: "tonal", rounded: "lg" }, () => h(c("VIcon"), null, () => icon)),
        h("div", { class: "min-w-0" }, [
          h("div", { class: "text-caption text-medium-emphasis" }, title),
          h("div", { class: "text-h6 font-weight-bold text-truncate" }, value),
          h("div", { class: "text-caption text-medium-emphasis text-truncate" }, subtitle),
        ]),
      ]));
    }

    function renderPathCard(field) {
      const selected = config[field.key] || "";
      return h(c("VCard"), { variant: "outlined", rounded: "lg" }, () => h(c("VCardText"), { class: "d-flex align-center ga-3" }, () => [
        h(c("VAvatar"), { color: field.accent, variant: "tonal", rounded: "lg" }, () => h(c("VIcon"), null, () => field.icon)),
        h("div", { class: "flex-grow-1 min-w-0" }, [
          h("div", { class: "d-flex align-center ga-2 flex-wrap" }, [
            h("span", { class: "font-weight-bold" }, field.label),
            field.locked ? h(c("VChip"), { size: "x-small", color: "warning", variant: "tonal", prependIcon: "mdi-lock-outline" }, () => "固定 115") : null,
          ]),
          h("div", { class: "text-body-2 text-medium-emphasis text-truncate mt-1" }, selected ? formatStoragePath(field.storage, selected) : "未选择"),
          h("div", { class: "text-caption text-medium-emphasis mt-1" }, field.hint),
        ]),
        h(c("VBtn"), { variant: "outlined", prependIcon: "mdi-folder-open-outline", onClick: () => openPicker(field.key) }, () => "选择文件夹"),
      ]));
    }

    function renderTask(task, index) {
      const color = task.status === "failed" ? "error" : task.status === "strm_generated" || task.status === "uploaded" ? "success" : "warning";
      return h(c("VListItem"), { key: `${task.title}-${index}`, title: task.title, subtitle: task.subtitle, class: "px-0" }, {
        prepend: () => h(c("VIcon"), { color, icon: task.status === "failed" ? "mdi-alert-circle-outline" : "mdi-circle" }),
      });
    }

    function recordColor(status) {
      if (status === "failed") return "error";
      if (status === "strm_generated" || status === "ads_exists") return "success";
      if (status === "uploaded") return "info";
      return "warning";
    }

    function renderRecord(item, index) {
      const title = item.title || item.bookName || "听书记录";
      return h(c("VCard"), { key: `${item.bookDir || title}-${index}`, variant: "outlined", rounded: "lg", class: "mb-3" }, () => h(c("VCardText"), null, () => [
        h("div", { class: "d-flex align-start justify-space-between ga-3 flex-wrap" }, [
          h("div", { class: "min-w-0 flex-grow-1" }, [
            h("div", { class: "d-flex align-center ga-2 flex-wrap" }, [
              h("span", { class: "font-weight-bold text-truncate" }, title),
              h(c("VChip"), { color: recordColor(item.status), size: "small", variant: "tonal" }, () => item.status || "pending"),
              item.category ? h(c("VChip"), { size: "x-small", variant: "tonal" }, () => item.category) : null,
            ]),
            h("div", { class: "text-body-2 text-medium-emphasis mt-1 text-truncate" }, item.author ? `作者：${item.author}` : item.bookName || ""),
          ]),
          h("div", { class: "d-flex ga-2 flex-wrap" }, [
            h(c("VChip"), { size: "small", variant: "tonal", prependIcon: "mdi-format-list-numbered" }, () => `${item.episodeCount || 0} 集`),
            h(c("VChip"), { size: "small", variant: "tonal", color: "info", prependIcon: "mdi-cloud-check-outline" }, () => `${item.uploadedCount || 0} 上传`),
            h(c("VChip"), { size: "small", variant: "tonal", color: item.strmCount ? "success" : "default", prependIcon: "mdi-link-variant" }, () => `${item.strmCount || 0} STRM`),
          ]),
        ]),
        h("div", { class: "mt-3 d-flex flex-column ga-1" }, [
          h("div", { class: "text-caption text-medium-emphasis text-truncate" }, `源目录：${item.bookDir || ""}`),
          h("div", { class: "text-caption text-medium-emphasis text-truncate" }, `115：${item.remotePath || "未记录"}`),
          h("div", { class: "text-caption text-medium-emphasis text-truncate" }, `STRM：${item.strmPath || "未生成"}`),
          item.message ? h("div", { class: "text-body-2 mt-1", style: "word-break:break-word;" }, item.message) : null,
        ]),
        h("div", { class: "d-flex align-center justify-space-between ga-2 flex-wrap mt-3" }, [
          h("span", { class: "text-caption text-medium-emphasis" }, item.updatedAt ? `更新时间：${compactTime(item.updatedAt)}` : ""),
          h("div", { class: "d-flex ga-2 flex-wrap" }, [
            h(c("VBtn"), { color: "primary", variant: "tonal", size: "small", prependIcon: "mdi-link-variant-plus", loading: recordLoading.value, onClick: () => resetRecord(item, "strm") }, () => "重新生成 STRM"),
            h(c("VBtn"), { color: "warning", variant: "tonal", size: "small", prependIcon: "mdi-cloud-upload-outline", loading: recordLoading.value, onClick: () => resetRecord(item, "reupload") }, () => "重新上传并生成"),
          ]),
        ]),
      ]));
    }

    function renderRecordsPanel() {
      return h(c("VCard"), { variant: "outlined", rounded: "lg" }, () => [
        h(c("VCardTitle"), { class: "d-flex align-center justify-space-between flex-wrap ga-2" }, () => [
          h("div", [
            h("div", { class: "text-subtitle-1 font-weight-bold" }, "整理记录"),
            h("div", { class: "text-caption text-medium-emphasis" }, "按书记录上传、STRM 和 ADS 处理结果，可单本重新生成 STRM 或重新上传。"),
          ]),
          h("div", { class: "d-flex ga-2 flex-wrap" }, [
            h(c("VTextField"), {
              modelValue: recordQuery.value,
              "onUpdate:modelValue": (value) => { recordQuery.value = value || ""; },
              density: "compact",
              hideDetails: true,
              style: "width:220px;",
              prependInnerIcon: "mdi-magnify",
              placeholder: "搜索书名/路径/状态",
            }),
            h(c("VBtn"), { variant: "outlined", prependIcon: "mdi-refresh", loading: recordLoading.value, onClick: fetchRecords }, () => "刷新"),
          ]),
        ]),
        h(c("VDivider")),
        h(c("VCardText"), null, () => [
          error.value ? h(c("VAlert"), { class: "mb-3", type: "error", variant: "tonal", density: "compact", text: error.value }) : null,
          recordLoading.value && !filteredRecords.value.length ? h(c("VAlert"), { type: "info", variant: "tonal", density: "compact", text: "整理记录加载中" }) : null,
          !recordLoading.value && !filteredRecords.value.length ? h(c("VAlert"), { type: "info", variant: "tonal", density: "compact", text: "暂无整理记录，扫描到 ready 书籍后会显示在这里。" }) : null,
          ...filteredRecords.value.map(renderRecord),
        ]),
      ]);
    }

    async function copyLog(item) {
      const text = `[${item.time || ""}] [${item.level || "info"}] [${item.stage || "runtime"}] ${item.message || ""}`;
      try {
        await navigator.clipboard.writeText(text);
        message.value = "日志已复制。";
      } catch {
        message.value = text;
      }
    }

    function renderLogItem(item, index) {
      const key = `${item.time || ""}-${index}`;
      const expanded = expandedLogKey.value === key;
      const color = levelColor(item.level);
      return h("div", {
        key,
        class: "rounded-lg border pa-2 mb-2",
        style: item.level === "error" ? "background:#FFF7F7;border-color:#FFD1D1;" : "background:#FFFFFF;border-color:#E5EAF2;",
      }, [
        h("div", { class: "d-flex align-center ga-2" }, [
          h(c("VIcon"), { color, size: "18", icon: levelIcon(item.level) }),
          h(c("VChip"), { color, size: "x-small", variant: "tonal" }, () => item.stage || "runtime"),
          h(c("VChip"), { color, size: "x-small", variant: item.level === "error" ? "flat" : "tonal" }, () => item.level || "info"),
          h("span", { class: "text-caption text-medium-emphasis ml-auto" }, compactTime(item.time)),
        ]),
        h("div", {
          class: "text-body-2 mt-1",
          style: expanded
            ? "white-space:pre-wrap;word-break:break-word;line-height:1.35;"
            : "display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word;line-height:1.35;",
        }, item.message || ""),
        h("div", { class: "d-flex justify-end ga-1 mt-1" }, [
          h(c("VBtn"), { size: "x-small", variant: "text", density: "comfortable", onClick: () => { expandedLogKey.value = expanded ? "" : key; } }, () => expanded ? "收起" : "详情"),
          h(c("VBtn"), { size: "x-small", variant: "text", density: "comfortable", prependIcon: "mdi-content-copy", onClick: () => copyLog(item) }, () => "复制"),
        ]),
      ]);
    }

    function renderPickerDialog() {
      return h(c("VDialog"), { modelValue: pickerOpen.value, "onUpdate:modelValue": (value) => { pickerOpen.value = value; }, maxWidth: 760 }, () => h(c("VCard"), { rounded: "lg" }, () => [
        h(c("VCardTitle"), { class: "d-flex align-center justify-space-between" }, () => [
          h("div", [
            h("div", { class: "text-h6" }, `选择${activeFieldDef.value.label}`),
            h("div", { class: "text-caption text-medium-emphasis" }, activeFieldDef.value.locked ? "当前存储已锁定为 u115" : "只选择文件夹，不手动输入路径"),
          ]),
          h(c("VBtn"), { icon: "mdi-close", variant: "text", onClick: () => { pickerOpen.value = false; } }),
        ]),
        h(c("VDivider")),
        h(c("VCardText"), { class: "d-flex flex-column ga-3" }, () => [
          h(c("VRow"), null, () => [
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VSelect"), {
              modelValue: activeStorage.value,
              items: storageItems.value,
              itemTitle: "title",
              itemValue: "value",
              label: "资源存储",
              disabled: Boolean(activeFieldDef.value.storage),
              hideDetails: true,
            })),
            h(c("VCol"), { cols: "12", md: "8" }, () => h(c("VTextField"), {
              modelValue: currentPath.value,
              "onUpdate:modelValue": (value) => { currentPath.value = value || "/"; },
              label: "资源目录",
              prependInnerIcon: "mdi-folder-outline",
              appendInnerIcon: "mdi-refresh",
              hideDetails: true,
              onKeyup: (event) => { if (event.key === "Enter") browse(currentPath.value); },
              "onClick:appendInner": () => browse(currentPath.value),
            })),
          ]),
          error.value ? h(c("VAlert"), { type: "error", variant: "tonal", density: "compact", text: error.value }) : null,
          h("div", { class: "d-flex ga-2 flex-wrap" }, [
            h(c("VBtn"), { variant: "outlined", prependIcon: "mdi-arrow-up", onClick: () => browse(parentPath(currentPath.value)) }, () => "上级目录"),
            h(c("VBtn"), { variant: "outlined", prependIcon: "mdi-home-outline", onClick: () => browse("/") }, () => "根目录"),
          ]),
          h(c("VList"), { density: "compact", lines: "two", class: "border rounded-lg", style: "min-height: 260px; max-height: 360px; overflow-y: auto;" }, () => [
            loading.value ? h(c("VListItem"), { title: "目录加载中", prependIcon: "mdi-loading" }) : null,
            !loading.value && !dirs.value.length ? h(c("VListItem"), { title: "当前目录没有子文件夹", subtitle: "可以直接选择当前目录", prependIcon: "mdi-folder-off-outline" }) : null,
            ...dirs.value.map((item) => h(c("VListItem"), {
              key: itemPath(item),
              title: item.name || itemPath(item),
              subtitle: itemPath(item),
              prependIcon: "mdi-folder-outline",
              onClick: () => browse(itemPath(item)),
            })),
          ]),
        ]),
        h(c("VDivider")),
        h(c("VCardActions"), { class: "px-4 py-3" }, () => [
          h("div", { class: "text-body-2 text-medium-emphasis flex-grow-1 text-truncate" }, `将保存为：${formatStoragePath(activeStorage.value, currentPath.value)}`),
          h(c("VBtn"), { variant: "text", onClick: () => { pickerOpen.value = false; } }, () => "取消"),
          h(c("VBtn"), { color: "primary", variant: "flat", prependIcon: "mdi-check", onClick: selectCurrentPath }, () => "选择当前目录"),
        ]),
      ]));
    }

    return () => h("div", { class: "pa-4", style: "background:#F5F7FA; min-height:100%;" }, [
      h("div", { class: "d-flex align-center justify-space-between flex-wrap ga-3 mb-4" }, [
        h("div", { class: "d-flex align-center ga-3" }, [
          h(c("VAvatar"), { color: "primary", rounded: "lg" }, () => h(c("VIcon"), null, () => "mdi-headphones")),
          h("div", [
            h("div", { class: "text-h6 font-weight-bold" }, "听书同步"),
            h("div", { class: "text-body-2 text-medium-emphasis" }, "真实上传 115 后生成 302 STRM"),
          ]),
        ]),
        h("div", { class: "d-flex align-center ga-2 flex-wrap" }, [
          h(c("VChip"), { color: config.enabled ? "success" : "default", variant: "tonal", prependIcon: config.enabled ? "mdi-check-circle-outline" : "mdi-pause-circle-outline" }, () => enabledText.value),
          h(c("VBtn"), { color: "primary", loading: saving.value, disabled: saving.value, prependIcon: "mdi-content-save-outline", onClick: saveConfig }, () => "保存配置"),
          h(c("VBtn"), { variant: "outlined", prependIcon: "mdi-refresh", onClick: fetchLogs }, () => "刷新"),
        ]),
      ]),
      message.value ? h(c("VAlert"), { class: "mb-4", type: "info", variant: "tonal", density: "compact", text: message.value }) : null,
      h(c("VTabs"), { modelValue: activeTab.value, "onUpdate:modelValue": (value) => { activeTab.value = value; }, color: "primary", class: "mb-4" }, () => [
        h(c("VTab"), { value: "config", prependIcon: "mdi-tune-variant" }, () => "配置"),
        h(c("VTab"), { value: "records", prependIcon: "mdi-format-list-bulleted-square" }, () => "整理记录"),
      ]),
      activeTab.value === "records" ? renderRecordsPanel() : [
      h(c("VRow"), { class: "mb-4" }, () => [
        h(c("VCol"), { cols: "12", md: "4" }, () => renderMetric("扫描间隔", `${config.scan_interval || 300} 秒`, "由 MP 定时任务执行", "mdi-timer-outline", "primary")),
        h(c("VCol"), { cols: "12", md: "4" }, () => renderMetric("最近结果", lastResultText.value, "上传成功后才生成播放地址", "mdi-check-decagram-outline", lastResult.value?.status === "failed" ? "error" : "success")),
        h(c("VCol"), { cols: "12", md: "4" }, () => renderMetric("上传模式", "真实 115", "无模拟上传，无 dry-run 分支", "mdi-cloud-upload-outline", "warning")),
      ]),
      h(c("VRow"), null, () => [
        h(c("VCol"), { cols: "12", lg: "8" }, () => h("div", { class: "d-flex flex-column ga-4" }, [
          h(c("VCard"), { variant: "outlined", rounded: "lg" }, () => [
            h(c("VCardTitle"), { class: "d-flex align-center justify-space-between flex-wrap ga-2" }, () => [
              h("div", [
                h("div", { class: "text-subtitle-1 font-weight-bold" }, "目录配置"),
                h("div", { class: "text-caption text-medium-emphasis" }, "按处理顺序配置三个目录，115 目标目录自动锁定 115 网盘。"),
              ]),
              h(c("VChip"), { color: "primary", variant: "tonal", size: "small", prependIcon: "mdi-cursor-default-click-outline" }, () => "点击选择文件夹"),
            ]),
            h(c("VCardText"), { class: "d-flex flex-column ga-3" }, () => FIELD_DEFS.map(renderPathCard)),
          ]),
          h(c("VCard"), { variant: "outlined", rounded: "lg" }, () => [
            h(c("VCardTitle"), { class: "d-flex align-center justify-space-between" }, () => [
              h("span", "高级设置"),
              h(c("VBtn"), { variant: "text", icon: advancedOpen.value ? "mdi-chevron-up" : "mdi-chevron-down", onClick: () => { advancedOpen.value = !advancedOpen.value; } }),
            ]),
            advancedOpen.value ? h(c("VCardText"), null, () => [
              h(c("VRow"), null, () => [
                h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VSwitch"), { modelValue: config.enabled, "onUpdate:modelValue": (value) => { config.enabled = value; }, label: "启用插件", color: "primary", hideDetails: true })),
                h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VTextField"), { modelValue: config.scan_interval, "onUpdate:modelValue": (value) => { config.scan_interval = value; }, label: "扫描间隔（秒）", type: "number", hideDetails: true })),
                h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VTextField"), { modelValue: config.min_file_count, "onUpdate:modelValue": (value) => { config.min_file_count = value; }, label: "最少音频数", type: "number", hideDetails: true })),
                h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VSwitch"), { modelValue: config.auto_adopt_loose_audio, "onUpdate:modelValue": (value) => { config.auto_adopt_loose_audio = value; }, label: "自动接管散音频", color: "primary", hideDetails: true })),
                h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VSwitch"), { modelValue: config.scrape_metadata, "onUpdate:modelValue": (value) => { config.scrape_metadata = value; }, label: "联网刮削补全书籍信息", color: "warning", hideDetails: true })),
                h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VSwitch"), { modelValue: config.overwrite_strm, "onUpdate:modelValue": (value) => { config.overwrite_strm = value; }, label: "覆盖已有 STRM", hideDetails: true })),
                h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VSwitch"), { modelValue: config.move_completed, "onUpdate:modelValue": (value) => { config.move_completed = value; }, label: "完成后移动目录", hideDetails: true })),
                h(c("VCol"), { cols: "12" }, () => h(c("VBtn"), {
                  color: "warning",
                  variant: "tonal",
                  prependIcon: "mdi-restore-alert",
                  loading: saving.value,
                  onClick: resetSyncState,
                }, () => "重置同步状态并重新处理")),
                h(c("VCol"), { cols: "12" }, () => h(c("VTextField"), {
                  modelValue: config.public_base_url,
                  "onUpdate:modelValue": (value) => { config.public_base_url = value || ""; },
                  label: "MP 外部访问地址",
                  hint: "用于写入 302 STRM，例如 http://192.168.1.10:3000；留空则写相对地址。",
                  persistentHint: true,
                  prependInnerIcon: "mdi-web",
                })),
                h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VSwitch"), { modelValue: config.ads_enabled, "onUpdate:modelValue": (value) => { config.ads_enabled = value; }, label: "启用 ADS 去重与刷新", color: "primary", hideDetails: true })),
                h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VTextField"), { modelValue: config.ads_library_id, "onUpdate:modelValue": (value) => { config.ads_library_id = value || ""; }, label: "ADS 媒体库 ID", prependInnerIcon: "mdi-bookshelf", hideDetails: true })),
                h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VTextField"), { modelValue: config.ads_base_url, "onUpdate:modelValue": (value) => { config.ads_base_url = value || ""; }, label: "ADS 地址", hint: "例如 http://192.168.1.10:13378", persistentHint: true, prependInnerIcon: "mdi-server-network" })),
                h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VTextField"), { modelValue: config.ads_token, "onUpdate:modelValue": (value) => { config.ads_token = value || ""; }, label: "ADS API Token", type: "password", prependInnerIcon: "mdi-key-variant", hideDetails: true })),
              ]),
              config.scrape_metadata ? h(c("VAlert"), { type: "warning", variant: "tonal", density: "compact", text: "联网刮削只发送清洗后的书名关键词，不发送本地完整路径、115 目录或凭证。" }) : null,
              config.ads_enabled ? h(c("VAlert"), { type: "info", variant: "tonal", density: "compact", text: "ADS 已存在同名资源时会跳过 115 上传；未存在时上传并生成 STRM 后触发 ADS 媒体库刷新。ADS Token 只用于请求，不写入运行日志。" }) : null,
            ]) : null,
          ]),
        ])),
        h(c("VCol"), { cols: "12", lg: "4" }, () => h("div", { class: "d-flex flex-column ga-4" }, [
          h(c("VCard"), { variant: "outlined", rounded: "lg" }, () => [
            h(c("VCardTitle"), { class: "d-flex align-center justify-space-between" }, () => [h("span", "最近任务"), h(c("VChip"), { size: "small", variant: "tonal" }, () => `${recentTasks.value.length} 条`)]),
            h(c("VCardText"), null, () => h(c("VList"), { density: "compact" }, () => recentTasks.value.map(renderTask))),
          ]),
          h(c("VCard"), { variant: "outlined", rounded: "lg" }, () => [
            h(c("VCardTitle"), { class: "d-flex align-center justify-space-between py-2 px-3" }, () => [
              h("span", { class: "text-subtitle-1 font-weight-bold" }, "运行日志"),
              h("div", { class: "d-flex ga-1" }, [
                h(c("VBtn"), { variant: "text", size: "small", density: "comfortable", icon: "mdi-refresh", loading: logLoading.value, onClick: fetchLogs }),
                h(c("VBtn"), { variant: "text", color: "warning", size: "small", density: "comfortable", icon: "mdi-delete-outline", loading: logLoading.value, onClick: clearLogs }),
              ]),
            ]),
            h(c("VCardText"), { class: "px-3 pt-1 pb-3" }, () => [
              h("div", { class: "d-flex ga-1 flex-wrap mb-2" }, LOG_TABS.map((tab) => h(c("VChip"), {
                key: tab.key,
                color: activeLogTab.value === tab.key ? "primary" : "default",
                variant: activeLogTab.value === tab.key ? "flat" : "tonal",
                size: "x-small",
                density: "comfortable",
                onClick: () => { activeLogTab.value = tab.key; },
              }, () => tab.label))),
              filteredLogs.value.length
                ? h("div", { style: "max-height: 380px; overflow-y: auto;" }, filteredLogs.value.map(renderLogItem))
                : h(c("VAlert"), { type: "info", variant: "tonal", density: "compact", text: "暂无运行日志" }),
            ]),
          ]),
        ])),
      ]),
      ],
      renderPickerDialog(),
    ]);
  },
});
