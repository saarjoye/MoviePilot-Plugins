import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "section-title d-flex flex-wrap align-center justify-space-between gap-2" };
const _hoisted_2 = { class: "text-body-2 text-medium-emphasis" };
const _hoisted_3 = { class: "d-flex align-center gap-2 mb-3" };

const {computed,reactive,ref,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const defaultConfig = {
  enabled: false,
  onlyonce: false,
  schedulereport: false,
  deleteimages: false,
  updatablenotify: false,
  autoupdatenotify: false,
  backupsnotify: false,
  updatecron: '',
  autoupdatecron: '',
  backupcron: '',
  interval: 10,
  intervallimit: 6,
  sources: [],
  updatablelist: [],
  autoupdatelist: [],
  backup_sources: [],
  container_items: [],
};

const config = reactive(cloneConfig(defaultConfig));
const error = ref('');
const saving = ref(false);
const visibleSecrets = reactive({});

const enabledSourceCount = computed(() => config.sources.filter(item => item.enabled !== false).length);
const sourceItems = computed(() => config.sources
  .filter(item => item.id)
  .map(item => ({ title: `${item.name || item.id} · ${item.id}`, value: item.id })));
const containerItems = computed(() => Array.isArray(config.container_items) ? config.container_items : []);

watch(
  () => props.initialConfig,
  value => applyInitialConfig(value || {}),
  { immediate: true, deep: true },
);

function cloneConfig(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function createKey() {
  return `source_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function normalizeSources(value) {
  if (Array.isArray(value))
    return value.map(normalizeSource).filter(item => item.id || item.host || item.secretKey)
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return normalizeSources(parsed)
    } catch {
      return []
    }
  }
  return []
}

function normalizeSource(source) {
  return {
    _key: source?._key || createKey(),
    id: String(source?.id || source?.name || '').trim(),
    name: String(source?.name || source?.id || '').trim(),
    host: String(source?.host || '').trim().replace(/\/+$/, ''),
    secretKey: String(source?.secretKey || source?.secret_key || '').trim(),
    enabled: source?.enabled !== false,
  }
}

function serializeSource(source) {
  const normalized = normalizeSource(source);
  return {
    id: normalized.id,
    name: normalized.name,
    host: normalized.host,
    secretKey: normalized.secretKey,
    enabled: normalized.enabled,
  }
}

function applyInitialConfig(initial) {
  Object.assign(config, cloneConfig(defaultConfig), cloneConfig(initial));
  config.sources = normalizeSources(initial.sources?.length ? initial.sources : initial.sources_text);
  if (!config.sources.length)
    config.sources = normalizeLegacySlots(initial);
  config.updatablelist = Array.isArray(initial.updatablelist) ? initial.updatablelist : [];
  config.autoupdatelist = Array.isArray(initial.autoupdatelist) ? initial.autoupdatelist : [];
  config.backup_sources = Array.isArray(initial.backup_sources) ? initial.backup_sources : [];
  config.container_items = Array.isArray(initial.container_items) ? initial.container_items : [];
  error.value = '';
}

function normalizeLegacySlots(initial) {
  const sources = [];
  for (let index = 1; index <= 100; index++) {
    const prefix = `source${index}`;
    if (!initial[`${prefix}_host`] && !initial[`${prefix}_secretKey`])
      continue
    sources.push(normalizeSource({
      id: initial[`${prefix}_id`],
      name: initial[`${prefix}_name`],
      host: initial[`${prefix}_host`],
      secretKey: initial[`${prefix}_secretKey`],
      enabled: initial[`${prefix}_enabled`],
    }));
  }
  if (!sources.length && initial.host && initial.secretKey) {
    sources.push(normalizeSource({
      id: 'default',
      name: '默认源',
      host: initial.host,
      secretKey: initial.secretKey,
      enabled: true,
    }));
  }
  return sources
}

function emptySource() {
  return { _key: createKey(), id: '', name: '', host: '', secretKey: '', enabled: true }
}

function addSource() {
  error.value = '';
  config.sources.push(emptySource());
}

function removeSource(index) {
  const source = config.sources[index];
  config.sources.splice(index, 1);
  if (source?._key)
    delete visibleSecrets[source._key];
  if (source?.id) {
    config.backup_sources = config.backup_sources.filter(item => item !== source.id);
    config.updatablelist = config.updatablelist.filter(item => !String(item).startsWith(`${source.id}::`));
    config.autoupdatelist = config.autoupdatelist.filter(item => !String(item).startsWith(`${source.id}::`));
  }
}

function toggleSecret(key) {
  visibleSecrets[key] = !visibleSecrets[key];
}

function resetConfig() {
  applyInitialConfig(props.initialConfig || {});
}

function validateSources(sources) {
  const ids = new Set();
  for (let index = 0; index < sources.length; index += 1) {
    const source = sources[index];
    const label = `DC 源设置 ${index + 1}`;
    if (!source.id)
      return `${label}：源ID不能为空`
    if (!/^[a-zA-Z0-9_-]+$/.test(source.id))
      return `${label}：源ID只能包含英文、数字、下划线或短横线`
    if (ids.has(source.id))
      return `${label}：源ID ${source.id} 已存在`
    ids.add(source.id);
    if (!source.name)
      return `${label}：显示名称不能为空`
    if (!/^https?:\/\//.test(source.host))
      return `${label}：服务地址必须以 http:// 或 https:// 开头`
    if (!source.secretKey)
      return `${label}：secretKey不能为空`
  }
  return ''
}

async function saveConfig() {
  saving.value = true;
  try {
    const payload = cloneConfig(config);
    payload.sources = config.sources.map(serializeSource);
    const validationError = validateSources(payload.sources);
    if (validationError) {
      error.value = validationError;
      return
    }
    payload.sources_text = JSON.stringify(payload.sources, null, 2);
    emit('save', payload);
  } finally {
    saving.value = false;
  }
}

return (_ctx, _cache) => {
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_card_subtitle = _resolveComponent("v-card-subtitle");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_actions = _resolveComponent("v-card-actions");

  return (_openBlock(), _createBlock(_component_v_card, {
    class: "dc-config",
    flat: ""
  }, {
    default: _withCtx(() => [
      _createVNode(_component_v_card_item, null, {
        append: _withCtx(() => [
          _createVNode(_component_v_btn, {
            icon: "",
            color: "primary",
            variant: "text",
            onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
          }, {
            default: _withCtx(() => [
              _createVNode(_component_v_icon, null, {
                default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                  _createTextVNode("mdi-close", -1)
                ]))]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        default: _withCtx(() => [
          _createVNode(_component_v_card_title, null, {
            default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
              _createTextVNode("DC助手 · 多 DockerCopilot 源", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_v_card_subtitle, null, {
            default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
              _createTextVNode("点击“新增源”后只新增 1 个 DC 源设置；支持任意数量，不再固定 5 个槽位。", -1)
            ]))]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_v_card_text, { class: "overflow-y-auto" }, {
        default: _withCtx(() => [
          _createVNode(_component_v_alert, {
            type: "warning",
            variant: "tonal",
            class: "mb-4"
          }, {
            default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
              _createTextVNode(" DC 地址与 secretKey 属于敏感配置；secretKey 仅保存到 MP 插件配置，页面摘要、通知和日志不显示明文。 ", -1)
            ]))]),
            _: 1
          }),
          _cache[27] || (_cache[27] = _createElementVNode("div", { class: "section-title" }, [
            _createElementVNode("div", { class: "text-h6 font-weight-bold" }, "基础开关"),
            _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "保存后定时任务按新配置生效")
          ], -1)),
          _createVNode(_component_v_row, null, {
            default: _withCtx(() => [
              _createVNode(_component_v_col, {
                cols: "12",
                sm: "6",
                md: "3"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_switch, {
                    modelValue: config.enabled,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.enabled) = $event)),
                    label: "启用插件",
                    color: "primary",
                    inset: ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                sm: "6",
                md: "3"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_switch, {
                    modelValue: config.onlyonce,
                    "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.onlyonce) = $event)),
                    label: "立即运行一次",
                    color: "primary",
                    inset: ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                sm: "6",
                md: "3"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_switch, {
                    modelValue: config.schedulereport,
                    "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.schedulereport) = $event)),
                    label: "进度汇报",
                    color: "primary",
                    inset: ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                sm: "6",
                md: "3"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_switch, {
                    modelValue: config.deleteimages,
                    "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.deleteimages) = $event)),
                    label: "镜像清理",
                    color: "primary",
                    inset: ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_v_row, null, {
            default: _withCtx(() => [
              _createVNode(_component_v_col, {
                cols: "12",
                md: "3"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_text_field, {
                    modelValue: config.interval,
                    "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.interval) = $event)),
                    label: "检查间隔（秒）",
                    variant: "outlined",
                    density: "comfortable"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "3"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_text_field, {
                    modelValue: config.intervallimit,
                    "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.intervallimit) = $event)),
                    label: "检查次数",
                    variant: "outlined",
                    density: "comfortable"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "3"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_text_field, {
                    modelValue: config.updatecron,
                    "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.updatecron) = $event)),
                    label: "更新通知 Cron",
                    variant: "outlined",
                    density: "comfortable",
                    placeholder: "15 8-23/2 * * *"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "3"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_text_field, {
                    modelValue: config.autoupdatecron,
                    "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.autoupdatecron) = $event)),
                    label: "自动更新 Cron",
                    variant: "outlined",
                    density: "comfortable",
                    placeholder: "15 2 * * *"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_v_row, null, {
            default: _withCtx(() => [
              _createVNode(_component_v_col, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_text_field, {
                    modelValue: config.backupcron,
                    "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.backupcron) = $event)),
                    label: "自动备份 Cron",
                    variant: "outlined",
                    density: "comfortable",
                    placeholder: "0 7 * * *"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_switch, {
                    modelValue: config.updatablenotify,
                    "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.updatablenotify) = $event)),
                    label: "更新通知开关",
                    color: "primary",
                    inset: ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "4"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_switch, {
                    modelValue: config.autoupdatenotify,
                    "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.autoupdatenotify) = $event)),
                    label: "自动更新通知",
                    color: "primary",
                    inset: ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createElementVNode("div", _hoisted_1, [
            _createElementVNode("div", null, [
              _cache[20] || (_cache[20] = _createElementVNode("div", { class: "text-h6 font-weight-bold" }, "DockerCopilot 源", -1)),
              _createElementVNode("div", _hoisted_2, "已配置 " + _toDisplayString(config.sources.length) + " 个源，启用 " + _toDisplayString(enabledSourceCount.value) + " 个", 1)
            ]),
            _createVNode(_component_v_btn, {
              color: "primary",
              "prepend-icon": "mdi-plus",
              onClick: addSource
            }, {
              default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                _createTextVNode("新增源", -1)
              ]))]),
              _: 1
            })
          ]),
          (!config.sources.length)
            ? (_openBlock(), _createBlock(_component_v_alert, {
                key: 0,
                type: "info",
                variant: "tonal",
                class: "mb-4"
              }, {
                default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                  _createTextVNode(" 暂无 DC 源。点击“新增源”后，页面会出现 1 个 DC 源设置卡片；继续点击可继续增加。 ", -1)
                ]))]),
                _: 1
              }))
            : _createCommentVNode("", true),
          (error.value)
            ? (_openBlock(), _createBlock(_component_v_alert, {
                key: 1,
                type: "error",
                variant: "tonal",
                class: "mb-4"
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(error.value), 1)
                ]),
                _: 1
              }))
            : _createCommentVNode("", true),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.sources, (source, index) => {
            return (_openBlock(), _createBlock(_component_v_card, {
              key: source._key || index,
              class: "source-card mb-4",
              variant: "outlined"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_card_item, null, {
                  append: _withCtx(() => [
                    _createVNode(_component_v_btn, {
                      icon: "",
                      variant: "text",
                      color: "error",
                      onClick: $event => (removeSource(index))
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_icon, null, {
                          default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                            _createTextVNode("mdi-delete-outline", -1)
                          ]))]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }, 8, ["onClick"])
                  ]),
                  default: _withCtx(() => [
                    _createVNode(_component_v_card_title, { class: "d-flex align-center gap-2" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_icon, { color: "primary" }, {
                          default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                            _createTextVNode("mdi-server-network", -1)
                          ]))]),
                          _: 1
                        }),
                        _createElementVNode("span", null, "DC 源设置 " + _toDisplayString(index + 1), 1),
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
                      _: 2
                    }, 1024)
                  ]),
                  _: 2
                }, 1024),
                _createVNode(_component_v_divider),
                _createVNode(_component_v_card_text, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_row, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_col, {
                          cols: "12",
                          md: "3"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_switch, {
                              modelValue: source.enabled,
                              "onUpdate:modelValue": $event => ((source.enabled) = $event),
                              label: "启用此源",
                              color: "primary",
                              inset: ""
                            }, null, 8, ["modelValue", "onUpdate:modelValue"])
                          ]),
                          _: 2
                        }, 1024),
                        _createVNode(_component_v_col, {
                          cols: "12",
                          md: "3"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_text_field, {
                              modelValue: source.id,
                              "onUpdate:modelValue": $event => ((source.id) = $event),
                              modelModifiers: { trim: true },
                              label: "源ID",
                              variant: "outlined",
                              density: "comfortable",
                              hint: "英文、数字、下划线、短横线",
                              "persistent-hint": ""
                            }, null, 8, ["modelValue", "onUpdate:modelValue"])
                          ]),
                          _: 2
                        }, 1024),
                        _createVNode(_component_v_col, {
                          cols: "12",
                          md: "3"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_text_field, {
                              modelValue: source.name,
                              "onUpdate:modelValue": $event => ((source.name) = $event),
                              modelModifiers: { trim: true },
                              label: "显示名称",
                              variant: "outlined",
                              density: "comfortable"
                            }, null, 8, ["modelValue", "onUpdate:modelValue"])
                          ]),
                          _: 2
                        }, 1024),
                        _createVNode(_component_v_col, {
                          cols: "12",
                          md: "3"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_text_field, {
                              modelValue: source.secretKey,
                              "onUpdate:modelValue": $event => ((source.secretKey) = $event),
                              label: "secretKey",
                              variant: "outlined",
                              density: "comfortable",
                              type: visibleSecrets[source._key] ? 'text' : 'password',
                              "append-inner-icon": visibleSecrets[source._key] ? 'mdi-eye-off' : 'mdi-eye',
                              "onClick:appendInner": $event => (toggleSecret(source._key))
                            }, null, 8, ["modelValue", "onUpdate:modelValue", "type", "append-inner-icon", "onClick:appendInner"])
                          ]),
                          _: 2
                        }, 1024),
                        _createVNode(_component_v_col, { cols: "12" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_text_field, {
                              modelValue: source.host,
                              "onUpdate:modelValue": $event => ((source.host) = $event),
                              modelModifiers: { trim: true },
                              label: "服务地址",
                              variant: "outlined",
                              density: "comfortable",
                              placeholder: "http://dc-lxc-01:12712",
                              hint: "必须以 http:// 或 https:// 开头，末尾不需要 /",
                              "persistent-hint": ""
                            }, null, 8, ["modelValue", "onUpdate:modelValue"])
                          ]),
                          _: 2
                        }, 1024)
                      ]),
                      _: 2
                    }, 1024)
                  ]),
                  _: 2
                }, 1024)
              ]),
              _: 2
            }, 1024))
          }), 128)),
          _createElementVNode("div", _hoisted_3, [
            _createVNode(_component_v_chip, {
              color: "primary",
              variant: "tonal"
            }, {
              default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                _createTextVNode("容器值：source_id::container_name", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_chip, {
              color: "success",
              variant: "tonal"
            }, {
              default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                _createTextVNode("防同名冲突", -1)
              ]))]),
              _: 1
            })
          ]),
          _cache[28] || (_cache[28] = _createElementVNode("div", { class: "section-title" }, [
            _createElementVNode("div", { class: "text-h6 font-weight-bold" }, "任务范围"),
            _createElementVNode("div", { class: "text-body-2 text-medium-emphasis" }, "保存后刷新页面，容器选项会按源名称 / 容器名加载")
          ], -1)),
          _createVNode(_component_v_row, null, {
            default: _withCtx(() => [
              _createVNode(_component_v_col, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_select, {
                    modelValue: config.updatablelist,
                    "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.updatablelist) = $event)),
                    label: "更新通知容器",
                    items: containerItems.value,
                    chips: "",
                    multiple: "",
                    variant: "outlined",
                    density: "comfortable",
                    hint: "选项保存为 source_id::container_name",
                    "persistent-hint": ""
                  }, null, 8, ["modelValue", "items"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_select, {
                    modelValue: config.autoupdatelist,
                    "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.autoupdatelist) = $event)),
                    label: "自动更新容器",
                    items: containerItems.value,
                    chips: "",
                    multiple: "",
                    variant: "outlined",
                    density: "comfortable",
                    hint: "只自动更新选中的容器",
                    "persistent-hint": ""
                  }, null, 8, ["modelValue", "items"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_select, {
                    modelValue: config.backup_sources,
                    "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((config.backup_sources) = $event)),
                    label: "自动备份源范围",
                    items: sourceItems.value,
                    chips: "",
                    multiple: "",
                    variant: "outlined",
                    density: "comfortable",
                    hint: "留空表示备份全部启用源",
                    "persistent-hint": ""
                  }, null, 8, ["modelValue", "items"])
                ]),
                _: 1
              }),
              _createVNode(_component_v_col, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_switch, {
                    modelValue: config.backupsnotify,
                    "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((config.backupsnotify) = $event)),
                    label: "备份结果通知",
                    color: "primary",
                    inset: ""
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_v_card_actions, null, {
        default: _withCtx(() => [
          _createVNode(_component_v_btn, {
            variant: "text",
            color: "secondary",
            onClick: resetConfig
          }, {
            default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
              _createTextVNode("重置", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_v_spacer),
          _createVNode(_component_v_btn, {
            color: "primary",
            "prepend-icon": "mdi-content-save",
            loading: saving.value,
            onClick: saveConfig
          }, {
            default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
              _createTextVNode("保存配置", -1)
            ]))]),
            _: 1
          }, 8, ["loading"])
        ]),
        _: 1
      })
    ]),
    _: 1
  }))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-6d2d907e"]]);

export { Config as default };
