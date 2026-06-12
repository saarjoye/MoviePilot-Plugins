import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const { computed, onMounted, reactive, ref, h, resolveComponent } = await importShared('vue');

const Page = {
  name: 'Page',
  props: {
    api: { type: Object, default: null },
    showSwitch: { type: Boolean, default: true },
    show_switch: { type: Boolean, default: undefined },
  },
  emits: ['switch'],
  setup(props, { emit }) {
    const loading = ref(false);
    const manualLoading = ref(false);
    const error = ref('');
    const message = ref('');
    const activeTaskSource = ref('all');
    const activeContainerSource = ref('all');
    const confirmDialog = ref(false);
    const selectedContainer = ref(null);

    const state = reactive({
      sources: [],
      source_states: [],
      containers: [],
      logs: [],
      updatablelist: [],
      autoupdatelist: [],
      metrics: {},
    });

    const sourceStates = computed(() => Array.isArray(state.source_states) ? state.source_states : []);
    const containers = computed(() => Array.isArray(state.containers) ? state.containers : []);
    const updateLogs = computed(() => Array.isArray(state.logs) ? state.logs : []);
    const showSettingsButton = computed(() => props.show_switch ?? props.showSwitch);
    const sourceTabs = computed(() => [
      { title: '全部', value: 'all' },
      ...sourceStates.value.map(source => ({
        title: source.name || source.id,
        value: source.id,
      })),
    ]);
    const metrics = computed(() => [
      { label: '已配置源', value: state.metrics?.sources || 0, color: 'primary' },
      { label: '启用源', value: state.metrics?.enabled_sources || 0, color: 'success' },
      { label: '容器总数', value: state.metrics?.containers || 0, color: 'primary' },
      { label: '已选自动更新', value: state.metrics?.auto_selected || 0, color: 'warning' },
      { label: '可自动升级', value: state.metrics?.auto_updatable || 0, color: 'error' },
      { label: '异常/失败', value: state.metrics?.failed_sources || 0, color: 'error' },
    ]);
    const logMetrics = computed(() => [
      { label: '更新日志', value: state.metrics?.logs_total || 0, color: 'primary' },
      { label: '成功', value: state.metrics?.logs_success || 0, color: 'success' },
      { label: '失败', value: state.metrics?.logs_failed || 0, color: 'error' },
    ]);
    const taskNotifyContainers = computed(() => bySource(containers.value, activeTaskSource.value).filter(item => item.selected_notify));
    const taskAutoContainers = computed(() => bySource(containers.value, activeTaskSource.value).filter(item => item.selected_auto));
    const filteredContainers = computed(() => bySource(containers.value, activeContainerSource.value));
    const activeTaskSourceLabel = computed(() => tabLabel(activeTaskSource.value));
    const activeContainerSourceLabel = computed(() => tabLabel(activeContainerSource.value));

    function bySource(list, sourceId) {
      if (sourceId === 'all')
        return list
      return list.filter(item => item.source_id === sourceId)
    }

    function tabLabel(value) {
      return sourceTabs.value.find(item => item.value === value)?.title || '全部'
    }

    function ensureActiveTabs() {
      const values = new Set(sourceTabs.value.map(item => item.value));
      if (!values.has(activeTaskSource.value))
        activeTaskSource.value = 'all';
      if (!values.has(activeContainerSource.value))
        activeContainerSource.value = 'all';
    }

    function yesNo(value) {
      return value ? '是' : '否'
    }

    function shortTime(value) {
      if (!value)
        return '-'
      return String(value).replace(/^\d{4}-\d{2}-\d{2}\s*/, '')
    }

    function sourceColor(source) {
      if (source.enabled === false || source.state === '停用')
        return 'grey'
      if (source.state === '已连接')
        return 'success'
      if (source.state === '异常')
        return 'error'
      return 'warning'
    }

    function openManualDialog(container) {
      if (!container?.haveUpdate)
        return
      selectedContainer.value = container;
      confirmDialog.value = true;
    }

    async function confirmManualUpgrade() {
      error.value = '';
      message.value = '';
      if (!selectedContainer.value?.key)
        return
      if (!props.api?.post) {
        error.value = '当前 MoviePilot 未注入插件 POST API，无法执行手动升级。';
        return
      }
      manualLoading.value = true;
      try {
        const result = await props.api.post('plugin/DockerCopilotHelperMulti/manual_update', {
          container_key: selectedContainer.value.key,
        });
        if (result?.success) {
          message.value = result.message || '手动升级任务已创建';
          confirmDialog.value = false;
          await loadState();
        } else {
          const failureMessage = result?.message || '手动升级失败';
          await loadState();
          error.value = failureMessage;
        }
      } catch (err) {
        error.value = `手动升级失败：${err?.message || err}`;
      } finally {
        manualLoading.value = false;
      }
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
          logs: Array.isArray(result?.logs) ? result.logs : [],
          updatablelist: Array.isArray(result?.updatablelist) ? result.updatablelist : [],
          autoupdatelist: Array.isArray(result?.autoupdatelist) ? result.autoupdatelist : [],
          metrics: result?.metrics || {},
        });
        ensureActiveTabs();
      } catch (err) {
        error.value = `加载详情失败：${err?.message || err}`;
      } finally {
        loading.value = false;
      }
    }

    onMounted(loadState);

    function C(name) {
      return resolveComponent(name)
    }

    function cardTitle(text) {
      return h(C('v-card-title'), null, { default: () => text })
    }

    function cardSubtitle(text) {
      return h(C('v-card-subtitle'), null, { default: () => text })
    }

    function metricCard(metric) {
      return h(C('v-col'), { cols: 6, md: 2, key: metric.label }, {
        default: () => [
          h(C('v-card'), { variant: 'outlined', class: 'metric-card' }, {
            default: () => [
              h(C('v-card-text'), null, {
                default: () => [
                  h('div', { class: ['text-h4', 'font-weight-bold', `text-${metric.color}`] }, String(metric.value)),
                  h('div', { class: 'text-body-2 text-medium-emphasis' }, metric.label),
                ],
              }),
            ],
          }),
        ],
      })
    }

    function renderTabs(model, setter, keyPrefix) {
      return h(C('v-tabs'), {
        modelValue: model.value,
        'onUpdate:modelValue': setter,
        density: 'compact',
        showArrows: true,
      }, {
        default: () => sourceTabs.value.map(tab => h(C('v-tab'), {
          key: `${keyPrefix}-${tab.value}`,
          value: tab.value,
        }, { default: () => tab.title })),
      })
    }

    function sourceStatusTable() {
      return h(C('v-card'), { variant: 'outlined' }, {
        default: () => [
          cardTitle('DockerCopilot 源状态'),
          cardSubtitle('可自动升级仅统计已勾选自动更新且当前可更新的容器'),
          h(C('v-table'), { density: 'comfortable', class: 'mt-2' }, {
            default: () => [
              h('thead', null, [
                h('tr', null, [
                  h('th', null, '源名称'),
                  h('th', null, '源ID'),
                  h('th', null, '状态'),
                  h('th', null, '容器'),
                  h('th', null, '已选自动更新'),
                  h('th', null, '可自动升级'),
                  h('th', null, '说明'),
                ]),
              ]),
              h('tbody', null, [
                ...sourceStates.value.map(source => h('tr', { key: source.id }, [
                  h('td', null, source.name || source.id),
                  h('td', null, [h('code', null, source.id)]),
                  h('td', null, [
                    h(C('v-chip'), {
                      size: 'small',
                      color: sourceColor(source),
                      variant: 'tonal',
                    }, { default: () => source.state || (source.enabled === false ? '停用' : '未知') }),
                  ]),
                  h('td', null, String(source.container_count || 0)),
                  h('td', null, String(source.selected_auto_count || 0)),
                  h('td', { class: 'font-weight-medium' }, String(source.auto_updatable_count || 0)),
                  h('td', { class: 'text-truncate max-message' }, source.message || '-'),
                ])),
                !sourceStates.value.length
                  ? h('tr', null, [h('td', { colspan: 7, class: 'text-medium-emphasis' }, '暂无源，请先进入配置页新增并保存 DC 源。')])
                  : null,
              ]),
            ],
          }),
        ],
      })
    }

    function taskRows(list, color) {
      if (!list.length)
        return [h('div', { class: 'empty-line' }, color === 'primary' ? '当前筛选范围未选择更新通知容器' : '当前筛选范围未选择自动更新容器')]
      return list.map(container => h('div', { key: `${color}-${container.key}`, class: 'task-row' }, [
        h(C('v-icon'), { color, size: 18 }, { default: () => 'mdi-checkbox-marked-circle' }),
        h('span', { class: 'task-name' }, container.name),
        h(C('v-chip'), {
          size: 'x-small',
          color: container.haveUpdate ? 'error' : 'success',
          variant: 'tonal',
        }, { default: () => container.haveUpdate ? '可升级' : '运行中' }),
      ]))
    }

    function taskCard() {
      return h(C('v-card'), { variant: 'outlined', class: 'fill-height' }, {
        default: () => [
          cardTitle('任务选择'),
          cardSubtitle('点击源标签后，仅显示该源已配置容器'),
          h(C('v-card-text'), null, {
            default: () => [
              renderTabs(activeTaskSource, value => { activeTaskSource.value = value; }, 'task'),
              h('div', { class: 'text-body-2 text-medium-emphasis mt-3 mb-4' }, `当前显示：${activeTaskSourceLabel.value} 源已配置容器`),
              h('div', { class: 'task-group' }, [
                h('div', { class: 'section-label' }, '更新通知容器'),
                ...taskRows(taskNotifyContainers.value, 'primary'),
              ]),
              h('div', { class: 'task-group mt-5' }, [
                h('div', { class: 'section-label' }, '自动更新容器'),
                ...taskRows(taskAutoContainers.value, 'success'),
              ]),
            ],
          }),
        ],
      })
    }

    function logMetricCard(item) {
      return h(C('v-col'), { cols: 4, key: item.label }, {
        default: () => [
          h(C('v-card'), { variant: 'outlined', class: 'log-metric' }, {
            default: () => [
              h(C('v-card-text'), null, {
                default: () => [
                  h('div', { class: ['text-h5', 'font-weight-bold', `text-${item.color}`] }, String(item.value)),
                  h('div', { class: 'text-caption text-medium-emphasis' }, item.label),
                ],
              }),
            ],
          }),
        ],
      })
    }

    function logsTable() {
      return h(C('v-table'), { density: 'compact', class: 'mt-3' }, {
        default: () => [
          h('thead', null, [
            h('tr', null, [
              h('th', null, '时间'),
              h('th', null, '类型'),
              h('th', null, '源'),
              h('th', null, '容器'),
              h('th', null, '镜像'),
              h('th', null, '结果'),
              h('th', null, '说明/失败原因'),
            ]),
          ]),
          h('tbody', null, [
            ...updateLogs.value.map(item => h('tr', { key: `${item.time}-${item.type}-${item.source}-${item.container}` }, [
              h('td', { class: 'log-time' }, shortTime(item.time)),
              h('td', null, item.type),
              h('td', null, item.source),
              h('td', { class: 'text-truncate max-container' }, item.container),
              h('td', { class: 'text-truncate max-image' }, item.image || '-'),
              h('td', null, [
                h(C('v-chip'), {
                  size: 'x-small',
                  color: item.success ? 'success' : 'error',
                  variant: 'tonal',
                }, { default: () => item.result }),
              ]),
              h('td', { class: 'text-truncate max-message' }, item.message),
            ])),
            !updateLogs.value.length
              ? h('tr', null, [h('td', { colspan: 7, class: 'text-medium-emphasis' }, '暂无执行日志，触发更新通知、自动更新、手动升级或镜像清理后显示。')])
              : null,
          ]),
        ],
      })
    }

    function statsCard() {
      return h(C('v-card'), { variant: 'outlined', class: 'fill-height' }, {
        default: () => [
          cardTitle('更新统计'),
          cardSubtitle('更新日志、成功日志、失败日志按任务结果聚合'),
          h(C('v-card-text'), null, {
            default: () => [
              h(C('v-row'), { dense: true }, { default: () => logMetrics.value.map(logMetricCard) }),
              logsTable(),
              h(C('v-alert'), { type: 'info', variant: 'tonal', class: 'mt-4' }, {
                default: () => '日志需明确 source、container、image、reason；镜像清理无法映射容器时记录 container=unknown。',
              }),
            ],
          }),
        ],
      })
    }

    function containerTable() {
      return h(C('v-table'), { density: 'comfortable' }, {
        default: () => [
          h('thead', null, [
            h('tr', null, [
              h('th', null, '容器'),
              h('th', null, '镜像'),
              h('th', null, '状态'),
              h('th', null, '可更新'),
              h('th', null, '已选自动更新'),
              h('th', null, '最近结果'),
              h('th', null, '操作'),
            ]),
          ]),
          h('tbody', null, [
            ...filteredContainers.value.map(container => h('tr', { key: container.key }, [
              h('td', null, container.name),
              h('td', { class: 'text-truncate max-image' }, container.usingImage || '-'),
              h('td', null, container.status || '-'),
              h('td', null, yesNo(container.haveUpdate)),
              h('td', null, yesNo(container.selected_auto)),
              h('td', null, container.last_result || '-'),
              h('td', null, container.haveUpdate
                ? h(C('v-btn'), {
                    color: 'primary',
                    size: 'small',
                    variant: 'flat',
                    onClick: () => openManualDialog(container),
                  }, { default: () => '手动升级' })
                : h('span', { class: 'text-medium-emphasis' }, '无需操作')),
            ])),
            !filteredContainers.value.length
              ? h('tr', null, [h('td', { colspan: 7, class: 'text-medium-emphasis' }, '暂无容器。请确认源已保存、DC 地址包含正确端口、服务可访问且 secretKey 正确。')])
              : null,
          ]),
        ],
      })
    }

    function containersCard() {
      return h(C('v-card'), { variant: 'outlined' }, {
        default: () => [
          cardTitle('容器列表'),
          cardSubtitle(`标签页名称来自已配置源名，当前只显示 ${activeContainerSourceLabel.value} 源容器`),
          h(C('v-card-text'), null, {
            default: () => [
              h('div', { class: 'mb-3' }, [
                renderTabs(activeContainerSource, value => { activeContainerSource.value = value; }, 'container'),
              ]),
              containerTable(),
            ],
          }),
        ],
      })
    }

    function confirmDialogNode() {
      return h(C('v-dialog'), {
        modelValue: confirmDialog.value,
        'onUpdate:modelValue': value => { confirmDialog.value = value; },
        maxWidth: 460,
      }, {
        default: () => [
          h(C('v-card'), null, {
            default: () => [
              cardTitle('确认手动升级'),
              h(C('v-card-text'), null, {
                default: () => [
                  h('div', { class: 'dialog-line' }, `源：${selectedContainer.value?.source_name || '-'}`),
                  h('div', { class: 'dialog-line' }, `容器：${selectedContainer.value?.name || '-'}`),
                  h('div', { class: 'dialog-line text-medium-emphasis' }, `当前镜像：${selectedContainer.value?.usingImage || '-'}`),
                  h(C('v-alert'), { type: 'warning', variant: 'tonal', class: 'mt-4' }, {
                    default: () => '手动升级会立即调用当前源的 DockerCopilot 更新接口，请确认容器正在空闲状态。',
                  }),
                ],
              }),
              h(C('v-card-actions'), null, {
                default: () => [
                  h(C('v-spacer')),
                  h(C('v-btn'), {
                    variant: 'tonal',
                    disabled: manualLoading.value,
                    onClick: () => { confirmDialog.value = false; },
                  }, { default: () => '取消' }),
                  h(C('v-btn'), {
                    color: 'primary',
                    loading: manualLoading.value,
                    onClick: confirmManualUpgrade,
                  }, { default: () => '确认升级' }),
                ],
              }),
            ],
          }),
        ],
      })
    }

    return () => h(C('v-card'), { flat: true, class: 'task-center-page' }, {
      default: () => [
        h(C('v-card-item'), { class: 'px-0 pt-0' }, {
          append: () => [
            h('div', { class: 'd-flex align-center gap-2' }, [
              h(C('v-btn'), {
                icon: true,
                color: 'primary',
                variant: 'text',
                loading: loading.value,
                onClick: loadState,
              }, { default: () => h(C('v-icon'), null, { default: () => 'mdi-refresh' }) }),
              showSettingsButton.value
                ? h(C('v-btn'), {
                    icon: true,
                    color: 'primary',
                    variant: 'text',
                    onClick: () => emit('switch'),
                  }, { default: () => h(C('v-icon'), null, { default: () => 'mdi-cog' }) })
                : null,
            ]),
          ],
          default: () => [
            cardTitle('DC助手 · 任务中心增强'),
            cardSubtitle('按源查看任务、容器、手动升级与执行日志'),
          ],
        }),
        h(C('v-card-text'), { class: 'px-0' }, {
          default: () => [
            error.value ? h(C('v-alert'), { type: 'error', variant: 'tonal', class: 'mb-4' }, { default: () => error.value }) : null,
            message.value ? h(C('v-alert'), { type: 'success', variant: 'tonal', class: 'mb-4' }, { default: () => message.value }) : null,
            h(C('v-row'), null, { default: () => metrics.value.map(metricCard) }),
            h(C('v-row'), { class: 'mt-2' }, { default: () => [h(C('v-col'), { cols: 12 }, { default: () => sourceStatusTable() })] }),
            h(C('v-row'), { class: 'mt-2' }, {
              default: () => [
                h(C('v-col'), { cols: 12, md: 6 }, { default: () => taskCard() }),
                h(C('v-col'), { cols: 12, md: 6 }, { default: () => statsCard() }),
              ],
            }),
            h(C('v-row'), { class: 'mt-2' }, { default: () => [h(C('v-col'), { cols: 12 }, { default: () => containersCard() })] }),
          ],
        }),
        confirmDialogNode(),
      ],
    })
  },
};

export { Page as default };
