/**
 * A-Share Quant Selector v2.0 — Frontend (ECharts)
 */

// ===== State =====
let currentPage = 'dashboard';
let allViews = [];
let currentViewId = null;
let schedulerRunning = false;
let klineChart = null;
let currentStockCode = null;
let currentKlinePeriod = 'daily';
let selectionResultsData = null;
let rankingResultsData = null;

const CATEGORY_LABELS = {
    bowl_center: '回落碗中',
    near_duokong: '靠近多空线',
    near_short_trend: '靠近趋势线',
};

// ===== ECharts Dark Theme Base =====
const darkThemeBase = {
    backgroundColor: 'transparent',
    textStyle: { color: '#94a3b8', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif' },
    tooltip: {
        backgroundColor: '#1c2539',
        borderColor: 'rgba(148,163,184,0.18)',
        borderWidth: 1,
        textStyle: { color: '#e2e8f0', fontSize: 12 },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
};

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadStats();
    loadViews();
    checkSchedulerStatus();
    createToastContainer();
});

function createToastContainer() {
    if (!document.querySelector('.toast-container')) {
        const c = document.createElement('div');
        c.className = 'toast-container';
        document.body.appendChild(c);
    }
}

function toast(msg, type = 'info') {
    const container = document.querySelector('.toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => {
        el.classList.add('toast-exit');
        setTimeout(() => el.remove(), 200);
    }, 3000);
}

// ===== Navigation =====
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => switchPage(item.dataset.page));
    });
}

function switchPage(page) {
    currentPage = page;
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });
    const titles = {
        dashboard: '系统概览',
        views: '选股视图',
        stocks: '股票列表',
        history: '历史结果',
        ranking: '每日排名',
    };
    document.getElementById('page-title').textContent = titles[page] || '';
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === page + '-page');
    });
    if (page === 'dashboard') loadStats();
    else if (page === 'views') loadViews();
    else if (page === 'stocks') loadStocks();
    else if (page === 'history') loadHistoryViewSelect();
    else if (page === 'ranking') loadRanking();
}

// ===== Dashboard =====
async function loadStats() {
    try {
        const r = await fetch('/api/stats');
        const d = await r.json();
        if (d.success) {
            animateNumber('stat-stocks', d.data.total_stocks);
            document.getElementById('stat-date').textContent = d.data.latest_date;
            animateNumber('stat-views', d.data.total_views);
            schedulerRunning = d.data.scheduler_running;
            document.getElementById('stat-scheduler').textContent =
                schedulerRunning ? '运行中' : '未启动';
            updateSchedulerUI();
        }
    } catch (e) {
        console.error('loadStats:', e);
    }
}

function animateNumber(elementId, target) {
    const el = document.getElementById(elementId);
    const num = parseInt(target);
    if (isNaN(num) || num === 0) {
        el.textContent = target;
        return;
    }
    const duration = 600;
    const start = performance.now();

    function tick(now) {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(num * eased);
        if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

function updateSchedulerUI() {
    const statusEl = document.getElementById('scheduler-status');
    const btn = document.getElementById('scheduler-toggle-btn');
    if (schedulerRunning) {
        statusEl.innerHTML = '<span class="dot green"></span> <span class="nav-text">调度器运行中</span>';
        if (btn) {
            btn.textContent = '停止调度器';
            btn.className = 'btn btn-danger';
        }
    } else {
        statusEl.innerHTML = '<span class="dot grey"></span> <span class="nav-text">调度器未启动</span>';
        if (btn) {
            btn.textContent = '启动调度器';
            btn.className = 'btn btn-secondary';
        }
    }
}

async function toggleScheduler() {
    const btn = document.getElementById('scheduler-toggle-btn');
    btn.disabled = true;
    try {
        const endpoint = schedulerRunning ? '/api/scheduler/stop' : '/api/scheduler/start';
        const r = await fetch(endpoint, { method: 'POST' });
        const d = await r.json();
        if (d.success) {
            schedulerRunning = !schedulerRunning;
            updateSchedulerUI();
            toast(d.message, 'success');
        } else {
            toast(d.error, 'error');
        }
    } catch (e) {
        toast('操作失败: ' + e.message, 'error');
    }
    btn.disabled = false;
}

async function checkSchedulerStatus() {
    try {
        const r = await fetch('/api/scheduler/status');
        const d = await r.json();
        if (d.success) {
            schedulerRunning = d.data.running;
            updateSchedulerUI();
        }
    } catch (_) {}
}

async function triggerDataUpdate() {
    toast('正在更新数据，请稍候...', 'info');
    try {
        const r = await fetch('/api/data/update', { method: 'POST' });
        const d = await r.json();
        if (d.success) {
            toast('数据更新完成', 'success');
            loadStats();
        } else {
            toast('更新失败: ' + d.error, 'error');
        }
    } catch (e) {
        toast('更新失败: ' + e.message, 'error');
    }
}

// ===== Views =====
async function loadViews() {
    try {
        const r = await fetch('/api/views');
        const d = await r.json();
        if (d.success) {
            allViews = d.data;
            renderViewCards();
        }
    } catch (e) {
        document.getElementById('views-list').innerHTML =
            '<p class="loading">加载失败</p>';
    }
}

function renderViewCards() {
    const container = document.getElementById('views-list');
    if (allViews.length === 0) {
        container.innerHTML = '<p class="placeholder">暂无视图</p>';
        return;
    }
    container.innerHTML = allViews.map(v => `
        <div class="view-card ${v.id === currentViewId ? 'active' : ''}"
             onclick="selectView(${v.id})">
            <div class="view-card-header">
                <span class="view-card-name">${escapeHtml(v.name)}</span>
                <div class="view-card-actions">
                    ${v.name !== '默认策略' ? `
                    <button class="btn btn-sm btn-danger"
                            onclick="event.stopPropagation(); deleteViewConfirm(${v.id}, '${escapeHtml(v.name)}')">
                        删除
                    </button>` : ''}
                </div>
            </div>
            <div class="view-card-meta">
                <span class="view-badge ${v.is_active ? 'active' : 'inactive'}">
                    ${v.is_active ? '活跃' : '停用'}
                </span>
                <span>N=${v.params.N || '-'}</span>
                <span>J&le;${v.params.J_VAL ?? '-'}</span>
                <span>CAP=${v.params.CAP ? (v.params.CAP / 1e8).toFixed(0) + '亿' : '-'}</span>
            </div>
        </div>
    `).join('');
}

async function selectView(viewId) {
    currentViewId = viewId;
    renderViewCards();
    const section = document.getElementById('view-detail-section');
    section.style.display = 'block';
    try {
        const r = await fetch(`/api/views/${viewId}`);
        const d = await r.json();
        if (d.success) {
            renderViewParams(d.data);
        }
    } catch (e) {
        toast('加载视图失败', 'error');
    }
}

function renderViewParams(view) {
    document.getElementById('view-detail-title').textContent =
        `编辑视图: ${view.name}`;
    const p = view.params;
    const form = document.getElementById('view-params-form');
    form.innerHTML = `
        <div class="param-group">
            <div class="param-group-title">成交量与回溯</div>
            ${sliderRow('N', '成交量倍数', p.N || 2.4, 1, 8, 0.1, 'x')}
            ${sliderRow('M', '回溯天数', p.M || 20, 5, 60, 1, '天')}
        </div>
        <div class="param-group">
            <div class="param-group-title">市值与J值</div>
            ${capRow('CAP', '市值门槛', p.CAP || 4000000000)}
            ${sliderRow('J_VAL', 'J值上限', p.J_VAL ?? 0, -50, 60, 1, '')}
        </div>
        <div class="param-group">
            <div class="param-group-title">多空线 MA 周期</div>
            ${sliderRow('M1', 'MA1', p.M1 || 14, 5, 60, 1, '日')}
            ${sliderRow('M2', 'MA2', p.M2 || 28, 10, 120, 1, '日')}
            ${sliderRow('M3', 'MA3', p.M3 || 57, 20, 200, 1, '日')}
            ${sliderRow('M4', 'MA4', p.M4 || 114, 30, 300, 1, '日')}
        </div>
        <div class="param-group">
            <div class="param-group-title">位置判定</div>
            ${sliderRow('duokong_pct', '靠近多空线', p.duokong_pct || 1.7, 0.5, 8, 0.1, '%')}
            ${sliderRow('short_pct', '靠近趋势线', p.short_pct || 2, 0.5, 8, 0.1, '%')}
        </div>
    `;
    form.querySelectorAll('.param-slider').forEach(slider => {
        const valInput = form.querySelector(
            `.param-value[data-param="${slider.dataset.param}"]`
        );
        slider.addEventListener('input', () => {
            valInput.value = slider.value;
        });
        valInput.addEventListener('change', () => {
            slider.value = valInput.value;
        });
    });
    document.getElementById('view-results').style.display = 'none';
}

function sliderRow(param, label, value, min, max, step, unit) {
    return `
        <div class="param-row">
            <span class="param-label">${label}</span>
            <div class="param-input-wrap">
                <input type="range" class="param-slider"
                       data-param="${param}"
                       min="${min}" max="${max}" step="${step}"
                       value="${value}">
                <input type="number" class="param-value"
                       data-param="${param}"
                       min="${min}" max="${max}" step="${step}"
                       value="${value}">
                <span class="param-unit">${unit}</span>
            </div>
        </div>
    `;
}

function capRow(param, label, value) {
    const billions = value / 1e8;
    return `
        <div class="param-row">
            <span class="param-label">${label}</span>
            <div class="param-input-wrap">
                <input type="number" class="param-value"
                       data-param="${param}" data-unit="yi"
                       min="0" step="5" style="width:100px"
                       value="${billions}">
                <span class="param-unit">亿</span>
            </div>
        </div>
    `;
}

function collectParams() {
    const params = {};
    document.querySelectorAll('#view-params-form .param-value').forEach(input => {
        const key = input.dataset.param;
        let val = parseFloat(input.value);
        if (input.dataset.unit === 'yi') {
            val = val * 1e8;
        }
        params[key] = val;
    });
    return params;
}

async function saveCurrentView() {
    if (!currentViewId) return;
    const params = collectParams();
    try {
        const r = await fetch(`/api/views/${currentViewId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ params }),
        });
        const d = await r.json();
        if (d.success) {
            toast('参数已保存', 'success');
            loadViews();
        } else {
            toast('保存失败: ' + d.error, 'error');
        }
    } catch (e) {
        toast('保存失败', 'error');
    }
}

async function runCurrentView() {
    if (!currentViewId) return;
    await saveCurrentView();

    const btn = document.querySelector('#view-detail-section .btn-success');
    btn.disabled = true;
    btn.textContent = '选股中...';
    document.getElementById('status-indicator').innerHTML =
        '<span class="dot yellow"></span> 运行中';

    const resultsSection = document.getElementById('view-results');
    const resultsContent = document.getElementById('view-results-content');
    resultsSection.style.display = 'block';
    resultsContent.innerHTML = `
        <div class="progress-container">
            <div class="progress-info">
                <span id="progress-text">正在初始化...</span>
                <span id="progress-pct">0%</span>
            </div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" id="progress-bar" style="width:0%"></div>
            </div>
        </div>`;

    const resetUI = () => {
        btn.disabled = false;
        btn.textContent = '执行选股';
        document.getElementById('status-indicator').innerHTML =
            '<span class="dot green"></span> 就绪';
    };

    try {
        const r = await fetch(`/api/views/${currentViewId}/run`, {
            method: 'POST',
        });
        const d = await r.json();
        if (!d.success) {
            resultsContent.innerHTML =
                `<p class="text-danger">选股失败: ${d.error}</p>`;
            toast('选股失败', 'error');
            resetUI();
            return;
        }

        const taskId = d.task_id;

        const poll = async () => {
            try {
                const sr = await fetch(
                    `/api/views/${currentViewId}/run/status?task_id=${taskId}`
                );
                const sd = await sr.json();

                if (sd.status === 'running' || sd.status === 'starting') {
                    const pct =
                        sd.total > 0
                            ? Math.round((sd.progress / sd.total) * 100)
                            : 0;
                    const phase = sd.phase || '扫描股票';
                    const bar = document.getElementById('progress-bar');
                    const pctEl = document.getElementById('progress-pct');
                    const textEl = document.getElementById('progress-text');
                    if (bar) bar.style.width = pct + '%';
                    if (pctEl) pctEl.textContent = pct + '%';
                    if (textEl)
                        textEl.textContent =
                            sd.total > 0
                                ? `${phase} ${sd.progress}/${sd.total}...`
                                : '正在初始化...';
                    setTimeout(poll, 300);
                } else if (sd.status === 'done') {
                    renderSelectionResults(sd.data);
                    toast(`选股完成，共 ${sd.data.total} 只`, 'success');
                    resetUI();
                } else if (sd.status === 'error') {
                    resultsContent.innerHTML =
                        `<p class="text-danger">选股失败: ${sd.error}</p>`;
                    toast('选股失败', 'error');
                    resetUI();
                }
            } catch (pollErr) {
                resultsContent.innerHTML =
                    `<p class="text-danger">轮询失败: ${pollErr.message}</p>`;
                resetUI();
            }
        };

        setTimeout(poll, 300);
    } catch (e) {
        resultsContent.innerHTML =
            `<p class="text-danger">选股失败: ${e.message}</p>`;
        resetUI();
    }
}

function renderSelectionResults(data) {
    selectionResultsData = data;
    renderFilteredSelectionResults('all');
}

function renderFilteredSelectionResults(filter) {
    const data = selectionResultsData;
    if (!data) return;

    const container = document.getElementById('view-results-content');
    const cc = data.category_count || {};
    const total = data.total || 0;

    let html = `
        <div class="result-summary">
            <div class="result-stat">
                <strong>${total}</strong>选出股票
            </div>
            <div class="result-stat">
                <strong>${cc.bowl_center || 0}</strong>回落碗中
            </div>
            <div class="result-stat">
                <strong>${cc.near_duokong || 0}</strong>靠近多空线
            </div>
            <div class="result-stat">
                <strong>${cc.near_short_trend || 0}</strong>靠近趋势线
            </div>
        </div>
    `;

    html += buildCategoryFilterHtml(filter, total, cc, 'selection');

    const stocks = data.stocks || [];
    const filtered = filter === 'all' ? stocks : stocks.filter(s => s.category === filter);

    if (filtered.length > 0) {
        html += filtered.map(s => buildSignalCardHtml(s)).join('');
    } else {
        html += '<p class="placeholder">未选出符合条件的股票</p>';
    }

    container.innerHTML = html;
}

function buildCategoryFilterHtml(active, total, cc, context) {
    const tabs = [
        { key: 'all', label: '全部', count: total },
        { key: 'bowl_center', label: '回落碗中', count: cc.bowl_center || 0 },
        { key: 'near_duokong', label: '靠近多空线', count: cc.near_duokong || 0 },
        { key: 'near_short_trend', label: '靠近趋势线', count: cc.near_short_trend || 0 },
    ];
    const handler = context === 'selection'
        ? 'renderFilteredSelectionResults'
        : 'renderFilteredRankingList';
    return `<div class="category-filter">${
        tabs.map(t =>
            `<button class="category-tab${active === t.key ? ' active' : ''}" onclick="${handler}('${t.key}')">${t.label}(${t.count})</button>`
        ).join('')
    }</div>`;
}

function buildSignalCardHtml(s) {
    const catClass =
        s.category === 'bowl_center' ? 'bowl' :
        s.category === 'near_duokong' ? 'duokong' : 'short-trend';
    const tagClass =
        s.category === 'bowl_center' ? 'tag-bowl' :
        s.category === 'near_duokong' ? 'tag-duokong' : 'tag-short';
    const tagText = CATEGORY_LABELS[s.category] || s.category;

    const hasB1 = s.similarity_score != null && s.matched_case;
    const bd = s.match_breakdown || {};

    let b1Html = '';
    if (hasB1) {
        const score = s.similarity_score.toFixed(1);
        const scoreClass = s.similarity_score >= 85 ? 'score-high' :
            s.similarity_score >= 70 ? 'score-mid' : 'score-low';
        b1Html = `
            <div class="b1-section">
                <div class="b1-header">
                    <span class="b1-score ${scoreClass}">${score}%</span>
                    <span class="b1-case">匹配 ${escapeHtml(s.matched_case)}</span>
                </div>
                <div class="b1-bars">
                    ${b1BarHtml('趋势', bd.trend_structure)}
                    ${b1BarHtml('KDJ', bd.kdj_state)}
                    ${b1BarHtml('量能', bd.volume_pattern)}
                    ${b1BarHtml('形态', bd.price_shape)}
                </div>
            </div>`;
    }

    return `
        <div class="signal-card ${catClass}" onclick="viewStockDetail('${s.code}')" style="cursor:pointer">
            <div class="signal-main">
                <div class="signal-left">
                    <div class="signal-header-row">
                        <span class="signal-code">${s.code}</span>
                        <span class="signal-name">${escapeHtml(s.name)}</span>
                        <span class="tag ${tagClass}">${tagText}</span>
                    </div>
                    <div class="signal-metrics">
                        <span>价格 <strong>&yen;${s.close}</strong></span>
                        <span>J值 <strong>${s.J}</strong></span>
                        <span>市值 <strong>${s.market_cap}亿</strong></span>
                    </div>
                </div>
                ${b1Html}
            </div>
        </div>
    `;
}

function b1BarHtml(label, value) {
    if (value == null) return '';
    const pct = Math.min(value, 100);
    const color = pct >= 85 ? 'var(--success)' :
        pct >= 60 ? 'var(--accent)' : 'var(--bull)';
    return `
        <div class="b1-bar-item">
            <span class="b1-bar-label">${label}</span>
            <div class="b1-bar-track">
                <div class="b1-bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            <span class="b1-bar-val">${value.toFixed(0)}%</span>
        </div>`;
}

// ===== Create/Delete Views =====
function showCreateViewModal() {
    const select = document.getElementById('new-view-source');
    select.innerHTML = '<option value="">使用默认参数</option>' +
        allViews.map(v =>
            `<option value="${v.id}">${escapeHtml(v.name)}</option>`
        ).join('');
    document.getElementById('new-view-name').value = '';
    document.getElementById('create-view-modal').classList.add('active');
}

function closeCreateViewModal() {
    document.getElementById('create-view-modal').classList.remove('active');
}

async function createView() {
    const name = document.getElementById('new-view-name').value.trim();
    if (!name) {
        toast('请输入视图名称', 'error');
        return;
    }
    const sourceId = document.getElementById('new-view-source').value;
    const body = { name };
    if (sourceId) body.source_id = parseInt(sourceId);

    try {
        const r = await fetch('/api/views', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (d.success) {
            closeCreateViewModal();
            toast('视图已创建', 'success');
            loadViews();
            selectView(d.data.id);
        } else {
            toast('创建失败: ' + d.error, 'error');
        }
    } catch (e) {
        toast('创建失败', 'error');
    }
}

async function deleteViewConfirm(viewId, name) {
    if (!confirm(`确定要删除视图 "${name}" 吗？关联的历史结果也会被删除。`)) return;
    try {
        const r = await fetch(`/api/views/${viewId}`, { method: 'DELETE' });
        const d = await r.json();
        if (d.success) {
            if (currentViewId === viewId) {
                currentViewId = null;
                document.getElementById('view-detail-section').style.display = 'none';
            }
            toast('视图已删除', 'success');
            loadViews();
        } else {
            toast('删除失败: ' + d.error, 'error');
        }
    } catch (e) {
        toast('删除失败', 'error');
    }
}

// ===== Stock List =====
async function loadStocks() {
    const tbody = document.getElementById('stocks-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="loading">加载中...</td></tr>';

    try {
        let allStocks = [];
        let page = 1;
        let totalPages = 1;

        do {
            const r = await fetch(`/api/stocks?page=${page}&per_page=500`);
            const d = await r.json();
            if (d.success) {
                allStocks = allStocks.concat(d.data);
                totalPages = d.total_pages;
                tbody.innerHTML = `<tr><td colspan="7" class="loading">
                    已加载 ${allStocks.length}/${d.total} ...</td></tr>`;
                page++;
            } else break;
        } while (page <= totalPages);

        renderStocks(allStocks);
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading">
            加载失败: ${e.message}</td></tr>`;
    }
}

function renderStocks(stocks) {
    const tbody = document.getElementById('stocks-tbody');
    if (!stocks.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">暂无数据</td></tr>';
        return;
    }
    tbody.innerHTML = stocks.map(s => `
        <tr>
            <td><strong>${s.code}</strong></td>
            <td>${escapeHtml(s.name)}</td>
            <td>&yen;${s.latest_price}</td>
            <td>${s.latest_date}</td>
            <td>${s.market_cap}</td>
            <td>${s.data_count}</td>
            <td><button class="btn btn-sm btn-secondary"
                onclick="viewStockDetail('${s.code}')">查看</button></td>
        </tr>
    `).join('');

    const searchEl = document.getElementById('stock-search');
    searchEl.oninput = (e) => {
        const kw = e.target.value.toLowerCase();
        tbody.querySelectorAll('tr').forEach(row => {
            row.style.display = row.textContent.toLowerCase().includes(kw) ? '' : 'none';
        });
    };
}

// ===== Stock Detail (ECharts K-line) =====
function viewStockDetail(code) {
    currentStockCode = code;
    currentKlinePeriod = 'daily';

    document.querySelectorAll('#kline-tabs .kline-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.period === 'daily');
    });

    document.getElementById('modal-title').textContent = code;
    document.getElementById('stock-info').innerHTML = '';
    document.getElementById('stock-modal').classList.add('active');

    loadKline(code, 'daily');
}

function switchKlinePeriod(period) {
    if (period === currentKlinePeriod) return;
    currentKlinePeriod = period;

    document.querySelectorAll('#kline-tabs .kline-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.period === period);
    });

    loadKline(currentStockCode, period);
}

async function loadKline(code, period) {
    const chartDom = document.getElementById('kline-chart');

    if (klineChart) {
        klineChart.dispose();
    }
    klineChart = echarts.init(chartDom);
    klineChart.showLoading({
        text: '加载中...',
        color: '#f59e0b',
        maskColor: 'rgba(19, 26, 43, 0.8)',
        textColor: '#94a3b8',
    });

    try {
        const r = await fetch(`/api/stock/${code}/kline?period=${period}`);
        const d = await r.json();
        if (d.success) {
            if (period === 'daily') {
                renderDailyKline(d.data);
            } else {
                renderWeeklyKline(d.data);
            }
            renderStockInfo(d.data, period);
        } else {
            klineChart.hideLoading();
            toast('K线数据加载失败: ' + d.error, 'error');
        }
    } catch (e) {
        klineChart.hideLoading();
        toast('K线数据加载失败', 'error');
    }
}

function renderStockInfo(data, period) {
    if (!data || data.length === 0) return;
    const latest = data[data.length - 1];
    const infoEl = document.getElementById('stock-info');

    if (period === 'daily') {
        infoEl.innerHTML = `
            <div class="signal-right" style="justify-content:flex-start;gap:24px;margin-top:14px;font-size:12px;flex-wrap:wrap;">
                <div>日期 <strong>${latest[0]}</strong></div>
                <div>开盘 <strong>&yen;${latest[1]}</strong></div>
                <div>收盘 <strong>&yen;${latest[2]}</strong></div>
                <div>最低 <strong>&yen;${latest[3]}</strong></div>
                <div>最高 <strong>&yen;${latest[4]}</strong></div>
                <div>成交量 <strong>${formatVolume(latest[5])}</strong></div>
                <div>K <strong style="color:#3b82f6">${latest[6] != null ? latest[6].toFixed(1) : '-'}</strong></div>
                <div>D <strong style="color:#f59e0b">${latest[7] != null ? latest[7].toFixed(1) : '-'}</strong></div>
                <div>J <strong style="color:#ef4444">${latest[8] != null ? latest[8].toFixed(1) : '-'}</strong></div>
            </div>
        `;
    } else {
        infoEl.innerHTML = `
            <div class="signal-right" style="justify-content:flex-start;gap:24px;margin-top:14px;font-size:12px;flex-wrap:wrap;">
                <div>日期 <strong>${latest[0]}</strong></div>
                <div>开盘 <strong>&yen;${latest[1]}</strong></div>
                <div>收盘 <strong>&yen;${latest[2]}</strong></div>
                <div>最低 <strong>&yen;${latest[3]}</strong></div>
                <div>最高 <strong>&yen;${latest[4]}</strong></div>
                <div>成交量 <strong>${formatVolume(latest[5])}</strong></div>
                <div>MA5 <strong style="color:#f59e0b">${latest[6] != null ? latest[6].toFixed(2) : '-'}</strong></div>
                <div>MA10 <strong style="color:#3b82f6">${latest[7] != null ? latest[7].toFixed(2) : '-'}</strong></div>
                <div>MA20 <strong style="color:#a855f7">${latest[8] != null ? latest[8].toFixed(2) : '-'}</strong></div>
                <div>MA60 <strong style="color:#22c55e">${latest[9] != null ? latest[9].toFixed(2) : '-'}</strong></div>
            </div>
        `;
    }
}

function formatVolume(vol) {
    if (vol == null) return '-';
    if (vol >= 1e8) return (vol / 1e8).toFixed(2) + '亿';
    if (vol >= 1e4) return (vol / 1e4).toFixed(1) + '万';
    return vol.toString();
}

function renderDailyKline(data) {
    if (!data || data.length === 0) {
        klineChart.hideLoading();
        return;
    }

    const dates = data.map(d => d[0]);
    const ohlc = data.map(d => [d[1], d[2], d[3], d[4]]);
    const volumes = data.map(d => d[5]);
    const kValues = data.map(d => d[6]);
    const dValues = data.map(d => d[7]);
    const jValues = data.map(d => d[8]);
    const trendLine = data.map(d => d[9]);
    const dkLine = data.map(d => d[10]);

    const volumeColors = data.map(d => d[2] >= d[1] ? '#ef4444' : '#22c55e');

    const option = {
        ...darkThemeBase,
        animation: false,
        legend: {
            data: ['K线', '短期趋势线', '多空线', '成交量', 'K', 'D', 'J'],
            top: 4,
            textStyle: { color: '#94a3b8', fontSize: 11 },
            itemWidth: 14,
            itemHeight: 8,
        },
        grid: [
            { left: 60, right: 60, top: 40, height: '45%' },
            { left: 60, right: 60, top: '58%', height: '12%' },
            { left: 60, right: 60, top: '75%', height: '18%' },
        ],
        xAxis: [
            {
                type: 'category',
                data: dates,
                gridIndex: 0,
                axisLine: { lineStyle: { color: 'rgba(148,163,184,0.18)' } },
                axisTick: { show: false },
                axisLabel: { show: false },
                splitLine: { show: false },
            },
            {
                type: 'category',
                data: dates,
                gridIndex: 1,
                axisLine: { lineStyle: { color: 'rgba(148,163,184,0.18)' } },
                axisTick: { show: false },
                axisLabel: { show: false },
                splitLine: { show: false },
            },
            {
                type: 'category',
                data: dates,
                gridIndex: 2,
                axisLine: { lineStyle: { color: 'rgba(148,163,184,0.18)' } },
                axisTick: { show: false },
                axisLabel: {
                    color: '#64748b',
                    fontSize: 10,
                    formatter: function(val) {
                        return val.substring(5);
                    },
                },
                splitLine: { show: false },
            },
        ],
        yAxis: [
            {
                scale: true,
                gridIndex: 0,
                splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)' } },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: '#64748b', fontSize: 10 },
            },
            {
                scale: true,
                gridIndex: 1,
                splitNumber: 2,
                splitLine: { show: false },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: {
                    color: '#64748b',
                    fontSize: 10,
                    formatter: function(val) {
                        if (val >= 1e8) return (val / 1e8).toFixed(0) + '亿';
                        if (val >= 1e4) return (val / 1e4).toFixed(0) + '万';
                        return val;
                    },
                },
            },
            {
                scale: true,
                gridIndex: 2,
                splitNumber: 3,
                splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)' } },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: '#64748b', fontSize: 10 },
            },
        ],
        dataZoom: [
            {
                type: 'slider',
                xAxisIndex: [0, 1, 2],
                bottom: 4,
                height: 20,
                borderColor: 'rgba(148,163,184,0.15)',
                fillerColor: 'rgba(245,158,11,0.08)',
                handleStyle: { color: '#f59e0b', borderColor: '#f59e0b' },
                textStyle: { color: '#64748b', fontSize: 10 },
                start: Math.max(0, 100 - (120 / dates.length) * 100),
                end: 100,
            },
            {
                type: 'inside',
                xAxisIndex: [0, 1, 2],
            },
        ],
        tooltip: {
            ...darkThemeBase.tooltip,
            trigger: 'axis',
            axisPointer: { type: 'cross' },
        },
        axisPointer: {
            link: [{ xAxisIndex: 'all' }],
            label: { backgroundColor: '#1c2539' },
        },
        series: [
            {
                name: 'K线',
                type: 'candlestick',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: ohlc,
                itemStyle: {
                    color: '#ef4444',
                    color0: '#22c55e',
                    borderColor: '#ef4444',
                    borderColor0: '#22c55e',
                },
            },
            {
                name: '短期趋势线',
                type: 'line',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: trendLine,
                lineStyle: { width: 1.5, color: '#ffffff' },
                itemStyle: { color: '#ffffff' },
                symbol: 'none',
                smooth: true,
                connectNulls: false,
            },
            {
                name: '多空线',
                type: 'line',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: dkLine,
                lineStyle: { width: 1.5, color: '#facc15' },
                itemStyle: { color: '#facc15' },
                symbol: 'none',
                smooth: true,
                connectNulls: false,
            },
            {
                name: '成交量',
                type: 'bar',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: volumes.map((v, i) => ({
                    value: v,
                    itemStyle: { color: volumeColors[i] },
                })),
            },
            {
                name: 'K',
                type: 'line',
                xAxisIndex: 2,
                yAxisIndex: 2,
                data: kValues,
                lineStyle: { width: 1.5, color: '#3b82f6' },
                itemStyle: { color: '#3b82f6' },
                symbol: 'none',
                smooth: true,
            },
            {
                name: 'D',
                type: 'line',
                xAxisIndex: 2,
                yAxisIndex: 2,
                data: dValues,
                lineStyle: { width: 1.5, color: '#f59e0b' },
                itemStyle: { color: '#f59e0b' },
                symbol: 'none',
                smooth: true,
            },
            {
                name: 'J',
                type: 'line',
                xAxisIndex: 2,
                yAxisIndex: 2,
                data: jValues,
                lineStyle: { width: 1.5, color: '#ef4444' },
                itemStyle: { color: '#ef4444' },
                symbol: 'none',
                smooth: true,
            },
        ],
    };

    klineChart.hideLoading();
    klineChart.setOption(option);
}

function renderWeeklyKline(data) {
    if (!data || data.length === 0) {
        klineChart.hideLoading();
        return;
    }

    const dates = data.map(d => d[0]);
    const ohlc = data.map(d => [d[1], d[2], d[3], d[4]]);
    const volumes = data.map(d => d[5]);
    const ma5 = data.map(d => d[6]);
    const ma10 = data.map(d => d[7]);
    const ma20 = data.map(d => d[8]);
    const ma60 = data.map(d => d[9]);

    const volumeColors = data.map(d => d[2] >= d[1] ? '#ef4444' : '#22c55e');

    const option = {
        ...darkThemeBase,
        animation: false,
        legend: {
            data: ['K线', 'MA5', 'MA10', 'MA20', 'MA60', '成交量'],
            top: 4,
            textStyle: { color: '#94a3b8', fontSize: 11 },
            itemWidth: 14,
            itemHeight: 8,
        },
        grid: [
            { left: 60, right: 60, top: 40, height: '58%' },
            { left: 60, right: 60, top: '72%', height: '18%' },
        ],
        xAxis: [
            {
                type: 'category',
                data: dates,
                gridIndex: 0,
                axisLine: { lineStyle: { color: 'rgba(148,163,184,0.18)' } },
                axisTick: { show: false },
                axisLabel: { show: false },
                splitLine: { show: false },
            },
            {
                type: 'category',
                data: dates,
                gridIndex: 1,
                axisLine: { lineStyle: { color: 'rgba(148,163,184,0.18)' } },
                axisTick: { show: false },
                axisLabel: {
                    color: '#64748b',
                    fontSize: 10,
                    formatter: function(val) {
                        return val.substring(5);
                    },
                },
                splitLine: { show: false },
            },
        ],
        yAxis: [
            {
                scale: true,
                gridIndex: 0,
                splitLine: { lineStyle: { color: 'rgba(148,163,184,0.06)' } },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: '#64748b', fontSize: 10 },
            },
            {
                scale: true,
                gridIndex: 1,
                splitNumber: 2,
                splitLine: { show: false },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: {
                    color: '#64748b',
                    fontSize: 10,
                    formatter: function(val) {
                        if (val >= 1e8) return (val / 1e8).toFixed(0) + '亿';
                        if (val >= 1e4) return (val / 1e4).toFixed(0) + '万';
                        return val;
                    },
                },
            },
        ],
        dataZoom: [
            {
                type: 'slider',
                xAxisIndex: [0, 1],
                bottom: 4,
                height: 20,
                borderColor: 'rgba(148,163,184,0.15)',
                fillerColor: 'rgba(245,158,11,0.08)',
                handleStyle: { color: '#f59e0b', borderColor: '#f59e0b' },
                textStyle: { color: '#64748b', fontSize: 10 },
                start: Math.max(0, 100 - (60 / dates.length) * 100),
                end: 100,
            },
            {
                type: 'inside',
                xAxisIndex: [0, 1],
            },
        ],
        tooltip: {
            ...darkThemeBase.tooltip,
            trigger: 'axis',
            axisPointer: { type: 'cross' },
        },
        axisPointer: {
            link: [{ xAxisIndex: 'all' }],
            label: { backgroundColor: '#1c2539' },
        },
        series: [
            {
                name: 'K线',
                type: 'candlestick',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: ohlc,
                itemStyle: {
                    color: '#ef4444',
                    color0: '#22c55e',
                    borderColor: '#ef4444',
                    borderColor0: '#22c55e',
                },
            },
            {
                name: 'MA5',
                type: 'line',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: ma5,
                lineStyle: { width: 1.5, color: '#f59e0b' },
                itemStyle: { color: '#f59e0b' },
                symbol: 'none',
                smooth: true,
                connectNulls: false,
            },
            {
                name: 'MA10',
                type: 'line',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: ma10,
                lineStyle: { width: 1.5, color: '#3b82f6' },
                itemStyle: { color: '#3b82f6' },
                symbol: 'none',
                smooth: true,
                connectNulls: false,
            },
            {
                name: 'MA20',
                type: 'line',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: ma20,
                lineStyle: { width: 1.5, color: '#a855f7' },
                itemStyle: { color: '#a855f7' },
                symbol: 'none',
                smooth: true,
                connectNulls: false,
            },
            {
                name: 'MA60',
                type: 'line',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: ma60,
                lineStyle: { width: 1.5, color: '#22c55e' },
                itemStyle: { color: '#22c55e' },
                symbol: 'none',
                smooth: true,
                connectNulls: false,
            },
            {
                name: '成交量',
                type: 'bar',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: volumes.map((v, i) => ({
                    value: v,
                    itemStyle: { color: volumeColors[i] },
                })),
            },
        ],
    };

    klineChart.hideLoading();
    klineChart.setOption(option);
}

function closeStockModal() {
    document.getElementById('stock-modal').classList.remove('active');
    if (klineChart) {
        klineChart.dispose();
        klineChart = null;
    }
}

// ===== Ranking =====
async function loadRanking() {
    const container = document.getElementById('ranking-list');
    container.innerHTML = '<p class="loading">加载中...</p>';

    try {
        const r = await fetch('/api/ranking');
        const d = await r.json();
        if (d.success && d.data && d.data.length > 0) {
            renderRankingList(d.data);
        } else {
            container.innerHTML = '<p class="placeholder">暂无排名数据</p>';
        }
    } catch (e) {
        container.innerHTML = '<p class="text-danger">加载失败</p>';
    }
}

function renderRankingList(data) {
    rankingResultsData = data;
    renderFilteredRankingList('all');
}

function renderFilteredRankingList(filter) {
    const data = rankingResultsData;
    if (!data) return;

    const container = document.getElementById('ranking-list');

    const cc = {};
    for (const s of data) {
        const cat = s.category || '';
        if (cat) cc[cat] = (cc[cat] || 0) + 1;
    }

    const filtered = filter === 'all' ? data : data.filter(s => s.category === filter);

    let html = buildCategoryFilterHtml(filter, data.length, cc, 'ranking');

    if (filtered.length === 0) {
        html += '<p class="placeholder">暂无排名数据</p>';
        container.innerHTML = html;
        return;
    }

    html += filtered.map((s, index) => {
        const code = s.code || '';
        const name = escapeHtml(s.name || '');
        const category = s.category || '';
        const close = s.close != null ? s.close : '-';
        const J = s.J != null ? s.J : '-';
        const marketCap = s.market_cap != null ? s.market_cap : '-';
        const views = s.views || [];

        const tagClass =
            category === 'bowl_center' ? 'tag-bowl' :
            category === 'near_duokong' ? 'tag-duokong' : 'tag-short';
        const tagText = CATEGORY_LABELS[category] || category;
        const viewTags = views.map(v =>
            `<span class="tag" style="background:var(--info-dim);color:var(--info)">${escapeHtml(v)}</span>`
        ).join('');

        const hasB1 = s.similarity_score != null && s.matched_case;
        const bd = s.match_breakdown || {};
        let b1Html = '';
        if (hasB1) {
            const score = s.similarity_score.toFixed(1);
            const scoreClass = s.similarity_score >= 85 ? 'score-high' :
                s.similarity_score >= 70 ? 'score-mid' : 'score-low';
            b1Html = `
                <div class="b1-section">
                    <div class="b1-header">
                        <span class="b1-score ${scoreClass}">${score}%</span>
                        <span class="b1-case">匹配 ${escapeHtml(s.matched_case)}</span>
                    </div>
                    <div class="b1-bars">
                        ${b1BarHtml('趋势', bd.trend_structure)}
                        ${b1BarHtml('KDJ', bd.kdj_state)}
                        ${b1BarHtml('量能', bd.volume_pattern)}
                        ${b1BarHtml('形态', bd.price_shape)}
                    </div>
                </div>`;
        }

        return `
            <div class="ranking-item" onclick="viewStockDetail('${code}')">
                <div class="rank-number">${index + 1}</div>
                <div class="ranking-main">
                    <div class="signal-left">
                        <span class="signal-code">${code}</span>
                        <span class="signal-name">${name}</span>
                        <div class="signal-tags">
                            <span class="tag ${tagClass}">${tagText}</span>
                            ${viewTags}
                        </div>
                    </div>
                    <div class="signal-right">
                        <div>价格<strong>&yen;${close}</strong></div>
                        <div>J值<strong>${J}</strong></div>
                        <div>市值<strong>${marketCap}亿</strong></div>
                    </div>
                    ${b1Html}
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = html;
}

// ===== History =====
async function loadHistoryViewSelect() {
    const select = document.getElementById('history-view-select');
    try {
        const r = await fetch('/api/views');
        const d = await r.json();
        if (d.success) {
            select.innerHTML = '<option value="">选择视图...</option>' +
                d.data.map(v =>
                    `<option value="${v.id}">${escapeHtml(v.name)}</option>`
                ).join('');
        }
    } catch (_) {}
}

async function loadHistory() {
    const viewId = document.getElementById('history-view-select').value;
    const container = document.getElementById('history-list');
    if (!viewId) {
        container.innerHTML = '<p class="placeholder">请先选择一个视图</p>';
        return;
    }
    container.innerHTML = '<p class="loading">加载中...</p>';

    try {
        const r = await fetch(`/api/views/${viewId}/results?limit=50`);
        const d = await r.json();
        if (d.success && d.data.length > 0) {
            container.innerHTML = d.data.map(result => `
                <div class="history-item" onclick="showHistoryDetail(${viewId}, '${result.run_date}')">
                    <span class="history-date">${result.run_date}</span>
                    <span class="history-count">选出 ${result.total_selected} 只</span>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="placeholder">暂无历史结果</p>';
        }
    } catch (e) {
        container.innerHTML = '<p class="text-danger">加载失败</p>';
    }
}

async function showHistoryDetail(viewId, runDate) {
    try {
        const r = await fetch(`/api/views/${viewId}/results/${runDate}`);
        const d = await r.json();
        if (d.success) {
            const container = document.getElementById('history-list');
            const stocks = d.data.stocks || [];
            let html = `<div style="margin-bottom:12px;display:flex;align-items:center;gap:12px;">
                <button class="btn btn-sm btn-secondary" onclick="loadHistory()">返回列表</button>
                <span style="font-weight:600;font-family:var(--font-mono);font-size:13px;">${runDate}</span>
                <span style="color:var(--ink-muted);font-size:12px;">${stocks.length} 只</span>
            </div>`;

            html += stocks.map(s => {
                const catClass =
                    s.category === 'bowl_center' ? 'bowl' :
                    s.category === 'near_duokong' ? 'duokong' : 'short-trend';
                const tagClass =
                    s.category === 'bowl_center' ? 'tag-bowl' :
                    s.category === 'near_duokong' ? 'tag-duokong' : 'tag-short';
                const tagText =
                    s.category === 'bowl_center' ? '回落碗中' :
                    s.category === 'near_duokong' ? '靠近多空线' : '靠近趋势线';
                return `
                    <div class="signal-card ${catClass}" onclick="viewStockDetail('${s.code}')" style="cursor:pointer">
                        <div class="signal-left">
                            <span class="signal-code">${s.code}</span>
                            <span class="signal-name">${escapeHtml(s.name)}</span>
                            <div class="signal-tags">
                                <span class="tag ${tagClass}">${tagText}</span>
                            </div>
                        </div>
                        <div class="signal-right">
                            <div>价格<strong>&yen;${s.close}</strong></div>
                            <div>J值<strong>${s.J}</strong></div>
                            <div>市值<strong>${s.market_cap}亿</strong></div>
                        </div>
                    </div>
                `;
            }).join('');

            container.innerHTML = html;
        }
    } catch (e) {
        toast('加载失败', 'error');
    }
}

// ===== ECharts Resize =====
window.addEventListener('resize', () => {
    if (klineChart) klineChart.resize();
});

// ===== Modal Close =====
document.addEventListener('click', (e) => {
    if (e.target.id === 'stock-modal') closeStockModal();
    if (e.target.id === 'create-view-modal') closeCreateViewModal();
});

// ===== Utilities =====
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
