/**
 * FORGE AI — 前端 SPA
 * Hash 路由：#projects | #config | #devops
 */

// ============================================================
// 全局状态
// ============================================================
let currentSessionId = null;
let currentProjectId = null;
let currentBuildProjectId = null;
let eventSource = null;
let currentOpsProjectId = null;

// ============================================================
// 路由
// ============================================================
const PAGES = ['projects', 'config', 'devops'];

function navigate(page) {
  if (!PAGES.includes(page)) page = 'projects';
  PAGES.forEach(p => {
    document.getElementById(`page-${p}`).classList.add('hidden');
  });
  document.getElementById(`page-${page}`).classList.remove('hidden');

  document.querySelectorAll('.nav-links a').forEach(a => {
    a.classList.toggle('active', a.dataset.page === page);
  });

  if (page === 'projects') loadProjects();
  if (page === 'config') loadConfig();
  if (page === 'devops') loadOpsProjects();
}

window.addEventListener('hashchange', () => {
  const hash = location.hash.replace('#', '') || 'projects';
  navigate(hash);
});

document.querySelectorAll('.nav-links a').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    const page = a.dataset.page;
    history.pushState(null, '', `#${page}`);
    navigate(page);
  });
});

document.getElementById('new-project-btn').addEventListener('click', openNewProjectModal);

// ============================================================
// Toast 通知
// ============================================================
function toast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  const icon = type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ';
  el.innerHTML = `<span style="color:var(--${type === 'success' ? 'accent' : type === 'error' ? 'danger' : 'text2'})">${icon}</span>${msg}`;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ============================================================
// 模态框通用
// ============================================================
function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

// 点击遮罩关闭
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', e => {
    if (e.target === overlay) overlay.classList.add('hidden');
  });
});

// ============================================================
// 工具函数
// ============================================================
function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' });
  } catch { return iso; }
}

function statusPill(status) {
  const map = {
    building: ['pill-building', '构建中'],
    completed: ['pill-completed', '已完成'],
    failed: ['pill-failed', '失败'],
    unknown: ['pill-unknown', '未知'],
  };
  const [cls, label] = map[status] || map.unknown;
  return `<span class="status-pill ${cls}">${label}</span>`;
}

const CATEGORY_LABELS = {
  general: '通用', frontend: '前端', backend: '后端', testing: '测试',
  devops: 'DevOps', execution: '执行', development: '开发', architecture: '架构',
};
function categoryTag(cat) {
  const label = CATEGORY_LABELS[cat] || cat;
  return `<span class="category-tag cat-${cat}">${label}</span>`;
}

const STAGE_META = {
  requirements_agent: { icon: '📋', name: '需求分析', sub: 'PRD → 任务拆解' },
  architecture_agent: { icon: '🏗️', name: '架构设计', sub: '系统图谱生成' },
  uiux_agent:         { icon: '🎨', name: 'UI/UX 设计', sub: '页面 & 组件定义' },
  coding_agent:       { icon: '⌨️', name: '代码生成', sub: 'Agent 编写中' },
  testing_agent:      { icon: '🧪', name: '自动测试', sub: '单元 & 集成测试' },
  devops_agent:       { icon: '🚢', name: 'DevOps', sub: 'Docker & CI/CD' },
};
const STAGE_ORDER = ['requirements_agent','architecture_agent','uiux_agent','coding_agent','testing_agent','devops_agent'];

function renderPipelineTrack(stages, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = '';
  STAGE_ORDER.forEach((key, i) => {
    const meta = STAGE_META[key];
    const stageInfo = stages ? stages[key] : null;
    const status = stageInfo ? stageInfo.status : 'pending';
    const cls = status === 'completed' ? 'stage-done' : status === 'running' ? 'stage-running' : status === 'failed' ? 'stage-failed' : 'stage-pending';
    el.innerHTML += `
      <div class="pipeline-stage ${cls}" data-stage="${key}">
        <div class="stage-dot"></div>
        <div class="stage-icon">${meta.icon}</div>
        <div class="stage-name">${meta.name}</div>
        <div class="stage-sub">${status === 'running' ? 'Agent 运行中…' : status === 'completed' ? '已完成 ✓' : status === 'failed' ? '失败 ✗' : meta.sub}</div>
      </div>
      ${i < STAGE_ORDER.length - 1 ? '<div class="pipeline-arrow">→</div>' : ''}
    `;
  });
}

// ============================================================
// 项目页
// ============================================================
async function loadProjects() {
  const grid = document.getElementById('projects-grid');
  const loading = document.getElementById('projects-loading');
  const empty = document.getElementById('projects-empty');
  const count = document.getElementById('projects-count');

  loading.classList.remove('hidden');
  grid.innerHTML = '';
  empty.classList.add('hidden');

  try {
    const res = await fetch('/api/projects/');
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const projects = await res.json();

    loading.classList.add('hidden');
    count.textContent = `${projects.length} 个项目`;

    if (projects.length === 0) {
      empty.classList.remove('hidden');
      return;
    }

    projects.forEach(p => {
      const card = document.createElement('div');
      card.className = 'project-card';
      card.innerHTML = `
        <div class="project-card-header">
          <div>
            <div class="project-card-name">${escHtml(p.name || p.id)}</div>
            <div class="project-card-desc">${escHtml(p.description || '暂无描述')}</div>
          </div>
          ${statusPill(p.status)}
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${p.progress || 0}%"></div></div>
        <div class="project-card-meta">
          <span class="meta-item">进度 <strong>${p.progress || 0}%</strong></span>
          <span class="meta-item">创建 <strong>${formatDate(p.created_at)}</strong></span>
          <span class="meta-item">阶段 <strong>${p.current_stage || '—'}</strong></span>
        </div>
        ${p.workspace_path ? `<div style="margin-top:8px;font-size:11px;color:var(--muted);font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(p.workspace_path)}">📁 ${escHtml(p.workspace_path)}</div>` : ''}
        <div style="margin-top:10px;text-align:right">
          <button class="btn-delete-project" data-id="${escHtml(p.id)}" data-name="${escHtml(p.name || p.id)}" style="font-size:11px;padding:3px 10px;background:transparent;border:1px solid var(--danger);color:var(--danger);border-radius:4px;cursor:pointer">删除</button>
        </div>
      `;
      card.addEventListener('click', () => openProjectDetail(p.id));
      card.querySelector('.btn-delete-project').addEventListener('click', e => {
        e.stopPropagation();
        deleteProject(p.id, p.name || p.id);
      });
      grid.appendChild(card);
    });
  } catch (e) {
    loading.classList.add('hidden');
    toast('加载项目失败：' + e.message, 'error');
  }
}

async function deleteProject(id, name) {
  if (!confirm(`⚠️ 高危操作：即将永久删除项目「${name}」\n\n项目记录及磁盘上所有相关文件将被彻底删除，无法恢复！\n\n确认删除？`)) return;
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(id)}?delete_files=true`, { method: 'DELETE' });
    if (!res.ok && res.status !== 204) throw new Error(res.statusText);
    toast(`项目「${name}」已删除`, 'success');
    loadProjects();
  } catch (e) {
    toast('删除失败：' + e.message, 'error');
  }
}

function openNewProjectModal() { openModal('modal-new-project'); }

// 宿主机项目目录（从后端获取，用于展示提示）
let _projectsHostDir = './projects';
fetch('/api/config/projects-host-dir').then(r => r.json()).then(d => {
  _projectsHostDir = d.host_dir || './projects';
  const hint = document.getElementById('workspace-host-hint');
  if (hint) hint.textContent = `容器内 /app/projects/ → 宿主机 ${_projectsHostDir}/`;
}).catch(() => {});

function fillDefaultWorkspace() {
  const desc = document.getElementById('new-project-desc').value.trim();
  const slug = desc.slice(0, 20).replace(/\s+/g, '-').replace(/[^a-zA-Z0-9\u4e00-\u9fa5-]/g, '') || 'new-project';
  const ts = new Date().toISOString().slice(0,10).replace(/-/g,'');
  // 始终使用容器内绝对路径，确保落在 /app/projects 挂载目录下
  document.getElementById('new-project-workspace').value = `/app/projects/proj_${ts}_${slug}`;
}

async function pickFolder() {
  try {
    const res = await fetch('/api/config/pick-folder');
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      toast(err.detail || '无法打开文件夹选择框', 'error');
      return;
    }
    const data = await res.json();
    document.getElementById('new-project-workspace').value = data.path;
  } catch (e) {
    toast('文件夹选择失败：' + e.message, 'error');
  }
}

async function startBuild() {
  const desc = document.getElementById('new-project-desc').value.trim();
  if (desc.length < 10) { toast('需求描述至少 10 个字符', 'error'); return; }

  const workspace = document.getElementById('new-project-workspace').value.trim();
  const btn = document.getElementById('start-build-btn');
  btn.disabled = true;
  btn.textContent = '启动中...';

  try {
    const body = { description: desc };
    if (workspace) body.workspace_path = workspace;

    const res = await fetch('/api/factory/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    currentSessionId = data.session_id;
    currentBuildProjectId = data.project_id;

    closeModal('modal-new-project');
    document.getElementById('new-project-desc').value = '';
    openBuildModal(data.project_id, data.session_id);
  } catch (e) {
    toast('启动失败：' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '开始构建 →';
  }
}

function openBuildModal(projectId, sessionId) {
  document.getElementById('detail-title').textContent = '构建进度 — ' + projectId;
  document.getElementById('detail-building').classList.remove('hidden');
  document.getElementById('detail-done-view').classList.add('hidden');
  document.getElementById('detail-done').classList.add('hidden');
  document.getElementById('detail-error').classList.add('hidden');
  document.getElementById('detail-clarify').classList.add('hidden');
  document.getElementById('detail-llm-output').textContent = '';

  renderPipelineTrack({}, 'detail-pipeline');
  openModal('modal-project-detail');
  startSSE(sessionId, projectId);
}

async function openProjectDetail(projectId) {
  try {
    const res = await fetch(`/api/projects/${projectId}`);
    if (!res.ok) throw new Error('加载失败');
    const project = await res.json();

    document.getElementById('detail-title').textContent = (project.name || projectId);

    if (project.status === 'building' && currentBuildProjectId === projectId) {
      // 正在构建中，切换到实时视图
      document.getElementById('detail-building').classList.remove('hidden');
      document.getElementById('detail-done-view').classList.add('hidden');
      renderPipelineTrack(project.stages, 'detail-pipeline');
    } else {
      // 已完成或失败，显示静态详情
      document.getElementById('detail-building').classList.add('hidden');
      document.getElementById('detail-done-view').classList.remove('hidden');

      renderPipelineTrack(project.stages, 'detail-pipeline-static-track');
      renderArtifacts(project.stages);
      renderFileList(project.files, projectId);

      // 显示 workspace 路径
      const wsEl = document.getElementById('detail-workspace-path');
      if (wsEl) wsEl.textContent = project.workspace_path || '—';
    }

    openModal('modal-project-detail');
  } catch (e) {
    toast('打开项目失败：' + e.message, 'error');
  }
}

function renderArtifacts(stages) {
  const container = document.getElementById('detail-artifacts-list');
  container.innerHTML = '';
  if (!stages) return;

  STAGE_ORDER.forEach(key => {
    const stage = stages[key];
    if (!stage) return;
    const meta = STAGE_META[key];
    const summary = stage.artifact_summary || {};
    const status = stage.status || 'pending';
    const statusIcon = status === 'completed' ? '✓' : status === 'failed' ? '✗' : status === 'running' ? '⟳' : '○';
    const statusColor = status === 'completed' ? 'var(--accent)' : status === 'failed' ? 'var(--danger)' : 'var(--muted)';

    let summaryHtml = '';
    const entries = Object.entries(summary);
    if (entries.length > 0) {
      summaryHtml = `<div class="artifact-kv">`;
      entries.forEach(([k, v]) => {
        summaryHtml += `<span class="kv-key">${k}</span><span class="kv-val">${JSON.stringify(v)}</span>`;
      });
      summaryHtml += `</div>`;
    } else {
      summaryHtml = `<span style="color:var(--muted);font-size:13px">${status === 'pending' ? '尚未执行' : status === 'running' ? '执行中...' : '无摘要数据'}</span>`;
    }

    container.innerHTML += `
      <div class="artifact-card">
        <div class="artifact-header" onclick="this.parentElement.classList.toggle('expanded')">
          <div class="artifact-title">
            <span>${meta.icon}</span>
            <span>${meta.name}</span>
            <span style="font-size:12px;color:${statusColor}">${statusIcon}</span>
          </div>
          <span class="artifact-chevron">▶</span>
        </div>
        <div class="artifact-body">${summaryHtml}</div>
      </div>
    `;
  });
}

function renderFileList(files, projectId) {
  const container = document.getElementById('detail-files-list');
  container.innerHTML = '';
  if (!files || files.length === 0) {
    container.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:8px">暂无文件</div>';
    return;
  }
  files.slice(0, 80).forEach(f => {
    const div = document.createElement('div');
    div.className = 'file-item';
    const ext = f.split('.').pop().toLowerCase();
    const icon = ['py','js','ts','java','go'].includes(ext) ? '📄' : ['html','css'].includes(ext) ? '🎨' : ['yml','yaml','json'].includes(ext) ? '⚙️' : ['md'].includes(ext) ? '📝' : ['dockerfile','sh'].includes(ext) ? '🐳' : '📄';
    div.innerHTML = `<span class="file-icon">${icon}</span>${escHtml(f)}`;
    div.addEventListener('click', () => {
      window.open(`/api/projects/${projectId}/file?path=${encodeURIComponent(f)}`, '_blank');
    });
    container.appendChild(div);
  });
  if (files.length > 80) {
    container.innerHTML += `<div style="color:var(--muted);font-size:12px;padding:8px">... 共 ${files.length} 个文件</div>`;
  }
}

// ============================================================
// SSE & 构建流
// ============================================================
function startSSE(sessionId, projectId) {
  if (eventSource) eventSource.close();

  appendBuildOutput('[连接实时进度流...]\n');
  eventSource = new EventSource(`/api/factory/stream/${sessionId}`);

  eventSource.addEventListener('started', e => {
    const d = JSON.parse(e.data);
    appendBuildOutput(`[${d.message}]\n`);
  });

  eventSource.addEventListener('stage_start', e => {
    const d = JSON.parse(e.data);
    setBuildStage(d.stage, 'running');
    appendBuildOutput(`\n▶ ${d.message || d.stage}\n`);
  });

  eventSource.addEventListener('stage_complete', e => {
    const d = JSON.parse(e.data);
    setBuildStage(d.stage, 'completed');
    appendBuildOutput(`✓ ${d.message || d.stage}\n`);
  });

  eventSource.addEventListener('stage_error', e => {
    const d = JSON.parse(e.data);
    setBuildStage(d.stage, 'failed');
    appendBuildOutput(`✗ 错误：${d.message}\n`);
  });

  eventSource.addEventListener('llm_stream', e => {
    const d = JSON.parse(e.data);
    appendBuildOutput(d.content || '');
  });

  eventSource.addEventListener('clarify_needed', e => {
    const d = JSON.parse(e.data);
    showClarifyPanel(d.questions || [], d.message || '');
  });

  eventSource.addEventListener('done', e => {
    const d = JSON.parse(e.data);
    eventSource.close();
    eventSource = null;
    showBuildDone(d.message || '构建完成！', projectId);
    loadProjects();
  });

  eventSource.addEventListener('error', e => {
    const d = e.data ? JSON.parse(e.data) : {};
    if (eventSource) eventSource.close();
    eventSource = null;
    showBuildError(d.message || '未知错误');
  });

  eventSource.onerror = () => {
    appendBuildOutput('\n[SSE 连接中断]\n');
  };
}

function appendBuildOutput(text) {
  const el = document.getElementById('detail-llm-output');
  if (!el) return;
  el.textContent += text;
  el.scrollTop = el.scrollHeight;
}

function setBuildStage(stageName, status) {
  const el = document.querySelector(`#detail-pipeline [data-stage="${stageName}"]`);
  if (!el) return;
  el.className = `pipeline-stage stage-${status === 'completed' ? 'done' : status === 'running' ? 'running' : status === 'failed' ? 'failed' : 'pending'}`;
  const meta = STAGE_META[stageName] || {};
  el.querySelector('.stage-sub').textContent =
    status === 'running' ? 'Agent 运行中…' :
    status === 'completed' ? '已完成 ✓' :
    status === 'failed' ? '失败 ✗' : (meta.sub || '');
}

function showClarifyPanel(questions, message) {
  const panel = document.getElementById('detail-clarify');
  const qEl = document.getElementById('detail-clarify-questions');
  qEl.textContent = message || questions.map((q, i) => `${i + 1}. ${q}`).join('\n');
  panel.classList.remove('hidden');
}

async function submitClarify() {
  const answer = document.getElementById('detail-clarify-answer').value.trim();
  if (!answer) return;
  try {
    const res = await fetch(`/api/factory/clarify/${currentSessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
    if (!res.ok) throw new Error('提交失败');
    document.getElementById('detail-clarify').classList.add('hidden');
    document.getElementById('detail-clarify-answer').value = '';
    appendBuildOutput('\n[用户已回答，继续构建...]\n');
  } catch (e) {
    toast('提交失败：' + e.message, 'error');
  }
}

function showBuildDone(message, projectId) {
  document.getElementById('detail-done').classList.remove('hidden');
  document.getElementById('detail-done-msg').textContent = message;
  const viewBtn = document.getElementById('detail-view-files-btn');
  viewBtn.onclick = () => window.open(`/api/projects/${projectId}/files`, '_blank');
  currentBuildProjectId = null;
  toast('🎉 ' + message, 'success');
}

function showBuildError(message) {
  document.getElementById('detail-error').classList.remove('hidden');
  document.getElementById('detail-error-msg').textContent = message;
  toast('构建出错：' + message, 'error');
}

// ============================================================
// 配置页
// ============================================================
const AGENT_LABELS = {
  requirements: { name: '需求分析',  hint: 'RequirementsAgent' },
  architecture: { name: '架构设计',  hint: 'ArchitectureAgent' },
  ui_ux:        { name: 'UI/UX 设计', hint: 'UIUXAgent' },
  coding:       { name: '代码生成',  hint: 'CodingAgent' },
  testing:      { name: '自动测试',  hint: 'TestingAgent' },
  devops:       { name: 'DevOps',    hint: 'DevOpsAgent' },
};

// 缓存已加载的供应商列表，renderAgentsForm 需要用到
let _cachedProviders = [];

async function loadConfig() {
  document.querySelectorAll('.config-tab').forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll('.config-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.config-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
      if (tab.dataset.tab === 'skills') loadSkills();
    };
  });

  try {
    const res = await fetch('/api/config/');
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const config = await res.json();
    _cachedProviders = config.llm_providers || [];
    renderProvidersTable(_cachedProviders);
    renderAgentsForm(config.agents || {}, _cachedProviders);
    renderDockerForm(config.docker || {});
    renderGitForm(config.git || {});
  } catch (e) {
    toast('加载配置失败：' + e.message, 'error');
  }
}

// ---- 供应商管理 ----

// 模型列表浮层
let _modelsPopover = null;
function showModelsPopover(btn, providerId) {
  // 关闭已有浮层
  if (_modelsPopover) { _modelsPopover.remove(); _modelsPopover = null; }
  const provider = _cachedProviders.find(p => p.id === providerId);
  if (!provider) return;
  const models = provider.models || [];

  const pop = document.createElement('div');
  pop.style.cssText = 'position:fixed;z-index:9999;background:#1a1b2e;border:1px solid rgba(255,255,255,0.15);border-radius:8px;padding:10px 0;min-width:240px;max-width:340px;max-height:320px;overflow-y:auto;box-shadow:0 12px 32px rgba(0,0,0,0.7)';
  pop.innerHTML = `
    <div style="padding:4px 14px 8px;font-size:11px;color:#888;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:4px">全部模型（${models.length}）</div>
    ${models.map(m => `<div style="padding:5px 14px;font-family:var(--mono);font-size:12px;color:#c8cde4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${escHtml(m)}">${escHtml(m)}</div>`).join('')}
  `;
  document.body.appendChild(pop);
  _modelsPopover = pop;

  // 定位到按钮下方
  const rect = btn.getBoundingClientRect();
  const popH = Math.min(320, models.length * 29 + 36);
  const top = rect.bottom + window.scrollY + 4;
  const left = Math.min(rect.left + window.scrollX, window.innerWidth - 340);
  pop.style.top = `${top}px`;
  pop.style.left = `${left}px`;

  // 点击外部关闭
  setTimeout(() => {
    document.addEventListener('click', function _close(e) {
      if (!pop.contains(e.target) && e.target !== btn) {
        pop.remove(); _modelsPopover = null;
        document.removeEventListener('click', _close);
      }
    });
  }, 0);
}

function renderProvidersTable(providers) {
  const tbody = document.getElementById('providers-tbody');
  if (!providers.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:20px">暂无供应商，点击"+ 添加供应商"开始配置</td></tr>';
    return;
  }

  const typeStyle = {
    anthropic:        { bg: 'rgba(205,127,50,0.12)', color: '#e8a84a', border: 'rgba(205,127,50,0.3)',  label: 'Anthropic' },
    openai:           { bg: 'rgba(16,185,129,0.12)', color: '#10b981', border: 'rgba(16,185,129,0.3)',  label: 'OpenAI' },
    openai_compatible:{ bg: 'rgba(99,102,241,0.12)', color: '#818cf8', border: 'rgba(99,102,241,0.3)',  label: 'OpenAI 兼容' },
  };

  tbody.innerHTML = providers.map(p => {
    const safeId   = p.id.replace(/'/g, "\\'");
    const safeName = (p.name || p.id).replace(/'/g, "\\'");
    const ts = typeStyle[p.provider] || { bg: 'rgba(255,255,255,0.06)', color: 'var(--text2)', border: 'rgba(255,255,255,0.15)', label: p.provider };

    const typeBadge = `<span style="display:inline-block;padding:2px 9px;font-size:11px;border-radius:12px;font-weight:500;background:${ts.bg};color:${ts.color};border:0.5px solid ${ts.border};white-space:nowrap">${ts.label}</span>`;

    const models = p.models || [];
    const MAX_SHOW = 4;
    let modelHtml;
    if (!models.length) {
      modelHtml = '<span style="color:var(--muted);font-size:12px">—</span>';
    } else {
      const shown = models.slice(0, MAX_SHOW).map(m =>
        `<span style="display:inline-block;margin:2px 3px 2px 0;padding:1px 7px;background:rgba(255,255,255,0.06);border:0.5px solid rgba(255,255,255,0.1);border-radius:10px;font-family:var(--mono);font-size:11px;color:var(--text2);white-space:nowrap;max-width:150px;overflow:hidden;text-overflow:ellipsis;vertical-align:middle" title="${escHtml(m)}">${escHtml(m)}</span>`
      ).join('');
      const extra = models.length > MAX_SHOW
        ? `<span data-provider-id="${escHtml(p.id)}" onclick="showModelsPopover(this,'${safeId}')" style="display:inline-block;margin:2px 0;padding:1px 8px;background:rgba(99,102,241,0.12);border:0.5px solid rgba(99,102,241,0.3);border-radius:10px;font-size:11px;color:#818cf8;vertical-align:middle;cursor:pointer;user-select:none">+${models.length - MAX_SHOW} 更多</span>`
        : '';
      modelHtml = shown + extra;
    }

    return `<tr>
      <td><strong>${escHtml(p.name || p.id)}</strong></td>
      <td>${typeBadge}</td>
      <td style="font-family:var(--mono);font-size:11px;color:var(--muted);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(p.base_url || '')}">${escHtml(p.base_url || '—')}</td>
      <td style="max-width:260px">${modelHtml}</td>
      <td style="white-space:nowrap">
        <button class="btn btn-ghost btn-sm" onclick="openProviderModal('${safeId}')">编辑</button>
        <button class="btn btn-ghost btn-sm" style="color:var(--danger)" onclick="deleteProvider('${safeId}','${safeName}')">删除</button>
      </td>
    </tr>`;
  }).join('');
}

function _syncTestModelOptions() {
  const models = document.getElementById('provider-models').value
    .split('\n').map(s => s.trim()).filter(Boolean);
  const sel = document.getElementById('provider-test-model');
  const cur = sel.value;
  sel.innerHTML = models.length
    ? models.map(m => `<option value="${escHtml(m)}" ${m === cur ? 'selected' : ''}>${escHtml(m)}</option>`).join('')
    : '<option value="">— 先填写模型列表 —</option>';
  document.getElementById('provider-test-result').textContent = '';
}

function openProviderModal(providerId) {
  const isEdit = !!providerId;
  document.getElementById('provider-modal-title').textContent = isEdit ? '编辑 LLM 供应商' : '添加 LLM 供应商';
  document.getElementById('provider-edit-id').value = providerId || '';

  if (isEdit) {
    const p = _cachedProviders.find(x => x.id === providerId) || {};
    document.getElementById('provider-name').value = p.name || '';
    document.getElementById('provider-type').value = p.provider || 'openai_compatible';
    document.getElementById('provider-base-url').value = p.base_url || '';
    document.getElementById('provider-api-key').value = p.api_key || '';
    document.getElementById('provider-models').value = (p.models || []).join('\n');
  } else {
    document.getElementById('provider-name').value = '';
    document.getElementById('provider-type').value = 'openai_compatible';
    document.getElementById('provider-base-url').value = '';
    document.getElementById('provider-api-key').value = '';
    document.getElementById('provider-models').value = '';
  }
  onProviderTypeChange();
  _syncTestModelOptions();
  // 模型列表变化时同步测试下拉框
  document.getElementById('provider-models').oninput = _syncTestModelOptions;
  openModal('modal-provider');
}

function onProviderTypeChange() {
  const type = document.getElementById('provider-type').value;
  document.getElementById('provider-url-row').style.display =
    type === 'openai_compatible' ? '' : 'none';
}

function _providerBody(model) {
  return {
    provider: document.getElementById('provider-type').value,
    base_url: document.getElementById('provider-base-url').value.trim(),
    api_key:  document.getElementById('provider-api-key').value,
    model: model || '',
  };
}

async function fetchProviderModels() {
  const btn = document.getElementById('fetch-models-btn');
  const status = document.getElementById('fetch-models-status');
  const modelsEl = document.getElementById('provider-models');
  btn.disabled = true;
  btn.textContent = '获取中...';
  status.textContent = '正在请求模型列表...';
  try {
    const res = await fetch('/api/config/llm-providers/fetch-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_providerBody()),
    });
    const data = await res.json();
    if (data.ok && data.models && data.models.length > 0) {
      modelsEl.value = data.models.join('\n');
      status.style.color = 'var(--accent)';
      status.textContent = `✓ 获取到 ${data.models.length} 个模型`;
      _syncTestModelOptions();
    } else {
      status.style.color = 'var(--danger)';
      status.textContent = `✗ ${data.error || '未获取到模型列表'}`;
    }
  } catch (e) {
    status.style.color = 'var(--danger)';
    status.textContent = `✗ 请求异常：${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = '获取模型列表';
  }
}

async function testProvider() {
  const model = document.getElementById('provider-test-model').value;
  if (!model) { toast('请先点击「获取模型列表」，再选择模型进行测试', 'error'); return; }

  const btn = document.getElementById('provider-test-btn');
  const result = document.getElementById('provider-test-result');
  btn.disabled = true;
  btn.textContent = '测试中...';
  result.style.color = 'var(--muted)';
  result.textContent = '正在连接...';

  try {
    const res = await fetch('/api/config/llm-providers/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_providerBody(model)),
    });
    const data = await res.json();
    if (data.ok) {
      result.style.color = 'var(--accent)';
      result.textContent = `✓ 连通成功  ${data.elapsed_ms}ms  回复：${data.reply}`;
    } else {
      result.style.color = 'var(--danger)';
      result.textContent = `✗ 连接失败  ${data.elapsed_ms}ms  ${data.error}`;
    }
  } catch (e) {
    result.style.color = 'var(--danger)';
    result.textContent = `✗ 请求异常：${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = '测试';
  }
}

async function saveProvider() {
  const id = document.getElementById('provider-edit-id').value;
  const body = {
    id,
    name: document.getElementById('provider-name').value.trim(),
    provider: document.getElementById('provider-type').value,
    base_url: document.getElementById('provider-base-url').value.trim(),
    api_key: document.getElementById('provider-api-key').value,
    models: document.getElementById('provider-models').value
      .split('\n').map(s => s.trim()).filter(Boolean),
  };
  if (!body.name) { toast('请填写供应商名称', 'error'); return; }

  try {
    const res = id
      ? await fetch(`/api/config/llm-providers/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      : await fetch('/api/config/llm-providers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const saved = await res.json();

    if (id) {
      _cachedProviders = _cachedProviders.map(p => p.id === id ? saved : p);
    } else {
      _cachedProviders.push(saved);
    }
    renderProvidersTable(_cachedProviders);
    renderAgentsForm(await _loadAgentsConfig(), _cachedProviders);
    closeModal('modal-provider');
    toast(id ? '供应商已更新' : '供应商已添加', 'success');
  } catch (e) {
    toast('保存失败：' + e.message, 'error');
  }
}

async function deleteProvider(id, name) {
  if (!confirm(`确认删除供应商「${name}」？`)) return;
  try {
    const res = await fetch(`/api/config/llm-providers/${id}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error(res.statusText);
    _cachedProviders = _cachedProviders.filter(p => p.id !== id);
    renderProvidersTable(_cachedProviders);
    renderAgentsForm(await _loadAgentsConfig(), _cachedProviders);
    toast('供应商已删除', 'success');
  } catch (e) {
    toast('删除失败：' + e.message, 'error');
  }
}

async function _loadAgentsConfig() {
  const res = await fetch('/api/config/');
  const cfg = await res.json();
  return cfg.agents || {};
}

// ---- Agent 模型分配 ----

// 供应商变更时更新对应的模型下拉列表
function onAgentProviderChange(agentKey) {
  const provId = document.getElementById(`agent-${agentKey}-provider-id`).value;
  const modelSel = document.getElementById(`agent-${agentKey}-model`);
  const provider = _cachedProviders.find(p => p.id === provId);
  const models = provider?.models || [];
  const current = modelSel.value;
  modelSel.innerHTML = models.length
    ? models.map(m => `<option value="${escHtml(m)}" ${m === current ? 'selected' : ''}>${escHtml(m)}</option>`).join('')
    : '<option value="">— 该供应商暂无模型 —</option>';
}

function renderAgentsForm(agentsConfig, providers) {
  const container = document.getElementById('agents-config-form');
  container.innerHTML = '';

  Object.entries(AGENT_LABELS).forEach(([key, meta]) => {
    const cfg  = agentsConfig[key] || {};
    // 旧格式兼容：没有 provider_id 时按 model 名匹配供应商
    let provId = cfg.provider_id || '';
    if (!provId && cfg.model) {
      const matched = providers.find(p => (p.models || []).includes(cfg.model));
      if (matched) provId = matched.id;
    }
    const model  = cfg.model || '';
    const temp   = cfg.temperature ?? 0.2;
    const maxTok = cfg.max_tokens || 16384;

    // 根据已选供应商构建模型选项
    const providerModels = providers.find(p => p.id === provId)?.models || [];
    const modelOptions = providerModels.length
      ? providerModels.map(m => `<option value="${escHtml(m)}" ${m === model ? 'selected' : ''}>${escHtml(m)}</option>`).join('')
      : (model ? `<option value="${escHtml(model)}" selected>${escHtml(model)}</option>` : '<option value="">— 请先选择供应商 —</option>');

    const providerOptions = `<option value="">— 请选择供应商 —</option>` +
      providers.map(p => `<option value="${escHtml(p.id)}" ${p.id === provId ? 'selected' : ''}>${escHtml(p.name || p.id)}</option>`).join('');

    container.innerHTML += `
      <div style="display:grid;grid-template-columns:140px 160px 1fr 90px 110px;gap:12px;align-items:center;padding:10px 20px;border-bottom:0.5px solid rgba(255,255,255,0.04)">
        <div>
          <div style="font-size:13px;font-weight:500;color:var(--text)">${meta.name}</div>
          <div style="font-size:11px;color:var(--muted);font-family:var(--mono);margin-top:2px">${meta.hint}</div>
        </div>
        <select class="form-select" id="agent-${key}-provider-id" style="padding:8px 10px"
          onchange="onAgentProviderChange('${key}')">
          ${providerOptions}
        </select>
        <select class="form-select" id="agent-${key}-model" style="padding:8px 10px">
          ${modelOptions}
        </select>
        <input class="form-input" id="agent-${key}-temperature" type="number"
          min="0" max="2" step="0.05" value="${temp}"
          style="padding:8px 10px;text-align:center" />
        <input class="form-input" id="agent-${key}-max_tokens" type="number"
          value="${maxTok}"
          style="padding:8px 10px;text-align:center" />
      </div>
    `;
  });
}

async function saveAgentsConfig() {
  const agents = {};
  for (const key of Object.keys(AGENT_LABELS)) {
    agents[key] = {
      provider_id: document.getElementById(`agent-${key}-provider-id`)?.value || '',
      model:       document.getElementById(`agent-${key}-model`)?.value || '',
      temperature: parseFloat(document.getElementById(`agent-${key}-temperature`)?.value || '0.2'),
      max_tokens:  parseInt(document.getElementById(`agent-${key}-max_tokens`)?.value || '16384'),
    };
  }

  try {
    const res = await fetch('/api/config/');
    const full = await res.json();
    full.agents = agents;
    const saveRes = await fetch('/api/config/', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(full),
    });
    if (!saveRes.ok) throw new Error((await saveRes.json()).detail);
    toast('Agent 模型分配已保存', 'success');
  } catch (e) {
    toast('保存失败：' + e.message, 'error');
  }
}

function renderDockerForm(docker) {
  document.getElementById('docker-mem').value = docker.mem_limit || '512m';
  document.getElementById('docker-cpu').value = docker.cpu_quota || 50000;
  document.getElementById('docker-timeout').value = docker.timeout_seconds || 120;
  document.getElementById('docker-network').checked = docker.network_disabled !== false;
}

async function saveDockerConfig() {
  const body = {
    mem_limit: document.getElementById('docker-mem').value,
    cpu_quota: parseInt(document.getElementById('docker-cpu').value),
    timeout_seconds: parseInt(document.getElementById('docker-timeout').value),
    network_disabled: document.getElementById('docker-network').checked,
  };
  try {
    const res = await fetch('/api/config/docker', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error();
    toast('Docker 配置已保存', 'success');
  } catch { toast('保存失败', 'error'); }
}

function renderGitForm(git) {
  document.getElementById('git-enabled').checked = !!git.enabled;
  document.getElementById('git-remote').value = git.remote_url || '';
  document.getElementById('git-branch').value = git.default_branch || 'main';
  document.getElementById('git-autopush').checked = !!git.auto_push;
}

async function saveGitConfig() {
  const body = {
    enabled: document.getElementById('git-enabled').checked,
    remote_url: document.getElementById('git-remote').value,
    default_branch: document.getElementById('git-branch').value || 'main',
    auto_push: document.getElementById('git-autopush').checked,
  };
  try {
    const res = await fetch('/api/config/git', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error();
    toast('Git 配置已保存', 'success');
  } catch { toast('保存失败', 'error'); }
}

// ============================================================
// Skills 管理
// ============================================================
async function loadSkills() {
  try {
    const res = await fetch('/api/skills/');
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const skills = await res.json();
    renderSkillsTable(skills);
  } catch (e) {
    toast('加载 Skills 失败：' + e.message, 'error');
  }
}

function renderSkillsTable(skills) {
  const tbody = document.getElementById('skills-tbody');
  const empty = document.getElementById('skills-empty');
  const count = document.getElementById('skills-count');

  count.textContent = `${skills.length} 个 Skill`;
  tbody.innerHTML = '';

  if (skills.length === 0) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  skills.forEach(s => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <div class="skill-name">${escHtml(s.name)}</div>
        <div class="skill-desc">${escHtml(s.description || '暂无描述')}</div>
      </td>
      <td>${categoryTag(s.category || 'general')}</td>
      <td>
        <label class="toggle">
          <input type="checkbox" ${s.is_active ? 'checked' : ''} onchange="toggleSkill('${s.id}', this.checked)" />
          <span class="toggle-slider"></span>
        </label>
      </td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-ghost btn-xs" onclick="openSkillModal('${s.id}')">编辑</button>
          <button class="btn btn-danger btn-xs" onclick="deleteSkill('${s.id}')">删除</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function openSkillModal(skillId) {
  const isEdit = !!skillId;
  document.getElementById('skill-modal-title').textContent = isEdit ? '编辑 Skill' : '新建 Skill';
  document.getElementById('skill-edit-id').value = skillId || '';
  document.getElementById('skill-name').value = '';
  document.getElementById('skill-desc').value = '';
  document.getElementById('skill-category').value = 'general';
  document.getElementById('skill-content').value = '';
  document.getElementById('skill-active').checked = true;

  if (isEdit) {
    fetch(`/api/skills/${skillId}`)
      .then(r => r.json())
      .then(s => {
        document.getElementById('skill-name').value = s.name;
        document.getElementById('skill-desc').value = s.description || '';
        document.getElementById('skill-category').value = s.category || 'general';
        document.getElementById('skill-content').value = s.content || '';
        document.getElementById('skill-active').checked = s.is_active;
      });
  }
  openModal('modal-skill');
}

async function saveSkill() {
  const id = document.getElementById('skill-edit-id').value;
  const name = document.getElementById('skill-name').value.trim();
  if (!name) { toast('请填写名称', 'error'); return; }

  const body = {
    name,
    description: document.getElementById('skill-desc').value,
    category: document.getElementById('skill-category').value,
    content: document.getElementById('skill-content').value,
    is_active: document.getElementById('skill-active').checked,
  };

  try {
    const url = id ? `/api/skills/${id}` : '/api/skills/';
    const method = id ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    closeModal('modal-skill');
    loadSkills();
    toast(id ? 'Skill 已更新' : 'Skill 已创建', 'success');
  } catch (e) {
    toast('保存失败：' + e.message, 'error');
  }
}

async function deleteSkill(id) {
  if (!confirm('确定删除此 Skill？')) return;
  try {
    await fetch(`/api/skills/${id}`, { method: 'DELETE' });
    loadSkills();
    toast('已删除', 'success');
  } catch { toast('删除失败', 'error'); }
}

async function toggleSkill(id, active) {
  try {
    await fetch(`/api/skills/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: active }),
    });
  } catch { toast('更新失败', 'error'); }
}

function openImportSkillModal() {
  document.getElementById('import-skills-json').value = '';
  openModal('modal-import-skills');
}

async function importSkills() {
  const raw = document.getElementById('import-skills-json').value.trim();
  try {
    const data = JSON.parse(raw);
    if (!Array.isArray(data)) throw new Error('需要 JSON 数组');
    const res = await fetch('/api/skills/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    const imported = await res.json();
    closeModal('modal-import-skills');
    loadSkills();
    toast(`成功导入 ${imported.length} 个 Skill`, 'success');
  } catch (e) {
    toast('导入失败：' + e.message, 'error');
  }
}

// ============================================================
// 运维管理页
// ============================================================
async function loadOpsProjects() {
  const list = document.getElementById('ops-project-list');
  const empty = document.getElementById('ops-empty');
  list.innerHTML = '';

  try {
    const res = await fetch('/api/projects/');
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const projects = await res.json();

    if (projects.length === 0) {
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');

    projects.forEach(p => {
      const div = document.createElement('div');
      div.className = `ops-item ${p.id === currentOpsProjectId ? 'active' : ''}`;
      div.dataset.id = p.id;
      div.innerHTML = `
        <div class="ops-item-name">${escHtml(p.name || p.id)}</div>
        <div class="ops-item-meta">
          ${statusPill(p.status)}
          <span>${formatDate(p.created_at)}</span>
        </div>
      `;
      div.addEventListener('click', () => selectOpsProject(p));
      list.appendChild(div);
    });
  } catch (e) {
    toast('加载失败：' + e.message, 'error');
  }
}

function selectOpsProject(project) {
  currentOpsProjectId = project.id;
  document.querySelectorAll('.ops-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === project.id);
  });

  document.getElementById('ops-placeholder').classList.add('hidden');
  document.getElementById('ops-log-panel').classList.remove('hidden');
  document.getElementById('ops-proj-name').textContent = project.name || project.id;
  document.getElementById('ops-proj-status').innerHTML = statusPill(project.status);

  loadProjectLogs(project.id);
}

async function loadProjectLogs(projectId) {
  const viewer = document.getElementById('ops-log-viewer');
  viewer.innerHTML = '<div style="color:var(--muted);padding:8px">加载中...</div>';

  try {
    const res = await fetch(`/api/projects/${projectId}/logs`);
    const data = await res.json();
    renderLogs(data.logs || []);
  } catch (e) {
    viewer.innerHTML = `<div style="color:var(--danger)">加载失败：${e.message}</div>`;
  }
}

function renderLogs(logs) {
  const viewer = document.getElementById('ops-log-viewer');
  if (!logs || logs.length === 0) {
    viewer.innerHTML = '<div style="color:var(--muted);padding:8px">暂无日志</div>';
    return;
  }

  viewer.innerHTML = logs.map(entry => {
    const ts = entry.ts ? entry.ts.substring(11, 19) : '';
    const type = entry.type || 'system';
    const msg = entry.message || entry.content || JSON.stringify(entry);
    return `<div class="log-entry">
      <span class="log-ts">${escHtml(ts)}</span>
      <span class="log-text log-${type}">[${type}] ${escHtml(msg)}</span>
    </div>`;
  }).join('');

  viewer.scrollTop = viewer.scrollHeight;
}

function refreshLogs() {
  if (currentOpsProjectId) loadProjectLogs(currentOpsProjectId);
}

function clearLogView() {
  document.getElementById('ops-log-viewer').innerHTML = '<div style="color:var(--muted);padding:8px">已清空视图（服务器日志未删除）</div>';
}

// ============================================================
// 工具
// ============================================================
function escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ============================================================
// 初始化
// ============================================================
(function init() {
  const hash = location.hash.replace('#', '') || 'projects';
  navigate(hash);
})();
