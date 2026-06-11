import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,renderList:_renderList,Fragment:_Fragment,openBlock:_openBlock,createElementBlock:_createElementBlock,toDisplayString:_toDisplayString,normalizeClass:_normalizeClass,createElementVNode:_createElementVNode,createBlock:_createBlock,createCommentVNode:_createCommentVNode} = await importShared('vue');


const _hoisted_1 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_2 = { class: "text-truncate max-host" };
const _hoisted_3 = { key: 0 };
const _hoisted_4 = {
  key: 0,
  class: "text-medium-emphasis"
};

const {computed} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: {
  model: {
    type: Object,
    default: () => ({}),
  },
},
  emits: ['switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const sources = computed(() => Array.isArray(props.model?.sources) ? props.model.sources : []);
const enabledSources = computed(() => sources.value.filter(item => item.enabled !== false));
const selectedItems = computed(() => [
  ...(Array.isArray(props.model?.updatablelist) ? props.model.updatablelist : []),
  ...(Array.isArray(props.model?.autoupdatelist) ? props.model.autoupdatelist : []),
]);
const metrics = computed(() => [
  { label: '已配置源', value: sources.value.length, color: 'primary' },
  { label: '启用源', value: enabledSources.value.length, color: 'success' },
  { label: '通知容器', value: Array.isArray(props.model?.updatablelist) ? props.model.updatablelist.length : 0, color: 'primary' },
  { label: '自动更新', value: Array.isArray(props.model?.autoupdatelist) ? props.model.autoupdatelist.length : 0, color: 'success' },
]);

return (_ctx, _cache) => {
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_card_subtitle = _resolveComponent("v-card-subtitle");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_table = _resolveComponent("v-table");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_list_item = _resolveComponent("v-list-item");
  const _component_v_list = _resolveComponent("v-list");

  return (_openBlock(), _createBlock(_component_v_card, { flat: "" }, {
    default: _withCtx(() => [
      _createVNode(_component_v_card_item, null, {
        append: _withCtx(() => [
          _createVNode(_component_v_btn, {
            icon: "",
            color: "primary",
            variant: "text",
            onClick: _cache[0] || (_cache[0] = $event => (emit('switch')))
          }, {
            default: _withCtx(() => [
              _createVNode(_component_v_icon, null, {
                default: _withCtx(() => [...(_cache[3] || (_cache[3] = [
                  _createTextVNode("mdi-cog", -1)
                ]))]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        default: _withCtx(() => [
          _createVNode(_component_v_card_title, null, {
            default: _withCtx(() => [...(_cache[1] || (_cache[1] = [
              _createTextVNode("DC助手 · 执行与通知", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_v_card_subtitle, null, {
            default: _withCtx(() => [...(_cache[2] || (_cache[2] = [
              _createTextVNode("多源状态、任务范围与失败源处理", -1)
            ]))]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_v_card_text, null, {
        default: _withCtx(() => [
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
                            _createElementVNode("div", _hoisted_1, _toDisplayString(metric.label), 1)
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
              _createVNode(_component_v_col, {
                cols: "12",
                md: "7"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_card, { variant: "outlined" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_card_title, null, {
                        default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
                          _createTextVNode("DockerCopilot 源", -1)
                        ]))]),
                        _: 1
                      }),
                      _createVNode(_component_v_table, { density: "comfortable" }, {
                        default: _withCtx(() => [
                          _cache[6] || (_cache[6] = _createElementVNode("thead", null, [
                            _createElementVNode("tr", null, [
                              _createElementVNode("th", null, "源名称"),
                              _createElementVNode("th", null, "源ID"),
                              _createElementVNode("th", null, "状态"),
                              _createElementVNode("th", null, "地址")
                            ])
                          ], -1)),
                          _createElementVNode("tbody", null, [
                            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(sources.value, (source) => {
                              return (_openBlock(), _createElementBlock("tr", {
                                key: source.id
                              }, [
                                _createElementVNode("td", null, _toDisplayString(source.name || source.id), 1),
                                _createElementVNode("td", null, [
                                  _createElementVNode("code", null, _toDisplayString(source.id), 1)
                                ]),
                                _createElementVNode("td", null, [
                                  _createVNode(_component_v_chip, {
                                    size: "small",
                                    color: source.enabled === false ? 'grey' : 'success',
                                    variant: "tonal"
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(source.enabled === false ? '停用' : '启用'), 1)
                                    ]),
                                    _: 2
                                  }, 1032, ["color"])
                                ]),
                                _createElementVNode("td", _hoisted_2, _toDisplayString(source.host), 1)
                              ]))
                            }), 128)),
                            (!sources.value.length)
                              ? (_openBlock(), _createElementBlock("tr", _hoisted_3, [...(_cache[5] || (_cache[5] = [
                                  _createElementVNode("td", {
                                    colspan: "4",
                                    class: "text-medium-emphasis"
                                  }, "暂无源，请先进入配置页新增。", -1)
                                ]))]))
                              : _createCommentVNode("", true)
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
              _createVNode(_component_v_col, {
                cols: "12",
                md: "5"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_card, { variant: "outlined" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_card_title, null, {
                        default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                          _createTextVNode("通知预览", -1)
                        ]))]),
                        _: 1
                      }),
                      _createVNode(_component_v_card_text, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_alert, {
                            type: "info",
                            variant: "tonal"
                          }, {
                            default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                              _createTextVNode(" 【DC助手-更新通知】", -1),
                              _createElementVNode("br", null, null, -1),
                              _createTextVNode(" [源名称] 容器名 可更新", -1),
                              _createElementVNode("br", null, null, -1),
                              _createTextVNode(" 当前镜像：image:tag", -1),
                              _createElementVNode("br", null, null, -1),
                              _createTextVNode(" 说明：通知始终带源名称，避免排障混乱。 ", -1)
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
              })
            ]),
            _: 1
          }),
          _createVNode(_component_v_row, { class: "mt-2" }, {
            default: _withCtx(() => [
              _createVNode(_component_v_col, {
                cols: "12",
                md: "7"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_card, { variant: "outlined" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_card_title, null, {
                        default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                          _createTextVNode("选择摘要", -1)
                        ]))]),
                        _: 1
                      }),
                      _createVNode(_component_v_card_text, null, {
                        default: _withCtx(() => [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selectedItems.value, (item) => {
                            return (_openBlock(), _createBlock(_component_v_chip, {
                              key: item,
                              color: "primary",
                              variant: "tonal",
                              class: "ma-1"
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(item), 1)
                              ]),
                              _: 2
                            }, 1024))
                          }), 128)),
                          (!selectedItems.value.length)
                            ? (_openBlock(), _createElementBlock("div", _hoisted_4, "暂无已选容器。"))
                            : _createCommentVNode("", true)
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "5"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_card, { variant: "outlined" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_card_title, null, {
                        default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                          _createTextVNode("失败源处理", -1)
                        ]))]),
                        _: 1
                      }),
                      _createVNode(_component_v_list, { density: "compact" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_list_item, {
                            title: "重试策略",
                            subtitle: "本轮跳过，下一次调度继续重试"
                          }),
                          _createVNode(_component_v_list_item, {
                            title: "日志级别",
                            subtitle: "ERROR，不输出 secretKey 明文"
                          }),
                          _createVNode(_component_v_list_item, {
                            title: "通知策略",
                            subtitle: "备份和更新结果按源名汇总推送"
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
      })
    ]),
    _: 1
  }))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-02029310"]]);

export { Page as default };
