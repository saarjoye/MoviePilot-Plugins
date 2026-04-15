import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,withKeys:_withKeys,renderList:_renderList,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode} = await importShared('vue');


const _hoisted_1 = { class: "page-shell" };
const _hoisted_2 = { class: "d-flex flex-wrap ga-2" };
const _hoisted_3 = { class: "d-flex flex-wrap ga-2" };
const _hoisted_4 = { class: "text-caption text-medium-emphasis" };
const _hoisted_5 = { class: "text-subtitle-1 font-weight-medium" };
const _hoisted_6 = { class: "text-body-2 break-all" };
const _hoisted_7 = { class: "break-all" };

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

return (_ctx, _cache) => {
  const _component_VChip = _resolveComponent("VChip");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VCardSubtitle = _resolveComponent("VCardSubtitle");
  const _component_VCardActions = _resolveComponent("VCardActions");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VCard, {
      class: "mb-4",
      variant: "tonal"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardTitle, { class: "d-flex align-center justify-space-between flex-wrap ga-3" }, {
          default: _withCtx(() => [
            _cache[3] || (_cache[3] = _createElementVNode("span", null, "盘链搜索", -1)),
            _createVNode(_component_VChip, {
              color: pluginState.value.enabled ? 'success' : 'warning',
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(pluginState.value.enabled ? "插件已启用" : "插件未启用"), 1)
              ]),
              _: 1
            }, 8, ["color"])
          ]),
          _: 1
        }),
        _createVNode(_component_VCardText, { class: "d-flex flex-column ga-4" }, {
          default: _withCtx(() => [
            _cache[8] || (_cache[8] = _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, " 手动搜索电影或电视剧，优先展示盘链中的 115 资源，并预留“加入 115”按钮接口。 ", -1)),
            _createVNode(_component_VAlert, {
              type: "info",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(statusMessage.value), 1)
              ]),
              _: 1
            }),
            _createElementVNode("div", _hoisted_2, [
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
                  _createTextVNode(" 最多展示 " + _toDisplayString(pluginState.value.max_results) + " 条搜索结果 ", 1)
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
            ]),
            _createVNode(_component_VRow, null, {
              default: _withCtx(() => [
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "8"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VTextField, {
                      modelValue: keyword.value,
                      "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((keyword).value = $event)),
                      clearable: "",
                      density: "comfortable",
                      "hide-details": "auto",
                      label: "影视名称",
                      placeholder: "例如：危险关系、流浪地球、庆余年",
                      onKeyup: _withKeys(searchPanlink, ["enter"])
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_VCol, {
                  cols: "12",
                  md: "4"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VBtn, {
                      block: "",
                      color: "primary",
                      loading: searching.value,
                      onClick: searchPanlink
                    }, {
                      default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
                        _createTextVNode(" 搜索盘链 ", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createElementVNode("div", _hoisted_3, [
              _createVNode(_component_VBtn, {
                variant: "text",
                color: "primary",
                onClick: _cache[1] || (_cache[1] = $event => (emit('switch')))
              }, {
                default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
                  _createTextVNode(" 打开插件配置 ", -1)
                ]))]),
                _: 1
              }),
              _createVNode(_component_VBtn, {
                variant: "text",
                color: "default",
                onClick: fetchState
              }, {
                default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
                  _createTextVNode(" 刷新状态 ", -1)
                ]))]),
                _: 1
              }),
              _createVNode(_component_VBtn, {
                variant: "text",
                color: "default",
                onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
              }, {
                default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                  _createTextVNode(" 关闭 ", -1)
                ]))]),
                _: 1
              })
            ])
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VCard, { class: "mb-4" }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardTitle, { class: "d-flex align-center justify-space-between flex-wrap ga-3" }, {
          default: _withCtx(() => [
            _cache[9] || (_cache[9] = _createElementVNode("span", null, "搜索结果", -1)),
            _createElementVNode("span", _hoisted_4, _toDisplayString(resultCountText.value), 1)
          ]),
          _: 1
        }),
        (searchResults.value.length)
          ? (_openBlock(), _createBlock(_component_VCardText, {
              key: 0,
              class: "d-flex flex-column ga-3"
            }, {
              default: _withCtx(() => [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(searchResults.value, (item) => {
                  return (_openBlock(), _createBlock(_component_VCard, {
                    key: item.vod_id,
                    variant: "outlined"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VCardTitle, null, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(item.vod_name), 1)
                        ]),
                        _: 2
                      }, 1024),
                      _createVNode(_component_VCardSubtitle, null, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(resultSubtitle(item) || `vod_id=${item.vod_id}`), 1)
                        ]),
                        _: 2
                      }, 1024),
                      _createVNode(_component_VCardText, { class: "d-flex flex-wrap ga-2" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VChip, {
                            size: "small",
                            variant: "outlined"
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode("语言：" + _toDisplayString(item.vod_lang || "未知"), 1)
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_VChip, {
                            size: "small",
                            variant: "outlined"
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode("编号：" + _toDisplayString(item.vod_id), 1)
                            ]),
                            _: 2
                          }, 1024)
                        ]),
                        _: 2
                      }, 1024),
                      _createVNode(_component_VCardActions, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_VBtn, {
                            color: "primary",
                            variant: "flat",
                            loading: loadingVodId.value === item.vod_id,
                            onClick: $event => (loadLinks(item))
                          }, {
                            default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                              _createTextVNode(" 加载资源 ", -1)
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
              ]),
              _: 1
            }))
          : (_openBlock(), _createBlock(_component_VCardText, { key: 1 }, {
              default: _withCtx(() => [
                _createVNode(_component_VAlert, {
                  type: "info",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
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
    _createVNode(_component_VCard, { class: "mb-4" }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardTitle, null, {
          default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
            _createTextVNode("资源列表", -1)
          ]))]),
          _: 1
        }),
        (groupEntries(linkGroups.value).length)
          ? (_openBlock(), _createBlock(_component_VCardText, {
              key: 0,
              class: "d-flex flex-column ga-4"
            }, {
              default: _withCtx(() => [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(groupEntries(linkGroups.value), ([groupName, entries]) => {
                  return (_openBlock(), _createElementBlock("div", {
                    key: groupName,
                    class: "d-flex flex-column ga-3"
                  }, [
                    _createElementVNode("div", _hoisted_5, _toDisplayString(groupTitle(groupName)), 1),
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(entries, (entry) => {
                      return (_openBlock(), _createBlock(_component_VCard, {
                        key: `${groupName}-${entry.url}`,
                        variant: "outlined"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VCardTitle, null, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(entry.title || "未命名资源"), 1)
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_VCardSubtitle, null, {
                            default: _withCtx(() => [
                              _createTextVNode(" 来源：" + _toDisplayString(entry.source || "未知") + " / 更新时间：" + _toDisplayString(entry.time || "未知"), 1)
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_VCardText, { class: "d-flex flex-column ga-2" }, {
                            default: _withCtx(() => [
                              _createElementVNode("div", _hoisted_6, _toDisplayString(entry.url), 1),
                              _createVNode(_component_VChip, {
                                size: "small",
                                variant: "outlined"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode(" 提取码：" + _toDisplayString(entry.password || "无"), 1)
                                ]),
                                _: 2
                              }, 1024)
                            ]),
                            _: 2
                          }, 1024),
                          _createVNode(_component_VCardActions, { class: "flex-wrap ga-2" }, {
                            default: _withCtx(() => [
                              _createVNode(_component_VBtn, {
                                href: entry.url,
                                target: "_blank",
                                rel: "noopener noreferrer",
                                variant: "text"
                              }, {
                                default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                                  _createTextVNode(" 打开链接 ", -1)
                                ]))]),
                                _: 1
                              }, 8, ["href"]),
                              (groupName === '115')
                                ? (_openBlock(), _createBlock(_component_VBtn, {
                                    key: 0,
                                    color: "primary",
                                    variant: "flat",
                                    loading: queueLoading.value,
                                    onClick: $event => (queue115(entry))
                                  }, {
                                    default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                                      _createTextVNode(" 加入 115 ", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["loading", "onClick"]))
                                : _createCommentVNode("", true)
                            ]),
                            _: 2
                          }, 1024)
                        ]),
                        _: 2
                      }, 1024))
                    }), 128))
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
                  default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                    _createTextVNode(" 还没有加载任何资源。先搜索影视条目，再点击对应结果上的“加载资源”。 ", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }))
      ]),
      _: 1
    }),
    _createVNode(_component_VCard, null, {
      default: _withCtx(() => [
        _createVNode(_component_VCardTitle, { class: "d-flex align-center justify-space-between flex-wrap ga-3" }, {
          default: _withCtx(() => [
            _cache[17] || (_cache[17] = _createElementVNode("span", null, "待转存到 115", -1)),
            _createVNode(_component_VBtn, {
              color: "warning",
              variant: "text",
              disabled: !queueItems.value.length,
              loading: queueLoading.value,
              onClick: clearQueue
            }, {
              default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
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
              class: "d-flex flex-column ga-3"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VAlert, {
                  type: "warning",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                    _createTextVNode(" 当前“加入 115”仍是占位接口，只会记录待处理队列，还不会自动转存到你的 115。 ", -1)
                  ]))]),
                  _: 1
                }),
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(queueItems.value, (item) => {
                  return (_openBlock(), _createBlock(_component_VCard, {
                    key: item.url,
                    variant: "outlined"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VCardTitle, null, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(item.title), 1)
                        ]),
                        _: 2
                      }, 1024),
                      _createVNode(_component_VCardSubtitle, null, {
                        default: _withCtx(() => [
                          _createTextVNode(" 加入时间：" + _toDisplayString(item.queued_at) + " / 状态：" + _toDisplayString(item.status), 1)
                        ]),
                        _: 2
                      }, 1024),
                      _createVNode(_component_VCardText, { class: "d-flex flex-column ga-2" }, {
                        default: _withCtx(() => [
                          _createElementVNode("div", null, "来源：" + _toDisplayString(item.source || "未知"), 1),
                          _createElementVNode("div", _hoisted_7, _toDisplayString(item.url), 1),
                          _createElementVNode("div", null, "提取码：" + _toDisplayString(item.password || "无"), 1)
                        ]),
                        _: 2
                      }, 1024)
                    ]),
                    _: 2
                  }, 1024))
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
                    _createTextVNode(" 待转存队列为空。加载到 115 资源后，可以先点“加入 115”做占位记录。 ", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }))
      ]),
      _: 1
    })
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-aadfc131"]]);

export { Page as default };
