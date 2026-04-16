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

const authModeItems = [
  { title: "API Token", value: "api_token" },
  { title: "网页登录 Token", value: "web_token" }
];

const form = reactive({
  enabled: false,
  username: "",
  password: "",
  timeout: 20,
  max_results: 10,
  only_show_115: true,
  cd2_url: "",
  cd2_auth_mode: "api_token",
  cd2_token: "",
  cd2_web_token: "",
  cd2_default_root: "",
  cd2_pending_root: "",
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
  form.cd2_auth_mode = String(config.cd2_auth_mode || "api_token") === "web_token" ? "web_token" : "api_token";
  form.cd2_token = String(config.cd2_token || "");
  form.cd2_web_token = String(config.cd2_web_token || "");
  form.cd2_default_root = String(config.cd2_default_root || "");
  form.cd2_pending_root = String(config.cd2_pending_root || "");
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
    cd2_auth_mode: form.cd2_auth_mode,
    cd2_token: form.cd2_token.trim(),
    cd2_web_token: form.cd2_web_token.trim(),
    cd2_default_root: form.cd2_default_root.trim(),
    cd2_pending_root: form.cd2_pending_root.trim(),
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
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VTextarea = _resolveComponent("VTextarea");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createBlock(_component_VCard, null, {
    default: _withCtx(() => [
      _createVNode(_component_VCardTitle, null, {
        default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
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
            default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
              _createTextVNode(" 提交到 115 时会优先读取 MoviePilot 的“存储 & 目录”配置，再结合本插件的 MP 目录映射、分类映射和默认根目录，解析出最终 CD2 路径。 ", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VAlert, {
            type: "warning",
            variant: "tonal"
          }, {
            default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
              _createTextVNode(" 当前环境已验证：CD2 API Token 的“读写”不等于具备“离线下载”权限。如果真实提交报离线权限不足，请改用“网页登录 Token”模式。 ", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VAlert, {
            type: "warning",
            variant: "outlined"
          }, {
            default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
              _createTextVNode(" 配置“115 待整理目录”后，插件会先把资源统一提交到该目录；页面里选择的 MoviePilot 分类只作为后续整理入库意图，不再直接作为下载落点。 ", -1)
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
                    placeholder: "例如：https://cd2.example.com:5555"
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
                  _createVNode(_component_VSelect, {
                    modelValue: form.cd2_auth_mode,
                    "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((form.cd2_auth_mode) = $event)),
                    items: authModeItems,
                    "item-title": "title",
                    "item-value": "value",
                    label: "CD2 鉴权模式"
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
                    modelValue: form.cd2_detect_delay,
                    "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((form.cd2_detect_delay) = $event)),
                    label: "CD2 检测等待秒数",
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
                    modelValue: form.cd2_token,
                    "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((form.cd2_token) = $event)),
                    label: "CD2 API Token",
                    type: "password",
                    placeholder: "填写 API 令牌页里的 Token"
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
                    modelValue: form.cd2_web_token,
                    "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((form.cd2_web_token) = $event)),
                    label: "CD2 网页登录 Token",
                    type: "password",
                    placeholder: "填写浏览器 localStorage.token"
                  }, null, 8, ["modelValue"])
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VAlert, {
            type: "info",
            variant: "outlined"
          }, {
            default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
              _createTextVNode(" 网页登录 Token 的获取方式：先登录 CD2 网页，再在浏览器开发者工具里读取 `localStorage.token`。当前插件不会自动抓浏览器会话，需手动粘贴一次。 ", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VRow, null, {
            default: _withCtx(() => [
              _createVNode(_component_VCol, { cols: "12" }, {
                default: _withCtx(() => [
                  _createVNode(_component_VTextField, {
                    modelValue: form.cd2_default_root,
                    "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((form.cd2_default_root) = $event)),
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
                  _createVNode(_component_VTextField, {
                    modelValue: form.cd2_pending_root,
                    "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((form.cd2_pending_root) = $event)),
                    label: "115 待整理目录",
                    placeholder: "例如：/115open/待整理/Panlink115"
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
                    "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((form.cd2_directory_roots) = $event)),
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
                    "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((form.cd2_category_roots) = $event)),
                    label: "CD2 分类目录映射",
                    rows: "5",
                    "auto-grow": "",
                    placeholder: "每行一个映射，例如：\n电影/华语电影=/115open/媒体库/电影/华语电影\n剧集/国产剧=/115open/媒体库/剧集/国产剧\n*=/115open/媒体库"
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
            default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
              _createTextVNode("保存配置", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VBtn, {
            variant: "text",
            onClick: _cache[15] || (_cache[15] = $event => (emit('close')))
          }, {
            default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
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
