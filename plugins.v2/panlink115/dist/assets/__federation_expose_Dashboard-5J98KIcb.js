import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,createElementVNode:_createElementVNode,openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');



const _sfc_main = {
  __name: 'Dashboard',
  props: {
  api: {
    type: Object,
    default: () => ({})
  },
  initialConfig: {
    type: Object,
    default: () => ({})
  }
},
  setup(__props) {

const props = __props;

function statusText() {
  return props.initialConfig?.enabled ? "已启用" : "未启用";
}

function modeText() {
  return props.initialConfig?.only_show_115 === false ? "全部网盘" : "仅 115";
}

return (_ctx, _cache) => {
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");

  return (_openBlock(), _createBlock(_component_VCard, { variant: "tonal" }, {
    default: _withCtx(() => [
      _createVNode(_component_VCardTitle, null, {
        default: _withCtx(() => [...(_cache[0] || (_cache[0] = [
          _createTextVNode("盘链 115 搜索", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_VCardText, { class: "d-flex flex-column ga-2" }, {
        default: _withCtx(() => [
          _createElementVNode("div", null, "状态：" + _toDisplayString(statusText()), 1),
          _createElementVNode("div", null, "展示模式：" + _toDisplayString(modeText()), 1),
          _cache[1] || (_cache[1] = _createElementVNode("div", null, "说明：插件已切换为 Vue 页面，可直接在详情弹窗中手动搜索盘链资源。", -1))
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
