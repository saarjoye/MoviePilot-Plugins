import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const { resolveComponent: _resolveComponent, withCtx: _withCtx, createVNode: _createVNode, createTextVNode: _createTextVNode, toDisplayString: _toDisplayString, openBlock: _openBlock, createBlock: _createBlock, createElementVNode: _createElementVNode, renderList: _renderList, Fragment: _Fragment, createElementBlock: _createElementBlock, createCommentVNode: _createCommentVNode, normalizeClass: _normalizeClass } = await importShared('vue');
const { computed, onMounted, reactive, ref } = await importShared('vue');

const _hoisted_gap = { class: "d-flex align-center gap-2" };
const _hoisted_metric = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_hint = { class: "text-body-2 text-medium-emphasis mb-2" };
const _hoisted_hint2 = { class: "text-body-2 text-medium-emphasis mb-2" };
const _hoisted_empty = { class: "text-medium-emphasis" };
const _hoisted_empty2 = { class: "text-medium-emphasis" };
const _hoisted_msg = { class: "text-truncate max-message" };
const _hoisted_image = { class: "text-truncate max-image" };

const _sfc_main = {
  __name: 'Page',
  props: {
    api: { type: Object, default: null },
    showSwitch: { type: Boolean, default: true },
    show_switch: { type: Boolean, default: undefined },
  },
  emits: ['switch'],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const loading = ref(false);
    const error = ref('');
    const state = reactive({
      sources: [],
      source_states: [],
      containers: [],
      updatablelist: [],
      autoupdatelist: [],
      metrics: {},
    });

    const sourceStates = computed(() => Array.isArray(state.source_states) ? state.source_states : []);
    const containers = computed(() => Array.isArray(state.containers) ? state.containers : []);
    const showSettingsButton = computed(() => props.show_switch ?? props.showSwitch);
    const metrics = computed(() => [
      { label: '已配置源', value: state.metrics?.sources || 0, color: 'primary' },
      { label: '启用源', value: state.metrics?.enabled_sources || 0, color: 'success' },
      { label: '容器总数', value: state.metrics?.containers || 0, color: 'primary' },
      { label: '异常源', value: state.metrics?.failed_sources || 0, color: 'error' },
    ]);

    function sourceColor(source) {
      if (source.enabled === false || source.state === '停用')
        return 'grey'
      if (source.state === '已连接')
        return 'success'
      if (source.state === '异常')
        return 'error'
      return 'warning'
    }

    async function loadState() {
      error.value = '';
      if (!props.api?.get) {
        error.value = '当前 MoviePilot 未注入插件 API，无法加载详情数据。';
        return
      }
      loading.value = true;
      try {
        const result = await props.api.get('plugin/DockerCopilotHelperMulti/state');
        Object.assign(state, {
          sources: Array.isArray(result?.sources) ? result.sources : [],
          source_states: Array.isArray(result?.source_states) ? result.source_states : [],
          containers: Array.isArray(result?.containers) ? result.containers : [],
          updatablelist: Array.isArray(result?.updatablelist) ? result.updatablelist : [],
          autoupdatelist: Array.isArray(result?.autoupdatelist) ? result.autoupdatelist : [],
          metrics: result?.metrics || {},
        });
      } catch (err) {
        error.value = `加载详情失败：${err?.message || err}`;
      } finally {
        loading.value = false;
      }
    }

    onMounted(loadState);

    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent("v-card-title");
      const _component_v_card_subtitle = _resolveComponent("v-card-subtitle");
      const _component_v_icon = _resolveComponent("v-icon");
      const _component_v_btn = _resolveComponent("v-btn");
      const _component_v_card_item = _resolveComponent("v-card-item");
      const _component_v_alert = _resolveComponent("v-alert");
      const _component_v_card_text = _resolveComponent("v-card-text");
      const _component_v_card = _resolveComponent("v-card");
      const _component_v_col = _resolveComponent("v-col");
      const _component_v_row = _resolveComponent("v-row");
      const _component_v_chip = _resolveComponent("v-chip");
      const _component_v_table = _resolveComponent("v-table");

      return (_openBlock(), _createBlock(_component_v_card, { flat: "" }, {
        default: _withCtx(() => [
          _createVNode(_component_v_card_item, null, {
            append: _withCtx(() => [
              _createElementVNode("div", _hoisted_gap, [
                _createVNode(_component_v_btn, {
                  icon: "",
                  color: "primary",
                  variant: "text",
                  loading: loading.value,
                  onClick: loadState
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, null, {
                      default: _withCtx(() => [...(_cache[0] || (_cache[0] = [_createTextVNode("mdi-refresh", -1)]))]),
                      _: 1
                    })
                  ]),
                  _: 1
                }, 8, ["loading"]),
                showSettingsButton.value ? (_openBlock(), _createBlock(_component_v_btn, {
                  key: 0,
                  icon: "",
                  color: "primary",
                  variant: "text",
                  onClick: _cache[1] || (_cache[1] = $event => emit('switch'))
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, null, {
                      default: _withCtx(() => [...(_cache[2] || (_cache[2] = [_createTextVNode("mdi-cog", -1)]))]),
                      _: 1
                    })
                  ]),
                  _: 1
                })) : _createCommentVNode("", true)
              ])
            ]),
            default: _withCtx(() => [
              _createVNode(_component_v_card_title, null, {
                default: _withCtx(() => [...(_cache[3] || (_cache[3] = [_createTextVNode("DC助手 · 执行与通知", -1)]))]),
                _: 1
              }),
              _createVNode(_component_v_card_subtitle, null, {
                default: _withCtx(() => [...(_cache[4] || (_cache[4] = [_createTextVNode("多源状态、容器列表与任务范围", -1)]))]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_v_card_text, null, {
            default: _withCtx(() => [
              error.value ? (_openBlock(), _createBlock(_component_v_alert, {
                key: 0,
                type: "error",
                variant: "tonal",
                class: "mb-4"
              }, {
                default: _withCtx(() => [_createTextVNode(_toDisplayString(error.value), 1)]),
                _: 1
              })) : _createCommentVNode("", true),
              _createVNode(_component_v_row, null, {
                default: _withCtx(() => [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(metrics.value, (metric) => {
                    return (_openBlock(), _createBlock(_component_v_col, {
                      cols: "6",
                      md: "3",
                      key: metric.label
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_card, { variant: "outlined" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_card_text, null, {
                              default: _withCtx(() => [
                                _createElementVNode("div", {
                                  class: _normalizeClass(['text-h4', 'font-weight-bold', `text-${metric.color}`])
                                }, _toDisplayString(metric.value), 3),
                                _createElementVNode("div", _hoisted_metric, _toDisplayString(metric.label), 1)
                              ]),
                              _: 2
                            }, 1024)
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
              _createVNode(_component_v_row, { class: "mt-2" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_col, { cols: "12", md: "7" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_card, { variant: "outlined" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_card_title, null, { default: _withCtx(() => [...(_cache[5] || (_cache[5] = [_createTextVNode("DockerCopilot 源", -1)]))]), _: 1 }),
                          _createVNode(_component_v_table, { density: "comfortable" }, {
                            default: _withCtx(() => [
                              _cache[6] || (_cache[6] = _createElementVNode("thead", null, [_createElementVNode("tr", null, [_createElementVNode("th", null, "源名称"), _createElementVNode("th", null, "源ID"), _createElementVNode("th", null, "状态"), _createElementVNode("th", null, "容器"), _createElementVNode("th", null, "说明")])], -1)),
                              _createElementVNode("tbody", null, [
                                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sourceStates.value, (source) => {
                                  return (_openBlock(), _createElementBlock("tr", { key: source.id }, [
                                    _createElementVNode("td", null, _toDisplayString(source.name || source.id), 1),
                                    _createElementVNode("td", null, [_createElementVNode("code", null, _toDisplayString(source.id), 1)]),
                                    _createElementVNode("td", null, [
                                      _createVNode(_component_v_chip, {
                                        size: "small",
                                        color: sourceColor(source),
                                        variant: "tonal"
                                      }, { default: _withCtx(() => [_createTextVNode(_toDisplayString(source.state || (source.enabled === false ? '停用' : '未知')), 1)]), _: 2 }, 1032, ["color"])
                                    ]),
                                    _createElementVNode("td", null, _toDisplayString(source.container_count || 0), 1),
                                    _createElementVNode("td", _hoisted_msg, _toDisplayString(source.message || '-'), 1)
                                  ]))
                                }), 128)),
                                !sourceStates.value.length ? (_openBlock(), _createElementBlock("tr", { key: 0 }, [_cache[7] || (_cache[7] = _createElementVNode("td", { colspan: "5", class: "text-medium-emphasis" }, "暂无源，请先进入配置页新增并保存 DC 源。", -1))])) : _createCommentVNode("", true)
                              ])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_v_col, { cols: "12", md: "5" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_card, { variant: "outlined" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_card_title, null, { default: _withCtx(() => [...(_cache[8] || (_cache[8] = [_createTextVNode("任务选择", -1)]))]), _: 1 }),
                          _createVNode(_component_v_card_text, null, {
                            default: _withCtx(() => [
                              _createElementVNode("div", _hoisted_hint, "更新通知容器"),
                              _createElementVNode("div", { class: "mb-4" }, [
                                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(state.updatablelist, (item) => {
                                  return (_openBlock(), _createBlock(_component_v_chip, { key: `notify-${item}`, color: "primary", variant: "tonal", class: "ma-1" }, { default: _withCtx(() => [_createTextVNode(_toDisplayString(item), 1)]), _: 2 }, 1024))
                                }), 128)),
                                !state.updatablelist?.length ? (_openBlock(), _createElementBlock("span", _hoisted_empty, "未选择")) : _createCommentVNode("", true)
                              ]),
                              _createElementVNode("div", _hoisted_hint2, "自动更新容器"),
                              _createElementVNode("div", null, [
                                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(state.autoupdatelist, (item) => {
                                  return (_openBlock(), _createBlock(_component_v_chip, { key: `auto-${item}`, color: "success", variant: "tonal", class: "ma-1" }, { default: _withCtx(() => [_createTextVNode(_toDisplayString(item), 1)]), _: 2 }, 1024))
                                }), 128)),
                                !state.autoupdatelist?.length ? (_openBlock(), _createElementBlock("span", _hoisted_empty2, "未选择")) : _createCommentVNode("", true)
                              ])
                            ]),
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
              }),
              _createVNode(_component_v_row, { class: "mt-2" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_col, { cols: "12" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_card, { variant: "outlined" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_card_title, null, { default: _withCtx(() => [...(_cache[9] || (_cache[9] = [_createTextVNode("容器列表", -1)]))]), _: 1 }),
                          _createVNode(_component_v_table, { density: "comfortable" }, {
                            default: _withCtx(() => [
                              _cache[10] || (_cache[10] = _createElementVNode("thead", null, [_createElementVNode("tr", null, [_createElementVNode("th", null, "源"), _createElementVNode("th", null, "容器"), _createElementVNode("th", null, "镜像"), _createElementVNode("th", null, "状态"), _createElementVNode("th", null, "可更新")])], -1)),
                              _createElementVNode("tbody", null, [
                                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(containers.value, (container) => {
                                  return (_openBlock(), _createElementBlock("tr", { key: container.key }, [
                                    _createElementVNode("td", null, _toDisplayString(container.source_name), 1),
                                    _createElementVNode("td", null, _toDisplayString(container.name), 1),
                                    _createElementVNode("td", _hoisted_image, _toDisplayString(container.usingImage || '-'), 1),
                                    _createElementVNode("td", null, _toDisplayString(container.status || '-'), 1),
                                    _createElementVNode("td", null, [
                                      _createVNode(_component_v_chip, { size: "small", color: container.haveUpdate ? 'primary' : 'grey', variant: "tonal" }, { default: _withCtx(() => [_createTextVNode(_toDisplayString(container.haveUpdate ? '是' : '否'), 1)]), _: 2 }, 1032, ["color"])
                                    ])
                                  ]))
                                }), 128)),
                                !containers.value.length ? (_openBlock(), _createElementBlock("tr", { key: 0 }, [_cache[11] || (_cache[11] = _createElementVNode("td", { colspan: "5", class: "text-medium-emphasis" }, "暂无容器。请确认源已保存、DC 地址包含正确端口、服务可访问且 secretKey 正确。", -1))])) : _createCommentVNode("", true)
                              ])
                            ]),
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
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }))
    }
  }
};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId', "data-v-02029310"]]);

export { Page as default };
