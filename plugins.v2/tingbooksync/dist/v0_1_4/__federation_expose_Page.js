import { importShared } from "./__federation_fn_import.js";

const { computed, defineComponent, h, onMounted, reactive, ref, resolveComponent } = await importShared("vue");

const FIELD_DEFS = [
  { key: "watch_dir", label: "下载监听目录", icon: "mdi-download", hint: "听书系统下载整理完成后的监听目录。" },
  { key: "strm_output_dir", label: "STRM 生成目录", icon: "mdi-file-link-outline", hint: "插件会按下载目录下的分类子目录自动新建分类文件夹。" },
  { key: "target_115_dir", label: "115 目标目录", icon: "mdi-folder-upload-outline", hint: "dry-run 阶段仅用于生成远端路径模板。" },
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
  dry_run: true,
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
    const storages = ref([{ title: "本地", value: "local" }]);
    const storage = ref("local");
    const currentPath = ref("/");
    const items = ref([]);
    const activeField = ref("watch_dir");
    const loading = ref(false);
    const saving = ref(false);
    const message = ref("请选择资源存储和资源目录。");
    const error = ref("");
    const dirs = computed(() => items.value.filter((item) => item.type === "dir" || item.isDir));
    const files = computed(() => items.value.filter((item) => item.type !== "dir" && !item.isDir));
    const activeFieldLabel = computed(() => FIELD_DEFS.find((item) => item.key === activeField.value)?.label || "目录");
    const c = (name) => resolveComponent(name);

    async function loadConfig() {
      const payload = await request("plugin/TingBookSync");
      Object.assign(config, { ...DEFAULT_CONFIG, ...payload });
    }

    async function loadStorages() {
      try {
        const payload = await request("plugin/TingBookSync/storages");
        if (Array.isArray(payload?.items) && payload.items.length) storages.value = payload.items;
      } catch {
        storages.value = [{ title: "本地", value: "local" }];
      }
    }

    async function browse(path = currentPath.value) {
      loading.value = true;
      error.value = "";
      try {
        const payload = await request(`plugin/TingBookSync/browse${buildQuery({ storage: storage.value, path })}`);
        if (!payload?.success) throw new Error(payload?.message || "目录读取失败");
        currentPath.value = payload.path || path || "/";
        items.value = Array.isArray(payload.items) ? payload.items : [];
        message.value = `当前位置：${storage.value}:${currentPath.value}`;
      } catch (err) {
        items.value = [];
        error.value = err?.message || "目录读取失败";
      } finally {
        loading.value = false;
      }
    }

    function selectCurrentPath() {
      config[activeField.value] = currentPath.value || "/";
      message.value = `${activeFieldLabel.value} 已选择：${config[activeField.value]}`;
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
          h(c("VChip"), { color: "primary", variant: "tonal" }, () => "dry-run"),
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
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VSwitch"), { modelValue: config.dry_run, "onUpdate:modelValue": (value) => { config.dry_run = value; }, label: "Dry-run", color: "warning", hideDetails: true })),
          ]),
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
            onClick: () => { activeField.value = field.key; },
            "onClick:appendInner": () => { activeField.value = field.key; selectCurrentPath(); },
          })),
        ]),
      ]),
      h(c("VCard"), { variant: "outlined" }, () => [
        h(c("VCardTitle"), null, () => "资源目录"),
        h(c("VCardText"), { class: "d-flex flex-column ga-3" }, () => [
          h(c("VRow"), null, () => [
            h(c("VCol"), { cols: "12", md: "4" }, () => h(c("VSelect"), {
              modelValue: storage.value,
              "onUpdate:modelValue": async (value) => { storage.value = value || "local"; await browse("/"); },
              items: storages.value,
              itemTitle: "title",
              itemValue: "value",
              label: "资源存储",
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
    ]);
  },
});
