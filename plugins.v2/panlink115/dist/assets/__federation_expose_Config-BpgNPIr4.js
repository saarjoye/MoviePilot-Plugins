import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const {reactive,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: {
    type: Object,
    default: () => ({})
  },
  saving: {
    type: Boolean,
    default: false
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
  u115_cookie: ""
});

function applyConfig(config = {}) {
  form.enabled = Boolean(config.enabled);
  form.username = String(config.username || "");
  form.password = String(config.password || "");
  form.timeout = Number(config.timeout || 20);
  form.max_results = Number(config.max_results || 10);
  form.only_show_115 = config.only_show_115 !== false;
  form.u115_cookie = String(config.u115_cookie || "");
}

function saveConfig() {
  emit("save", {
    enabled: form.enabled,
    username: form.username.trim(),
    password: form.password,
    timeout: Number(form.timeout || 20),
    max_results: Number(form.max_results || 10),
    only_show_115: form.only_show_115,
    u115_cookie: form.u115_cookie.trim()
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

  return (_openBlock(), _createBlock(_component_VCard, { loading: __props.saving }, {
    default: _withCtx(() => [
      _createVNode(_component_VCardTitle, null, {
        default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
          _createTextVNode("盘链 115 插件配置", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_VCardText, { class: "d-flex flex-column ga-4" }, {
        default: _withCtx(() => [
          _createVNode(_component_VAlert, {
            type: "info",
            variant: "tonal"
          }, {
            default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
              _createTextVNode(" 插件已切换为直连 115 模式，不再依赖 CD2。目标目录会复用 MoviePilot 中已配置的 u115 存储路径。 ", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VAlert, {
            type: "warning",
            variant: "outlined"
          }, {
            default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
              _createTextVNode(" 分享转存使用 115 网页 Cookie 调用官方网页接口。MoviePilot 的 u115 OAuth 登录仍用于目录解析和目标目录创建。 ", -1)
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
                    label: "仅显示 115 资源"
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
                    label: "盘链账号"
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
                    type: "password"
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
          _createVNode(_component_VTextarea, {
            modelValue: form.u115_cookie,
            "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((form.u115_cookie) = $event)),
            label: "115 网页 Cookie",
            rows: "5",
            "auto-grow": "",
            placeholder: "粘贴已登录 115 网页后的完整 Cookie"
          }, null, 8, ["modelValue"])
        ]),
        _: 1
      }),
      _createVNode(_component_VCardActions, { class: "px-4 pb-4" }, {
        default: _withCtx(() => [
          _createVNode(_component_VBtn, {
            color: "primary",
            loading: __props.saving,
            disabled: __props.saving,
            onClick: saveConfig
          }, {
            default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
              _createTextVNode("保存配置", -1)
            ]))]),
            _: 1
          }, 8, ["loading", "disabled"]),
          _createVNode(_component_VBtn, {
            variant: "text",
            disabled: __props.saving,
            onClick: _cache[7] || (_cache[7] = $event => (emit('close')))
          }, {
            default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
              _createTextVNode("关闭", -1)
            ]))]),
            _: 1
          }, 8, ["disabled"])
        ]),
        _: 1
      })
    ]),
    _: 1
  }, 8, ["loading"]))
}
}

};

export { _sfc_main as default };
