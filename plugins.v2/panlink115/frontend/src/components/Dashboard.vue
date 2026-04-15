<script setup>
const props = defineProps({
  api: {
    type: Object,
    default: () => ({})
  },
  initialConfig: {
    type: Object,
    default: () => ({})
  }
});

function statusText() {
  return props.initialConfig?.enabled ? "已启用" : "未启用";
}

function modeText() {
  return props.initialConfig?.only_show_115 === false ? "全部网盘" : "仅 115";
}
</script>

<template>
  <VCard variant="tonal">
    <VCardTitle>盘链 115 搜索</VCardTitle>
    <VCardText class="d-flex flex-column ga-2">
      <div>状态：{{ statusText() }}</div>
      <div>展示模式：{{ modeText() }}</div>
      <div>说明：插件已切换为 Vue 页面，可直接在详情弹窗中手动搜索盘链资源。</div>
    </VCardText>
  </VCard>
</template>
