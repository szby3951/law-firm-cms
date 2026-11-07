import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 视口断点（与 styles/mobile.css 里的 @media 阈值保持一致）
 *   mobile  ≤ 768px   手机：侧边栏收进抽屉、栅格降为单列/双列
 *   tablet  769–1024  平板：侧边栏保留但收起、栅格两列
 *   desktop > 1024    桌面：完整布局
 *
 * 用 matchMedia 而不是监听 resize：只在跨过断点时触发一次，
 * 滚动、地址栏收起等引起的尺寸抖动不会引发重复渲染。
 */
const MOBILE_QUERY = '(max-width: 768px)'
const TABLET_QUERY = '(min-width: 769px) and (max-width: 1024px)'

export function useBreakpoint() {
  const isMobile = ref(false)
  const isTablet = ref(false)

  let mqMobile = null
  let mqTablet = null

  const sync = () => {
    isMobile.value = mqMobile ? mqMobile.matches : false
    isTablet.value = mqTablet ? mqTablet.matches : false
  }

  // Safari 13 及以下只有 addListener，做个兜底
  const listen = (mq, fn) => {
    if (mq.addEventListener) mq.addEventListener('change', fn)
    else if (mq.addListener) mq.addListener(fn)
  }
  const unlisten = (mq, fn) => {
    if (mq.removeEventListener) mq.removeEventListener('change', fn)
    else if (mq.removeListener) mq.removeListener(fn)
  }

  onMounted(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    mqMobile = window.matchMedia(MOBILE_QUERY)
    mqTablet = window.matchMedia(TABLET_QUERY)
    sync()
    listen(mqMobile, sync)
    listen(mqTablet, sync)
  })

  onBeforeUnmount(() => {
    if (mqMobile) unlisten(mqMobile, sync)
    if (mqTablet) unlisten(mqTablet, sync)
  })

  return { isMobile, isTablet }
}
