<template>
  <div class="gis-view">
    <div class="gis-toolbar">
      <a-space>
        <a-button><PlusOutlined /> 添加图层</a-button>
        <a-button><DownloadOutlined /> 导出</a-button>
        <a-divider type="vertical" />
        <a-button-group>
          <a-button @click="zoomIn"><ZoomInOutlined /></a-button>
          <a-button @click="zoomOut"><ZoomOutOutlined /></a-button>
        </a-button-group>
      </a-space>
    </div>
    <div class="gis-map" ref="mapRef">
      <div class="map-placeholder">
        <EnvironmentOutlined style="font-size: 48px; color: var(--primary-color)" />
        <p>GIS 地图视图</p>
        <p class="hint">集成地图组件后显示实际地图</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { PlusOutlined, DownloadOutlined, ZoomInOutlined, ZoomOutOutlined, EnvironmentOutlined } from '@ant-design/icons-vue'

const mapRef = ref<HTMLElement | null>(null)

const zoomIn = () => {
  console.log('Zoom in')
}

const zoomOut = () => {
  console.log('Zoom out')
}
</script>

<style lang="less" scoped>
.gis-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
}

.gis-toolbar {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.gis-map {
  flex: 1;
  position: relative;
}

.map-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--bg-tertiary) 0%, var(--bg-primary) 100%);
  
  p {
    margin: 8px 0 0;
    font-size: 16px;
  }
  
  .hint {
    font-size: 12px;
    color: var(--text-secondary);
  }
}
</style>
