import { importShared } from './__federation_fn_import-nbMRKTIW.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {reactive,ref: ref$1} = await importShared('vue');


const PLUGIN_API_BASE = 'plugin/UpcomingReleases';

function createDefaultFilters() {
  return {
    platform: 'all',
    mtype: 'all',
    time_range: 'all',
    region: 'all',
    genre: 'all',
  }
}

function createEmptyState() {
  return {
    filters: createDefaultFilters(),
    options: {
      platforms: [],
      types: [],
      times: [],
      regions: [],
      genres: [],
      rule_types: [],
      rule_platforms: [],
      rule_regions: [],
      rule_genres: [],
    },
    stats: {
      total: 0,
      matched: 0,
      showing: 0,
      last_refresh: '未同步',
      platform_counts: [],
      type_counts: [],
    },
    items: [],
  }
}

function normalizeError(error) {
  return (
    error?.response?.data?.detail ||
    error?.response?.data?.message ||
    error?.message ||
    '请求失败，请稍后重试。'
  )
}

function cloneConfig(config) {
  return JSON.parse(JSON.stringify(config || {}))
}

function useUpcomingBrowser(api, options = {}) {
  const state = ref$1(createEmptyState());
  const filters = reactive(createDefaultFilters());
  const loading = ref$1(false);
  const busyMediaId = ref$1('');
  const notice = reactive({ type: 'info', text: '' });
  const limit = options.limit || 24;

  function setNotice(type, text) {
    notice.type = type || 'info';
    notice.text = text || '';
  }

  async function load(forceRefresh = false) {
    loading.value = true;
    try {
      const result = await api.get(`${PLUGIN_API_BASE}/config_state`, {
        params: {
          ...cloneConfig(filters),
          limit,
          force_refresh: forceRefresh ? 1 : 0,
        },
      });
      state.value = {
        ...createEmptyState(),
        ...(result || {}),
      };
      Object.assign(filters, state.value.filters || createDefaultFilters());
      if (result?.message) {
        setNotice(result?.success === false ? 'error' : 'info', result.message);
      } else {
        setNotice('info', '');
      }
    } catch (error) {
      setNotice('error', normalizeError(error));
    } finally {
      loading.value = false;
    }
  }

  async function refresh() {
    loading.value = true;
    try {
      const result = await api.get(`${PLUGIN_API_BASE}/page_refresh`);
      setNotice('success', `已同步最新待播数据，共 ${result?.count || 0} 条。`);
      await load(true);
    } catch (error) {
      setNotice('error', normalizeError(error));
      loading.value = false;
    }
  }

  async function subscribe(mediaId) {
    if (!mediaId) {
      return
    }
    busyMediaId.value = mediaId;
    try {
      const result = await api.get(`${PLUGIN_API_BASE}/page_subscribe`, {
        params: {
          media_id: mediaId,
        },
      });
      if (result?.success) {
        const messageMap = {
          exists: { type: 'info', text: '该影视已在订阅列表中。' },
          completed: { type: 'info', text: '该影视已在订阅历史中，资源已处理完成。' },
          claimed: { type: 'success', text: '已同步订阅状态。' },
        };
        const feedback = messageMap[result?.message] || { type: 'success', text: '已添加到订阅列表。' };
        setNotice(feedback.type, feedback.text);
      } else {
        setNotice('error', result?.message || '订阅失败，请稍后重试。');
      }
      await load(false);
    } catch (error) {
      setNotice('error', normalizeError(error));
    } finally {
      busyMediaId.value = '';
    }
  }

  async function setFilter(field, value) {
    filters[field] = value;
    await load(false);
  }

  async function resetFilters() {
    Object.assign(filters, createDefaultFilters());
    await load(false);
  }

  return {
    state,
    filters,
    loading,
    busyMediaId,
    notice,
    load,
    refresh,
    subscribe,
    setFilter,
    resetFilters,
  }
}

const {toDisplayString:_toDisplayString,createElementVNode:_createElementVNode$1,openBlock:_openBlock$1,createElementBlock:_createElementBlock$1,createCommentVNode:_createCommentVNode$1,unref:_unref,normalizeClass:_normalizeClass,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1$1 = { class: "browser-shell" };
const _hoisted_2$1 = { class: "browser-toolbar" };
const _hoisted_3$1 = { class: "browser-title" };
const _hoisted_4 = {
  key: 0,
  class: "browser-subtitle"
};
const _hoisted_5 = { class: "browser-actions" };
const _hoisted_6 = ["disabled"];
const _hoisted_7 = ["disabled"];
const _hoisted_8 = { class: "browser-summary" };
const _hoisted_9 = { class: "filter-layout" };
const _hoisted_10 = { class: "filter-grid" };
const _hoisted_11 = { class: "filter-label" };
const _hoisted_12 = { class: "filter-chip-wrap" };
const _hoisted_13 = ["disabled", "onClick"];
const _hoisted_14 = { class: "filter-rail" };
const _hoisted_15 = { class: "filter-rail__body" };
const _hoisted_16 = { class: "filter-chip-wrap filter-chip-wrap--rail" };
const _hoisted_17 = ["disabled", "onClick"];
const _hoisted_18 = ["disabled"];
const _hoisted_19 = {
  key: 1,
  class: "count-grid"
};
const _hoisted_20 = { class: "count-card" };
const _hoisted_21 = { class: "count-chip-wrap" };
const _hoisted_22 = { class: "count-card" };
const _hoisted_23 = { class: "count-chip-wrap" };
const _hoisted_24 = {
  key: 2,
  class: "browser-empty"
};
const _hoisted_25 = {
  key: 3,
  class: "browser-empty"
};
const _hoisted_26 = {
  key: 4,
  class: "media-grid"
};
const _hoisted_27 = { class: "media-poster" };
const _hoisted_28 = ["src", "alt"];
const _hoisted_29 = {
  key: 1,
  class: "media-poster__fallback"
};
const _hoisted_30 = { class: "media-body" };
const _hoisted_31 = { class: "media-tags" };
const _hoisted_32 = { class: "media-tag media-tag--type" };
const _hoisted_33 = {
  key: 1,
  class: "media-tag media-tag--time"
};
const _hoisted_34 = {
  key: 2,
  class: "media-tag media-tag--count"
};
const _hoisted_35 = { class: "media-title" };
const _hoisted_36 = { class: "media-meta" };
const _hoisted_37 = { class: "media-meta" };
const _hoisted_38 = { class: "media-meta" };
const _hoisted_39 = {
  key: 0,
  class: "media-story"
};
const _hoisted_40 = { class: "media-actions" };
const _hoisted_41 = ["disabled", "onClick"];
const _hoisted_42 = ["href"];

const {computed,onMounted,ref,watch} = await importShared('vue');

const genreCollapseThreshold = 18;

const _sfc_main$1 = {
  __name: 'UpcomingBrowserPanel',
  props: {
  api: {
    type: Object,
    required: true,
  },
  title: {
    type: String,
    default: '近期预览',
  },
  subtitle: {
    type: String,
    default: '',
  },
  showSwitch: {
    type: Boolean,
    default: false,
  },
},
  emits: ['switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const {
  state,
  filters,
  loading,
  busyMediaId,
  notice,
  load,
  refresh,
  subscribe,
  setFilter,
  resetFilters,
} = useUpcomingBrowser(props.api, {
  limit: 24,
});

const showAllGenres = ref(false);

const primaryFilterGroups = computed(() => [
  { field: 'platform', label: '平台', options: state.value.options.platforms || [] },
  { field: 'mtype', label: '类型', options: state.value.options.types || [] },
  { field: 'time_range', label: '时间', options: state.value.options.times || [] },
  { field: 'region', label: '地区', options: state.value.options.regions || [] },
]);

const genreOptions = computed(() => state.value.options.genres || []);

const visibleGenreOptions = computed(() => {
  if (showAllGenres.value || genreOptions.value.length <= genreCollapseThreshold) {
    return genreOptions.value
  }

  const baseOptions = genreOptions.value.slice(0, genreCollapseThreshold);
  if (!filters.genre || filters.genre === 'all') {
    return baseOptions
  }

  const selectedOption = genreOptions.value.find(option => option.value === filters.genre);
  if (!selectedOption || baseOptions.some(option => option.value === selectedOption.value)) {
    return baseOptions
  }

  return [...baseOptions.slice(0, genreCollapseThreshold - 1), selectedOption]
});

const canToggleGenres = computed(() => genreOptions.value.length > genreCollapseThreshold);
const genreToggleText = computed(() => (showAllGenres.value ? '收起' : '更多'));

const platformCounts = computed(() => (state.value.stats.platform_counts || []).filter(item => item.count > 0));
const typeCounts = computed(() => (state.value.stats.type_counts || []).filter(item => item.count > 0));

function getPlatformLabels(item) {
  const labels = Array.isArray(item?.platform_labels) ? item.platform_labels.filter(Boolean) : [];
  if (labels.length) {
    return labels
  }
  return item?.platform_label ? [item.platform_label] : []
}

function getSubscriptionTag(item) {
  if (item?.subscription_status === 'history') {
    return { label: '\u5df2\u5b8c\u6210', className: 'media-tag--completed' }
  }
  if (item?.subscription_status === 'active') {
    return { label: '\u5df2\u8ba2\u9605', className: 'media-tag--subscribed' }
  }
  return null
}

watch(
  () => filters.genre,
  value => {
    if (value && value !== 'all' && !visibleGenreOptions.value.some(option => option.value === value)) {
      showAllGenres.value = true;
    }
  }
);

onMounted(() => {
  load(false);
});

return (_ctx, _cache) => {
  return (_openBlock$1(), _createElementBlock$1("section", _hoisted_1$1, [
    _createElementVNode$1("header", _hoisted_2$1, [
      _createElementVNode$1("div", null, [
        _createElementVNode$1("h2", _hoisted_3$1, _toDisplayString(__props.title), 1),
        (__props.subtitle)
          ? (_openBlock$1(), _createElementBlock$1("p", _hoisted_4, _toDisplayString(__props.subtitle), 1))
          : _createCommentVNode$1("", true)
      ]),
      _createElementVNode$1("div", _hoisted_5, [
        _createElementVNode$1("button", {
          type: "button",
          class: "ghost-button",
          disabled: _unref(loading),
          onClick: _cache[0] || (_cache[0] = (...args) => (_unref(resetFilters) && _unref(resetFilters)(...args)))
        }, "重置筛选", 8, _hoisted_6),
        _createElementVNode$1("button", {
          type: "button",
          class: "ghost-button",
          disabled: _unref(loading),
          onClick: _cache[1] || (_cache[1] = (...args) => (_unref(refresh) && _unref(refresh)(...args)))
        }, "刷新数据", 8, _hoisted_7),
        (__props.showSwitch)
          ? (_openBlock$1(), _createElementBlock$1("button", {
              key: 0,
              type: "button",
              class: "primary-button",
              onClick: _cache[2] || (_cache[2] = $event => (emit('switch')))
            }, "切换到详情页"))
          : _createCommentVNode$1("", true)
      ])
    ]),
    _createElementVNode$1("div", _hoisted_8, [
      _createElementVNode$1("span", null, "总计 " + _toDisplayString(_unref(state).stats.total) + " 部", 1),
      _createElementVNode$1("span", null, "命中 " + _toDisplayString(_unref(state).stats.matched) + " 部", 1),
      _createElementVNode$1("span", null, "当前展示 " + _toDisplayString(_unref(state).stats.showing) + " 部", 1),
      _createElementVNode$1("span", null, "最近同步 " + _toDisplayString(_unref(state).stats.last_refresh), 1)
    ]),
    (_unref(notice).text)
      ? (_openBlock$1(), _createElementBlock$1("div", {
          key: 0,
          class: _normalizeClass(["browser-notice", `browser-notice--${_unref(notice).type}`])
        }, _toDisplayString(_unref(notice).text), 3))
      : _createCommentVNode$1("", true),
    _createElementVNode$1("div", _hoisted_9, [
      _createElementVNode$1("div", _hoisted_10, [
        (_openBlock$1(true), _createElementBlock$1(_Fragment, null, _renderList(primaryFilterGroups.value, (group) => {
          return (_openBlock$1(), _createElementBlock$1("section", {
            key: group.field,
            class: "filter-card"
          }, [
            _createElementVNode$1("div", _hoisted_11, _toDisplayString(group.label), 1),
            _createElementVNode$1("div", _hoisted_12, [
              (_openBlock$1(true), _createElementBlock$1(_Fragment, null, _renderList(group.options, (option) => {
                return (_openBlock$1(), _createElementBlock$1("button", {
                  key: `${group.field}-${option.value}`,
                  type: "button",
                  class: _normalizeClass(["filter-chip", { 'filter-chip--active': _unref(filters)[group.field] === option.value }]),
                  disabled: _unref(loading),
                  onClick: $event => (_unref(setFilter)(group.field, option.value))
                }, _toDisplayString(option.label), 11, _hoisted_13))
              }), 128))
            ])
          ]))
        }), 128))
      ]),
      _createElementVNode$1("section", _hoisted_14, [
        _cache[4] || (_cache[4] = _createElementVNode$1("div", { class: "filter-rail__label" }, "题材", -1)),
        _createElementVNode$1("div", _hoisted_15, [
          _createElementVNode$1("div", _hoisted_16, [
            (_openBlock$1(true), _createElementBlock$1(_Fragment, null, _renderList(visibleGenreOptions.value, (option) => {
              return (_openBlock$1(), _createElementBlock$1("button", {
                key: `genre-${option.value}`,
                type: "button",
                class: _normalizeClass(["filter-chip filter-chip--compact", { 'filter-chip--active': _unref(filters).genre === option.value }]),
                disabled: _unref(loading),
                onClick: $event => (_unref(setFilter)('genre', option.value))
              }, _toDisplayString(option.label), 11, _hoisted_17))
            }), 128))
          ])
        ]),
        (canToggleGenres.value)
          ? (_openBlock$1(), _createElementBlock$1("button", {
              key: 0,
              type: "button",
              class: "ghost-button ghost-button--small filter-rail__toggle",
              disabled: _unref(loading),
              onClick: _cache[3] || (_cache[3] = $event => (showAllGenres.value = !showAllGenres.value))
            }, _toDisplayString(genreToggleText.value), 9, _hoisted_18))
          : _createCommentVNode$1("", true)
      ])
    ]),
    (platformCounts.value.length || typeCounts.value.length)
      ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_19, [
          _createElementVNode$1("section", _hoisted_20, [
            _cache[5] || (_cache[5] = _createElementVNode$1("div", { class: "count-title" }, "平台数量", -1)),
            _createElementVNode$1("div", _hoisted_21, [
              (_openBlock$1(true), _createElementBlock$1(_Fragment, null, _renderList(platformCounts.value, (item) => {
                return (_openBlock$1(), _createElementBlock$1("span", {
                  key: `platform-${item.value}`,
                  class: "count-chip"
                }, _toDisplayString(item.label) + " " + _toDisplayString(item.count), 1))
              }), 128))
            ])
          ]),
          _createElementVNode$1("section", _hoisted_22, [
            _cache[6] || (_cache[6] = _createElementVNode$1("div", { class: "count-title" }, "类型数量", -1)),
            _createElementVNode$1("div", _hoisted_23, [
              (_openBlock$1(true), _createElementBlock$1(_Fragment, null, _renderList(typeCounts.value, (item) => {
                return (_openBlock$1(), _createElementBlock$1("span", {
                  key: `type-${item.value}`,
                  class: "count-chip"
                }, _toDisplayString(item.label) + " " + _toDisplayString(item.count), 1))
              }), 128))
            ])
          ])
        ]))
      : _createCommentVNode$1("", true),
    (_unref(loading))
      ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_24, "正在加载近期上线内容..."))
      : (!_unref(state).items.length)
        ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_25, "当前筛选条件下没有匹配内容，可以尝试切换平台、时间或题材后再看。"))
        : (_openBlock$1(), _createElementBlock$1("div", _hoisted_26, [
            (_openBlock$1(true), _createElementBlock$1(_Fragment, null, _renderList(_unref(state).items, (item) => {
              return (_openBlock$1(), _createElementBlock$1("article", {
                key: item.media_id,
                class: "media-card"
              }, [
                _createElementVNode$1("div", _hoisted_27, [
                  (item.poster)
                    ? (_openBlock$1(), _createElementBlock$1("img", {
                        key: 0,
                        src: item.poster,
                        alt: item.title,
                        loading: "lazy"
                      }, null, 8, _hoisted_28))
                    : (_openBlock$1(), _createElementBlock$1("div", _hoisted_29, _toDisplayString(item.title), 1))
                ]),
                _createElementVNode$1("div", _hoisted_30, [
                  _createElementVNode$1("div", _hoisted_31, [
                    (_openBlock$1(true), _createElementBlock$1(_Fragment, null, _renderList(getPlatformLabels(item), (platformLabel) => {
                      return (_openBlock$1(), _createElementBlock$1("span", {
                        key: `${item.media_id}-${platformLabel}`,
                        class: "media-tag media-tag--platform"
                      }, _toDisplayString(platformLabel), 1))
                    }), 128)),
                    _createElementVNode$1("span", _hoisted_32, _toDisplayString(item.type_label), 1),
                    (getSubscriptionTag(item))
                      ? (_openBlock$1(), _createElementBlock$1("span", {
                          key: 0,
                          class: _normalizeClass(["media-tag", getSubscriptionTag(item).className])
                        }, _toDisplayString(getSubscriptionTag(item).label), 3))
                      : _createCommentVNode$1("", true),
                    (item.time_label)
                      ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_33, _toDisplayString(item.time_label), 1))
                      : _createCommentVNode$1("", true),
                    (item.reserve_count > 0)
                      ? (_openBlock$1(), _createElementBlock$1("span", _hoisted_34, _toDisplayString('\u9884\u7ea6') + " " + _toDisplayString(item.reserve_count), 1))
                      : _createCommentVNode$1("", true)
                  ]),
                  _createElementVNode$1("h3", _hoisted_35, _toDisplayString(item.title), 1),
                  _createElementVNode$1("p", _hoisted_36, "上映时间：" + _toDisplayString(item.release_display), 1),
                  _createElementVNode$1("p", _hoisted_37, "地区：" + _toDisplayString(item.region_text), 1),
                  _createElementVNode$1("p", _hoisted_38, "题材：" + _toDisplayString(item.genre_text), 1),
                  (item.story)
                    ? (_openBlock$1(), _createElementBlock$1("p", _hoisted_39, _toDisplayString(item.story), 1))
                    : _createCommentVNode$1("", true),
                  _createElementVNode$1("div", _hoisted_40, [
                    _createElementVNode$1("button", {
                      type: "button",
                      class: _normalizeClass(["primary-button", { 'primary-button--subscribed': item.subscription_status === 'active', 'primary-button--completed': item.subscription_status === 'history' }]),
                      disabled: item.subscribed || _unref(busyMediaId) === item.media_id || _unref(loading),
                      onClick: $event => (_unref(subscribe)(item.media_id))
                    }, _toDisplayString(_unref(busyMediaId) === item.media_id ? '\u8ba2\u9605\u4e2d...' : item.subscription_label || '\u7acb\u5373\u8ba2\u9605'), 11, _hoisted_41),
                    (item.detail_link)
                      ? (_openBlock$1(), _createElementBlock$1("a", {
                          key: 0,
                          class: "link-button",
                          href: item.detail_link,
                          target: "_blank",
                          rel: "noreferrer"
                        }, "查看详情", 8, _hoisted_42))
                      : _createCommentVNode$1("", true)
                  ])
                ])
              ]))
            }), 128))
          ]))
  ]))
}
}

};
const UpcomingBrowserPanel = /*#__PURE__*/_export_sfc(_sfc_main$1, [['__scopeId',"data-v-a07620fb"]]);

const {createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode} = await importShared('vue');


const _hoisted_1 = { class: "page-shell" };
const _hoisted_2 = { class: "page-header" };
const _hoisted_3 = { class: "page-actions" };


const _sfc_main = {
  __name: 'PageView',
  props: {
  api: {
    type: Object,
    required: true,
  },
  show_switch: {
    type: Boolean,
    default: true,
  },
},
  emits: ['switch', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _cache[2] || (_cache[2] = _createElementVNode("div", null, [
        _createElementVNode("h1", { class: "page-title" }, "待播影视详情"),
        _createElementVNode("p", { class: "page-subtitle" }, "与配置页保持同一套组合筛选和卡片订阅能力。")
      ], -1)),
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("button", {
          type: "button",
          class: "ghost-button",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        }, "关闭"),
        (props.show_switch)
          ? (_openBlock(), _createElementBlock("button", {
              key: 0,
              type: "button",
              class: "primary-button",
              onClick: _cache[1] || (_cache[1] = $event => (emit('switch')))
            }, "打开配置"))
          : _createCommentVNode("", true)
      ])
    ]),
    _createVNode(UpcomingBrowserPanel, {
      api: __props.api,
      title: "近期预览",
      subtitle: "支持平台、类型、时间、地区、题材组合筛选，并可直接订阅。",
      "show-switch": false
    }, null, 8, ["api"])
  ]))
}
}

};
const PageView = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-4aa950ce"]]);

export { PageView as default };
