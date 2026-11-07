<template>
  <div class="login-page">
    <!-- 左侧品牌区 -->
    <div class="brand-side">
      <!-- 背景装饰：网格线 + 金色大字水印 -->
      <div class="bg-grid"></div>
      <div class="bg-watermark">LEX</div>
      <div class="bg-orb"></div>

      <div class="brand-gold-blob"></div>
      <div class="brand-inner">
        <div class="brand-logo-big">
          <div class="seal">
            <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M20 8v24M8 14h24M12 14l-4 8h8l-4-8zm16 0l-4 8h8l-4-8zM13 32h14"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </div>
          <div class="brand-text">
            <div class="name">律所客户智能管理系统</div>
            <div class="en">LAW FIRM INTELLIGENT CMS</div>
          </div>
        </div>

        <!-- 金色分隔线 -->
        <div class="divider"></div>

        <div class="slogan">
          <h2>以专业与智能<br />守护每一份委托</h2>
          <p>客户 · 案件 · 合同 · 收费 · 文书 · AI 法律助手<br />一体化律所智能管理平台</p>
        </div>

        <ul class="points">
          <li v-for="p in points" :key="p">{{ p }}</li>
        </ul>

        <div class="brand-foot">专业 · 严谨 · 高效</div>
      </div>
    </div>

    <!-- 右侧表单区 -->
    <div class="form-side">
      <div class="form-card">
        <h1>欢迎登录</h1>
        <p class="sub">请使用您的账号进入系统</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @keyup.enter="onSubmit"
        >
          <el-form-item label="账号" prop="username">
            <el-input
              v-model="form.username"
              placeholder="手机号 / 工号"
              :prefix-icon="User"
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
          <el-button
            type="primary"
            class="submit"
            :loading="loading"
            @click="onSubmit"
          >
            登 录
          </el-button>
        </el-form>

        <div class="links">
          <span class="tip">委托人还没有账号？</span>
          <el-link type="primary" :underline="false" @click="$router.push('/register')">
            客户注册
          </el-link>
        </div>
      </div>

      <div class="form-foot">律所客户智能管理系统 · Law Firm Intelligent CMS</div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'

const ROLE_HOME = { client: '/client', lawyer: '/lawyer', admin: '/admin' }

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const points = [
  '案件全流程线上化，进度实时可查',
  'AI 法律助手辅助问答、文书与合同审查',
  '收费、日程、文书一体化协同',
]

const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await userStore.login({ username: form.username, password: form.password })
    ElMessage.success(`欢迎回来，${userStore.realName}`)
    const target = route.query.redirect || ROLE_HOME[userStore.role] || '/'
    router.push(target)
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
}

/* ---------- 左侧品牌区 ---------- */
.brand-side {
  flex: 1.1;
  min-width: 0;
  background:
    radial-gradient(ellipse 100% 70% at 20% 0%, rgba(201, 165, 92, 0.16), transparent 55%),
    linear-gradient(160deg, #1a2b4a 0%, var(--brand-navy) 45%, var(--brand-navy-deep) 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

/* 右下角哑光金装饰：大金圈 + 渐变金片 */
.brand-side::after {
  content: '';
  position: absolute;
  right: -100px;
  bottom: -100px;
  width: 520px;
  height: 520px;
  border-radius: 50%;
  border: 2px solid rgba(201, 165, 92, 0.5);
}

.brand-side::before {
  content: '';
  position: absolute;
  right: -10px;
  bottom: -10px;
  width: 360px;
  height: 360px;
  border-radius: 50%;
  border: 1px solid rgba(201, 165, 92, 0.35);
}

/* 背景装饰：暗网格（法律文书/信纸质感） */
.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 44px 44px;
  pointer-events: none;
}

/* 背景装饰：金色大字水印 */
.bg-watermark {
  position: absolute;
  right: -30px;
  top: 6%;
  font-size: 220px;
  font-weight: 700;
  letter-spacing: 4px;
  color: transparent;
  -webkit-text-stroke: 1px rgba(201, 165, 92, 0.14);
  font-family: 'Georgia', 'Times New Roman', serif;
  pointer-events: none;
  user-select: none;
}

/* 背景装饰：左上角淡金光晕 */
.bg-orb {
  position: absolute;
  left: -80px;
  top: -60px;
  width: 340px;
  height: 340px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(201, 165, 92, 0.16), transparent 70%);
  pointer-events: none;
}

.brand-gold-blob {
  position: absolute;
  right: 80px;
  bottom: 50px;
  width: 200px;
  height: 200px;
  border-radius: 50%;
  background: radial-gradient(circle at 32% 30%, rgba(232, 201, 138, 0.5), rgba(201, 165, 92, 0.18) 62%, transparent 75%);
}

.brand-inner {
  padding: 0;
  max-width: 560px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  position: relative;
  z-index: 1;
  transform: translateY(-12px);
}

/* 品牌 Logo（放大居中版） */
.brand-logo-big {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
  color: #fff;
}

.brand-logo-big .seal {
  width: 72px;
  height: 72px;
  border-radius: 18px;
  background: linear-gradient(135deg, var(--brand-gold-light) 0%, var(--brand-gold) 40%, var(--brand-gold-deep) 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 24px rgba(201, 165, 92, 0.35);
}

.brand-logo-big .seal svg {
  width: 46px;
  height: 46px;
}

.brand-logo-big .name {
  font-size: 26px;
  font-weight: 600;
  letter-spacing: 4px;
  line-height: 1.3;
  color: #fff;
}

.brand-logo-big .en {
  font-size: 12px;
  letter-spacing: 4px;
  color: var(--brand-gold-light);
  margin-top: 6px;
}

.slogan {
  margin-top: 40px;
}

/* 金色分隔线：品牌名与标语之间的过渡 */
.divider {
  width: 48px;
  height: 2px;
  margin-top: 34px;
  background: linear-gradient(90deg, transparent, var(--brand-gold), transparent);
}

.slogan h2 {
  font-size: 40px;
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: 3px;
  margin: 0 0 18px;
}

.slogan p {
  font-size: 15px;
  line-height: 2;
  color: rgba(255, 255, 255, 0.6);
  letter-spacing: 1px;
  margin: 0;
}

.points {
  list-style: none;
  margin: 44px 0 0;
  padding: 0;
  text-align: left;
}

.points li {
  position: relative;
  padding-left: 26px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.75);
  line-height: 2.4;
  letter-spacing: 0.5px;
}

.points li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  width: 14px;
  height: 1.5px;
  background: var(--brand-gold);
}

.brand-foot {
  margin-top: 40px;
  font-size: 13px;
  letter-spacing: 8px;
  color: var(--brand-gold-light);
}

/* ---------- 右侧表单区 ---------- */
.form-side {
  width: 480px;
  flex-shrink: 0;
  background: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
}

.form-card {
  width: 340px;
}

.form-card h1 {
  font-size: 26px;
  font-weight: 600;
  color: var(--brand-ink);
  margin: 0 0 6px;
  letter-spacing: 1px;
}

.sub {
  font-size: 13px;
  color: var(--brand-muted);
  margin: 0 0 36px;
}

.form-card :deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--brand-ink);
  padding-bottom: 6px !important;
}

.submit {
  width: 100%;
  height: 46px;
  margin-top: 12px;
  font-size: 15px;
  letter-spacing: 8px;
  text-indent: 8px;
  border: none;
  background: linear-gradient(135deg, var(--brand-navy-soft) 0%, var(--brand-navy) 100%);
}

.submit:hover,
.submit:focus {
  background: linear-gradient(135deg, var(--brand-navy) 0%, var(--brand-navy-deep) 100%);
}

.links {
  margin-top: 24px;
  text-align: center;
  font-size: 13px;
}

.links .tip {
  color: var(--brand-muted);
  margin-right: 6px;
}

.form-foot {
  position: absolute;
  bottom: 28px;
  font-size: 11px;
  letter-spacing: 1px;
  color: #b8bdca;
}

/* 窄屏时隐藏品牌区 */
@media (max-width: 900px) {
  .brand-side {
    display: none;
  }
  .form-side {
    width: 100%;
  }
}

/* 手机端：卡片撑满宽度，压缩纵向间距，避免键盘弹起后按钮被顶出屏幕 */
@media (max-width: 768px) {
  .form-side {
    padding: 24px 18px;
    justify-content: flex-start;
    overflow-y: auto;
    overflow-x: hidden;
  }

  .form-card {
    width: 100%;
    max-width: 420px;
    margin: auto;
  }

  .form-card h1 {
    font-size: 22px;
  }

  .sub {
    margin-bottom: 24px;
  }

  /* 底部版权行英文名较长，窄屏允许换行，否则会横向溢出被裁 */
  .form-foot {
    margin-top: 20px;
    font-size: 10px;
    line-height: 1.6;
    text-align: center;
    white-space: normal;
    overflow-wrap: anywhere;
  }
}
</style>
