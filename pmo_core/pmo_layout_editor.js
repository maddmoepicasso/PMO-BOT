(function () {
    'use strict';

    if (window.PMOVisualLayoutEditorLoaded) return;
    window.PMOVisualLayoutEditorLoaded = true;

    const currentScript = document.currentScript || document.querySelector('script[data-pmo-layout-editor]');
    const scriptConfig = currentScript ? currentScript.dataset : {};
    const rootSelector = scriptConfig.root || 'main';
    const dashboardName = scriptConfig.dashboard || document.title || location.pathname;
    const layoutStorageVersion = scriptConfig.storageVersion || 'v3';
    const storageKey = 'pmo.visualLayout.' + layoutStorageVersion + '.' + dashboardName + '.' + location.pathname;
    const mobileQuery = window.matchMedia('(max-width: 760px)');
    const blockSelector = [
        '.panel',
        '.card',
        '.mini',
        'details.panel',
        'details.admin-settings',
        '.family-menu',
        '.command-panel',
        '.service-card',
        '.news-card',
        '.feature-card',
        '.step-card',
        '.timeline-card',
        '.chart-shell',
        '[data-module]',
        '[data-pmo-section]',
        '[data-layout-widget]'
    ].join(',');
    const groupSelector = [
        '.grid',
        '.wide-grid',
        '.top-command-grid',
        '.switch-grid',
        '.summary-grid',
        '.projection-grid',
        '.form-grid',
        '.playz',
        '.platform-grid',
        '.how-flow',
        '.owner-flow-grid',
        '.lifecycle-board',
        '.service-panel-stack',
        '.login-grid',
        '.split'
    ].join(',');

    const defaults = new Map();
    const widgets = new Map();
    let root = null;
    let toolbar = null;
    let panel = null;
    let hiddenSelect = null;
    let selectedId = '';
    let activeDrag = null;
    let toolbarDrag = null;
    let saveTimer = 0;
    let observerTimer = 0;
    let applying = false;

    const state = loadState();

    function loadState() {
        const base = {
            version: 1,
            movementModeVersion: 2,
            dashboard: dashboardName,
            snap: false,
            grid: 24,
            editMode: false,
            previewMode: false,
            hasCustomLayout: false,
            toolbar: {},
            widgets: {},
            duplicates: []
        };
        try {
            const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
            if (saved && typeof saved === 'object') {
                const merged = Object.assign(base, saved, {
                    editMode: false,
                    previewMode: false,
                    toolbar: saved.toolbar && typeof saved.toolbar === 'object' ? saved.toolbar : {},
                    widgets: saved.widgets && typeof saved.widgets === 'object' ? saved.widgets : {},
                    duplicates: Array.isArray(saved.duplicates) ? saved.duplicates : []
                });
                merged.snap = parseBool(merged.snap, false);
                if (saved.movementModeVersion !== 2) {
                    merged.snap = false;
                    merged.movementModeVersion = 2;
                }
                return merged;
            }
        } catch (err) {
            console.warn('PMO layout editor could not read saved layout', err);
        }
        return base;
    }

    function saveStateNow() {
        collectAllLayouts();
        state.updatedAt = new Date().toISOString();
        try {
            localStorage.setItem(storageKey, JSON.stringify(state));
            setStatus('Saved');
        } catch (err) {
            setStatus('Save failed');
            console.warn('PMO layout editor save failed', err);
        }
    }

    function saveStateSoon() {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(saveStateNow, 450);
    }

    function installStyles() {
        if (document.getElementById('pmoVisualLayoutStyle')) return;
        const style = document.createElement('style');
        style.id = 'pmoVisualLayoutStyle';
        style.textContent = `
            body.pmo-layout-editing { --pmo-editor-blue:#7ab7ff; }
            body.pmo-layout-editing * { scroll-margin-top:86px; }
            .pmo-layout-canvas {
                position:relative !important;
                display:block !important;
                align-items:initial !important;
                gap:0 !important;
                background-image:none;
            }
            body.pmo-layout-editing .pmo-layout-canvas.pmo-snap-grid {
                background-image:
                    linear-gradient(rgba(122,183,255,.08) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(122,183,255,.08) 1px, transparent 1px);
                background-size:var(--pmo-grid-size, 24px) var(--pmo-grid-size, 24px);
                background-position:18px 18px;
            }
            .pmo-layout-widget {
                min-width:150px;
                min-height:72px;
                transition:box-shadow .16s ease, outline-color .16s ease, opacity .16s ease;
                pointer-events:auto;
            }
            .pmo-layout-positioned {
                position:absolute !important;
                max-width:none !important;
                box-sizing:border-box !important;
                overflow:auto;
                overflow-wrap:anywhere;
                overscroll-behavior:contain;
                scrollbar-gutter:stable;
                transform:none !important;
            }
            .pmo-layout-positioned img,
            .pmo-layout-positioned video,
            .pmo-layout-positioned canvas,
            .pmo-layout-positioned iframe {
                max-width:100%;
                height:auto;
            }
            .pmo-layout-positioned table {
                max-width:100%;
            }
            .pmo-layout-positioned pre,
            .pmo-layout-positioned code {
                white-space:pre-wrap;
                overflow-wrap:anywhere;
            }
            body.pmo-layout-editing .pmo-layout-widget {
                outline:1px dashed rgba(122,183,255,.56);
                outline-offset:3px;
                cursor:grab;
                touch-action:none;
                user-select:none;
                -webkit-user-select:none;
            }
            body.pmo-layout-editing .pmo-layout-widget * {
                pointer-events:auto;
            }
            body.pmo-layout-editing .pmo-layout-widget iframe,
            body.pmo-layout-editing .pmo-layout-widget .tradingview-widget-container,
            body.pmo-layout-editing .pmo-layout-widget .tradingview-widget-container__widget {
                pointer-events:none;
            }
            body.pmo-layout-editing .pmo-layout-widget:hover {
                outline-color:rgba(0,255,157,.82);
                box-shadow:0 0 0 1px rgba(0,255,157,.18), 0 14px 38px rgba(0,0,0,.26);
            }
            body.pmo-layout-editing .pmo-layout-widget.pmo-selected {
                outline:2px solid rgba(0,255,157,.92);
                box-shadow:0 0 0 3px rgba(0,255,157,.13), 0 18px 44px rgba(0,0,0,.32);
            }
            body.pmo-layout-editing .pmo-layout-widget.pmo-widget-locked {
                outline-color:rgba(255,209,102,.82);
                cursor:not-allowed;
            }
            .pmo-resize-handle {
                display:none;
                position:absolute;
                width:18px;
                height:18px;
                background:#7ab7ff;
                border:2px solid #05070a;
                border-radius:4px;
                z-index:2147482500;
                box-shadow:0 0 0 1px rgba(255,255,255,.24);
                pointer-events:auto;
                touch-action:none;
                user-select:none;
            }
            body.pmo-layout-editing .pmo-layout-widget.pmo-selected > .pmo-resize-handle { display:block; }
            .pmo-resize-handle[data-dir="n"] { top:4px; left:50%; transform:translateX(-50%); cursor:ns-resize; }
            .pmo-resize-handle[data-dir="s"] { bottom:4px; left:50%; transform:translateX(-50%); cursor:ns-resize; }
            .pmo-resize-handle[data-dir="e"] { right:4px; top:50%; transform:translateY(-50%); cursor:ew-resize; }
            .pmo-resize-handle[data-dir="w"] { left:4px; top:50%; transform:translateY(-50%); cursor:ew-resize; }
            .pmo-resize-handle[data-dir="ne"] { right:4px; top:4px; cursor:nesw-resize; }
            .pmo-resize-handle[data-dir="nw"] { left:4px; top:4px; cursor:nwse-resize; }
            .pmo-resize-handle[data-dir="se"] { right:4px; bottom:4px; cursor:nwse-resize; }
            .pmo-resize-handle[data-dir="sw"] { left:4px; bottom:4px; cursor:nesw-resize; }
            .pmo-layout-toolbar,
            .pmo-editor-panel,
            .pmo-preview-exit {
                font-family:Arial, sans-serif;
                color:#edf4ff;
                box-sizing:border-box;
            }
            .pmo-layout-toolbar {
                position:fixed;
                left:12px;
                right:12px;
                top:10px;
                z-index:2147482600;
                display:flex;
                align-items:center;
                gap:8px;
                flex-wrap:wrap;
                padding:9px;
                background:rgba(7,10,15,.94);
                border:1px solid rgba(122,183,255,.42);
                border-radius:8px;
                box-shadow:0 18px 42px rgba(0,0,0,.34);
                backdrop-filter:blur(10px);
            }
            .pmo-toolbar-drag-handle {
                display:inline-flex;
                align-items:center;
                gap:7px;
                min-height:32px;
                border:1px solid rgba(122,183,255,.38);
                border-radius:6px;
                padding:6px 9px;
                background:#0b121c;
                color:#bfffe8;
                font-size:13px;
                font-weight:bold;
                margin-right:2px;
                cursor:move;
                user-select:none;
                touch-action:none;
            }
            .pmo-toolbar-drag-handle::before {
                content:'::::';
                color:#7ab7ff;
                font-family:Consolas, 'Courier New', monospace;
                letter-spacing:0;
                line-height:1;
            }
            .pmo-layout-toolbar strong {
                color:#bfffe8;
                font-size:13px;
                margin-right:4px;
            }
            .pmo-layout-toolbar button,
            .pmo-layout-toolbar select,
            .pmo-editor-panel button,
            .pmo-editor-panel input,
            .pmo-editor-panel select {
                min-height:32px;
                border-radius:6px;
                border:1px solid #34475f;
                background:#172130;
                color:#edf4ff;
                padding:6px 8px;
                font:inherit;
                font-size:12px;
            }
            .pmo-layout-toolbar button {
                cursor:pointer;
                font-weight:bold;
            }
            .pmo-layout-toolbar button.is-on {
                border-color:rgba(0,255,157,.68);
                color:#bfffe8;
                background:#073b2f;
            }
            .pmo-layout-toolbar button.is-warn {
                border-color:rgba(255,209,102,.7);
                color:#ffe6a6;
            }
            .pmo-layout-toolbar button:disabled {
                opacity:.48;
                cursor:not-allowed;
            }
            .pmo-layout-toolbar button.is-danger,
            .pmo-editor-panel button.is-danger {
                border-color:rgba(255,92,122,.7);
                color:#ffd3dc;
                background:#3b1119;
            }
            .pmo-layout-toolbar .pmo-status {
                color:#9fb3c8;
                font-size:12px;
                margin-left:auto;
                min-width:96px;
                text-align:right;
            }
            .pmo-editor-panel {
                position:fixed;
                right:14px;
                top:76px;
                width:min(360px, calc(100vw - 28px));
                max-height:calc(100vh - 96px);
                overflow:auto;
                z-index:2147482650;
                background:rgba(9,16,25,.97);
                border:1px solid rgba(0,255,157,.42);
                border-radius:8px;
                padding:12px;
                box-shadow:0 18px 44px rgba(0,0,0,.38);
            }
            .pmo-editor-panel[hidden] { display:none !important; }
            .pmo-editor-head {
                display:flex;
                align-items:center;
                justify-content:space-between;
                gap:10px;
                margin-bottom:10px;
            }
            .pmo-editor-head strong { color:#bfffe8; }
            .pmo-editor-panel label {
                display:grid;
                gap:5px;
                color:#9fb3c8;
                font-size:11px;
                line-height:1.25;
            }
            .pmo-editor-grid {
                display:grid;
                grid-template-columns:1fr 1fr;
                gap:8px;
            }
            .pmo-editor-panel input,
            .pmo-editor-panel select { width:100%; }
            .pmo-editor-actions {
                display:grid;
                grid-template-columns:1fr 1fr;
                gap:7px;
                margin-top:10px;
            }
            .pmo-editor-actions button { cursor:pointer; font-weight:bold; }
            .pmo-preview-exit {
                display:none;
                position:fixed;
                top:10px;
                right:10px;
                z-index:2147482700;
                border:1px solid rgba(0,255,157,.7);
                background:#073b2f;
                color:#bfffe8;
                border-radius:6px;
                padding:8px 10px;
                font-weight:bold;
            }
            body.pmo-layout-preview .pmo-layout-toolbar,
            body.pmo-layout-preview .pmo-editor-panel { display:none !important; }
            body.pmo-layout-preview .pmo-preview-exit { display:block; }
            body.pmo-layout-preview .pmo-layout-widget,
            body:not(.pmo-layout-editing) .pmo-layout-widget {
                cursor:auto;
                outline:none;
            }
            .pmo-hidden-by-layout { display:none !important; }
            .pmo-deleted-by-layout { display:none !important; }
            .pmo-chart-type-bar table tr,
            .pmo-chart-type-bar .metric {
                box-shadow:inset 4px 0 0 rgba(122,183,255,.55);
            }
            .pmo-chart-type-line table tr,
            .pmo-chart-type-line .metric {
                text-decoration:underline;
                text-decoration-color:rgba(0,255,157,.6);
                text-decoration-thickness:2px;
            }
            @media(max-width:760px) {
                .pmo-layout-toolbar {
                    left:8px;
                    right:8px;
                    top:8px;
                    gap:6px;
                    max-height:44vh;
                    overflow:auto;
                }
                .pmo-layout-toolbar .pmo-status {
                    width:100%;
                    margin-left:0;
                    text-align:left;
                }
                .pmo-editor-panel {
                    left:8px;
                    right:8px;
                    top:auto;
                    bottom:8px;
                    width:auto;
                    max-height:64vh;
                }
                body:not(.pmo-layout-editing) .pmo-layout-canvas {
                    display:grid !important;
                    gap:10px !important;
                    min-height:0 !important;
                }
                body:not(.pmo-layout-editing) .pmo-layout-positioned {
                    position:relative !important;
                    left:auto !important;
                    top:auto !important;
                    width:auto !important;
                    height:auto !important;
                    max-width:100% !important;
                }
                body.pmo-layout-editing .pmo-layout-widget {
                    touch-action:none;
                }
            }
        `;
        document.head.appendChild(style);
    }

    function init() {
        root = document.querySelector(rootSelector);
        if (!root) return;
        installStyles();
        restoreDuplicates();
        discoverWidgets();
        buildToolbar();
        buildPanel();
        bindEvents();
        requestAnimationFrame(() => {
            measureDefaults();
            applyLayout();
            updateToolbar();
            updateHiddenSelect();
            observeChanges();
        });
    }

    function restoreDuplicates() {
        if (!root || !Array.isArray(state.duplicates)) return;
        state.duplicates.forEach((item) => {
            if (!item || !item.id || !item.html || root.querySelector(`[data-pmo-layout-id="${cssEscape(item.id)}"]`)) return;
            const holder = document.createElement('div');
            holder.innerHTML = String(item.html).trim();
            const clone = holder.firstElementChild;
            if (!clone) return;
            removeEditorArtifacts(clone);
            clone.dataset.pmoLayoutId = item.id;
            clone.dataset.pmoDuplicate = 'true';
            root.appendChild(clone);
        });
    }

    function discoverWidgets() {
        if (!root || applying) return;
        const previousSelection = selectedId;
        widgets.clear();
        const candidates = [];
        const topChildren = Array.from(root.children).filter((child) => !isEditorElement(child));
        topChildren.forEach((child) => {
            if (child.matches(groupSelector)) {
                const direct = Array.from(child.children).filter(isWidgetCandidate);
                if (direct.length) {
                    direct.forEach((item) => candidates.push(item));
                    return;
                }
            }
            if (isWidgetCandidate(child)) candidates.push(child);
        });
        root.querySelectorAll('[data-layout-widget]').forEach((item) => candidates.push(item));

        const unique = [];
        candidates.forEach((item) => {
            if (!item || isEditorElement(item)) return;
            if (unique.includes(item)) return;
            if (unique.some((existing) => existing.contains(item) && !item.dataset.layoutWidget)) return;
            unique.push(item);
        });

        unique.forEach((item, index) => registerWidget(item, index));
        if (previousSelection && widgets.has(previousSelection)) selectWidget(previousSelection, false);
    }

    function isWidgetCandidate(el) {
        if (!el || el.nodeType !== 1 || isEditorElement(el)) return false;
        if (el.matches('script,style,template,link,meta')) return false;
        if (el.matches(blockSelector)) return true;
        if (el.tagName === 'SECTION' || el.tagName === 'ARTICLE' || el.tagName === 'ASIDE') return true;
        return false;
    }

    function registerWidget(el, index) {
        const id = stableWidgetId(el, index);
        el.dataset.pmoLayoutId = id;
        el.classList.add('pmo-layout-widget');
        widgets.set(id, el);
        ensureLayout(id, index);
        ensureResizeHandles(el);
    }

    function stableWidgetId(el, index) {
        if (el.dataset.pmoLayoutId) return el.dataset.pmoLayoutId;
        if (el.id) return 'id-' + cleanId(el.id);
        if (el.dataset.module) return 'module-' + cleanId(el.dataset.module);
        if (el.dataset.pmoSection) return 'section-' + cleanId(el.dataset.pmoSection);
        const title = readTitle(el) || el.getAttribute('aria-label') || el.className || el.tagName || 'widget';
        return cleanId(title).slice(0, 44) + '-' + elementPath(el);
    }

    function cleanId(value) {
        return String(value || 'widget').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'widget';
    }

    function elementPath(el) {
        const parts = [];
        let cursor = el;
        while (cursor && cursor !== root && parts.length < 4) {
            const parent = cursor.parentElement;
            if (!parent) break;
            parts.unshift(Array.from(parent.children).indexOf(cursor) + 1);
            cursor = parent;
        }
        return parts.join('-') || '0';
    }

    function ensureLayout(id, index) {
        if (!state.widgets[id]) {
            state.widgets[id] = {
                visible: true,
                locked: false,
                order: (index + 1) * 10,
                z: index + 1,
                chartType: 'auto',
                spacing: 0,
                padding: '',
                borderRadius: '',
                background: ''
            };
        }
        return state.widgets[id];
    }

    function parentLayoutWidget(el) {
        if (!el || !el.parentElement) return null;
        return el.parentElement.closest('.pmo-layout-widget');
    }

    function layoutAnchorFor(el) {
        return parentLayoutWidget(el) || root;
    }

    function measureDefaults() {
        if (!root) return;
        widgets.forEach((el, id) => {
            const layout = state.widgets[id] || {};
            if (layout.deleted) return;
            const oldDisplay = el.style.display;
            if (layout.visible === false) el.style.display = '';
            const rect = el.getBoundingClientRect();
            const anchor = layoutAnchorFor(el);
            const anchorRect = anchor.getBoundingClientRect();
            defaults.set(id, {
                x: Math.max(0, Math.round(rect.left - anchorRect.left + anchor.scrollLeft)),
                y: Math.max(0, Math.round(rect.top - anchorRect.top + anchor.scrollTop)),
                width: Math.max(160, Math.round(rect.width || 260)),
                height: Math.max(90, Math.round(rect.height || 140)),
                order: layout.order || 0,
                z: layout.z || 1
            });
            el.style.display = oldDisplay;
        });
    }

    function collectAllLayouts() {
        widgets.forEach((el, id) => {
            const layout = ensureLayout(id, 0);
            const base = defaults.get(id) || {};
            layout.x = numberOr(layout.x, base.x || 0);
            layout.y = numberOr(layout.y, base.y || 0);
            layout.width = numberOr(layout.width, base.width || Math.round(el.getBoundingClientRect().width || 260));
            layout.height = numberOr(layout.height, base.height || Math.round(el.getBoundingClientRect().height || 140));
            layout.visible = layout.visible !== false;
            layout.order = numberOr(layout.order, base.order || 0);
            layout.z = numberOr(layout.z, base.z || 1);
            layout.locked = !!layout.locked;
            layout.title = layout.title || '';
            layout.chartType = layout.chartType || 'auto';
            layout.spacing = numberOr(layout.spacing, 0);
            layout.padding = layout.padding || '';
            layout.borderRadius = layout.borderRadius || '';
            layout.background = layout.background || '';
        });
        state.duplicates = Object.keys(state.widgets)
            .map((id) => Object.assign({ id }, state.widgets[id]))
            .filter((item) => item.duplicate && item.html)
            .map((item) => ({ id: item.id, html: item.html }));
    }

    function applyLayout() {
        if (!root) return;
        applying = true;
        const desktopCanvas = shouldUseCanvas();
        document.body.classList.toggle('pmo-layout-editing', !!state.editMode);
        document.body.classList.toggle('pmo-layout-preview', !!state.previewMode);
        root.classList.toggle('pmo-layout-canvas', desktopCanvas || mobileQuery.matches);
        root.classList.toggle('pmo-snap-grid', !!state.editMode && !!state.snap);
        root.style.setProperty('--pmo-grid-size', (state.grid || 24) + 'px');

        let maxBottom = 0;
        widgets.forEach((el, id) => {
            const layout = normalizedLayout(id);
            const visible = layout.visible !== false && !layout.deleted;
            const nestedWidget = !!parentLayoutWidget(el);
            el.classList.toggle('pmo-hidden-by-layout', !visible && !layout.deleted);
            el.classList.toggle('pmo-deleted-by-layout', !!layout.deleted);
            el.classList.toggle('pmo-widget-locked', !!layout.locked);
            el.classList.toggle('pmo-selected', id === selectedId);
            applyTitle(el, layout.title);
            applyVisualStyles(el, layout);
            applyChartClass(el, layout.chartType);
            if (!visible) {
                el.style.display = 'none';
                return;
            }
            el.style.display = '';
            el.style.zIndex = String(layout.z || 1);
            el.style.order = String(layout.order || 0);
            if (desktopCanvas) {
                el.classList.add('pmo-layout-positioned');
                el.style.left = layout.x + 'px';
                el.style.top = layout.y + 'px';
                el.style.width = layout.width + 'px';
                el.style.height = layout.height + 'px';
                if (!nestedWidget) maxBottom = Math.max(maxBottom, layout.y + layout.height + 48);
            } else {
                el.classList.toggle('pmo-layout-positioned', mobileQuery.matches && state.hasCustomLayout);
                el.style.left = '';
                el.style.top = '';
                el.style.width = '';
                el.style.height = '';
                maxBottom = 0;
            }
        });
        root.style.minHeight = desktopCanvas ? Math.max(maxBottom, window.innerHeight - 110) + 'px' : '';
        applying = false;
        updateToolbar();
        updatePanelFields();
        updateHiddenSelect();
    }

    function shouldUseCanvas() {
        return !!(state.editMode || (!mobileQuery.matches && (state.previewMode || state.hasCustomLayout)));
    }

    function normalizedLayout(id) {
        const base = defaults.get(id) || {};
        const layout = state.widgets[id] || {};
        return {
            x: numberOr(layout.x, base.x || 0),
            y: numberOr(layout.y, base.y || 0),
            width: numberOr(layout.width, base.width || 260),
            height: numberOr(layout.height, base.height || 140),
            visible: layout.visible !== false,
            deleted: !!layout.deleted,
            locked: !!layout.locked,
            order: numberOr(layout.order, base.order || 0),
            z: numberOr(layout.z, base.z || 1),
            title: layout.title || '',
            chartType: layout.chartType || 'auto',
            spacing: numberOr(layout.spacing, 0),
            padding: layout.padding || '',
            borderRadius: layout.borderRadius || '',
            background: layout.background || '',
            duplicate: !!layout.duplicate,
            html: layout.html || ''
        };
    }

    function applyVisualStyles(el, layout) {
        el.style.margin = layout.spacing ? layout.spacing + 'px' : '';
        el.style.padding = layout.padding || '';
        el.style.borderRadius = layout.borderRadius || '';
        el.style.background = layout.background || '';
    }

    function applyChartClass(el, type) {
        ['auto', 'metric', 'table', 'bar', 'line', 'area'].forEach((name) => el.classList.remove('pmo-chart-type-' + name));
        if (type && type !== 'auto') el.classList.add('pmo-chart-type-' + type);
        el.dataset.chartType = type || 'auto';
        if (type && type !== 'auto') {
            el.dispatchEvent(new CustomEvent('pmo:chart-type-change', { bubbles: true, detail: { chartType: type } }));
        }
    }

    function readTitle(el) {
        return (el.querySelector('[data-edit-title], h1, h2, h3, h4, .brand-title, .muted, .setting-value')?.textContent || '').trim();
    }

    function applyTitle(el, title) {
        if (!title) return;
        let target = el.querySelector('[data-edit-title], h1, h2, h3, h4');
        if (!target) target = el.querySelector('.muted, .setting-value');
        if (target) target.textContent = title;
    }

    function buildToolbar() {
        if (toolbar) return;
        toolbar = document.createElement('div');
        toolbar.className = 'pmo-layout-toolbar';
        toolbar.innerHTML = `
            <span class="pmo-toolbar-drag-handle" data-action="move-toolbar" title="Drag to move Layout Builder. Double-click to reset position.">Layout Builder</span>
            <button type="button" data-action="toggle-edit">Edit Mode</button>
            <button type="button" data-action="free-mode">Free Move</button>
            <button type="button" data-action="snap-mode">Snap Grid</button>
            <button type="button" data-action="move-top" title="Move selected block to the top of the dashboard">To Top</button>
            <button type="button" data-action="move-bottom" title="Move selected block to the bottom of the dashboard">To Bottom</button>
            <button type="button" data-action="preview">Preview Mode</button>
            <button type="button" data-action="save">Save Layout</button>
            <button type="button" data-action="reset" class="is-warn">Reset Layout</button>
            <select data-role="hidden-select" aria-label="Hidden blocks"><option value="">Hidden blocks</option></select>
            <button type="button" data-action="show-hidden">Show</button>
            <span class="pmo-status" data-role="status">Ready</span>
        `;
        document.body.appendChild(toolbar);
        hiddenSelect = toolbar.querySelector('[data-role="hidden-select"]');
        applyToolbarPosition();
        toolbar.querySelector('[data-action="move-toolbar"]')?.addEventListener('pointerdown', onToolbarPointerDown, true);
        toolbar.querySelector('[data-action="move-toolbar"]')?.addEventListener('mousedown', onToolbarPointerDown, true);
        toolbar.querySelector('[data-action="move-toolbar"]')?.addEventListener('touchstart', onToolbarPointerDown, { capture: true, passive: false });
        toolbar.querySelector('[data-action="move-toolbar"]')?.addEventListener('dblclick', resetToolbarPosition);
        toolbar.addEventListener('click', onToolbarClick);
        toolbar.addEventListener('change', (event) => {
            if (event.target.matches('[data-role="hidden-select"]') && event.target.value) {
                selectWidget(event.target.value, true);
            }
        });
        const exit = document.createElement('button');
        exit.type = 'button';
        exit.className = 'pmo-preview-exit';
        exit.textContent = 'Exit Preview';
        exit.addEventListener('click', () => {
            state.previewMode = false;
            applyLayout();
        });
        document.body.appendChild(exit);
    }

    function buildPanel() {
        if (panel) return;
        panel = document.createElement('div');
        panel.className = 'pmo-editor-panel';
        panel.hidden = true;
        panel.innerHTML = `
            <div class="pmo-editor-head">
                <strong>Block Controls</strong>
                <button type="button" data-action="close-panel">Close</button>
            </div>
            <label>Title <input data-field="title" placeholder="Custom block title"></label>
            <div class="pmo-editor-grid">
                <label>X <input data-field="x" type="number" step="1"></label>
                <label>Y <input data-field="y" type="number" step="1"></label>
                <label>Width <input data-field="width" type="number" min="120" step="1"></label>
                <label>Height <input data-field="height" type="number" min="70" step="1"></label>
                <label>Layer <input data-field="z" type="number" step="1"></label>
                <label>Order <input data-field="order" type="number" step="1"></label>
                <label>Spacing <input data-field="spacing" type="number" min="0" max="80" step="1"></label>
                <label>Padding <input data-field="padding" placeholder="16px"></label>
                <label>Radius <input data-field="borderRadius" placeholder="8px"></label>
                <label>Background <input data-field="background" placeholder="#101722 or gradient"></label>
            </div>
            <label>Chart Type
                <select data-field="chartType">
                    <option value="auto">Auto</option>
                    <option value="metric">Metric</option>
                    <option value="table">Table</option>
                    <option value="bar">Bar</option>
                    <option value="line">Line</option>
                    <option value="area">Area</option>
                </select>
            </label>
            <div class="pmo-editor-actions">
                <button type="button" data-action="move-top">Move Top</button>
                <button type="button" data-action="move-bottom">Move Bottom</button>
                <button type="button" data-action="bring-forward">Forward</button>
                <button type="button" data-action="send-backward">Backward</button>
                <button type="button" data-action="duplicate">Duplicate</button>
                <button type="button" data-action="toggle-lock">Lock</button>
                <button type="button" data-action="hide">Hide</button>
                <button type="button" data-action="delete" class="is-danger">Delete</button>
            </div>
        `;
        document.body.appendChild(panel);
        panel.addEventListener('input', onPanelInput);
        panel.addEventListener('change', onPanelInput);
        panel.addEventListener('click', onPanelClick);
    }

    function bindEvents() {
        root.addEventListener('pointerdown', onPointerDown, true);
        root.addEventListener('mousedown', onPointerDown, true);
        root.addEventListener('touchstart', onPointerDown, { capture: true, passive: false });
        root.addEventListener('dblclick', onDoubleClick, true);
        root.addEventListener('click', onRootClick, true);
        window.addEventListener('resize', () => {
            if (!state.hasCustomLayout && !state.editMode) measureDefaults();
            applyToolbarPosition(true);
            applyLayout();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                if (state.previewMode) state.previewMode = false;
                closePanel();
                applyLayout();
            }
            if (!state.editMode || !selectedId) return;
            if (event.key === 'Delete') {
                event.preventDefault();
                deleteSelected();
            }
            if (event.key.startsWith('Arrow')) {
                event.preventDefault();
                nudgeSelected(event.key, event.shiftKey ? 24 : 6);
            }
        });
    }

    function observeChanges() {
        if (!window.MutationObserver || !root) return;
        const observer = new MutationObserver(() => {
            if (applying) return;
            window.clearTimeout(observerTimer);
            observerTimer = window.setTimeout(() => {
                discoverWidgets();
                measureDefaults();
                applyLayout();
            }, 350);
        });
        observer.observe(root, { childList: true, subtree: true });
    }

    function onToolbarPointerDown(event) {
        if (toolbarDrag) return;
        if (!toolbar) return;
        event.preventDefault();
        event.stopPropagation();
        const point = eventPoint(event);
        const rect = toolbar.getBoundingClientRect();
        toolbarDrag = {
            startX: point.x,
            startY: point.y,
            x: rect.left,
            y: rect.top,
            width: rect.width
        };
        document.addEventListener('pointermove', onToolbarPointerMove, true);
        document.addEventListener('pointerup', onToolbarPointerUp, true);
        document.addEventListener('mousemove', onToolbarPointerMove, true);
        document.addEventListener('mouseup', onToolbarPointerUp, true);
        document.addEventListener('touchmove', onToolbarPointerMove, { capture: true, passive: false });
        document.addEventListener('touchend', onToolbarPointerUp, true);
        document.addEventListener('touchcancel', onToolbarPointerUp, true);
    }

    function onToolbarPointerMove(event) {
        if (!toolbarDrag || !toolbar) return;
        event.preventDefault();
        const point = eventPoint(event);
        const next = clampToolbarPosition({
            x: toolbarDrag.x + point.x - toolbarDrag.startX,
            y: toolbarDrag.y + point.y - toolbarDrag.startY,
            width: toolbarDrag.width
        });
        state.toolbar = next;
        applyToolbarPosition();
    }

    function onToolbarPointerUp(event) {
        if (!toolbarDrag) return;
        event.preventDefault();
        document.removeEventListener('pointermove', onToolbarPointerMove, true);
        document.removeEventListener('pointerup', onToolbarPointerUp, true);
        document.removeEventListener('mousemove', onToolbarPointerMove, true);
        document.removeEventListener('mouseup', onToolbarPointerUp, true);
        document.removeEventListener('touchmove', onToolbarPointerMove, true);
        document.removeEventListener('touchend', onToolbarPointerUp, true);
        document.removeEventListener('touchcancel', onToolbarPointerUp, true);
        toolbarDrag = null;
        setStatus('Builder moved');
        saveStateSoon();
    }

    function applyToolbarPosition(clampOnly) {
        if (!toolbar) return;
        const saved = state.toolbar && typeof state.toolbar === 'object' ? state.toolbar : {};
        if (!Number.isFinite(Number(saved.x)) || !Number.isFinite(Number(saved.y))) {
            toolbar.style.left = '';
            toolbar.style.right = '';
            toolbar.style.top = '';
            toolbar.style.width = '';
            return;
        }
        const next = clampToolbarPosition(saved);
        if (clampOnly) state.toolbar = next;
        toolbar.style.left = next.x + 'px';
        toolbar.style.top = next.y + 'px';
        toolbar.style.right = 'auto';
        toolbar.style.width = Math.max(280, next.width || Math.min(window.innerWidth - 24, 960)) + 'px';
    }

    function clampToolbarPosition(position) {
        const margin = 8;
        const width = Math.min(Math.max(280, Number(position.width || toolbar?.offsetWidth || 560)), Math.max(280, window.innerWidth - (margin * 2)));
        const maxX = Math.max(margin, window.innerWidth - width - margin);
        const maxY = Math.max(margin, window.innerHeight - 52);
        return {
            x: Math.round(Math.min(Math.max(margin, Number(position.x || margin)), maxX)),
            y: Math.round(Math.min(Math.max(margin, Number(position.y || margin)), maxY)),
            width: Math.round(width)
        };
    }

    function resetToolbarPosition(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        state.toolbar = {};
        applyToolbarPosition();
        setStatus('Builder reset');
        saveStateSoon();
    }

    function onToolbarClick(event) {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        const action = button.dataset.action;
        if (action === 'toggle-edit') {
            if (state.editMode) {
                state.editMode = false;
                state.previewMode = false;
            } else {
                enterEditMode();
            }
            applyLayout();
            saveStateSoon();
        } else if (action === 'toggle-snap') {
            state.snap = !state.snap;
            applyLayout();
            saveStateSoon();
        } else if (action === 'free-mode') {
            enterEditMode();
            state.snap = false;
            state.movementModeVersion = 2;
            setStatus('Free move active');
            applyLayout();
            saveStateSoon();
        } else if (action === 'snap-mode') {
            enterEditMode();
            state.snap = true;
            state.movementModeVersion = 2;
            setStatus('Snap grid active');
            applyLayout();
            saveStateSoon();
        } else if (action === 'move-top' || action === 'move-bottom') {
            moveSelectedToPageEdge(action === 'move-top' ? 'top' : 'bottom');
        } else if (action === 'preview') {
            state.previewMode = true;
            state.editMode = false;
            closePanel();
            applyLayout();
        } else if (action === 'save') {
            state.hasCustomLayout = true;
            saveStateNow();
        } else if (action === 'reset') {
            if (window.confirm('Reset PMO dashboard layout to the original default view?')) {
                localStorage.removeItem(storageKey);
                location.reload();
            }
        } else if (action === 'show-hidden') {
            const id = hiddenSelect && hiddenSelect.value;
            if (id) {
                updateLayout(id, { visible: true, deleted: false });
                selectWidget(id, true);
                saveStateSoon();
            }
        }
    }

    function onPanelClick(event) {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        const action = button.dataset.action;
        if (action === 'close-panel') closePanel();
        if (!selectedId) return;
        if (action === 'bring-forward') bumpLayer(selectedId, 1);
        if (action === 'send-backward') bumpLayer(selectedId, -1);
        if (action === 'move-top') moveSelectedToPageEdge('top');
        if (action === 'move-bottom') moveSelectedToPageEdge('bottom');
        if (action === 'duplicate') duplicateSelected();
        if (action === 'toggle-lock') toggleLockSelected();
        if (action === 'hide') hideSelected();
        if (action === 'delete') deleteSelected();
    }

    function enterEditMode() {
        state.editMode = true;
        state.previewMode = false;
        if (!state.hasCustomLayout) {
            measureDefaults();
            collectAllLayouts();
            state.hasCustomLayout = true;
        }
    }

    function onPanelInput(event) {
        if (!selectedId || !event.target.matches('[data-field]')) return;
        const field = event.target.dataset.field;
        const value = event.target.value;
        const patch = {};
        if (['x', 'y', 'width', 'height', 'z', 'order', 'spacing'].includes(field)) {
            patch[field] = Number(value || 0);
        } else {
            patch[field] = value;
        }
        updateLayout(selectedId, patch);
        state.hasCustomLayout = true;
        applyLayout();
        saveStateSoon();
    }

    function onPointerDown(event) {
        if (activeDrag) return;
        if (!state.editMode || state.previewMode) return;
        const handle = event.target.closest('.pmo-resize-handle');
        if (!handle && isEditorElement(event.target)) return;
        const widget = event.target.closest('.pmo-layout-widget');
        if (!widget || !root.contains(widget)) return;
        const id = widget.dataset.pmoLayoutId;
        if (!id) return;
        selectWidget(id, false);
        const layout = normalizedLayout(id);
        if (layout.locked && !event.target.classList.contains('pmo-resize-handle')) {
            event.preventDefault();
            openPanel(id);
            return;
        }
        const type = handle ? 'resize' : 'drag';
        event.preventDefault();
        event.stopPropagation();
        const point = eventPoint(event);
        activeDrag = {
            id,
            type,
            dir: handle ? handle.dataset.dir : '',
            startX: point.x,
            startY: point.y,
            layout: Object.assign({}, layout),
            moved: false
        };
        if (widget.setPointerCapture && event.pointerId !== undefined) {
            try { widget.setPointerCapture(event.pointerId); } catch (err) {}
        }
        document.addEventListener('pointermove', onPointerMove, true);
        document.addEventListener('pointerup', onPointerUp, true);
        document.addEventListener('mousemove', onPointerMove, true);
        document.addEventListener('mouseup', onPointerUp, true);
        document.addEventListener('touchmove', onPointerMove, { capture: true, passive: false });
        document.addEventListener('touchend', onPointerUp, true);
        document.addEventListener('touchcancel', onPointerUp, true);
    }

    function onPointerMove(event) {
        if (!activeDrag) return;
        event.preventDefault();
        const point = eventPoint(event);
        const dx = point.x - activeDrag.startX;
        const dy = point.y - activeDrag.startY;
        if (Math.abs(dx) + Math.abs(dy) > 2) activeDrag.moved = true;
        const next = Object.assign({}, activeDrag.layout);
        const forceFree = !state.snap || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey;
        if (activeDrag.type === 'drag') {
            next.x = snap(activeDrag.layout.x + dx, forceFree);
            next.y = snap(activeDrag.layout.y + dy, forceFree);
        } else {
            resizeLayout(next, dx, dy, activeDrag.dir, forceFree);
        }
        updateLayout(activeDrag.id, next, false);
        state.hasCustomLayout = true;
        applyLayout();
    }

    function onPointerUp(event) {
        if (!activeDrag) return;
        event.preventDefault();
        document.removeEventListener('pointermove', onPointerMove, true);
        document.removeEventListener('pointerup', onPointerUp, true);
        document.removeEventListener('mousemove', onPointerMove, true);
        document.removeEventListener('mouseup', onPointerUp, true);
        document.removeEventListener('touchmove', onPointerMove, true);
        document.removeEventListener('touchend', onPointerUp, true);
        document.removeEventListener('touchcancel', onPointerUp, true);
        saveStateSoon();
        activeDrag = null;
    }

    function eventPoint(event) {
        const touch = event.touches && event.touches[0] ? event.touches[0] : event.changedTouches && event.changedTouches[0] ? event.changedTouches[0] : null;
        return {
            x: Number(touch ? touch.clientX : event.clientX) || 0,
            y: Number(touch ? touch.clientY : event.clientY) || 0
        };
    }

    function resizeLayout(layout, dx, dy, dir, forceFree) {
        const minWidth = 150;
        const minHeight = 72;
        if (dir.includes('e')) layout.width = Math.max(minWidth, snap(layout.width + dx, forceFree));
        if (dir.includes('s')) layout.height = Math.max(minHeight, snap(layout.height + dy, forceFree));
        if (dir.includes('w')) {
            const width = Math.max(minWidth, snap(layout.width - dx, forceFree));
            layout.x = snap(layout.x + (layout.width - width), forceFree);
            layout.width = width;
        }
        if (dir.includes('n')) {
            const height = Math.max(minHeight, snap(layout.height - dy, forceFree));
            layout.y = snap(layout.y + (layout.height - height), forceFree);
            layout.height = height;
        }
    }

    function onDoubleClick(event) {
        if (!state.editMode) return;
        if (isEditorElement(event.target)) return;
        const widget = event.target.closest('.pmo-layout-widget');
        if (!widget) return;
        event.preventDefault();
        event.stopPropagation();
        openPanel(widget.dataset.pmoLayoutId);
    }

    function onRootClick(event) {
        if (!state.editMode) return;
        if (isEditorElement(event.target)) return;
        const widget = event.target.closest('.pmo-layout-widget');
        if (!widget) return;
        selectWidget(widget.dataset.pmoLayoutId, false);
        const interactive = event.target.closest('button, a, input, select, textarea, label, summary');
        if (interactive) {
            event.preventDefault();
            event.stopPropagation();
        }
    }

    function updateLayout(id, patch, markCustom) {
        const current = ensureLayout(id, 0);
        state.widgets[id] = Object.assign(current, patch);
        if (markCustom !== false) state.hasCustomLayout = true;
    }

    function selectWidget(id, scrollIntoView) {
        if (!widgets.has(id)) return;
        selectedId = id;
        widgets.forEach((el, widgetId) => el.classList.toggle('pmo-selected', widgetId === id));
        if (scrollIntoView) widgets.get(id).scrollIntoView({ behavior: 'smooth', block: 'center' });
        updatePanelFields();
        updateToolbar();
    }

    function openPanel(id) {
        selectWidget(id, false);
        if (panel) panel.hidden = false;
        updatePanelFields();
    }

    function closePanel() {
        if (panel) panel.hidden = true;
    }

    function updatePanelFields() {
        if (!panel || !selectedId || panel.hidden) return;
        const el = widgets.get(selectedId);
        if (!el) return;
        const layout = normalizedLayout(selectedId);
        setPanelValue('title', layout.title || readTitle(el));
        ['x', 'y', 'width', 'height', 'z', 'order', 'spacing', 'padding', 'borderRadius', 'background', 'chartType'].forEach((field) => {
            setPanelValue(field, layout[field] ?? '');
        });
        const lockButton = panel.querySelector('[data-action="toggle-lock"]');
        if (lockButton) lockButton.textContent = layout.locked ? 'Unlock' : 'Lock';
    }

    function setPanelValue(field, value) {
        const input = panel.querySelector(`[data-field="${field}"]`);
        if (input && document.activeElement !== input) input.value = value;
    }

    function bumpLayer(id, direction) {
        const layout = normalizedLayout(id);
        updateLayout(id, {
            z: Math.max(1, layout.z + direction),
            order: Math.max(0, layout.order + (direction * 10))
        });
        applyLayout();
        saveStateSoon();
    }

    function moveSelectedToPageEdge(edge) {
        if (!selectedId || !widgets.has(selectedId)) {
            setStatus('Select a block first');
            return;
        }
        const selectedEl = widgets.get(selectedId);
        const selectedLayout = normalizedLayout(selectedId);
        if (selectedLayout.locked) {
            setStatus('Unlock block first');
            return;
        }

        collectAllLayouts();
        const siblings = visibleWidgetLayouts(selectedId);
        const siblingOrders = siblings.map((item) => numberOr(item.layout.order, 0));
        const maxZ = siblings.reduce((highest, item) => Math.max(highest, numberOr(item.layout.z, 1)), numberOr(selectedLayout.z, 1));
        const gap = Math.max(12, numberOr(state.grid, 24), numberOr(selectedLayout.spacing, 0));

        if (edge === 'top') {
            const minOrder = siblingOrders.length ? Math.min(...siblingOrders, selectedLayout.order) : selectedLayout.order;
            updateLayout(selectedId, {
                y: 0,
                order: Math.round(minOrder - 10),
                z: Math.max(1, maxZ + 1)
            });
            setStatus('Moved to top');
        } else {
            const maxOrder = siblingOrders.length ? Math.max(...siblingOrders, selectedLayout.order) : selectedLayout.order;
            const maxBottom = siblings.reduce((bottom, item) => {
                return Math.max(bottom, numberOr(item.layout.y, 0) + numberOr(item.layout.height, 140) + numberOr(item.layout.spacing, 0));
            }, 0);
            updateLayout(selectedId, {
                y: snap(maxBottom + gap, true),
                order: Math.round(maxOrder + 10)
            });
            setStatus('Moved to bottom');
        }

        applyLayout();
        selectWidget(selectedId, true);
        saveStateSoon();
        if (selectedEl) {
            requestAnimationFrame(() => selectedEl.scrollIntoView({ behavior: 'smooth', block: edge === 'top' ? 'start' : 'end' }));
        }
    }

    function visibleWidgetLayouts(excludeId) {
        const items = [];
        widgets.forEach((el, id) => {
            if (id === excludeId) return;
            const layout = normalizedLayout(id);
            if (layout.visible === false || layout.deleted) return;
            items.push({ id, el, layout });
        });
        return items;
    }

    function toggleLockSelected() {
        const layout = normalizedLayout(selectedId);
        updateLayout(selectedId, { locked: !layout.locked });
        applyLayout();
        saveStateSoon();
    }

    function hideSelected() {
        if (!selectedId) return;
        updateLayout(selectedId, { visible: false });
        closePanel();
        applyLayout();
        saveStateSoon();
    }

    function deleteSelected() {
        if (!selectedId) return;
        const id = selectedId;
        const layout = normalizedLayout(id);
        if (!window.confirm('Delete this layout block from the dashboard? Reset Layout brings original blocks back.')) return;
        const el = widgets.get(id);
        if (layout.duplicate && el) {
            el.remove();
            delete state.widgets[id];
        } else {
            updateLayout(id, { deleted: true, visible: false });
        }
        selectedId = '';
        closePanel();
        discoverWidgets();
        applyLayout();
        saveStateSoon();
    }

    function duplicateSelected() {
        const el = widgets.get(selectedId);
        if (!el) return;
        const layout = normalizedLayout(selectedId);
        const clone = el.cloneNode(true);
        removeEditorArtifacts(clone);
        stripDuplicateIds(clone);
        const copyId = selectedId + '-copy-' + Date.now().toString(36);
        clone.dataset.pmoLayoutId = copyId;
        clone.dataset.pmoDuplicate = 'true';
        root.appendChild(clone);
        const html = clone.outerHTML;
        const offset = state.snap ? (state.grid || 24) : 18;
        state.widgets[copyId] = Object.assign({}, layout, {
            x: layout.x + offset,
            y: layout.y + offset,
            z: layout.z + 1,
            order: layout.order + 1,
            visible: true,
            locked: false,
            deleted: false,
            duplicate: true,
            html,
            title: layout.title ? layout.title + ' Copy' : ''
        });
        state.hasCustomLayout = true;
        discoverWidgets();
        measureDefaults();
        selectWidget(copyId, true);
        applyLayout();
        saveStateSoon();
    }

    function removeEditorArtifacts(el) {
        el.classList.remove('pmo-layout-widget', 'pmo-layout-positioned', 'pmo-selected', 'pmo-widget-locked');
        el.querySelectorAll('.pmo-resize-handle').forEach((handle) => handle.remove());
        el.querySelectorAll('.pmo-layout-widget, .pmo-layout-positioned, .pmo-selected, .pmo-widget-locked').forEach((item) => {
            item.classList.remove('pmo-layout-widget', 'pmo-layout-positioned', 'pmo-selected', 'pmo-widget-locked');
        });
        ['left', 'top', 'width', 'height', 'position', 'zIndex', 'order', 'display'].forEach((prop) => {
            el.style[prop] = '';
        });
    }

    function stripDuplicateIds(el) {
        if (el.id) el.removeAttribute('id');
        el.querySelectorAll('[id]').forEach((item) => item.removeAttribute('id'));
        el.querySelectorAll('[for]').forEach((item) => item.removeAttribute('for'));
    }

    function ensureResizeHandles(el) {
        if (el.querySelector(':scope > .pmo-resize-handle')) return;
        ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'].forEach((dir) => {
            const handle = document.createElement('span');
            handle.className = 'pmo-resize-handle';
            handle.dataset.dir = dir;
            handle.setAttribute('aria-hidden', 'true');
            el.appendChild(handle);
        });
    }

    function nudgeSelected(key, amount) {
        const layout = normalizedLayout(selectedId);
        const patch = {};
        if (key === 'ArrowLeft') patch.x = Math.max(0, layout.x - amount);
        if (key === 'ArrowRight') patch.x = layout.x + amount;
        if (key === 'ArrowUp') patch.y = Math.max(0, layout.y - amount);
        if (key === 'ArrowDown') patch.y = layout.y + amount;
        updateLayout(selectedId, patch);
        applyLayout();
        saveStateSoon();
    }

    function updateToolbar() {
        if (!toolbar) return;
        const edit = toolbar.querySelector('[data-action="toggle-edit"]');
        const snap = toolbar.querySelector('[data-action="snap-mode"], [data-action="toggle-snap"]');
        const free = toolbar.querySelector('[data-action="free-mode"]');
        if (edit) {
            edit.textContent = state.editMode ? 'Locked Mode' : 'Edit Mode';
            edit.classList.toggle('is-on', state.editMode);
        }
        if (free) {
            free.textContent = state.editMode && !state.snap ? 'Free Move On' : 'Free Move';
            free.classList.toggle('is-on', !state.snap);
            free.title = 'Enter edit mode and move blocks without grid snapping.';
        }
        if (snap) {
            snap.textContent = state.editMode && state.snap ? 'Snap Grid On' : 'Snap Grid';
            snap.classList.toggle('is-on', state.snap);
            snap.title = 'Enter edit mode and snap movement to clean grid steps.';
        }
        toolbar.querySelectorAll('[data-action="move-top"], [data-action="move-bottom"]').forEach((button) => {
            button.disabled = !selectedId || !widgets.has(selectedId);
        });
    }

    function updateHiddenSelect() {
        if (!hiddenSelect) return;
        const selected = hiddenSelect.value;
        hiddenSelect.innerHTML = '<option value="">Hidden blocks</option>';
        widgets.forEach((el, id) => {
            const layout = normalizedLayout(id);
            if (layout.visible === false && !layout.deleted) {
                const option = document.createElement('option');
                option.value = id;
                option.textContent = layout.title || readTitle(el) || id;
                hiddenSelect.appendChild(option);
            }
        });
        if (selected) hiddenSelect.value = selected;
    }

    function setStatus(message) {
        if (!toolbar) return;
        const status = toolbar.querySelector('[data-role="status"]');
        if (status) status.textContent = message;
    }

    function snap(value, forceFree) {
        const grid = Number(state.grid || 24);
        const raw = Math.max(0, Number(value || 0));
        if (!state.snap || forceFree) return Math.round(raw * 100) / 100;
        return Math.round(raw / grid) * grid;
    }

    function numberOr(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function parseBool(value, fallback) {
        if (typeof value === 'boolean') return value;
        if (typeof value === 'string') {
            if (value.toLowerCase() === 'true') return true;
            if (value.toLowerCase() === 'false') return false;
        }
        return fallback;
    }

    function isEditorElement(el) {
        return !!(el && el.closest && el.closest('.pmo-layout-toolbar, .pmo-editor-panel, .pmo-preview-exit, .pmo-resize-handle'));
    }

    function cssEscape(value) {
        if (window.CSS && CSS.escape) return CSS.escape(value);
        return String(value).replace(/"/g, '\\"');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
