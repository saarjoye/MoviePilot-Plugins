import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const { computed, onBeforeUnmount, onMounted, reactive, ref, watch, h, resolveComponent } = await importShared('vue');

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
    const batchLoading = ref(false);
    const error = ref('');
    const message = ref('');
    const messageType = ref('info');
    const search = ref('');
    const activeSource = ref('all');
    const sourceFilter = ref('all');
    const confirmDialog = ref(false);
    const batchDialog = ref(false);
    const selectedContainer = ref(null);
    const refreshTimer = ref(null);

    const state = reactive({
      sources: [],
      source_states: [],
      containers: [],
      logs: [],
      progress_tasks: [],
      updatablelist: [],
      autoupdatelist: [],
      metrics: {},
    });

    const sourceFilters = [
      { title: '全部', value: 'all' },
      { title: '在线', value: 'online' },
      { title: '可升级', value: 'updatable' },
      { title: '有失败', value: 'failed' },
    ];

    const sourceStates = computed(() => Array.isArray(state.source_states) ? state.source_states : []);
    const containers = computed(() => Array.isArray(state.containers) ? state.containers : []);
    const updateLogs = computed(() => Array.isArray(state.logs) ? state.logs : []);
    const progressTasks = computed(() => Array.isArray(state.progress_tasks) ? state.progress_tasks : []);
    const showSettingsButton = computed(() => props.show_switch ?? props.showSwitch);
    const sourceTabs = computed(() => [
      { title: '全部', value: 'all' },
      ...sourceStates.value.map(source => ({
        title: source.name || source.id,
        value: source.id,
      })),
    ]);
    const currentSourceTitle = computed(() => tabLabel(activeSource.value));
    const filteredLogs = computed(() => logsBySource(updateLogs.value, activeSource.value));
    const visibleLogs = computed(() => filteredLogs.value.slice(0, 8));
    const filteredProgressTasks = computed(() => bySource(progressTasks.value, activeSource.value));
    const visibleProgressTasks = computed(() => filteredProgressTasks.value.slice(0, 8));
    const runningProgressTasks = computed(() => progressTasks.value.filter(isProgressRunning));
    const filteredLogMetrics = computed(() => [
      { label: '更新日志', value: filteredLogs.value.length, color: 'primary' },
      { label: '成功', value: filteredLogs.value.filter(item => displayLogResult(item) === '成功').length, color: 'success' },
      { label: '失败', value: filteredLogs.value.filter(item => !item.success).length, color: 'error' },
    ]);
    const filteredSourceStates = computed(() => sourceStates.value.filter(source => {
      if (sourceFilter.value === 'online')
        return source.state === '已连接';
      if (sourceFilter.value === 'updatable')
        return Number(source.auto_updatable_count || 0) > 0;
      if (sourceFilter.value === 'failed')
        return source.state === '异常' || logsBySource(updateLogs.value, source.id).some(item => !item.success);
      return true;
    }));
    const operationContainers = computed(() => {
      const keyword = search.value.trim().toLowerCase();
      return [...bySource(containers.value, activeSource.value)]
        .filter(container => {
          if (!keyword)
            return true;
          return [container.name, container.source_name, container.usingImage]
            .filter(Boolean)
            .some(value => String(value).toLowerCase().includes(keyword));
        })
        .sort((left, right) => containerRank(left) - containerRank(right));
    });
    const pendingContainers = computed(() => containers.value.filter(container => container.haveUpdate));
    const actionableContainers = computed(() => operationContainers.value.filter(canManualUpgrade));
    const selectedSourceSummary = computed(() => {
      const scopedContainers = bySource(containers.value, activeSource.value);
      const scopedLogs = logsBySource(updateLogs.value, activeSource.value);
      const lastLog = scopedLogs[0];
      return {
        notify: scopedContainers.filter(item => item.selected_notify).length,
        auto: scopedContainers.filter(item => item.selected_auto).length,
        updatable: scopedContainers.filter(item => item.selected_auto && item.haveUpdate).length,
        lastResult: lastLog ? displayLogResult(lastLog) : '暂无日志',
      };
    });
    const metrics = computed(() => [
      { label: '已配置源', value: state.metrics?.sources || 0, color: 'primary' },
      { label: '已选自动更新', value: state.metrics?.auto_selected || 0, color: 'warning' },
      { label: '可自动升级', value: state.metrics?.auto_updatable || 0, color: 'error' },
      { label: '待处理容器', value: state.metrics?.updatable || pendingContainers.value.length, color: 'primary' },
      { label: '更新中', value: state.metrics?.progress_running || runningProgressTasks.value.length, color: 'primary' },
      { label: '失败', value: state.metrics?.logs_failed || 0, color: 'error' },
    ]);

    function C(name) {
      return resolveComponent(name)
    }

    function setActiveSource(value) {
      activeSource.value = value || 'all';
    }

    function bySource(list, sourceId) {
      if (sourceId === 'all')
        return list;
      return list.filter(item => item.source_id === sourceId)
    }

    function logsBySource(list, sourceId) {
      if (sourceId === 'all')
        return list;
      const source = sourceStates.value.find(item => item.id === sourceId);
      return list.filter(item => item.source_id === sourceId || item.source === source?.name || item.source === sourceId)
    }

    function tabLabel(value) {
      return sourceTabs.value.find(item => item.value === value)?.title || '全部'
    }

    function ensureActiveSource() {
      const values = new Set(sourceTabs.value.map(item => item.value));
      if (!values.has(activeSource.value))
        activeSource.value = 'all';
    }

    function yesNo(value) {
      return value ? '是' : '否'
    }

    function shortTime(value) {
      if (!value)
        return '-';
      return String(value).replace(/^\d{4}-\d{2}-\d{2}\s*/, '')
    }

    function isSubmittedLog(item) {
      const text = `${item?.result || ''} ${item?.message || ''} ${item?.type || ''}`;
      return /任务创建成功|已提交|提交成功/.test(text)
    }

    function isFailedLog(item) {
      const text = `${item?.result || ''} ${item?.message || ''} ${item?.type || ''}`;
      return /失败/.test(text)
    }

    function displayLogResult(item) {
      if (isFailedLog(item))
        return '失败';
      if (isSubmittedLog(item))
        return '已提交';
      return item?.result || '-'
    }

    function logResultColor(item) {
      const text = displayLogResult(item);
      if (text === '失败')
        return 'error';
      if (text === '已提交')
        return 'primary';
      if (text === '成功')
        return 'success';
      return undefined
    }

    function isProgressRunning(task) {
      return ['已提交', '执行中'].includes(task?.status)
    }

    function isProgressFailed(task) {
      return task?.status === '更新失败'
    }

    function progressColor(task) {
      if (task?.status === '更新成功')
        return 'success';
      if (task?.status === '更新失败')
        return 'error';
      if (['超时待确认', '远程源无法确认'].includes(task?.status))
        return 'warning';
      return 'primary'
    }

    function sourceColor(source) {
      if (source.enabled === false || source.state === '停用')
        return 'grey';
      if (source.state === '已连接')
        return 'success';
      if (source.state === '异常')
        return 'error';
      return 'warning'
    }

    function containerRank(container) {
      if (container.haveUpdate)
        return 0;
      if (String(container.last_result || '').includes('失败'))
        return 1;
      if (container.selected_auto)
        return 2;
      return 3
    }

    function canManualUpgrade(container) {
      return Boolean(container?.haveUpdate)
    }

    function lastResultText(container) {
      const combined = `${container?.last_result || ''} ${container?.last_message || ''}`;
      if (/任务创建成功|已提交|提交成功/.test(combined))
        return '已提交';
      if (container.haveUpdate)
        return '可升级';
      return container.last_result || '无更新'
    }

    function lastResultColor(container) {
      const text = lastResultText(container);
      if (text === '已提交')
        return 'primary';
      if (container.haveUpdate)
        return 'error';
      if (text.includes('失败'))
        return 'warning';
      if (text.includes('成功'))
        return 'success';
      if (text.includes('最新'))
        return 'primary';
      return undefined
    }

    function openManualDialog(container) {
      if (!canManualUpgrade(container))
        return;
      selectedContainer.value = container;
      confirmDialog.value = true;
    }

    function openBatchDialog() {
      error.value = '';
      message.value = '';
      if (!actionableContainers.value.length) {
        message.value = '当前筛选条件下没有可升级容器。';
        return;
      }
      batchDialog.value = true;
    }

    async function runManualUpgrade(container) {
      const result = await props.api.post('plugin/DockerCopilotHelperMulti/manual_update', {
        container_key: container.key,
      });
      return {
        container,
        success: Boolean(result?.success),
        message: result?.message || (result?.success ? '升级任务已提交' : '升级失败'),
      }
    }

    async function confirmManualUpgrade() {
      error.value = '';
      message.value = '';
      messageType.value = 'info';
      if (!selectedContainer.value?.key)
        return;
      if (!props.api?.post) {
        error.value = '当前 MoviePilot 未注入插件 POST API，无法执行手动升级。';
        return;
      }
      manualLoading.value = true;
      try {
        const result = await runManualUpgrade(selectedContainer.value);
        if (result.success) {
          message.value = '手动升级任务已提交，实际完成后会刷新在日志里。';
          messageType.value = 'info';
          confirmDialog.value = false;
          await loadState();
        } else {
          await loadState();
          error.value = result.message || '手动升级失败';
        }
      } catch (err) {
        error.value = `手动升级失败：${err?.message || err}`;
      } finally {
        manualLoading.value = false;
      }
    }

    async function confirmBatchUpgrade() {
      error.value = '';
      message.value = '';
      messageType.value = 'info';
      if (!props.api?.post) {
        error.value = '当前 MoviePilot 未注入插件 POST API，无法执行批量升级。';
        return;
      }
      const targets = [...actionableContainers.value];
      if (!targets.length) {
        batchDialog.value = false;
        return;
      }
      batchLoading.value = true;
      try {
        const results = [];
        for (const container of targets) {
          results.push(await runManualUpgrade(container));
        }
        const successCount = results.filter(item => item.success).length;
        const failedCount = results.length - successCount;
        batchDialog.value = false;
        await loadState();
        if (failedCount) {
          error.value = `批量升级完成：成功 ${successCount} 个，失败 ${failedCount} 个。`;
        } else {
          message.value = `批量升级任务已提交：${successCount} 个容器。`;
          messageType.value = 'info';
        }
      } catch (err) {
        error.value = `批量升级失败：${err?.message || err}`;
      } finally {
        batchLoading.value = false;
      }
    }

    async function loadState() {
      error.value = '';
      if (!props.api?.get) {
        error.value = '当前 MoviePilot 未注入插件 API，无法加载详情数据。';
        return;
      }
      loading.value = true;
      try {
        const result = await props.api.get('plugin/DockerCopilotHelperMulti/state');
        Object.assign(state, {
          sources: Array.isArray(result?.sources) ? result.sources : [],
          source_states: Array.isArray(result?.source_states) ? result.source_states : [],
          containers: Array.isArray(result?.containers) ? result.containers : [],
          logs: Array.isArray(result?.logs) ? result.logs : [],
          progress_tasks: Array.isArray(result?.progress_tasks) ? result.progress_tasks : [],
          updatablelist: Array.isArray(result?.updatablelist) ? result.updatablelist : [],
          autoupdatelist: Array.isArray(result?.autoupdatelist) ? result.autoupdatelist : [],
          metrics: result?.metrics || {},
        });
        ensureActiveSource();
      } catch (err) {
        error.value = `加载详情失败：${err?.message || err}`;
      } finally {
        loading.value = false;
      }
    }

    function startProgressAutoRefresh() {
      stopProgressAutoRefresh();
      refreshTimer.value = window.setInterval(() => {
        if (runningProgressTasks.value.length && !loading.value)
          loadState();
      }, 5000);
    }

    function stopProgressAutoRefresh() {
      if (refreshTimer.value) {
        window.clearInterval(refreshTimer.value);
        refreshTimer.value = null;
      }
    }

    watch(runningProgressTasks, tasks => {
      if (tasks.length)
        startProgressAutoRefresh();
      else
        stopProgressAutoRefresh();
    });

    onMounted(loadState);
    onBeforeUnmount(stopProgressAutoRefresh);

    function cardTitle(text) {
      return h(C('v-card-title'), null, { default: () => text })
    }

    function cardSubtitle(text) {
      return h(C('v-card-subtitle'), null, { default: () => text })
    }

    function iconButton(icon, onClick, options = {}) {
      return h(C('v-btn'), {
        icon: true,
        color: options.color || 'primary',
        variant: 'text',
        loading: options.loading || false,
        onClick,
      }, { default: () => h(C('v-icon'), null, { default: () => icon }) })
    }

    function textButton(label, props, icon) {
      return h(C('v-btn'), props, {
        default: () => [
          icon ? h(C('v-icon'), { start: true }, { default: () => icon }) : null,
          label,
        ],
      })
    }

    function metricCard(metric) {
      return h(C('v-col'), { cols: 6, sm: 4, md: 2, key: metric.label }, {
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

    function chipButton(item, modelValue, onClick) {
      const active = modelValue === item.value;
      return h(C('v-btn'), {
        key: item.value,
        size: 'small',
        rounded: 'lg',
        color: active ? 'primary' : undefined,
        variant: active ? 'flat' : 'tonal',
        onClick: () => onClick(item.value),
      }, { default: () => item.title })
    }

    function sourceOverview() {
      return h(C('v-card'), { variant: 'outlined', class: 'source-panel fill-height' }, {
        default: () => [
          cardTitle('源概览'),
          cardSubtitle('选中一个源后，右侧容器与日志同步联动'),
          h(C('v-card-text'), null, {
            default: () => [
              h('div', { class: 'chip-row mb-3' }, sourceFilters.map(item => chipButton(item, sourceFilter.value, value => { sourceFilter.value = value; }))),
              h('div', { class: 'table-shell table-shell-sm' }, [
                h(C('v-table'), { density: 'compact', class: 'source-table' }, {
                  default: () => [
                    h('thead', null, [h('tr', null, [
                      h('th', null, '源'),
                      h('th', null, '状态'),
                      h('th', null, '容器'),
                      h('th', null, '自动'),
                      h('th', null, '可升级'),
                    ])]),
                    h('tbody', null, [
                      ...filteredSourceStates.value.map(source => h('tr', {
                        key: source.id,
                        class: { 'is-selected': activeSource.value === source.id },
                        onClick: () => setActiveSource(source.id),
                      }, [
                        h('td', { class: 'font-weight-medium text-truncate' }, source.name || source.id),
                        h('td', null, [h(C('v-chip'), {
                          size: 'x-small',
                          color: sourceColor(source),
                          variant: 'tonal',
                        }, { default: () => source.state || (source.enabled === false ? '停用' : '未知') })]),
                        h('td', null, String(source.container_count || 0)),
                        h('td', null, String(source.selected_auto_count || 0)),
                        h('td', { class: 'font-weight-bold' }, String(source.auto_updatable_count || 0)),
                      ])),
                      !filteredSourceStates.value.length
                        ? h('tr', null, [h('td', { colspan: 5, class: 'text-medium-emphasis' }, '当前筛选下暂无源。')])
                        : null,
                    ]),
                  ],
                }),
              ]),
              h('div', { class: 'current-source-box mt-5' }, [
                h('div', { class: 'text-caption text-medium-emphasis' }, '当前源'),
                h('div', { class: 'text-h5 font-weight-bold' }, currentSourceTitle.value),
                summaryLine('更新通知容器', selectedSourceSummary.value.notify, 'text-primary', 'mt-3'),
                summaryLine('自动更新容器', selectedSourceSummary.value.auto, 'text-success'),
                summaryLine('可自动升级', selectedSourceSummary.value.updatable, 'text-error'),
              ]),
            ],
          }),
        ],
      })
    }

    function summaryLine(label, value, valueClass, extraClass = '') {
      return h('div', { class: ['source-summary-line', extraClass] }, [
        h('span', null, label),
        h('strong', { class: valueClass }, String(value)),
      ])
    }

    function operationToolbar() {
      return h('div', { class: 'ops-toolbar mb-3' }, [
        h(C('v-text-field'), {
          modelValue: search.value,
          'onUpdate:modelValue': value => { search.value = value || ''; },
          density: 'compact',
          variant: 'outlined',
          hideDetails: true,
          clearable: true,
          prependInnerIcon: 'mdi-magnify',
          placeholder: '搜索容器 / 镜像',
        }),
        h('div', { class: 'ops-actions' }, [
          textButton('刷新容器', { variant: 'tonal', loading: loading.value, onClick: loadState }, 'mdi-refresh'),
          textButton('批量升级', { color: 'primary', disabled: !actionableContainers.value.length, onClick: openBatchDialog }, 'mdi-upload'),
          showSettingsButton.value
            ? textButton('同步源', { variant: 'tonal', onClick: () => emit('switch') }, 'mdi-cog')
            : null,
        ]),
      ])
    }

    function sourceChips() {
      return h('div', { class: 'chip-row mb-3' }, sourceTabs.value.map(tab => chipButton(tab, activeSource.value, setActiveSource)))
    }

    function containerTable() {
      return h(C('v-table'), { density: 'comfortable', class: 'container-table' }, {
        default: () => [
          h('thead', null, [h('tr', null, [
            h('th', null, '容器'),
            h('th', null, '镜像'),
            h('th', null, '更新通知'),
            h('th', null, '自动更新'),
            h('th', null, '最近结果'),
            h('th', null, '操作'),
          ])]),
          h('tbody', null, [
            ...operationContainers.value.map(container => h('tr', { key: container.key }, [
              h('td', null, [
                h('div', { class: 'font-weight-bold text-truncate max-container' }, container.name),
                h('div', { class: 'text-caption text-medium-emphasis' }, container.source_name),
              ]),
              h('td', { class: 'text-truncate max-image' }, container.usingImage || '-'),
              h('td', null, [h(C('v-chip'), {
                size: 'small',
                color: container.selected_notify ? 'primary' : undefined,
                variant: 'tonal',
              }, { default: () => yesNo(container.selected_notify) })]),
              h('td', null, [h(C('v-chip'), {
                size: 'small',
                color: container.selected_auto ? 'success' : undefined,
                variant: 'tonal',
              }, { default: () => yesNo(container.selected_auto) })]),
              h('td', null, [h(C('v-chip'), {
                size: 'small',
                color: lastResultColor(container),
                variant: 'tonal',
              }, { default: () => lastResultText(container) })]),
              h('td', null, canManualUpgrade(container)
                ? h(C('v-btn'), {
                    color: 'primary',
                    size: 'small',
                    variant: 'flat',
                    onClick: () => openManualDialog(container),
                  }, { default: () => '升级' })
                : h('span', { class: 'text-medium-emphasis' }, '无需操作')),
            ])),
            !operationContainers.value.length
              ? h('tr', null, [h('td', { colspan: 6, class: 'text-medium-emphasis' }, '暂无容器。请确认源已保存、DC 地址包含正确端口、服务可访问且 secretKey 正确。')])
              : null,
          ]),
        ],
      })
    }

    function progressPanel() {
      return h(C('v-card'), { variant: 'outlined', class: 'progress-panel mb-3' }, {
        default: () => [
          cardTitle('更新进度'),
          cardSubtitle('显示已提交和正在执行的 DockerCopilot 更新任务，失败时保留脱敏后的详细日志'),
          h(C('v-card-text'), null, {
            default: () => [
              !visibleProgressTasks.value.length
                ? h('div', { class: 'empty-progress text-medium-emphasis' }, '暂无更新中的容器。点击“升级”或“批量升级”后会在这里显示任务进度。')
                : h('div', { class: 'progress-list' }, visibleProgressTasks.value.map(task => h('div', {
                    key: task.task_id,
                    class: 'progress-item',
                  }, [
                    h('div', { class: 'progress-main' }, [
                      h('div', { class: 'progress-title' }, [
                        h('div', { class: 'font-weight-bold text-truncate max-container' }, task.container),
                        h('div', { class: 'text-caption text-medium-emphasis' }, `${task.source} · ${task.scene} · ${shortTime(task.updated_at)}`),
                      ]),
                      h(C('v-chip'), {
                        size: 'small',
                        color: progressColor(task),
                        variant: 'tonal',
                      }, { default: () => task.status || '-' }),
                    ]),
                    h('div', { class: 'text-caption text-medium-emphasis text-truncate max-progress-image' }, task.image || '-'),
                    h(C('v-progress-linear'), {
                      class: 'mt-2',
                      modelValue: Number(task.percent || 0),
                      color: progressColor(task),
                      height: 8,
                      rounded: true,
                    }),
                    h('div', { class: 'progress-message mt-2' }, [
                      h('span', null, task.message || '-'),
                      h('strong', null, `${Number(task.percent || 0)}%`),
                    ]),
                    isProgressFailed(task)
                      ? h(C('v-alert'), { type: 'error', variant: 'tonal', density: 'compact', class: 'mt-2' }, {
                          default: () => [
                            task.reason || task.message || '更新失败，未返回详细原因',
                            Array.isArray(task.logs) && task.logs.length
                              ? h('div', { class: 'progress-log-list mt-2' }, task.logs.slice(0, 4).map(log => h('div', {
                                  key: `${task.task_id}-${log.time}-${log.status}`,
                                }, `${shortTime(log.time)} · ${log.status} · ${log.message || log.reason || '-'}`)))
                              : null,
                          ],
                        })
                      : null,
                  ]))),
            ],
          }),
        ],
      })
    }

    function operationPanel() {
      return h(C('v-card'), { variant: 'outlined', class: 'ops-panel' }, {
        default: () => [
          cardTitle('容器操作台'),
          cardSubtitle('通知列 = 收到更新提醒；自动列 = 进入自动升级队列'),
          h(C('v-card-text'), null, {
            default: () => [
              sourceChips(),
              operationToolbar(),
              progressPanel(),
              h('div', { class: 'table-shell table-shell-lg' }, [containerTable()]),
            ],
          }),
        ],
      })
    }

    function logSummary(item) {
      return h(C('v-col'), { cols: 4, key: item.label }, {
        default: () => h('div', { class: 'log-summary-box' }, [
          h('div', { class: ['text-h5', 'font-weight-bold', `text-${item.color}`] }, String(item.value)),
          h('div', { class: 'text-caption text-medium-emphasis' }, item.label),
        ]),
      })
    }

    function logsPanel() {
      return h(C('v-card'), { variant: 'outlined', class: 'fill-height' }, {
        default: () => [
          cardTitle('最近日志'),
          cardSubtitle('更新、成功、失败按任务结果聚合'),
          h(C('v-card-text'), null, {
            default: () => [
              h(C('v-row'), { dense: true }, { default: () => filteredLogMetrics.value.map(logSummary) }),
              h('div', { class: 'table-shell table-shell-md mt-3' }, [
                h(C('v-table'), { density: 'compact' }, {
                  default: () => [
                  h('thead', null, [h('tr', null, [
                    h('th', null, '时间'),
                    h('th', null, '类型'),
                    h('th', null, '源'),
                    h('th', null, '容器'),
                    h('th', null, '结果'),
                    h('th', null, '说明/原因'),
                  ])]),
                  h('tbody', null, [
                    ...visibleLogs.value.map(item => h('tr', { key: `${item.time}-${item.type}-${item.source}-${item.container}` }, [
                      h('td', { class: 'log-time' }, shortTime(item.time)),
                      h('td', null, item.type),
                      h('td', null, item.source),
                      h('td', { class: 'text-truncate max-container' }, item.container),
                      h('td', null, [h(C('v-chip'), {
                        size: 'x-small',
                        color: logResultColor(item),
                        variant: 'tonal',
                      }, { default: () => displayLogResult(item) })]),
                      h('td', { class: 'text-truncate max-message' }, item.message),
                    ])),
                    !visibleLogs.value.length
                      ? h('tr', null, [h('td', { colspan: 6, class: 'text-medium-emphasis' }, '暂无执行日志，触发更新通知、自动更新、手动升级或镜像清理后显示。')])
                      : null,
                  ]),
                  ],
                }),
              ]),
              h('div', { class: 'text-body-2 text-medium-emphasis mt-3' }, '日志格式固定为 source / container / image / reason；映射不到容器时记录 container=unknown。'),
            ],
          }),
        ],
      })
    }

    function summaryPanel() {
      return h(C('v-card'), { variant: 'outlined', class: 'fill-height' }, {
        default: () => [
          cardTitle('执行摘要'),
          cardSubtitle('确认升级前先看当前源与日志结果'),
          h(C('v-card-text'), null, {
            default: () => [
              h('div', { class: 'summary-title' }, currentSourceTitle.value),
              plainSummaryRow('更新通知容器', selectedSourceSummary.value.notify, 'text-primary'),
              plainSummaryRow('自动更新容器', selectedSourceSummary.value.auto, 'text-success'),
              plainSummaryRow('可自动升级', selectedSourceSummary.value.updatable, 'text-error'),
              plainSummaryRow('上次结果', selectedSourceSummary.value.lastResult),
              h(C('v-alert'), { type: 'warning', variant: 'tonal', density: 'compact', class: 'mt-4' }, {
                default: () => '手动升级更适合临时补救，平时优先依赖自动更新。',
              }),
              h('div', { class: 'text-body-2 text-medium-emphasis mt-3' }, '日志只保留脱敏后的 source/container/image/reason。'),
              h('div', { class: 'manual-preview mt-4' }, [
                h('div', { class: 'text-subtitle-1 font-weight-bold' }, '确认手动升级'),
                h('div', { class: 'text-body-2 mt-2' }, `当前候选：${actionableContainers.value[0]?.name || '暂无可升级容器'}`),
                h('div', { class: 'text-caption text-medium-emphasis mt-1' }, '单容器升级会在点击行内按钮后弹出确认框。'),
              ]),
            ],
          }),
        ],
      })
    }

    function plainSummaryRow(label, value, valueClass = '') {
      return h('div', { class: 'summary-row' }, [
        h('span', null, label),
        h('strong', { class: valueClass }, String(value)),
      ])
    }

    function manualDialog() {
      return h(C('v-dialog'), {
        modelValue: confirmDialog.value,
        'onUpdate:modelValue': value => { confirmDialog.value = value; },
        maxWidth: 480,
      }, {
        default: () => h(C('v-card'), null, {
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
      })
    }

    function batchDialogNode() {
      return h(C('v-dialog'), {
        modelValue: batchDialog.value,
        'onUpdate:modelValue': value => { batchDialog.value = value; },
        maxWidth: 520,
      }, {
        default: () => h(C('v-card'), null, {
          default: () => [
            cardTitle('确认批量升级'),
            h(C('v-card-text'), null, {
              default: () => [
                h('div', { class: 'text-body-2' }, `将按当前筛选条件升级 ${actionableContainers.value.length} 个可更新容器。`),
                h('div', { class: 'batch-list mt-3' }, actionableContainers.value.map(container => h('div', {
                  key: `batch-${container.key}`,
                  class: 'batch-row',
                }, [
                  h('span', null, container.source_name),
                  h('strong', null, container.name),
                ]))),
                h(C('v-alert'), { type: 'warning', variant: 'tonal', class: 'mt-4' }, {
                  default: () => '批量升级会逐个调用现有手动升级接口，失败项会保留在执行日志中。',
                }),
              ],
            }),
            h(C('v-card-actions'), null, {
              default: () => [
                h(C('v-spacer')),
                h(C('v-btn'), {
                  variant: 'tonal',
                  disabled: batchLoading.value,
                  onClick: () => { batchDialog.value = false; },
                }, { default: () => '取消' }),
                h(C('v-btn'), {
                  color: 'primary',
                  loading: batchLoading.value,
                  onClick: confirmBatchUpgrade,
                }, { default: () => '确认批量升级' }),
              ],
            }),
          ],
        }),
      })
    }

    return () => h(C('v-card'), { flat: true, class: 'task-center-page' }, {
      default: () => [
        h(C('v-card-item'), { class: 'px-0 pt-0' }, {
          append: () => h('div', { class: 'd-flex align-center gap-2' }, [
            iconButton('mdi-refresh', loadState, { loading: loading.value }),
            showSettingsButton.value ? iconButton('mdi-cog', () => emit('switch')) : null,
          ]),
          default: () => [
            cardTitle('DC助手 · 任务中心'),
            cardSubtitle('源、容器、更新进度和日志'),
          ],
        }),
        h(C('v-card-text'), { class: 'px-0' }, {
          default: () => [
            error.value ? h(C('v-alert'), { type: 'error', variant: 'tonal', class: 'mb-4' }, { default: () => error.value }) : null,
            message.value ? h(C('v-alert'), { type: messageType.value, variant: 'tonal', class: 'mb-4' }, { default: () => message.value }) : null,
            h(C('v-row'), { dense: true }, { default: () => metrics.value.map(metricCard) }),
            h(C('v-row'), { class: 'mt-2', align: 'stretch' }, {
              default: () => [
                h(C('v-col'), { cols: 12, md: 2 }, { default: () => sourceOverview() }),
                h(C('v-col'), { cols: 12, md: 10 }, {
                  default: () => [
                    operationPanel(),
                    h(C('v-row'), { class: 'mt-3' }, {
                      default: () => [
                        h(C('v-col'), { cols: 12, md: 7 }, { default: () => logsPanel() }),
                        h(C('v-col'), { cols: 12, md: 5 }, { default: () => summaryPanel() }),
                      ],
                    }),
                  ],
                }),
              ],
            }),
          ],
        }),
        manualDialog(),
        batchDialogNode(),
      ],
    })
  },
};

export { Page as default };
