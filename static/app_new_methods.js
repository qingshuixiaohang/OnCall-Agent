
    // ================================================================
    // 诊断进度卡片渲染（结构化 UI，替代纯文本堆砌）
    // ================================================================

    _ensureProgressCard(messageElement, mode) {
        // 如果消息里已有进度卡片则返回，否则创建
        let card = messageElement.querySelector('.diag-progress-card');
        if (card) return card;

        const wrapper = messageElement.querySelector('.message-content-wrapper');
        if (!wrapper) return null;

        // 移除旧的纯文本 content
        const oldContent = wrapper.querySelector('.message-content');
        if (oldContent) oldContent.innerHTML = '';

        card = document.createElement('div');
        card.className = 'diag-progress-card';
        card.innerHTML = `
            <div class="dpc-header">
                <span class="dpc-icon">${mode === 'aiops' ? '&#128269;' : '&#129504;'}</span>
                <span class="dpc-title">${mode === 'aiops' ? '单Agent诊断' : '多Agent诊断'}</span>
                <span class="dpc-badge">${mode === 'aiops' ? 'Plan-Execute-Replan' : 'Supervisor + Specialist'}</span>
            </div>
            <div class="dpc-phases"></div>
            <div class="dpc-body"></div>
            <div class="dpc-progress-wrap">
                <div class="dpc-progress-bar"><div class="dpc-progress-fill" style="width:0%"></div></div>
                <div class="dpc-progress-label">初始化...</div>
            </div>
        `;
        wrapper.insertBefore(card, wrapper.firstChild);
        return card;
    }

    _renderPhaseLights(card, phases) {
        // phases: [{key,label,done,active}]
        const container = card.querySelector('.dpc-phases');
        if (!container) return;
        container.innerHTML = phases.map((p, i) => {
            let cls = 'dpc-phase';
            if (p.active) cls += ' active';
            else if (p.done) cls += ' done';
            const dot = p.done ? '&#10003;' : (p.active ? '&#9679;' : '&#9675;');
            return `<div class="${cls}"><span class="phase-dot">${dot}</span><span class="phase-label">${p.label}</span>${i < phases.length - 1 ? '<span class="phase-line"></span>' : ''}</div>`;
        }).join('');
    }

    _renderAIOpsProgress(card, state) {
        // state: { phase, plan:[], completed:number, message:'' }
        const phaseMap = {
            'planner':  [{ key:'plan',   label:'制定计划', done:false, active:true }],
            'executor': [{ key:'plan',   label:'制定计划', done:true,  active:false},
                         { key:'exec',   label:'执行步骤', done:false, active:true }],
            'replanner':[{ key:'plan',   label:'制定计划', done:true,  active:false},
                         { key:'exec',   label:'执行步骤', done:true,  active:false},
                         { key:'report', label:'生成报告', done:false, active:true }],
            'complete': [{ key:'plan',   label:'制定计划', done:true,  active:false},
                         { key:'exec',   label:'执行步骤', done:true,  active:false},
                         { key:'report', label:'生成报告', done:true,  active:false}],
        };
        const phases = phaseMap[state.phase] || phaseMap['planner'];
        this._renderPhaseLights(card, phases);

        // 步骤列表
        const body = card.querySelector('.dpc-body');
        const total = state.plan.length;
        const done = state.completed;
        if (body && total > 0) {
            body.innerHTML = state.plan.map((s, i) => {
                let cls = 'dpc-step';
                let icon = '&#9675;'; // pending
                if (i < done) { cls += ' done'; icon = '&#10003;'; }
                else if (i === done && state.phase === 'executor') { cls += ' active'; icon = '&#9679;'; }
                return `<div class="${cls}"><span class="step-icon">${icon}</span><span class="step-text">${this.escapeHtml(s)}</span></div>`;
            }).join('');
        } else if (body && state.message) {
            body.innerHTML = `<div class="dpc-step active"><span class="step-icon">&#9679;</span><span class="step-text">${this.escapeHtml(state.message)}</span></div>`;
        }

        // 进度条
        const fill = card.querySelector('.dpc-progress-fill');
        const label = card.querySelector('.dpc-progress-label');
        if (total > 0) {
            const pct = Math.max(5, Math.round((done / total) * 100));
            fill.style.width = (state.phase === 'complete' ? '100' : pct) + '%';
            label.textContent = state.phase === 'complete' ? '完成' : `步骤 ${done}/${total}`;
        } else if (state.phase === 'planner') {
            fill.style.width = '10%';
            label.textContent = '制定计划中...';
        }
    }

    _renderMultiAgentProgress(card, state) {
        // state: { phase:'supervisor'|'executing'|'aggregating'|'complete', specialists:[{name,status}], reason:'' }
        const phaseMap = {
            'supervisor':   [{ key:'route', label:'分析路由', done:false, active:true }],
            'executing':    [{ key:'route', label:'分析路由', done:true,  active:false},
                             { key:'exec',  label:'专家并行', done:false, active:true }],
            'aggregating':  [{ key:'route', label:'分析路由', done:true,  active:false},
                             { key:'exec',  label:'专家并行', done:true,  active:false},
                             { key:'agg',   label:'汇总分析', done:false, active:true }],
            'complete':     [{ key:'route', label:'分析路由', done:true,  active:false},
                             { key:'exec',  label:'专家并行', done:true,  active:false},
                             { key:'agg',   label:'汇总分析', done:true,  active:false}],
        };
        const phases = phaseMap[state.phase] || phaseMap['supervisor'];
        this._renderPhaseLights(card, phases);

        // 专家卡片
        const body = card.querySelector('.dpc-body');
        const specs = state.specialists || [];
        if (body && specs.length > 0) {
            body.innerHTML = specs.map(s => {
                let cls = 'dpc-spec';
                let icon = '&#9675;';
                const icons = { 'log_analyzer': '&#128220;', 'monitor_expert': '&#128200;', 'knowledge_retriever': '&#128214;' };
                const labels = { 'log_analyzer': '日志分析', 'monitor_expert': '监控分析', 'knowledge_retriever': '知识检索' };
                if (s.status === 'done') { cls += ' done'; icon = '&#10003;'; }
                else if (s.status === 'running') { cls += ' active'; icon = '&#9679;'; }
                return `<div class="${cls}"><span class="spec-icon">${icons[s.name] || '&#9881;'}</span><span class="spec-name">${labels[s.name] || s.name}</span><span class="spec-badge">${icon}</span></div>`;
            }).join('');
        } else if (body && state.reason) {
            body.innerHTML = `<div class="dpc-step active"><span class="step-text">${this.escapeHtml(state.reason)}</span></div>`;
        }

        // 进度条
        const fill = card.querySelector('.dpc-progress-fill');
        const label = card.querySelector('.dpc-progress-label');
        const total = specs.length;
        const done = specs.filter(s => s.status === 'done').length;
        if (total > 0) {
            const pct = Math.max(5, Math.round((done / total) * 100));
            fill.style.width = (state.phase === 'complete' ? '100' : pct) + '%';
            label.textContent = state.phase === 'complete' ? '完成' : `专家 ${done}/${total}`;
        } else if (state.phase === 'supervisor') {
            fill.style.width = '10%';
            label.textContent = '分析中...';
        }
    }

    _collapseProgressCard(messageElement) {
        const card = messageElement.querySelector('.diag-progress-card');
        if (!card) return;
        card.classList.add('collapsed');
        // 只保留一行摘要
        const body = card.querySelector('.dpc-body');
        const phases = card.querySelector('.dpc-phases');
        const progWrap = card.querySelector('.dpc-progress-wrap');
        if (body) body.style.display = 'none';
        if (phases) phases.style.display = 'none';
        if (progWrap) {
            const fill = progWrap.querySelector('.dpc-progress-fill');
            const label = progWrap.querySelector('.dpc-progress-label');
            if (fill) fill.style.width = '100%';
            if (label) label.textContent = '完成';
        }
    }

