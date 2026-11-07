<template>
  <div class="register-page">
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
          <h2>委托事务<br />从此清晰透明</h2>
          <p>注册后即可在线查询案件进度<br />查看文书与账单，随时与律师沟通</p>
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
        <h1>客户注册</h1>
        <p class="sub">填写以下信息创建您的委托人账号</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
        >
          <el-form-item label="姓名" prop="real_name">
            <el-input v-model="form.real_name" placeholder="请输入真实姓名" :prefix-icon="User" />
          </el-form-item>
          <el-form-item label="手机号" prop="phone">
            <el-input v-model="form.phone" placeholder="11 位手机号，作为登录账号" :prefix-icon="Iphone" />
          </el-form-item>
          <el-form-item label="设置密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="至少 6 位"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
          <el-form-item label="确认密码" prop="confirm">
            <el-input
              v-model="form.confirm"
              type="password"
              placeholder="再次输入密码"
              :prefix-icon="Lock"
              show-password
              @keyup.enter="onSubmit"
            />
          </el-form-item>
          <el-button
            type="primary"
            class="submit"
            :loading="loading"
            @click="onSubmit"
          >
            注 册
          </el-button>
        </el-form>

        <div class="links">
          <span class="tip">已有账号？</span>
          <el-link type="primary" :underline="false" @click="$router.push('/login')">
            返回登录
          </el-link>
        </div>
      </div>

      <div class="form-foot">注册即代表同意《委托服务协议》与《隐私政策》</div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Iphone } from '@element-plus/icons-vue'
import { register } from '@/api/auth'

const router = useRouter()
const formRef = ref()
const loading = ref(false)
const form = reactive({ real_name: '', phone: '', password: '', confirm: '' })

const points = [
  '案件进展实时推送，随时掌握动态',
  '在线查阅合同、文书与费用明细',
  'AI 法律助手 7×24 小时解答疑问',
]

const rules = {
  real_name: [
    { required: true, message: '请输入姓名', trigger: 'blur' },
    { max: 64, message: '姓名不能超过 64 个字符', trigger: 'blur' },
  ],
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: /^1\d{10}$/, message: '手机号格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
    { max: 72, message: '密码不能超过 72 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_, value, cb) =>
        value === form.password ? cb() : cb(new Error('两次密码不一致')),
      trigger: 'blur',
    },
  ],
}

async function onSubmit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await register({
      username: form.phone,
      phone: form.phone,
      real_name: form.real_name,
      password: form.password,
    })
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } catch {
    /* 错误提示由 request 拦截器统一处理 */
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-page {
  height: 100%;
  display: flex;
}

/* ---------- 左侧品牌区（与登录页同风格） ---------- */
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
  margin: 0 0 28px;
}

.form-card :deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--brand-ink);
  padding-bottom: 6px !important;
}

.form-card :deep(.el-form-item) {
  margin-bottom: 18px;
}

.submit {
  width: 100%;
  height: 46px;
  margin-top: 8px;
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
  margin-top: 20px;
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

@media (max-width: 900px) {
  .brand-side {
    display: none;
  }
  .form-side {
    width: 100%;
  }
}
</style>
