<template>
  <div class="user-manage">
    <!-- 账号开通口径说明 -->
    <div class="policy-tip">
      <el-icon class="policy-icon"><InfoFilled /></el-icon>
      <span>
        律师账号由管理员在此开通，初始密码请线下告知本人；客户账号由客户在注册页自助注册，
        <b>注册后即可登录，无需审核</b>。
      </span>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-radio-group v-model="query.role" @change="search">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="lawyer">律师</el-radio-button>
        <el-radio-button value="client">客户</el-radio-button>
        <el-radio-button value="admin">管理员</el-radio-button>
      </el-radio-group>

      <el-select v-model="query.status" placeholder="账号状态" clearable class="sel" @change="search">
        <el-option label="正常" :value="1" />
        <el-option label="已禁用" :value="0" />
      </el-select>

      <el-input
        v-model="query.keyword"
        placeholder="账号 / 姓名 / 手机号"
        clearable
        class="kw"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <div class="spacer" />

      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>开通律师账号
      </el-button>
    </div>

    <!-- 列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="username" label="登录账号" min-width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.username }}</span>
            <el-tag v-if="row.id === meId" size="small" effect="plain" class="me-tag">我</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="real_name" label="姓名" min-width="110">
          <template #default="{ row }">{{ row.real_name || '—' }}</template>
        </el-table-column>

        <el-table-column label="角色" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="roleMeta[row.role]?.type" effect="light" size="small">
              {{ roleMeta[row.role]?.label || row.role }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="手机号" width="130">
          <template #default="{ row }">{{ row.phone || '—' }}</template>
        </el-table-column>

        <el-table-column label="关联业务" width="110" align="center">
          <template #default="{ row }">
            <span v-if="row.role === 'lawyer'" class="case-count">{{ row.case_count }} 件</span>
            <el-tag
              v-else-if="row.role === 'client'"
              :type="row.profile_id ? 'success' : 'warning'"
              effect="plain"
              size="small"
              class="profile-tag"
              :title="
                row.profile_id
                  ? `已建档：${row.profile_name || '客户档案'}`
                  : '客户已注册但尚未建档。律师在「客户管理」按此手机号建档后，客户即可看到自己的委托与文书'
              "
            >
              {{ row.profile_id ? '已建档' : '待建档' }}
            </el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'" effect="plain" size="small">
              {{ row.status === 1 ? '正常' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="170" align="center">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              :disabled="row.id === meId"
              @click="openReset(row)"
            >
              重置密码
            </el-button>
            <el-button
              link
              :type="row.status === 1 ? 'danger' : 'success'"
              size="small"
              :disabled="row.id === meId"
              @click="toggleStatus(row)"
            >
              {{ row.status === 1 ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <!-- 开通律师账号 -->
    <el-dialog v-model="createVisible" title="开通律师账号" width="480px" @closed="resetCreate">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
        <el-form-item label="登录账号" prop="username">
          <el-input v-model="form.username" placeholder="建议使用工号，3~64 位" />
        </el-form-item>
        <el-form-item label="真实姓名" prop="real_name">
          <el-input v-model="form.real_name" placeholder="对外展示的律师姓名" />
        </el-form-item>
        <el-form-item label="初始密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="form.phone" placeholder="选填，11 位手机号" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">开通</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog
      v-model="resetVisible"
      :title="`重置密码 · ${resetTarget?.real_name || resetTarget?.username || ''}`"
      width="420px"
      @closed="resetPwdForm"
    >
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="重置后旧密码立即失效，请把新密码线下告知本人"
        class="reset-tip"
      />
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="76px">
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="submitReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, InfoFilled } from '@element-plus/icons-vue'
import { createLawyer, listUsers, resetUserPassword, updateUserStatus } from '@/api/admin'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const meId = computed(() => userStore.userInfo?.id)

const roleMeta = {
  client: { label: '客户', type: 'info' },
  lawyer: { label: '律师', type: 'primary' },
  admin: { label: '管理员', type: 'warning' },
}

const loading = ref(false)
const rows = ref([])
const total = ref(0)

const query = reactive({
  role: 'lawyer',
  status: '',
  keyword: '',
  page: 1,
  page_size: 20,
})

async function load() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.role) delete params.role
    if (params.status === '' || params.status === null) delete params.status
    if (!params.keyword) delete params.keyword
    const data = await listUsers(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

load()

/* ---------- 开通律师账号 ---------- */
const createVisible = ref(false)
const creating = ref(false)
const formRef = ref(null)

const form = reactive({
  username: '',
  real_name: '',
  password: '',
  phone: '',
  email: '',
})

const rules = {
  username: [
    { required: true, message: '请输入登录账号', trigger: 'blur' },
    { min: 3, max: 64, message: '长度 3~64 位', trigger: 'blur' },
  ],
  real_name: [{ required: true, message: '请输入真实姓名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 6, max: 72, message: '长度 6~72 位', trigger: 'blur' },
  ],
  phone: [{ pattern: /^1\d{10}$/, message: '应为 11 位手机号', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}

function openCreate() {
  createVisible.value = true
}

function resetCreate() {
  formRef.value?.clearValidate()
  Object.assign(form, { username: '', real_name: '', password: '', phone: '', email: '' })
}

async function submitCreate() {
  await formRef.value?.validate()
  creating.value = true
  try {
    await createLawyer({
      username: form.username.trim(),
      real_name: form.real_name.trim(),
      password: form.password,
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
    })
    ElMessage.success('账号已开通，请把初始密码线下告知本人')
    createVisible.value = false
    if (query.role !== 'lawyer') query.role = 'lawyer'
    search()
  } finally {
    creating.value = false
  }
}

/* ---------- 禁用 / 启用 ---------- */
async function toggleStatus(row) {
  const disable = row.status === 1
  const tip = disable
    ? `禁用后「${row.real_name || row.username}」将无法登录，历史数据与承办关系保留。确定禁用？`
    : `确定恢复「${row.real_name || row.username}」的登录权限？`
  await ElMessageBox.confirm(tip, disable ? '禁用账号' : '启用账号', {
    type: disable ? 'warning' : 'info',
    confirmButtonText: disable ? '确定禁用' : '确定启用',
  })
  await updateUserStatus(row.id, disable ? 0 : 1)
  ElMessage.success(disable ? '已禁用' : '已启用')
  load()
}

/* ---------- 重置密码 ---------- */
const resetVisible = ref(false)
const resetting = ref(false)
const resetTarget = ref(null)
const pwdFormRef = ref(null)
const pwdForm = reactive({ new_password: '' })

const pwdRules = {
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 72, message: '长度 6~72 位', trigger: 'blur' },
  ],
}

function openReset(row) {
  resetTarget.value = row
  resetVisible.value = true
}

function resetPwdForm() {
  pwdFormRef.value?.clearValidate()
  pwdForm.new_password = ''
  resetTarget.value = null
}

async function submitReset() {
  await pwdFormRef.value?.validate()
  resetting.value = true
  try {
    await resetUserPassword(resetTarget.value.id, pwdForm.new_password)
    ElMessage.success('密码已重置')
    resetVisible.value = false
  } finally {
    resetting.value = false
  }
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.user-manage {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 账号开通口径说明：浅底 + 左侧金色导条 */
.policy-tip {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 11px 14px;
  border-radius: 10px;
  border-left: 3px solid var(--brand-gold);
  background: linear-gradient(90deg, rgba(201, 165, 92, 0.09), rgba(201, 165, 92, 0.03));
  font-size: 13px;
  line-height: 1.65;
  color: var(--brand-text);
}

.policy-tip b {
  font-weight: 600;
  color: var(--brand-ink);
}

.policy-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--brand-gold-deep);
  font-size: 15px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-bar .sel {
  width: 140px;
}

.filter-bar .kw {
  width: 240px;
}

.spacer {
  flex: 1;
}

.table-card {
  border-radius: 12px;
}

.mono {
  font-variant-numeric: tabular-nums;
  color: var(--brand-ink);
}

.me-tag {
  margin-left: 6px;
  transform: scale(0.9);
}

.case-count {
  font-variant-numeric: tabular-nums;
  color: var(--brand-text);
}

.profile-tag {
  cursor: help;
}

.muted {
  color: var(--brand-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 14px;
}

.reset-tip {
  margin-bottom: 14px;
}

@media (max-width: 900px) {
  .filter-bar .kw {
    width: 100%;
  }
}

/* ---------- 手机端：筛选栏竖排占满整行，避免输入框被压成一条 ---------- */
@media (max-width: 768px) {
  .filter-bar {
    gap: 8px;
  }

  .filter-bar .kw,
  .filter-bar .sel,
  .filter-bar .el-select,
  .filter-bar .el-date-editor,
  .filter-bar .client-filter {
    width: 100% !important;
    max-width: none;
  }

  .spacer {
    display: none;
  }
}
</style>
