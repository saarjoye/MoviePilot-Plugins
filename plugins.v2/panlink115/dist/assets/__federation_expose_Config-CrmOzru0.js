import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const {reactive,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: {
    type: Object,
    default: () => ({})
  }
},
  emits: ["save", "close"],
  setup(__props, { emit: __emit }) {

const emit = __emit;

const props = __props;

const form = reactive({
  enabled: false,
  username: "",
  password: "",
  timeout: 20,
  max_results: 10,
  only_show_115: true,
  cd2_url: "",
  cd2_token: "",
  cd2_default_root: "",
  cd2_directory_roots: "",
  cd2_category_roots: "",
  cd2_detect_delay: 1.2
});

function applyConfig(config = {}) {
  form.enabled = Boolean(config.enabled);
  form.username = String(config.username || "");
  form.password = String(config.password || "");
  form.timeout = Number(config.timeout || 20);
  form.max_results = Number(config.max_results || 10);
  form.only_show_115 = config.only_show_115 !== false;
  form.cd2_url = String(config.cd2_url || "");
  form.cd2_token = String(config.cd2_token || "");
  form.cd2_default_root = String(config.cd2_default_root || "");
  form.cd2_directory_roots = String(config.cd2_directory_roots || "");
  form.cd2_category_roots = String(config.cd2_category_roots || "");
  form.cd2_detect_delay = Number(config.cd2_detect_delay || 1.2);
}

function saveConfig() {
  emit("save", {
    enabled: form.enabled,
    username: form.username.trim(),
    password: form.password,
    timeout: Number(form.timeout || 20),
    max_results: Number(form.max_results || 10),
    only_show_115: form.only_show_115,
    cd2_url: form.cd2_url.trim(),
    cd2_token: form.cd2_token.trim(),
    cd2_default_root: form.cd2_default_root.trim(),
    cd2_directory_roots: form.cd2_directory_roots,
    cd2_category_roots: form.cd2_category_roots,
    cd2_detect_delay: Number(form.cd2_detect_delay || 1.2)
  });
}

watch(
  () => props.initialConfig,
  (value) => applyConfig(value),
  { immediate: true, deep: true }
);

return (_ctx, _cache) => {
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VTextarea = _resolveComponent("VTextarea");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createBlock(_component_VCard, null, {
    default: _withCtx(() => [
      _createVNode(_component_VCardTitle, null, {
        default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
          _createTextVNode("盘链 115 搜索配置", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_VCardText, { class: "d-flex flex-column ga-4" }, {
        default: _withCtx(() => [
          _createVNode(_component_VAlert, {
            type: "info",
            variant: "tonal"
          }, {
            default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
              _createTextVNode(" 提交到 115 时会优先读取 MoviePilot 的“存储 & 目录”配置，先把所选分类解析成真实的媒体库存储与目录， 再按“CD2 MP目录映射”换算成 CD2 路径；只有无法换算时，才会回退到分类映射和默认根目录。 ", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VSwitch, {
                    modelValue: form.enabled,
                    "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((form.enabled) = $event)),
                    label: "启用插件"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VSwitch, {
                    modelValue: form.only_show_115,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((form.only_show_115) = $event)),
                    label: "仅展示 115 资源"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.username,
                    "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((form.username) = $event)),
                    label: "盘链账号",
                    placeholder: "填写盘链用户名"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.password,
                    "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((form.password) = $event)),
                    label: "盘链密码",
                    type: "password",
                    placeholder: "填写盘链密码"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.timeout,
                    "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((form.timeout) = $event)),
                    label: "请求超时秒数",
                    type: "number"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              }),
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.max_results,
                    "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((form.max_results) = $event)),
                    label: "搜索结果数量",
                    type: "number"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, { cols: "12" }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.cd2_url,
                    "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((form.cd2_url) = $event)),
                    label: "CD2 地址",
                    placeholder: "例如：https://cd2.example.com:19798"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, { cols: "12" }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.cd2_token,
                    "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((form.cd2_token) = $event)),
                    label: "CD2 API Token",
                    type: "password",
                    placeholder: "填写 CD2 的 API Token"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, { cols: "12" }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.cd2_default_root,
                    "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((form.cd2_default_root) = $event)),
                    label: "CD2 默认根目录",
                    placeholder: "例如：/115open/媒体库"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, { cols: "12" }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextarea, {
                    modelValue: form.cd2_directory_roots,
                    "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((form.cd2_directory_roots) = $event)),
                    label: "CD2 MP目录映射",
                    rows: "5",
                    "auto-grow": "",
                    placeholder: "每行一个映射，例如：\nlocal:D:/115挂载/媒体库=/115open/媒体库\nlocal:D:/115挂载/媒体库/电影=/115open/媒体库/电影"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, { cols: "12" }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextarea, {
                    modelValue: form.cd2_category_roots,
                    "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((form.cd2_category_roots) = $event)),
                    label: "CD2 分类目录映射",
                    rows: "5",
                    "auto-grow": "",
                    placeholder: "每行一个映射，例如：\n综艺节目=/115open/媒体库/综艺节目\n电视剧/国产剧=/115open/媒体库/剧集/国产剧\n*=/115open/媒体库"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, {
                cols: "12",
                md: "6"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.cd2_detect_delay,
                    "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((form.cd2_detect_delay) = $event)),
                    label: "CD2 检测等待秒数",
                    type: "number"
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
      _createVNode(_component_VCardActions, { class: "px-4 pb-4" }, {
        default: _withCtx(() => [
          _createVNode(_component_VBtn, {
            color: "primary",
            onClick: saveConfig
          }, {
            default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
              _createTextVNode("保存配置", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VBtn, {
            variant: "text",
            onClick: _cache[12] || (_cache[12] = $event => (emit('close')))
          }, {
            default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
              _createTextVNode("关闭", -1)
            ]))]),
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

export { _sfc_main as default };
