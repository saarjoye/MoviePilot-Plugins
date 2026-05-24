import { importShared } from "./__federation_fn_import.js";

const { computed, defineComponent, h, onMounted, reactive, ref, resolveComponent } = await importShared("vue");

const FIELD_DEFS = [
  { key: "watch_dir", label: "下载监听目录", icon: "mdi-download", storage: "local", hint: "听书系统下载整理完成后的监听目录。" },
  { key: "strm_output_dir", label: "STRM 生成目录", icon: "mdi-file-link-outline", storage: "local", hint: "插件会按下载目录下的分类子目录自动新建分类文件夹。" },
  { key: "target_115_dir", label: "115 目标目录", icon: "mdi-folder-upload-outline", storage: "u115", hint: "使用 MP 的 115 网盘存储选择远端目录。" },
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
    const activeField = ref("watch_dir");
    const loading = ref(false);
    const saving = ref(false);
    const logLoading = ref(false);
    const message = ref("请选择资源存储和资源目录。");
    const error = ref("");
    const dirs = computed(() => items.value.filter((item) => item.type === "dir" || item.isDir));
    const files = computed(() => items.value.filter((item) => item.type !== "dir" && !item.isDir));
    const activeFieldLabel = computed(() => FIELD_DEFS.find((item) => item.key === activeField.value)?.label || "目录");
    const activeFieldDef = computed(() => FIELD_DEFS.find((item) => item.key === activeField.value) || FIELD_DEFS[0]);
    const activeStorage = computed(() => activeFieldDef.value.storage || storage.value || "local");
    const storageLocked = computed(() => Boolean(activeFieldDef.value.storage));
    const storageItems = computed(() => {
      if (!storageLocked.value) return storages.value;
      const value = activeStorage.value;
      return storages.value.filter((item) => item.value === value);
    });
    const c = (name) => resolveComponent(name);

    async function loadConfig() {
      const payload = await request("plugin/TingBookSync");
      Object.assign(config, { ...DEFAULT_CONFIG, ...payload });
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

    async function setActiveField(fieldKey) {
      activeField.value = fieldKey;
      const requiredStorage = activeFieldDef.value.storage;
      if (requiredStorage && storage.value !== requiredStorage) {
        storage.value = requiredStorage;
        await browse("/");
      }
    }

    async function browse(path = currentPath.value) {
      loading.value = true;
      error.value = "";
      try {
        const requestStorage = activeStorage.value;
        const payload = await request(`plugin/TingBookSync/browse${buildQuery({ storage: requestStorage, path })}`);
        if (!payload?.success) throw new Error(payload?.message || "目录读取失败");
        currentPath.value = payload.path || path || "/";
        items.value = Array.isArray(payload.items) ? payload.items : [];
        storage.value = requestStorage;
        message.value = `当前位置：${requestStorage}:${currentPath.value}`;
      } catch (err) {
        items.value = [];
        error.value = err?.message || "目录读取失败";
      } finally {
        loading.value = false;
      }
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

    function selectCurrentPath() {
      const requiredStorage = activeFieldDef.value.storage;
      config[activeField.value] = currentPath.value || "/";
      message.value = `${activeFieldLabel.value} 已选择：${config[activeField.value]}`;
      if (requiredStorage) {
        message.value = `${activeFieldLabel.value} 已从 ${requiredStorage === "u115" ? "115 网盘" : "本地"} 选择：${config[activeField.value]}`;
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
        await browse("/");
        await fetchLogs();
      } catch (err) {
        error.value = err?.message || "初始化失败";
      }
    });

    return () => h("div", { class: "pa-4 d-flex flex-column ga-4" }, [
      h("div", { class: "d-flex justify-space-between align-start flex-wrap ga-3" }, [
        h("div", [
          h("div", { class: "text-h6 font-weight-medium" }, "听书同步"),
          h("div", { class: "text-body-2 text-medium-emphasis" }, message.value),
        ]),
        h("div", { class: "d-flex ga-2 flex-wrap" }, [
          h(c("VChip"), { color: "success", variant: "tonal" }, () => "真实上传"),
          h(c("VBtn"), { color: "primary", loading: saving.value, disabled: saving.value, onClick: saveConfig }, () => "保存配置"),
        ]),
      ]),
      error.value ? h(c("VAlert"), { type: "error", variant: "tonal", text: error.value }) : null,
      h(c("VCard"), { variant: "outlined" }, () => [
        h(c("VCardText"), { class: "d-flex flex-column ga-4" }, () => [
          h(c("VRow"), null, () => [
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VSwitch"), { modelValue: config.enabled, "onUpdate:modelValue": (value) => { config.enabled = value; }, label: "启用插件", color: "primary", hideDetails: true })),
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VTextField"), { modelValue: config.scan_interval, "onUpdate:modelValue": (value) => { config.scan_interval = value; }, label: "扫描间隔（秒）", type: "number", hideDetails: true })),
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VTextField"), { modelValue: config.min_file_count, "onUpdate:modelValue": (value) => { config.min_file_count = value; }, label: "最少音频数", type: "number", hideDetails: true })),
          ]),
          h(c("VRow"), null, () => [
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VSwitch"), { modelValue: config.move_completed, "onUpdate:modelValue": (value) => { config.move_completed = value; }, label: "完成后移动目录", hideDetails: true })),
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VSwitch"), { modelValue: config.overwrite_strm, "onUpdate:modelValue": (value) => { config.overwrite_strm = value; }, label: "覆盖已有 STRM", hideDetails: true })),
          ]),
          h(c("VRow"), null, () => [
            h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VSwitch"), { modelValue: config.auto_adopt_loose_audio, "onUpdate:modelValue": (value) => { config.auto_adopt_loose_audio = value; }, label: "自动接管散音频", color: "primary", hideDetails: true })),
            h(c("VCol"), { cols: "12", md: "6" }, () => h(c("VSwitch"), { modelValue: config.scrape_metadata, "onUpdate:modelValue": (value) => { config.scrape_metadata = value; }, label: "联网刮削补全书籍信息", color: "warning", hideDetails: true })),
          ]),
          h(c("VTextField"), {
            modelValue: config.public_base_url,
            "onUpdate:modelValue": (value) => { config.public_base_url = value || ""; },
            label: "MP 外部访问地址",
            hint: "用于写入 302 STRM，例如 http://192.168.1.10:3000；留空则写相对地址。",
            persistentHint: true,
            prependInnerIcon: "mdi-web",
          }),
          config.scrape_metadata ? h(c("VAlert"), { type: "warning", variant: "tonal", density: "compact", text: "联网刮削会把清洗后的书名关键词发送到 Google Books / Open Library，不发送本地完整路径、115 目录或凭证。" }) : null,
          h(c("VAlert"), { type: "info", variant: "tonal", density: "compact", text: "插件会真实上传音频到 115；STRM 会写入本插件 302 播放地址，播放时再换取 115 临时下载链接。" }),
          h(c("VDivider")),
          ...FIELD_DEFS.map((field) => h(c("VTextField"), {
            modelValue: config[field.key],
            "onUpdate:modelValue": (value) => { config[field.key] = value; },
            label: field.label,
            hint: field.hint,
            persistentHint: true,
            readonly: true,
            prependInnerIcon: field.icon,
            appendInnerIcon: activeField.value === field.key ? "mdi-check-circle" : "mdi-folder-search-outline",
            onClick: () => { setActiveField(field.key); },
            "onClick:appendInner": async () => { await setActiveField(field.key); selectCurrentPath(); },
          })),
        ]),
      ]),
      h(c("VCard"), { variant: "outlined" }, () => [
        h(c("VCardTitle"), null, () => "资源目录"),
        h(c("VCardText"), { class: "d-flex flex-column ga-3" }, () => [
          h(c("VRow"), null, () => [
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VSelect"), {
              modelValue: activeStorage.value,
              "onUpdate:modelValue": async (value) => {
                if (storageLocked.value) return;
                storage.value = value || "local";
                await browse("/");
              },
              items: storageItems.value,
              itemTitle: "title",
              itemValue: "value",
              label: "资源存储",
              disabled: storageLocked.value,
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
          h("div", { class: "d-flex ga-2 flex-wrap" }, [
            h(c("VBtn"), { variant: "outlined", prependIcon: "mdi-arrow-up", onClick: () => browse(parentPath(currentPath.value)) }, () => "上级目录"),
            h(c("VBtn"), { variant: "tonal", color: "primary", prependIcon: "mdi-check", onClick: selectCurrentPath }, () => `选为${activeFieldLabel.value}`),
          ]),
          h(c("VList"), { density: "compact", lines: "one", loading: loading.value }, () => [
            ...dirs.value.map((item) => h(c("VListItem"), {
              key: `${itemPath(item)}:dir`,
              title: item.name || itemPath(item),
              subtitle: itemPath(item),
              prependIcon: "mdi-folder-outline",
              onClick: () => browse(itemPath(item)),
            })),
            ...files.value.slice(0, 50).map((item) => h(c("VListItem"), {
              key: `${itemPath(item)}:file`,
              title: item.name || itemPath(item),
              subtitle: itemPath(item),
              prependIcon: "mdi-file-outline",
            })),
            !loading.value && !dirs.value.length && !files.value.length ? h(c("VListItem"), { title: "当前目录为空", prependIcon: "mdi-folder-off-outline" }) : null,
          ]),
        ]),
      ]),
      h(c("VCard"), { variant: "outlined" }, () => [
        h(c("VCardTitle"), { class: "d-flex justify-space-between align-center flex-wrap ga-2" }, () => [
          h("span", "运行日志"),
          h("div", { class: "d-flex ga-2" }, [
            h(c("VBtn"), { variant: "outlined", size: "small", prependIcon: "mdi-refresh", loading: logLoading.value, onClick: fetchLogs }, () => "刷新"),
            h(c("VBtn"), { variant: "tonal", color: "warning", size: "small", prependIcon: "mdi-delete-outline", loading: logLoading.value, onClick: clearLogs }, () => "清空"),
          ]),
        ]),
        h(c("VCardText"), null, () => [
          logs.value.length ? h(c("VList"), { density: "compact", lines: "two" }, () => logs.value.map((item, index) => h(c("VListItem"), {
            key: `${item.time}-${index}`,
            title: `[${item.level || "info"}] ${item.stage || "runtime"} - ${item.message || ""}`,
            subtitle: item.time || "",
            prependIcon: item.level === "error" ? "mdi-alert-circle-outline" : "mdi-information-outline",
          }))) : h(c("VAlert"), { type: "info", variant: "tonal", text: "暂无运行日志" }),
        ]),
      ]),
    ]);
  },
});
