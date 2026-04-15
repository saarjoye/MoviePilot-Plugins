import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,withKeys:_withKeys,renderList:_renderList,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,normalizeClass:_normalizeClass,normalizeStyle:_normalizeStyle} = await importShared('vue');


const _hoisted_1 = { class: "page-shell" };
const _hoisted_2 = { class: "hero-panel" };
const _hoisted_3 = { class: "hero-copy" };
const _hoisted_4 = { class: "hero-chips" };
const _hoisted_5 = { class: "hero-search" };
const _hoisted_6 = { class: "hero-actions" };
const _hoisted_7 = { class: "content-grid" };
const _hoisted_8 = { class: "text-caption text-medium-emphasis" };
const _hoisted_9 = ["onClick"];
const _hoisted_10 = ["src", "alt"];
const _hoisted_11 = { class: "result-body" };
const _hoisted_12 = { class: "result-name" };
const _hoisted_13 = { class: "result-subtitle" };
const _hoisted_14 = { class: "result-lang" };
const _hoisted_15 = { class: "result-tail" };
const _hoisted_16 = { key: 1 };
const _hoisted_17 = { class: "detail-stack" };
const _hoisted_18 = { class: "detail-header" };
const _hoisted_19 = ["src", "alt"];
const _hoisted_20 = { class: "detail-copy" };
const _hoisted_21 = { class: "detail-title-row" };
const _hoisted_22 = { class: "detail-title" };
const _hoisted_23 = ["href"];
const _hoisted_24 = { class: "detail-tags" };
const _hoisted_25 = { class: "detail-meta-grid" };
const _hoisted_26 = { class: "meta-label" };
const _hoisted_27 = { class: "meta-value" };
const _hoisted_28 = {
  key: 0,
  class: "meta-item full-width"
};
const _hoisted_29 = { class: "meta-value" };
const _hoisted_30 = {
  key: 0,
  class: "plot-panel"
};
const _hoisted_31 = { class: "plot-text" };
const _hoisted_32 = {
  key: 0,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_33 = ["onClick"];
const _hoisted_34 = { class: "resource-name" };
const _hoisted_35 = { class: "resource-count" };
const _hoisted_36 = { class: "resource-hint" };
const _hoisted_37 = { class: "queue-name" };
const _hoisted_38 = { class: "queue-path" };
const _hoisted_39 = { class: "queue-meta" };
const _hoisted_40 = { class: "queue-status" };
const _hoisted_41 = { class: "queue-url" };
const _hoisted_42 = { class: "queue-pass" };
const _hoisted_43 = { class: "dialog-entry-title" };
const _hoisted_44 = { class: "dialog-entry-subtitle" };
const _hoisted_45 = { class: "dialog-entry-url" };
const _hoisted_46 = { class: "dialog-entry-pass" };
const _hoisted_47 = { class: "dialog-actions" };
const _hoisted_48 = { class: "download-summary" };
const _hoisted_49 = { class: "download-row" };
const _hoisted_50 = { class: "download-row" };
const _hoisted_51 = { class: "download-row" };
const _hoisted_52 = {
  key: 0,
  class: "selection-preview"
};

const {computed,onMounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: {
  api: {
    type: Object,
    default: () => ({})
  }
},
  emits: ["action", "switch", "close"],
  setup(__props, { emit: __emit }) {

const emit = __emit;

const props = __props;

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

return (_ctx, _cache) => {
  const _component_VChip = _resolveComponent("VChip");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VProgressCircular = _resolveComponent("VProgressCircular");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VDialog = _resolveComponent("VDialog");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VCardActions = _resolveComponent("VCardActions");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("section", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _cache[7] || (_cache[7] = _createElementVNode("div", { class: "hero-kicker" }, "PANLIAN x MOVIEPILOT", -1)),
        _cache[8] || (_cache[8] = _createElementVNode("h1", { class: "hero-title" }, "盘链搜索与 115 下载任务面板", -1)),
        _cache[9] || (_cache[9] = _createElementVNode("p", { class: "hero-text" }, " 手动查询电视剧或电影，按盘链详情页方式查看资源，并把 115 链接投递到基于 MoviePilot 当前分类的下载任务里。 ", -1)),
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_VChip, {
            color: pluginState.value.enabled ? 'success' : 'warning',
            size: "small",
            variant: "flat"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(pluginState.value.enabled ? "插件已启用" : "插件未启用"), 1)
            ]),
            _: 1
          }, 8, ["color"]),
          _createVNode(_component_VChip, {
            size: "small",
            variant: "outlined"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(pluginState.value.only_show_115 ? "当前仅显示 115" : "当前显示全部网盘"), 1)
            ]),
            _: 1
          }),
          _createVNode(_component_VChip, {
            size: "small",
            variant: "outlined"
          }, {
            default: _withCtx(() => [
              _createTextVNode(" 最多 " + _toDisplayString(pluginState.value.max_results) + " 条结果 ", 1)
            ]),
            _: 1
          }),
          _createVNode(_component_VChip, {
            size: "small",
            variant: "outlined"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(queueCountText.value), 1)
            ]),
            _: 1
          })
        ])
      ]),
      _createElementVNode("div", _hoisted_5, [
        _createVNode(_component_VAlert, {
          class: "mb-4",
          type: "info",
          variant: "tonal"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(statusMessage.value), 1)
          ]),
          _: 1
        }),
        _createVNode(_component_VTextField, {
          modelValue: keyword.value,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((keyword).value = $event)),
          clearable: "",
          density: "comfortable",
          "hide-details": "auto",
          label: "影视名称",
          placeholder: "例如：危险关系、流浪地球、庆余年",
          onKeyup: _withKeys(searchPanlink, ["enter"])
        }, null, 8, ["modelValue"]),
        _createElementVNode("div", _hoisted_6, [
          _createVNode(_component_VBtn, {
            color: "primary",
            size: "large",
            loading: searching.value,
            onClick: searchPanlink
          }, {
            default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
              _createTextVNode(" 搜索盘链 ", -1)
            ]))]),
            _: 1
          }, 8, ["loading"]),
          _createVNode(_component_VBtn, {
            variant: "text",
            color: "primary",
            onClick: _cache[1] || (_cache[1] = $event => (emit('switch')))
          }, {
            default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
              _createTextVNode(" 打开插件配置 ", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VBtn, {
            variant: "text",
            color: "default",
            onClick: fetchState
          }, {
            default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
              _createTextVNode(" 刷新状态 ", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VBtn, {
            variant: "text",
            color: "default",
            onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
          }, {
            default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
              _createTextVNode(" 关闭 ", -1)
            ]))]),
            _: 1
          })
        ])
      ])
    ]),
    _createElementVNode("section", _hoisted_7, [
      _createVNode(_component_VCard, {
        class: "result-panel",
        rounded: "xl"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardTitle, { class: "d-flex align-center justify-space-between flex-wrap ga-3" }, {
            default: _withCtx(() => [
              _cache[14] || (_cache[14] = _createElementVNode("span", null, "搜索结果", -1)),
              _createElementVNode("span", _hoisted_8, _toDisplayString(resultCountText.value), 1)
            ]),
            _: 1
          }),
          (searchResults.value.length)
            ? (_openBlock(), _createBlock(_component_VCardText, {
                key: 0,
                class: "result-list"
              }, {
                default: _withCtx(() => [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(searchResults.value, (item) => {
                    return (_openBlock(), _createElementBlock("button", {
                      key: item.vod_id,
                      class: _normalizeClass(["result-card", { active: selectedMedia.value?.vod_id === item.vod_id }]),
                      type: "button",
                      onClick: $event => (loadLinks(item))
                    }, [
                      _createElementVNode("img", {
                        class: "result-thumb",
                        src: item.vod_pic || 'https://115.com/favicon.ico',
                        alt: item.vod_name
                      }, null, 8, _hoisted_10),
                      _createElementVNode("div", _hoisted_11, [
                        _createElementVNode("div", _hoisted_12, _toDisplayString(item.vod_name), 1),
                        _createElementVNode("div", _hoisted_13, _toDisplayString(resultSubtitle(item) || `vod_id=${item.vod_id}`), 1),
                        _createElementVNode("div", _hoisted_14, "语言：" + _toDisplayString(item.vod_lang || "未知"), 1)
                      ]),
                      _createElementVNode("div", _hoisted_15, [
                        (loadingVodId.value === item.vod_id)
                          ? (_openBlock(), _createBlock(_component_VProgressCircular, {
                              key: 0,
                              indeterminate: "",
                              size: "18",
                              width: "2"
                            }))
                          : (_openBlock(), _createElementBlock("span", _hoisted_16, "查看"))
                      ])
                    ], 10, _hoisted_9))
                  }), 128))
                ]),
                _: 1
              }))
            : (_openBlock(), _createBlock(_component_VCardText, { key: 1 }, {
                default: _withCtx(() => [
                  _createVNode(_component_VAlert, {
                    type: "info",
                    variant: "tonal"
                  }, {
                    default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                      _createTextVNode(" 暂无搜索结果。输入关键词后点击“搜索盘链”即可开始查询。 ", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _: 1
              }))
        ]),
        _: 1
      }),
      _createElementVNode("div", _hoisted_17, [
        (selectedMedia.value)
          ? (_openBlock(), _createBlock(_component_VCard, {
              key: 0,
              class: "detail-panel",
              rounded: "xl"
            }, {
              default: _withCtx(() => [
                _createElementVNode("div", {
                  class: "detail-banner",
                  style: _normalizeStyle({ backgroundImage: `url(${selectedMedia.value.vod_pic || 'https://115.com/favicon.ico'})` })
                }, null, 4),
                _createVNode(_component_VCardText, { class: "detail-content" }, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_18, [
                      _createElementVNode("img", {
                        class: "detail-poster",
                        src: selectedMedia.value.vod_pic || 'https://115.com/favicon.ico',
                        alt: selectedMedia.value.vod_name
                      }, null, 8, _hoisted_19),
                      _createElementVNode("div", _hoisted_20, [
                        _createElementVNode("div", _hoisted_21, [
                          _createElementVNode("h2", _hoisted_22, _toDisplayString(selectedMedia.value.vod_name), 1),
                          (selectedMedia.value.detail_url)
                            ? (_openBlock(), _createElementBlock("a", {
                                key: 0,
                                class: "detail-link",
                                href: selectedMedia.value.detail_url,
                                target: "_blank",
                                rel: "noopener noreferrer"
                              }, " 盘链原页 ", 8, _hoisted_23))
                            : _createCommentVNode("", true)
                        ]),
                        _createElementVNode("div", _hoisted_24, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(mediaFacts(selectedMedia.value), (fact) => {
                            return (_openBlock(), _createElementBlock("span", {
                              key: fact,
                              class: "detail-tag"
                            }, _toDisplayString(fact), 1))
                          }), 128))
                        ]),
                        _createElementVNode("div", _hoisted_25, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(mediaMeta(selectedMedia.value), (meta) => {
                            return (_openBlock(), _createElementBlock("div", {
                              key: meta.label,
                              class: "meta-item"
                            }, [
                              _createElementVNode("span", _hoisted_26, _toDisplayString(meta.label), 1),
                              _createElementVNode("span", _hoisted_27, _toDisplayString(meta.value), 1)
                            ]))
                          }), 128)),
                          (selectedMedia.value.vod_actor)
                            ? (_openBlock(), _createElementBlock("div", _hoisted_28, [
                                _cache[16] || (_cache[16] = _createElementVNode("span", { class: "meta-label" }, "主演", -1)),
                                _createElementVNode("span", _hoisted_29, _toDisplayString(selectedMedia.value.vod_actor), 1)
                              ]))
                            : _createCommentVNode("", true)
                        ]),
                        (selectedMedia.value.vod_content)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_30, [
                              _cache[17] || (_cache[17] = _createElementVNode("div", { class: "plot-title" }, "剧情简介", -1)),
                              _createElementVNode("p", _hoisted_31, _toDisplayString(selectedMedia.value.vod_content), 1)
                            ]))
                          : _createCommentVNode("", true)
                      ])
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_VCard, {
          class: "resource-panel",
          rounded: "xl"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "d-flex align-center justify-space-between flex-wrap ga-3" }, {
              default: _withCtx(() => [
                _cache[18] || (_cache[18] = _createElementVNode("span", null, "资源展示", -1)),
                (preferredCategoryHint.value)
                  ? (_openBlock(), _createElementBlock("span", _hoisted_32, " 默认推荐分类组：" + _toDisplayString(preferredCategoryHint.value), 1))
                  : _createCommentVNode("", true)
              ]),
              _: 1
            }),
            (groupCards.value.length)
              ? (_openBlock(), _createBlock(_component_VCardText, {
                  key: 0,
                  class: "resource-grid"
                }, {
                  default: _withCtx(() => [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(groupCards.value, (group) => {
                      return (_openBlock(), _createElementBlock("button", {
                        key: group.name,
                        type: "button",
                        class: _normalizeClass(["resource-card", { primary: group.name === '115' }]),
                        onClick: $event => (openGroupDialog(group.name))
                      }, [
                        _createElementVNode("div", _hoisted_34, _toDisplayString(group.label), 1),
                        _createElementVNode("div", _hoisted_35, _toDisplayString(group.count) + " 条", 1),
                        _createElementVNode("div", _hoisted_36, _toDisplayString(group.name === "115" ? "点击查看并创建下载任务" : "点击查看原始链接"), 1)
                      ], 10, _hoisted_33))
                    }), 128))
                  ]),
                  _: 1
                }))
              : (_openBlock(), _createBlock(_component_VCardText, { key: 1 }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VAlert, {
                      type: "info",
                      variant: "tonal"
                    }, {
                      default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                        _createTextVNode(" 先从左侧选择一个搜索结果，这里就会展示对应的网盘资源分组。 ", -1)
                      ]))]),
                      _: 1
                    })
                  ]),
                  _: 1
                }))
          ]),
          _: 1
        }),
        _createVNode(_component_VCard, {
          class: "queue-panel",
          rounded: "xl"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "d-flex align-center justify-space-between flex-wrap ga-3" }, {
              default: _withCtx(() => [
                _cache[21] || (_cache[21] = _createElementVNode("span", null, "下载任务", -1)),
                _createVNode(_component_VBtn, {
                  color: "warning",
                  variant: "text",
                  disabled: !queueItems.value.length,
                  loading: queueLoading.value,
                  onClick: clearQueue
                }, {
                  default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                    _createTextVNode(" 清空队列 ", -1)
                  ]))]),
                  _: 1
                }, 8, ["disabled", "loading"])
              ]),
              _: 1
            }),
            (queueItems.value.length)
              ? (_openBlock(), _createBlock(_component_VCardText, {
                  key: 0,
                  class: "queue-list"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VAlert, {
                      type: "warning",
                      variant: "tonal"
                    }, {
                      default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                        _createTextVNode(" 当前“下载”仍是占位任务，只会记录你选择的 115 链接和 MoviePilot 分类。下一阶段再接真实 115 转存与 MP 整理入库。 ", -1)
                      ]))]),
                      _: 1
                    }),
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(queueItems.value, (item) => {
                      return (_openBlock(), _createElementBlock("article", {
                        key: `${item.url}-${item.category_name}`,
                        class: "queue-card"
                      }, [
                        _createElementVNode("div", _hoisted_37, _toDisplayString(item.vod_name || item.title), 1),
                        _createElementVNode("div", _hoisted_38, _toDisplayString(queueSubtitle(item)), 1),
                        _createElementVNode("div", _hoisted_39, [
                          _createElementVNode("span", null, "来源：" + _toDisplayString(item.source || "未知"), 1),
                          _createElementVNode("span", null, "创建时间：" + _toDisplayString(item.queued_at), 1)
                        ]),
                        _createElementVNode("div", _hoisted_40, _toDisplayString(item.status), 1),
                        _createElementVNode("div", _hoisted_41, _toDisplayString(item.url), 1),
                        _createElementVNode("div", _hoisted_42, "提取码：" + _toDisplayString(item.password || "无"), 1)
                      ]))
                    }), 128))
                  ]),
                  _: 1
                }))
              : (_openBlock(), _createBlock(_component_VCardText, { key: 1 }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VAlert, {
                      type: "info",
                      variant: "tonal"
                    }, {
                      default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                        _createTextVNode(" 还没有下载任务。打开 115 资源弹层后点击“下载”，并选择一个 MoviePilot 分类即可创建任务。 ", -1)
                      ]))]),
                      _: 1
                    })
                  ]),
                  _: 1
                }))
          ]),
          _: 1
        })
      ])
    ]),
    _createVNode(_component_VDialog, {
      modelValue: groupDialog.value,
      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((groupDialog).value = $event)),
      "max-width": "920"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, { rounded: "xl" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "d-flex align-center justify-space-between flex-wrap ga-3" }, {
              default: _withCtx(() => [
                _createElementVNode("span", null, _toDisplayString(diskLabel(activeGroupName.value)), 1),
                _createVNode(_component_VChip, {
                  size: "small",
                  variant: "outlined"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(" 共 " + _toDisplayString(activeEntries.value.length) + " 条 ", 1)
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            (activeEntries.value.length)
              ? (_openBlock(), _createBlock(_component_VCardText, {
                  key: 0,
                  class: "dialog-list"
                }, {
                  default: _withCtx(() => [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(activeEntries.value, (entry) => {
                      return (_openBlock(), _createElementBlock("article", {
                        key: entry.url,
                        class: "dialog-entry"
                      }, [
                        _createElementVNode("div", _hoisted_43, _toDisplayString(entry.title || "未命名资源"), 1),
                        _createElementVNode("div", _hoisted_44, _toDisplayString(entrySubtitle(entry)), 1),
                        _createElementVNode("div", _hoisted_45, _toDisplayString(entry.url), 1),
                        _createElementVNode("div", _hoisted_46, "提取码：" + _toDisplayString(entry.password || "无"), 1),
                        _createElementVNode("div", _hoisted_47, [
                          (activeGroupName.value === '115')
                            ? (_openBlock(), _createBlock(_component_VBtn, {
                                key: 0,
                                color: "primary",
                                variant: "flat",
                                onClick: $event => (openDownloadDialog(entry))
                              }, {
                                default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                                  _createTextVNode(" 下载 ", -1)
                                ]))]),
                                _: 1
                              }, 8, ["onClick"]))
                            : _createCommentVNode("", true),
                          _createVNode(_component_VBtn, {
                            href: entry.url,
                            target: "_blank",
                            rel: "noopener noreferrer",
                            variant: "text"
                          }, {
                            default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                              _createTextVNode(" 打开链接 ", -1)
                            ]))]),
                            _: 1
                          }, 8, ["href"])
                        ])
                      ]))
                    }), 128))
                  ]),
                  _: 1
                }))
              : (_openBlock(), _createBlock(_component_VCardText, { key: 1 }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VAlert, {
                      type: "info",
                      variant: "tonal"
                    }, {
                      default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                        _createTextVNode(" 当前分组没有可展示的链接。 ", -1)
                      ]))]),
                      _: 1
                    })
                  ]),
                  _: 1
                }))
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_VDialog, {
      modelValue: downloadDialog.value,
      "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((downloadDialog).value = $event)),
      "max-width": "720"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, { rounded: "xl" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, null, {
              default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
                _createTextVNode("创建 115 下载任务", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_VCardText, { class: "dialog-list" }, {
              default: _withCtx(() => [
                _createVNode(_component_VAlert, {
                  type: "info",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                    _createTextVNode(" 分类直接读取 MoviePilot 当前配置，后续真实接入整理链路时会以这里选中的分类作为落库目标。 ", -1)
                  ]))]),
                  _: 1
                }),
                _createElementVNode("div", _hoisted_48, [
                  _createElementVNode("div", _hoisted_49, [
                    _cache[29] || (_cache[29] = _createElementVNode("span", { class: "download-label" }, "影视条目", -1)),
                    _createElementVNode("span", null, _toDisplayString(selectedMedia.value?.vod_name || "未选择"), 1)
                  ]),
                  _createElementVNode("div", _hoisted_50, [
                    _cache[30] || (_cache[30] = _createElementVNode("span", { class: "download-label" }, "资源标题", -1)),
                    _createElementVNode("span", null, _toDisplayString(selectedEntry.value?.title || "未选择"), 1)
                  ]),
                  _createElementVNode("div", _hoisted_51, [
                    _cache[31] || (_cache[31] = _createElementVNode("span", { class: "download-label" }, "推荐分类组", -1)),
                    _createElementVNode("span", null, _toDisplayString(preferredCategoryHint.value || "未识别"), 1)
                  ])
                ]),
                _createVNode(_component_VSelect, {
                  modelValue: selectedCategoryKey.value,
                  "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((selectedCategoryKey).value = $event)),
                  items: categoryOptions.value,
                  "item-title": "label",
                  "item-value": "key",
                  label: "MoviePilot 分类",
                  placeholder: "请选择分类",
                  loading: categoryLoading.value,
                  "hide-details": "auto"
                }, null, 8, ["modelValue", "items", "loading"]),
                (selectedCategoryLabel.value)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_52, " 当前任务将写入：" + _toDisplayString(selectedCategoryLabel.value), 1))
                  : _createCommentVNode("", true)
              ]),
              _: 1
            }),
            _createVNode(_component_VCardActions, { class: "px-6 pb-5" }, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  onClick: _cache[5] || (_cache[5] = $event => (downloadDialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[32] || (_cache[32] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  variant: "flat",
                  loading: queueLoading.value,
                  onClick: queue115
                }, {
                  default: _withCtx(() => [...(_cache[33] || (_cache[33] = [
                    _createTextVNode(" 创建任务 ", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-1198f81f"]]);

export { Page as default };
