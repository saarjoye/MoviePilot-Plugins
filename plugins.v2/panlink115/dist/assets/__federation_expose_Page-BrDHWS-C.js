import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import _sfc_main$1 from './__federation_expose_Config-BpgNPIr4.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,withKeys:_withKeys,renderList:_renderList,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1 = { class: "panlink-page" };
const _hoisted_2 = { class: "hero-card" };
const _hoisted_3 = { class: "hero-copy" };
const _hoisted_4 = { class: "hero-side" };
const _hoisted_5 = { class: "hero-meta" };
const _hoisted_6 = { class: "hero-actions" };
const _hoisted_7 = { class: "status-alert" };
const _hoisted_8 = { class: "status-alert-copy" };
const _hoisted_9 = { class: "panel-card" };
const _hoisted_10 = { class: "panel-head" };
const _hoisted_11 = { class: "panel-subtitle" };
const _hoisted_12 = { class: "search-bar" };
const _hoisted_13 = {
  key: 0,
  class: "result-grid"
};
const _hoisted_14 = { class: "result-title" };
const _hoisted_15 = { class: "result-subtitle" };
const _hoisted_16 = { class: "fact-list" };
const _hoisted_17 = {
  key: 0,
  class: "panel-card"
};
const _hoisted_18 = { class: "panel-head" };
const _hoisted_19 = { class: "panel-subtitle" };
const _hoisted_20 = { class: "media-overview" };
const _hoisted_21 = { class: "media-copy" };
const _hoisted_22 = { class: "fact-list" };
const _hoisted_23 = { class: "meta-grid" };
const _hoisted_24 = { class: "media-content" };
const _hoisted_25 = {
  key: 0,
  class: "group-grid"
};
const _hoisted_26 = { class: "group-title" };
const _hoisted_27 = { class: "group-subtitle" };
const _hoisted_28 = { class: "panel-head" };
const _hoisted_29 = { class: "panel-subtitle" };
const _hoisted_30 = {
  key: 0,
  class: "queue-list"
};
const _hoisted_31 = { class: "queue-title" };
const _hoisted_32 = { class: "queue-path" };
const _hoisted_33 = { class: "queue-path" };
const _hoisted_34 = { class: "queue-path" };
const _hoisted_35 = { class: "queue-path" };
const _hoisted_36 = { class: "queue-status" };
const _hoisted_37 = { class: "dialog-title" };
const _hoisted_38 = { class: "dialog-subtitle" };
const _hoisted_39 = { class: "dialog-entry-url" };
const _hoisted_40 = { class: "dialog-entry-pass" };
const _hoisted_41 = {
  key: 0,
  class: "dialog-summary"
};
const _hoisted_42 = { class: "dialog-title" };
const _hoisted_43 = { class: "dialog-entry-url" };
const _hoisted_44 = { class: "dialog-entry-pass" };

const {computed,nextTick,onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: {
    type: Object,
    default: () => ({})
  }
},
  setup(__props) {

const props = __props;

const keyword = ref("");
const statusMessage = ref("准备就绪，输入影视名称后开始搜索。");
const searching = ref(false);
const loadingVodId = ref("");
const queueLoading = ref(false);
const categoryLoading = ref(false);
const configDialog = ref(false);
const configSaving = ref(false);
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
const pluginConfig = ref(defaultPluginConfig());
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

function defaultPluginConfig() {
  return {
    enabled: false,
    username: "",
    password: "",
    timeout: 20,
    max_results: 10,
    only_show_115: true,
    u115_cookie: ""
  };
}

function normalizePluginConfig(config = {}) {
  const defaults = defaultPluginConfig();
  return {
    enabled: Boolean(config.enabled),
    username: String(config.username ?? defaults.username),
    password: String(config.password ?? defaults.password),
    timeout: Number(config.timeout || defaults.timeout),
    max_results: Number(config.max_results || defaults.max_results),
    only_show_115: config.only_show_115 !== false,
    u115_cookie: String(config.u115_cookie ?? defaults.u115_cookie)
  };
}

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

function pickDefaultCategoryKey(options = categoryOptions.value) {
  if (!options.length) {
    return "";
  }
  if (options.some((item) => item.key === selectedCategoryKey.value)) {
    return selectedCategoryKey.value;
  }
  return options[0].key;
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
    const options = flattenCategories(payload);
    categoryOptions.value = options;
    selectedCategoryKey.value = pickDefaultCategoryKey(options);
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
    pluginConfig.value = {
      ...pluginConfig.value,
      enabled: Boolean(payload?.enabled),
      max_results: Number(payload?.max_results || 10),
      only_show_115: Boolean(payload?.only_show_115)
    };
  } catch (error) {
    statusMessage.value = error?.message || "读取插件状态失败。";
  }
}

async function openConfigDialog() {
  if (configSaving.value) {
    return;
  }
  try {
    const payload = await fetchMpApi("plugin/Panlink115");
    pluginConfig.value = normalizePluginConfig(payload);
  } catch (error) {
    pluginConfig.value = normalizePluginConfig(pluginConfig.value);
    statusMessage.value = error?.message || "读取插件配置失败。";
  }
  configDialog.value = true;
}

async function savePluginConfig(conf) {
  if (configSaving.value) {
    return;
  }
  configSaving.value = true;
  try {
    const nextConfig = normalizePluginConfig(conf);
    await fetchMpApi("plugin/Panlink115", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(nextConfig)
    });
    pluginConfig.value = nextConfig;
    configDialog.value = false;
    statusMessage.value = "插件配置已保存。";
    await fetchState();
  } catch (error) {
    statusMessage.value = error?.message || "保存插件配置失败。";
  } finally {
    configSaving.value = false;
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

return (_ctx, _cache) => {
  const _component_VChip = _resolveComponent("VChip");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VImg = _resolveComponent("VImg");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VDialog = _resolveComponent("VDialog");
  const _component_VSelect = _resolveComponent("VSelect");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _cache[8] || (_cache[8] = _createElementVNode("div", { class: "eyebrow" }, "Panlink115", -1)),
        _cache[9] || (_cache[9] = _createElementVNode("h1", null, "直连 115 分享转存", -1)),
        _createElementVNode("p", null, _toDisplayString(statusMessage.value), 1)
      ]),
      _createElementVNode("div", _hoisted_4, [
        _createVNode(_component_VChip, {
          color: "primary",
          variant: "outlined"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(pluginState.value.workflow_label), 1)
          ]),
          _: 1
        }),
        _createElementVNode("div", _hoisted_5, _toDisplayString(authSummaryText.value), 1),
        _createElementVNode("div", _hoisted_6, [
          _createVNode(_component_VBtn, {
            color: "primary",
            variant: "flat",
            onClick: openConfigDialog
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(pluginState.value.u115_cookie_configured ? "插件配置" : "配置 115 Cookie"), 1)
            ]),
            _: 1
          })
        ])
      ])
    ]),
    _createVNode(_component_VAlert, {
      type: "info",
      variant: "tonal",
      class: "mb-4"
    }, {
      default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
        _createTextVNode(" 当前模式：直连 115。目标目录复用 MoviePilot 的 u115 存储，分享转存使用 115 网页 Cookie。 ", -1)
      ]))]),
      _: 1
    }),
    _createVNode(_component_VAlert, {
      type: pluginState.value.mp_u115_ready && pluginState.value.u115_cookie_configured ? 'success' : 'warning',
      variant: "outlined",
      class: "mb-6"
    }, {
      default: _withCtx(() => [
        _createElementVNode("div", _hoisted_7, [
          _createElementVNode("div", _hoisted_8, [
            _createElementVNode("span", null, "MP u115：" + _toDisplayString(pluginState.value.mp_u115_ready ? "已就绪" : "未就绪"), 1),
            _createElementVNode("span", null, "115 Cookie：" + _toDisplayString(pluginState.value.u115_cookie_configured ? "已配置" : "未配置"), 1)
          ]),
          _createVNode(_component_VBtn, {
            color: pluginState.value.u115_cookie_configured ? 'primary' : 'warning',
            variant: "flat",
            size: "small",
            onClick: openConfigDialog
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(pluginState.value.u115_cookie_configured ? "修改配置" : "立即配置"), 1)
            ]),
            _: 1
          }, 8, ["color"])
        ])
      ]),
      _: 1
    }, 8, ["type"]),
    _createElementVNode("div", _hoisted_9, [
      _createElementVNode("div", _hoisted_10, [
        _createElementVNode("div", null, [
          _cache[11] || (_cache[11] = _createElementVNode("div", { class: "panel-title" }, "搜索资源", -1)),
          _createElementVNode("div", _hoisted_11, _toDisplayString(resultCountText.value), 1)
        ])
      ]),
      _createElementVNode("div", _hoisted_12, [
        _createVNode(_component_VTextField, {
          modelValue: keyword.value,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((keyword).value = $event)),
          label: "影视名称",
          placeholder: "输入电影、剧集、综艺名称",
          "hide-details": "",
          density: "comfortable",
          onKeyup: _withKeys(searchPanlink, ["enter"])
        }, null, 8, ["modelValue"]),
        _createVNode(_component_VBtn, {
          color: "primary",
          loading: searching.value,
          onClick: searchPanlink
        }, {
          default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
            _createTextVNode("搜索", -1)
          ]))]),
          _: 1
        }, 8, ["loading"])
      ]),
      (searchResults.value.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_13, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(searchResults.value, (item) => {
              return (_openBlock(), _createBlock(_component_VCard, {
                key: item.vod_id,
                class: "result-card",
                variant: "outlined"
              }, {
                default: _withCtx(() => [
                  (item.vod_pic)
                    ? (_openBlock(), _createBlock(_component_VImg, {
                        key: 0,
                        src: item.vod_pic,
                        height: "240",
                        cover: ""
                      }, null, 8, ["src"]))
                    : _createCommentVNode("", true),
                  _createVNode(_component_VCardText, { class: "d-flex flex-column ga-3" }, {
                    default: _withCtx(() => [
                      _createElementVNode("div", null, [
                        _createElementVNode("div", _hoisted_14, _toDisplayString(item.vod_name), 1),
                        _createElementVNode("div", _hoisted_15, _toDisplayString(resultSubtitle(item) || "暂无附加信息"), 1)
                      ]),
                      _createElementVNode("div", _hoisted_16, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(mediaFacts(item), (fact) => {
                          return (_openBlock(), _createBlock(_component_VChip, {
                            key: fact,
                            size: "small",
                            variant: "tonal"
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(fact), 1)
                            ]),
                            _: 2
                          }, 1024))
                        }), 128))
                      ]),
                      _createVNode(_component_VBtn, {
                        color: "primary",
                        variant: "flat",
                        loading: loadingVodId.value === item.vod_id,
                        onClick: $event => (loadLinks(item))
                      }, {
                        default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                          _createTextVNode(" 查看网盘链接 ", -1)
                        ]))]),
                        _: 1
                      }, 8, ["loading", "onClick"])
                    ]),
                    _: 2
                  }, 1024)
                ]),
                _: 2
              }, 1024))
            }), 128))
          ]))
        : _createCommentVNode("", true)
    ]),
    (selectedMedia.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_17, [
          _createElementVNode("div", _hoisted_18, [
            _createElementVNode("div", null, [
              _cache[14] || (_cache[14] = _createElementVNode("div", { class: "panel-title" }, "资源详情", -1)),
              _createElementVNode("div", _hoisted_19, _toDisplayString(selectedMedia.value.vod_name), 1)
            ])
          ]),
          _createElementVNode("div", _hoisted_20, [
            (selectedMedia.value.vod_pic)
              ? (_openBlock(), _createBlock(_component_VImg, {
                  key: 0,
                  src: selectedMedia.value.vod_pic,
                  class: "media-poster",
                  cover: ""
                }, null, 8, ["src"]))
              : _createCommentVNode("", true),
            _createElementVNode("div", _hoisted_21, [
              _createElementVNode("div", _hoisted_22, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(mediaFacts(selectedMedia.value), (fact) => {
                  return (_openBlock(), _createBlock(_component_VChip, {
                    key: fact,
                    size: "small",
                    variant: "outlined"
                  }, {
                    default: _withCtx(() => [
                      _createTextVNode(_toDisplayString(fact), 1)
                    ]),
                    _: 2
                  }, 1024))
                }), 128))
              ]),
              _createElementVNode("div", _hoisted_23, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(mediaMeta(selectedMedia.value), (entry) => {
                  return (_openBlock(), _createElementBlock("div", {
                    key: entry.label,
                    class: "meta-line"
                  }, [
                    _createElementVNode("span", null, _toDisplayString(entry.label), 1),
                    _createElementVNode("strong", null, _toDisplayString(entry.value), 1)
                  ]))
                }), 128))
              ]),
              _createElementVNode("p", _hoisted_24, _toDisplayString(selectedMedia.value.vod_content || "暂无剧情简介"), 1)
            ])
          ]),
          (groupCards.value.length)
            ? (_openBlock(), _createElementBlock("div", _hoisted_25, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(groupCards.value, (group) => {
                  return (_openBlock(), _createBlock(_component_VCard, {
                    key: group.name,
                    class: "group-card",
                    variant: "outlined",
                    onClick: $event => (openGroup(group.name))
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VCardText, null, {
                        default: _withCtx(() => [
                          _createElementVNode("div", _hoisted_26, _toDisplayString(group.label), 1),
                          _createElementVNode("div", _hoisted_27, _toDisplayString(group.count) + " 条链接", 1)
                        ]),
                        _: 2
                      }, 1024)
                    ]),
                    _: 2
                  }, 1032, ["onClick"]))
                }), 128))
              ]))
            : _createCommentVNode("", true)
        ]))
      : _createCommentVNode("", true),
    _createElementVNode("div", {
      ref_key: "queueSectionRef",
      ref: queueSectionRef,
      class: "panel-card"
    }, [
      _createElementVNode("div", _hoisted_28, [
        _createElementVNode("div", null, [
          _cache[15] || (_cache[15] = _createElementVNode("div", { class: "panel-title" }, "任务队列", -1)),
          _createElementVNode("div", _hoisted_29, _toDisplayString(queueCountText.value), 1)
        ]),
        _createVNode(_component_VBtn, {
          variant: "text",
          loading: queueLoading.value,
          onClick: clearQueue
        }, {
          default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
            _createTextVNode("清空队列", -1)
          ]))]),
          _: 1
        }, 8, ["loading"])
      ]),
      (queueItems.value.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_30, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(queueItems.value, (item) => {
              return (_openBlock(), _createBlock(_component_VCard, {
                key: `${item.url}-${item.target_path}-${item.queued_at}`,
                class: _normalizeClass(["queue-card", { latest: latestQueueKey.value && item.queued_at === latestQueueKey.value }]),
                variant: "outlined"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VCardText, { class: "d-flex flex-column ga-2" }, {
                    default: _withCtx(() => [
                      _createElementVNode("div", _hoisted_31, _toDisplayString(item.vod_name || item.title), 1),
                      _createElementVNode("div", _hoisted_32, "分类：" + _toDisplayString(item.category_group) + " / " + _toDisplayString(item.category_name), 1),
                      _createElementVNode("div", _hoisted_33, "目标目录：" + _toDisplayString(item.target_path), 1),
                      _createElementVNode("div", _hoisted_34, "目标 CID：" + _toDisplayString(item.target_cid || "未知"), 1),
                      _createElementVNode("div", _hoisted_35, "认证：" + _toDisplayString(item.auth_label || "115 网页 Cookie"), 1),
                      _createElementVNode("div", _hoisted_36, _toDisplayString(item.status), 1)
                    ]),
                    _: 2
                  }, 1024)
                ]),
                _: 2
              }, 1032, ["class"]))
            }), 128))
          ]))
        : (_openBlock(), _createBlock(_component_VAlert, {
            key: 1,
            type: "info",
            variant: "outlined"
          }, {
            default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
              _createTextVNode("暂无任务。", -1)
            ]))]),
            _: 1
          }))
    ], 512),
    _createVNode(_component_VDialog, {
      modelValue: groupDialog.value,
      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((groupDialog).value = $event)),
      "max-width": "880"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, null, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, null, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(diskLabel(activeGroupName.value)), 1)
              ]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "dialog-list" }, {
              default: _withCtx(() => [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(activeEntries.value, (entry) => {
                  return (_openBlock(), _createBlock(_component_VCard, {
                    key: `${entry.url}-${entry.password}`,
                    class: "dialog-card",
                    variant: "outlined"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VCardText, { class: "d-flex flex-column ga-3" }, {
                        default: _withCtx(() => [
                          _createElementVNode("div", null, [
                            _createElementVNode("div", _hoisted_37, _toDisplayString(entry.title || "未命名资源"), 1),
                            _createElementVNode("div", _hoisted_38, _toDisplayString(entrySubtitle(entry)), 1)
                          ]),
                          _createElementVNode("div", _hoisted_39, _toDisplayString(entry.url), 1),
                          _createElementVNode("div", _hoisted_40, "提取码：" + _toDisplayString(entry.password || "无"), 1),
                          _createVNode(_component_VBtn, {
                            color: "primary",
                            disabled: activeGroupName.value !== '115',
                            onClick: $event => (chooseEntry(entry))
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(submitButtonText.value), 1)
                            ]),
                            _: 1
                          }, 8, ["disabled", "onClick"])
                        ]),
                        _: 2
                      }, 1024)
                    ]),
                    _: 2
                  }, 1024))
                }), 128))
              ]),
              _: 1
            }),
            _createVNode(_component_VCardActions, null, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[1] || (_cache[1] = $event => (groupDialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                    _createTextVNode("关闭", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_VDialog, {
      modelValue: downloadDialog.value,
      "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((downloadDialog).value = $event)),
      "max-width": "640"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, null, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, null, {
              default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                _createTextVNode("提交到 115", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "d-flex flex-column ga-4" }, {
              default: _withCtx(() => [
                _createVNode(_component_VAlert, {
                  type: "info",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                    _createTextVNode(" 目标目录会根据 MoviePilot 当前分类对应的 u115 存储自动解析。 ", -1)
                  ]))]),
                  _: 1
                }),
                (selectedEntry.value)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_41, [
                      _createElementVNode("div", _hoisted_42, _toDisplayString(selectedEntry.value.title || "未命名资源"), 1),
                      _createElementVNode("div", _hoisted_43, _toDisplayString(selectedEntry.value.url), 1),
                      _createElementVNode("div", _hoisted_44, "提取码：" + _toDisplayString(selectedEntry.value.password || "无"), 1)
                    ]))
                  : _createCommentVNode("", true),
                _createVNode(_component_VSelect, {
                  modelValue: selectedCategoryKey.value,
                  "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((selectedCategoryKey).value = $event)),
                  items: categoryOptions.value,
                  loading: categoryLoading.value,
                  "item-title": "label",
                  "item-value": "key",
                  label: "MoviePilot 分类"
                }, null, 8, ["modelValue", "items", "loading"])
              ]),
              _: 1
            }),
            _createVNode(_component_VCardActions, null, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[4] || (_cache[4] = $event => (downloadDialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  loading: queueLoading.value,
                  disabled: !selectedCategory.value,
                  onClick: submitSelectedEntry
                }, {
                  default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                    _createTextVNode("提交", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading", "disabled"])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_VDialog, {
      modelValue: configDialog.value,
      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((configDialog).value = $event)),
      "max-width": "820"
    }, {
      default: _withCtx(() => [
        _createVNode(_sfc_main$1, {
          "initial-config": pluginConfig.value,
          saving: configSaving.value,
          onSave: savePluginConfig,
          onClose: _cache[6] || (_cache[6] = $event => (configDialog.value = false))
        }, null, 8, ["initial-config", "saving"])
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-2e0f84d2"]]);

export { Page as default };
