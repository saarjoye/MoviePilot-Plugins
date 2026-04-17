import { importShared } from './__federation_fn_import-nbMRKTIW.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,vModelCheckbox:_vModelCheckbox,withDirectives:_withDirectives,createTextVNode:_createTextVNode,vModelText:_vModelText,toDisplayString:_toDisplayString,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,normalizeClass:_normalizeClass,vModelRadio:_vModelRadio} = await importShared('vue');


const _hoisted_1 = { class: "config-shell" };
const _hoisted_2 = { class: "config-header" };
const _hoisted_3 = { class: "config-actions" };
const _hoisted_4 = { class: "panel-card" };
const _hoisted_5 = { class: "field-grid field-grid--4" };
const _hoisted_6 = { class: "toggle-field" };
const _hoisted_7 = { class: "toggle-field" };
const _hoisted_8 = { class: "toggle-field" };
const _hoisted_9 = { class: "toggle-field" };
const _hoisted_10 = { class: "field-grid field-grid--4" };
const _hoisted_11 = { class: "form-field" };
const _hoisted_12 = { class: "form-field field-span-2" };
const _hoisted_13 = { class: "form-field" };
const _hoisted_14 = { class: "form-field" };
const _hoisted_15 = { class: "panel-card" };
const _hoisted_16 = { class: "field-grid field-grid--4" };
const _hoisted_17 = { class: "toggle-field" };
const _hoisted_18 = { class: "toggle-field" };
const _hoisted_19 = { class: "toggle-field" };
const _hoisted_20 = { class: "toggle-field" };
const _hoisted_21 = { class: "panel-card" };
const _hoisted_22 = { class: "rules-header" };
const _hoisted_23 = { class: "rules-header__actions" };
const _hoisted_24 = ["disabled"];
const _hoisted_25 = { class: "rule-overview" };
const _hoisted_26 = {
  key: 0,
  class: "browser-notice browser-notice--warning"
};
const _hoisted_27 = {
  key: 0,
  class: "action-detail-list"
};
const _hoisted_28 = { class: "rule-list" };
const _hoisted_29 = { class: "rule-card__header" };
const _hoisted_30 = { class: "rule-card__header-main" };
const _hoisted_31 = { class: "rule-card__title" };
const _hoisted_32 = { class: "rule-card__summary" };
const _hoisted_33 = { class: "rule-card__actions" };
const _hoisted_34 = { class: "inline-check" };
const _hoisted_35 = ["onUpdate:modelValue"];
const _hoisted_36 = ["onClick"];
const _hoisted_37 = { class: "field-grid field-grid--2" };
const _hoisted_38 = { class: "form-field field-span-2" };
const _hoisted_39 = ["onUpdate:modelValue"];
const _hoisted_40 = { class: "rule-block field-span-2" };
const _hoisted_41 = { class: "choice-grid" };
const _hoisted_42 = ["onUpdate:modelValue", "name", "value"];
const _hoisted_43 = { class: "rule-block" };
const _hoisted_44 = { class: "choice-grid" };
const _hoisted_45 = ["checked", "onChange"];
const _hoisted_46 = { class: "rule-block" };
const _hoisted_47 = { class: "choice-grid" };
const _hoisted_48 = ["checked", "onChange"];
const _hoisted_49 = { class: "rule-block" };
const _hoisted_50 = { class: "choice-grid" };
const _hoisted_51 = ["checked", "onChange"];
const _hoisted_52 = { class: "rule-block field-span-2" };
const _hoisted_53 = { class: "choice-grid" };
const _hoisted_54 = ["checked", "onChange"];
const _hoisted_55 = { class: "toggle-field" };
const _hoisted_56 = ["onUpdate:modelValue"];
const _hoisted_57 = { class: "form-field" };
const _hoisted_58 = ["onUpdate:modelValue"];
const _hoisted_59 = { class: "form-field" };
const _hoisted_60 = ["onUpdate:modelValue"];

const {computed,reactive,ref,watch} = await importShared('vue');



const _sfc_main = {
  __name: 'ConfigView',
  props: {
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
  api: {
    type: Object,
    required: true,
  },
},
  emits: ['save', 'switch', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const defaults = {
  enabled: true,
  push_enabled: true,
  auto_subscribe_enabled: false,
  auto_subscribe_notify: true,
  cache_ttl_minutes: 180,
  push_cron: '0 9,18 * * *',
  push_days: 7,
  push_limit: 8,
  enable_iqiyi: true,
  enable_tencent: true,
  enable_youku: true,
  enable_mgtv: true,
  enable_netflix: true,
  auto_subscribe_rules: '[]',
};

const TIME_OPTIONS = [
  { value: 'today', label: '今日上映' },
  { value: 'tomorrow', label: '明日上映' },
  { value: '3days', label: '3天内' },
  { value: '7days', label: '7天内' },
  { value: '30days', label: '30天内' },
  { value: 'pending', label: '敬请期待' },
  { value: 'all', label: '全部时间' },
];

const TYPE_OPTIONS = [
  { value: 'movie', label: '电影' },
  { value: 'tv', label: '电视剧' },
  { value: 'anime', label: '动漫' },
  { value: 'variety', label: '综艺' },
];

const PLATFORM_OPTIONS = [
  { value: 'iqiyi', label: '爱奇艺' },
  { value: 'tencent', label: '腾讯视频' },
  { value: 'youku', label: '优酷' },
  { value: 'mgtv', label: '芒果 TV' },
  { value: 'netflix', label: 'Netflix' },
];

const REGION_OPTIONS = [
  { value: '国产', label: '国产' },
  { value: '华语', label: '华语' },
  { value: '韩国', label: '韩国' },
  { value: '日本', label: '日本' },
  { value: '美国', label: '美国' },
  { value: '英国', label: '英国' },
  { value: '香港', label: '香港' },
  { value: '台湾', label: '台湾' },
];

const GENRE_OPTIONS = [
  { value: '喜剧', label: '喜剧' },
  { value: '剧情', label: '剧情' },
  { value: '爱情', label: '爱情' },
  { value: '伦理', label: '伦理' },
  { value: '家庭', label: '家庭' },
  { value: '悬疑', label: '悬疑' },
  { value: '犯罪', label: '犯罪' },
  { value: '动作', label: '动作' },
  { value: '动画', label: '动画' },
  { value: '科幻', label: '科幻' },
  { value: '奇幻', label: '奇幻' },
  { value: '古装', label: '古装' },
  { value: '真人秀', label: '真人秀' },
  { value: '脱口秀', label: '脱口秀' },
  { value: '音乐', label: '音乐' },
  { value: '冒险', label: '冒险' },
  { value: '武侠', label: '武侠' },
  { value: '少儿', label: '少儿' },
];

const config = reactive({ ...defaults, ...(props.initialConfig || {}) });
const rules = ref([]);
const ruleParseNotice = ref('');
const runLoading = ref(false);
const actionNotice = reactive({ type: 'info', text: '', details: [] });

let ruleSeed = 0;

function nextRuleId() {
  ruleSeed += 1;
  return `rule-${Date.now()}-${ruleSeed}`
}

function splitToList(value) {
  if (Array.isArray(value)) {
    return value
  }
  if (value === null || value === undefined) {
    return []
  }
  return String(value)
    .split(/[,，、|\n]+/)
    .map(item => item.trim())
    .filter(Boolean)
}

function normalizeTimeRange(value) {
  const rawValue = String(value || '').trim();
  if (!rawValue) {
    return ''
  }
  const lowerValue = rawValue.toLowerCase();
  const directMatch = TIME_OPTIONS.find(option => option.value === lowerValue);
  if (directMatch) {
    return directMatch.value
  }
  const labelMatch = TIME_OPTIONS.find(option => option.label === rawValue);
  return labelMatch?.value || ''
}

function inferTimeRange(rule) {
  const directTimeRange = normalizeTimeRange(rule?.time_range || rule?.window);
  if (directTimeRange) {
    return directTimeRange
  }
  const days = Number(rule?.days ?? rule?.window_days);
  if (!Number.isFinite(days)) {
    return rule?.include_pending ? 'pending' : '7days'
  }
  if (days <= 0) {
    return rule?.include_pending ? 'pending' : '7days'
  }
  if (days === 1) {
    return 'today'
  }
  if (days <= 3) {
    return '3days'
  }
  if (days <= 7) {
    return '7days'
  }
  if (days <= 30) {
    return '30days'
  }
  return 'all'
}

function normalizeOptionValues(values, options) {
  const allowedValues = new Set(options.map(option => option.value));
  return splitToList(values)
    .map(item => String(item || '').trim())
    .filter(item => item && item !== 'all' && allowedValues.has(item))
}

function createRule(raw = {}) {
  return {
    id: nextRuleId(),
    name: String(raw.name || '').trim(),
    enabled: raw.enabled !== false,
    time_range: inferTimeRange(raw),
    types: normalizeOptionValues(raw.types ?? raw.type ?? raw.mtype, TYPE_OPTIONS),
    platforms: normalizeOptionValues(raw.platforms ?? raw.platform, PLATFORM_OPTIONS),
    regions: normalizeOptionValues(raw.regions ?? raw.region ?? raw.countries, REGION_OPTIONS),
    genres: normalizeOptionValues(raw.genres ?? raw.genre ?? raw.tags, GENRE_OPTIONS),
    exclude_genres: normalizeOptionValues(raw.exclude_genres ?? raw.exclude_genre, GENRE_OPTIONS),
    include_pending: Boolean(raw.include_pending),
    keyword: String(raw.keyword || '').trim(),
    exclude_keyword: String(raw.exclude_keyword || raw.exclude || '').trim(),
  }
}

function parseRules(rawRules) {
  ruleParseNotice.value = '';
  if (Array.isArray(rawRules)) {
    const parsedRules = rawRules.filter(item => item && typeof item === 'object').map(item => createRule(item));
    return parsedRules.length ? parsedRules : [createRule()]
  }
  const textValue = String(rawRules || '').trim();
  if (!textValue) {
    return [createRule()]
  }
  try {
    const parsed = JSON.parse(textValue);
    if (!Array.isArray(parsed)) {
      ruleParseNotice.value = '检测到现有规则格式不是数组，已回退为空白条件，请确认后保存。';
      return [createRule()]
    }
    const parsedRules = parsed.filter(item => item && typeof item === 'object').map(item => createRule(item));
    return parsedRules.length ? parsedRules : [createRule()]
  } catch (error) {
    ruleParseNotice.value = '检测到现有自动订阅规则 JSON 无法解析，已回退为空白条件，请确认后保存。';
    return [createRule()]
  }
}

function applyInitialConfig(value) {
  Object.assign(config, defaults, value || {});
  rules.value = parseRules((value || {}).auto_subscribe_rules ?? defaults.auto_subscribe_rules);
}

watch(
  () => props.initialConfig,
  value => {
    applyInitialConfig(value);
  },
  { deep: true, immediate: true }
);

function getOptionLabel(options, value) {
  return options.find(option => option.value === value)?.label || ''
}

function getSelectedLabels(options, values) {
  const labels = values
    .map(value => getOptionLabel(options, value))
    .filter(Boolean);
  return labels
}

function buildRuleSummary(rule, index) {
  const parts = [];
  const typeLabels = getSelectedLabels(TYPE_OPTIONS, rule.types);
  const regionLabels = getSelectedLabels(REGION_OPTIONS, rule.regions);
  const genreLabels = getSelectedLabels(GENRE_OPTIONS, rule.genres);
  const platformLabels = getSelectedLabels(PLATFORM_OPTIONS, rule.platforms);
  const timeLabel = getOptionLabel(TIME_OPTIONS, rule.time_range) || '7天内';

  if (typeLabels.length) {
    parts.push(typeLabels.join('、'));
  }
  if (regionLabels.length) {
    parts.push(regionLabels.join('、'));
  }
  if (genreLabels.length) {
    parts.push(genreLabels.join('、'));
  }
  if (platformLabels.length) {
    parts.push(platformLabels.join('、'));
  }
  parts.push(timeLabel);

  if (rule.include_pending && rule.time_range !== 'pending') {
    parts.push('含未定档');
  }
  if (rule.keyword) {
    parts.push(`包含“${rule.keyword}”`);
  }
  if (rule.exclude_keyword) {
    parts.push(`排除“${rule.exclude_keyword}”`);
  }

  return `条件${index + 1}：${parts.join(' + ')}`
}

function isChecked(rule, field, value) {
  return Array.isArray(rule[field]) && rule[field].includes(value)
}

function toggleRuleValue(rule, field, value, checked) {
  const nextValues = new Set(rule[field] || []);
  if (checked) {
    nextValues.add(value);
  } else {
    nextValues.delete(value);
  }
  rule[field] = Array.from(nextValues);
}

function addRule() {
  rules.value.push(createRule());
}

function removeRule(ruleId) {
  if (rules.value.length === 1) {
    rules.value = [createRule()];
    return
  }
  rules.value = rules.value.filter(rule => rule.id !== ruleId);
}

function mapTimeRangeToDays(timeRange) {
  if (timeRange === 'today' || timeRange === 'tomorrow') {
    return 1
  }
  if (timeRange === '3days') {
    return 3
  }
  if (timeRange === '7days') {
    return 7
  }
  if (timeRange === '30days' || timeRange === 'pending' || timeRange === 'all') {
    return 30
  }
  return 7
}

function serializeRule(rule, index) {
  return {
    name: rule.name.trim() || buildRuleSummary(rule, index).replace(/^条件\d+：/, '').trim(),
    enabled: Boolean(rule.enabled),
    time_range: normalizeTimeRange(rule.time_range) || '7days',
    days: mapTimeRangeToDays(rule.time_range),
    types: rule.types.length ? [...rule.types] : ['all'],
    platforms: rule.platforms.length ? [...rule.platforms] : ['all'],
    regions: [...rule.regions],
    genres: [...rule.genres],
    exclude_genres: [...rule.exclude_genres],
    include_pending: Boolean(rule.include_pending),
    keyword: rule.keyword.trim(),
    exclude_keyword: rule.exclude_keyword.trim(),
  }
}

function normalizeApiError(error) {
  return (
    error?.response?.data?.detail ||
    error?.response?.data?.message ||
    error?.message ||
    '请求失败，请稍后重试。'
  )
}

function setActionNotice(type, text, details = []) {
  actionNotice.type = type || 'info';
  actionNotice.text = text || '';
  actionNotice.details = Array.isArray(details) ? details.filter(Boolean) : [];
}

function buildActionDetails(summary = {}) {
  return [
    ...(summary?.added || []).slice(0, 6).map(item => `新增：${item}`),
    ...(summary?.existing || []).slice(0, 4).map(item => `已存在：${item}`),
    ...(summary?.failed || []).slice(0, 4).map(item => `失败：${item}`),
  ]
}

async function runAutoSubscribeOnce() {
  runLoading.value = true;
  setActionNotice('info', '正在按最近一次已保存的规则执行自动订阅，请稍候...');
  try {
    const result = await props.api.get('plugin/UpcomingReleases/run_auto_subscribe_once');
    if (result?.success) {
      setActionNotice('success', result?.message || '执行完成。', buildActionDetails(result?.summary || {}));
    } else {
      setActionNotice('error', result?.message || '执行失败，请稍后重试。');
    }
  } catch (error) {
    setActionNotice('error', normalizeApiError(error));
  } finally {
    runLoading.value = false;
  }
}

function saveConfig() {
  const nextConfig = JSON.parse(JSON.stringify(config));
  nextConfig.auto_subscribe_rules = JSON.stringify(rules.value.map((rule, index) => serializeRule(rule, index)), null, 2);
  emit('save', nextConfig);
  setActionNotice('info', '配置已发送保存。若刚修改了规则，请保存完成后再点击“立即执行已保存规则”。');
}

const enabledRuleCount = computed(() => rules.value.filter(rule => rule.enabled).length);

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _cache[13] || (_cache[13] = _createElementVNode("div", null, [
        _createElementVNode("h1", { class: "config-title" }, "待播影视日历"),
        _createElementVNode("p", { class: "config-subtitle" }, "配置页只保留插件参数和自动订阅条件，近期预览继续放在插件详情页中查看。")
      ], -1)),
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("button", {
          type: "button",
          class: "ghost-button",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        }, "关闭"),
        _createElementVNode("button", {
          type: "button",
          class: "primary-button",
          onClick: saveConfig
        }, "保存配置")
      ])
    ]),
    _createElementVNode("section", _hoisted_4, [
      _cache[22] || (_cache[22] = _createElementVNode("div", { class: "panel-title" }, "基础设置", -1)),
      _createElementVNode("div", _hoisted_5, [
        _createElementVNode("label", _hoisted_6, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.enabled) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.enabled]
          ]),
          _cache[14] || (_cache[14] = _createTextVNode(" 启用插件", -1))
        ]),
        _createElementVNode("label", _hoisted_7, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.push_enabled) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.push_enabled]
          ]),
          _cache[15] || (_cache[15] = _createTextVNode(" 启用信息推送", -1))
        ]),
        _createElementVNode("label", _hoisted_8, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.auto_subscribe_enabled) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.auto_subscribe_enabled]
          ]),
          _cache[16] || (_cache[16] = _createTextVNode(" 启用自动订阅", -1))
        ]),
        _createElementVNode("label", _hoisted_9, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.auto_subscribe_notify) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.auto_subscribe_notify]
          ]),
          _cache[17] || (_cache[17] = _createTextVNode(" 订阅结果通知", -1))
        ])
      ]),
      _createElementVNode("div", _hoisted_10, [
        _createElementVNode("label", _hoisted_11, [
          _cache[18] || (_cache[18] = _createElementVNode("span", null, "缓存分钟数", -1)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.cache_ttl_minutes) = $event)),
            type: "number",
            min: "5"
          }, null, 512), [
            [_vModelText, config.cache_ttl_minutes]
          ])
        ]),
        _createElementVNode("label", _hoisted_12, [
          _cache[19] || (_cache[19] = _createElementVNode("span", null, "同步 / 推送 Cron", -1)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.push_cron) = $event)),
            type: "text",
            placeholder: "0 9,18 * * *"
          }, null, 512), [
            [_vModelText, config.push_cron]
          ])
        ]),
        _createElementVNode("label", _hoisted_13, [
          _cache[20] || (_cache[20] = _createElementVNode("span", null, "推送窗口天数", -1)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.push_days) = $event)),
            type: "number",
            min: "1"
          }, null, 512), [
            [_vModelText, config.push_days]
          ])
        ]),
        _createElementVNode("label", _hoisted_14, [
          _cache[21] || (_cache[21] = _createElementVNode("span", null, "推送上限", -1)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.push_limit) = $event)),
            type: "number",
            min: "1"
          }, null, 512), [
            [_vModelText, config.push_limit]
          ])
        ])
      ])
    ]),
    _createElementVNode("section", _hoisted_15, [
      _cache[27] || (_cache[27] = _createElementVNode("div", { class: "panel-title" }, "平台抓取开关", -1)),
      _createElementVNode("div", _hoisted_16, [
        _createElementVNode("label", _hoisted_17, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.enable_iqiyi) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.enable_iqiyi]
          ]),
          _cache[23] || (_cache[23] = _createTextVNode(" 爱奇艺", -1))
        ]),
        _createElementVNode("label", _hoisted_18, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.enable_tencent) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.enable_tencent]
          ]),
          _cache[24] || (_cache[24] = _createTextVNode(" 腾讯视频", -1))
        ]),
        _createElementVNode("label", _hoisted_19, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.enable_youku) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.enable_youku]
          ]),
          _cache[25] || (_cache[25] = _createTextVNode(" 优酷", -1))
        ]),
        _createElementVNode("label", _hoisted_20, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.enable_mgtv) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.enable_mgtv]
          ]),
          _cache[26] || (_cache[26] = _createTextVNode(" 芒果 TV", -1))
        ]),
        _createElementVNode("label", { class: "toggle-field" }, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.enable_netflix) = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, config.enable_netflix]
          ]),
          _createTextVNode(" Netflix")
        ])
      ])
    ]),
    _createElementVNode("section", _hoisted_21, [
      _createElementVNode("div", _hoisted_22, [
        _cache[28] || (_cache[28] = _createElementVNode("div", null, [
          _createElementVNode("div", { class: "panel-title" }, "自动订阅规则"),
          _createElementVNode("p", { class: "panel-subtitle" }, "按条件勾选即可，不再手写 JSON。每条条件会独立执行，例如“电影 + 国产 + 喜剧 + 今日上映”。如需测试，请先保存配置，再点击“立即执行已保存规则”。")
        ], -1)),
        _createElementVNode("div", _hoisted_23, [
          _createElementVNode("button", {
            type: "button",
            class: "ghost-button ghost-button--accent",
            disabled: runLoading.value,
            onClick: runAutoSubscribeOnce
          }, _toDisplayString(runLoading.value ? '执行中...' : '立即执行已保存规则'), 9, _hoisted_24),
          _createElementVNode("button", {
            type: "button",
            class: "primary-button",
            onClick: addRule
          }, "新增条件")
        ])
      ]),
      _createElementVNode("div", _hoisted_25, [
        _createElementVNode("span", null, "当前共 " + _toDisplayString(rules.value.length) + " 条规则", 1),
        _createElementVNode("span", null, "已启用 " + _toDisplayString(enabledRuleCount.value) + " 条", 1),
        _cache[29] || (_cache[29] = _createElementVNode("span", null, "不勾选的平台、类型、地区、题材表示“不限”", -1))
      ]),
      (ruleParseNotice.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_26, _toDisplayString(ruleParseNotice.value), 1))
        : _createCommentVNode("", true),
      (actionNotice.text)
        ? (_openBlock(), _createElementBlock("div", {
            key: 1,
            class: _normalizeClass(["browser-notice", `browser-notice--${actionNotice.type}`])
          }, [
            _createElementVNode("div", null, _toDisplayString(actionNotice.text), 1),
            (actionNotice.details.length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_27, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(actionNotice.details, (detail, detailIndex) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: `action-detail-${detailIndex}`
                    }, _toDisplayString(detail), 1))
                  }), 128))
                ]))
              : _createCommentVNode("", true)
          ], 2))
        : _createCommentVNode("", true),
      _createElementVNode("div", _hoisted_28, [
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(rules.value, (rule, index) => {
          return (_openBlock(), _createElementBlock("article", {
            key: rule.id,
            class: "rule-card"
          }, [
            _createElementVNode("div", _hoisted_29, [
              _createElementVNode("div", _hoisted_30, [
                _createElementVNode("h3", _hoisted_31, "条件 " + _toDisplayString(index + 1), 1),
                _createElementVNode("p", _hoisted_32, _toDisplayString(buildRuleSummary(rule, index)), 1)
              ]),
              _createElementVNode("div", _hoisted_33, [
                _createElementVNode("label", _hoisted_34, [
                  _withDirectives(_createElementVNode("input", {
                    "onUpdate:modelValue": $event => ((rule.enabled) = $event),
                    type: "checkbox"
                  }, null, 8, _hoisted_35), [
                    [_vModelCheckbox, rule.enabled]
                  ]),
                  _cache[30] || (_cache[30] = _createElementVNode("span", null, "启用", -1))
                ]),
                _createElementVNode("button", {
                  type: "button",
                  class: "ghost-button ghost-button--danger",
                  onClick: $event => (removeRule(rule.id))
                }, "删除", 8, _hoisted_36)
              ])
            ]),
            _createElementVNode("div", _hoisted_37, [
              _createElementVNode("label", _hoisted_38, [
                _cache[31] || (_cache[31] = _createElementVNode("span", null, "规则名称", -1)),
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": $event => ((rule.name) = $event),
                  type: "text",
                  placeholder: "留空时自动按组合条件生成名称"
                }, null, 8, _hoisted_39), [
                  [_vModelText, rule.name]
                ])
              ]),
              _createElementVNode("section", _hoisted_40, [
                _cache[32] || (_cache[32] = _createElementVNode("div", { class: "rule-block__title" }, "时间条件", -1)),
                _createElementVNode("div", _hoisted_41, [
                  (_openBlock(), _createElementBlock(_Fragment, null, _renderList(TIME_OPTIONS, (option) => {
                    return _createElementVNode("label", {
                      key: `time-${rule.id}-${option.value}`,
                      class: _normalizeClass(["choice-option choice-option--radio", { 'choice-option--active': rule.time_range === option.value }])
                    }, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": $event => ((rule.time_range) = $event),
                        name: `time-${rule.id}`,
                        type: "radio",
                        value: option.value
                      }, null, 8, _hoisted_42), [
                        [_vModelRadio, rule.time_range]
                      ]),
                      _createElementVNode("span", null, _toDisplayString(option.label), 1)
                    ], 2)
                  }), 64))
                ])
              ]),
              _createElementVNode("section", _hoisted_43, [
                _cache[33] || (_cache[33] = _createElementVNode("div", { class: "rule-block__title" }, "影视类型", -1)),
                _createElementVNode("div", _hoisted_44, [
                  (_openBlock(), _createElementBlock(_Fragment, null, _renderList(TYPE_OPTIONS, (option) => {
                    return _createElementVNode("label", {
                      key: `type-${rule.id}-${option.value}`,
                      class: _normalizeClass(["choice-option", { 'choice-option--active': isChecked(rule, 'types', option.value) }])
                    }, [
                      _createElementVNode("input", {
                        type: "checkbox",
                        checked: isChecked(rule, 'types', option.value),
                        onChange: $event => (toggleRuleValue(rule, 'types', option.value, $event.target.checked))
                      }, null, 40, _hoisted_45),
                      _createElementVNode("span", null, _toDisplayString(option.label), 1)
                    ], 2)
                  }), 64))
                ]),
                _cache[34] || (_cache[34] = _createElementVNode("div", { class: "rule-tip" }, "不勾选表示不限类型", -1))
              ]),
              _createElementVNode("section", _hoisted_46, [
                _cache[35] || (_cache[35] = _createElementVNode("div", { class: "rule-block__title" }, "平台", -1)),
                _createElementVNode("div", _hoisted_47, [
                  (_openBlock(), _createElementBlock(_Fragment, null, _renderList(PLATFORM_OPTIONS, (option) => {
                    return _createElementVNode("label", {
                      key: `platform-${rule.id}-${option.value}`,
                      class: _normalizeClass(["choice-option", { 'choice-option--active': isChecked(rule, 'platforms', option.value) }])
                    }, [
                      _createElementVNode("input", {
                        type: "checkbox",
                        checked: isChecked(rule, 'platforms', option.value),
                        onChange: $event => (toggleRuleValue(rule, 'platforms', option.value, $event.target.checked))
                      }, null, 40, _hoisted_48),
                      _createElementVNode("span", null, _toDisplayString(option.label), 1)
                    ], 2)
                  }), 64))
                ]),
                _cache[36] || (_cache[36] = _createElementVNode("div", { class: "rule-tip" }, "不勾选表示全平台", -1))
              ]),
              _createElementVNode("section", _hoisted_49, [
                _cache[37] || (_cache[37] = _createElementVNode("div", { class: "rule-block__title" }, "地区", -1)),
                _createElementVNode("div", _hoisted_50, [
                  (_openBlock(), _createElementBlock(_Fragment, null, _renderList(REGION_OPTIONS, (option) => {
                    return _createElementVNode("label", {
                      key: `region-${rule.id}-${option.value}`,
                      class: _normalizeClass(["choice-option", { 'choice-option--active': isChecked(rule, 'regions', option.value) }])
                    }, [
                      _createElementVNode("input", {
                        type: "checkbox",
                        checked: isChecked(rule, 'regions', option.value),
                        onChange: $event => (toggleRuleValue(rule, 'regions', option.value, $event.target.checked))
                      }, null, 40, _hoisted_51),
                      _createElementVNode("span", null, _toDisplayString(option.label), 1)
                    ], 2)
                  }), 64))
                ]),
                _cache[38] || (_cache[38] = _createElementVNode("div", { class: "rule-tip" }, "不勾选表示不限地区", -1))
              ]),
              _createElementVNode("section", _hoisted_52, [
                _cache[39] || (_cache[39] = _createElementVNode("div", { class: "rule-block__title" }, "题材", -1)),
                _createElementVNode("div", _hoisted_53, [
                  (_openBlock(), _createElementBlock(_Fragment, null, _renderList(GENRE_OPTIONS, (option) => {
                    return _createElementVNode("label", {
                      key: `genre-${rule.id}-${option.value}`,
                      class: _normalizeClass(["choice-option", { 'choice-option--active': isChecked(rule, 'genres', option.value) }])
                    }, [
                      _createElementVNode("input", {
                        type: "checkbox",
                        checked: isChecked(rule, 'genres', option.value),
                        onChange: $event => (toggleRuleValue(rule, 'genres', option.value, $event.target.checked))
                      }, null, 40, _hoisted_54),
                      _createElementVNode("span", null, _toDisplayString(option.label), 1)
                    ], 2)
                  }), 64))
                ]),
                _cache[40] || (_cache[40] = _createElementVNode("div", { class: "rule-tip" }, "不勾选表示不限题材", -1))
              ]),
              _createElementVNode("label", _hoisted_55, [
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": $event => ((rule.include_pending) = $event),
                  type: "checkbox"
                }, null, 8, _hoisted_56), [
                  [_vModelCheckbox, rule.include_pending]
                ]),
                _cache[41] || (_cache[41] = _createTextVNode(" 同时包含未定档内容 ", -1))
              ]),
              _createElementVNode("label", _hoisted_57, [
                _cache[42] || (_cache[42] = _createElementVNode("span", null, "关键词包含", -1)),
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": $event => ((rule.keyword) = $event),
                  type: "text",
                  placeholder: "可选，例如：重生"
                }, null, 8, _hoisted_58), [
                  [_vModelText, rule.keyword]
                ])
              ]),
              _createElementVNode("label", _hoisted_59, [
                _cache[43] || (_cache[43] = _createElementVNode("span", null, "排除关键词", -1)),
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": $event => ((rule.exclude_keyword) = $event),
                  type: "text",
                  placeholder: "可选，例如：花絮"
                }, null, 8, _hoisted_60), [
                  [_vModelText, rule.exclude_keyword]
                ])
              ])
            ])
          ]))
        }), 128))
      ])
    ])
  ]))
}
}

};
const ConfigView = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-559ded42"]]);

export { ConfigView as default };
