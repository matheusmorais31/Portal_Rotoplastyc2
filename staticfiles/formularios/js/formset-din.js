/*****************************************************************
 * formset-din.js  –  Builder de Formulários
 * --------------------------------------------------------------
 * • Sortable + Autosave via HTMX
 * • Campos multipla / checkbox / lista  →  opcoes_json
 * • Campo Upload (arquivo)              →  valid_json
 * • Suporte completo a origem "SQLHub" p/ Lista (sem inline <script>)
 * • ESCOPADO ao #campos-formset
 * • Habilita/Desabilita inputs p/ não irem ao POST indevido
 * • Validação visual (cliente) p/ “Rótulo”, “Tipo” e configs (SQLHub/Upload)
 *****************************************************************/

(function () {
  const LOG = true;
  const log = (...args) => LOG && console.debug("[CLIENT]", ...args);

  // ===== Escopo / utils =====
  const getFormset = () => document.getElementById("campos-formset");
  const qsaFS = (sel) => (getFormset() ? getFormset().querySelectorAll(sel) : []);
  const debounce = (fn, ms = 400) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const setDisabled = (el, disabled, reason = "") => {
    if (!el) return;
    el.disabled = !!disabled;
    if (disabled) el.setAttribute("data-disabled-by", reason || "formset-din");
    else el.removeAttribute("data-disabled-by");
  };
  const getPrefix = (card) => {
    if (card?.dataset?.prefix) return card.dataset.prefix;
    const any = card?.querySelector("[name^='campo_set-']");
    const m = any?.name?.match?.(/^(campo_set-\d+)-/);
    return m ? m[1] : "";
  };
  const getTipoValue = (card) => card?.querySelector("select[name$='-tipo']")?.value || "";
  const fillSelect = (sel, items, vKey, tKey, firstLabel, decorate) => {
    if (!sel) return;
    sel.innerHTML = '';
    const o0 = document.createElement('option');
    o0.value = ''; o0.textContent = firstLabel || 'Selecione…';
    sel.appendChild(o0);
    (items||[]).forEach(it=>{
      const o = document.createElement('option');
      o.value = String(it[vKey] ?? '');
      o.textContent = String(it[tKey] ?? it[vKey] ?? '');
      if (typeof decorate === 'function') decorate(o, it);
      sel.appendChild(o);
    });
  };

  // ===== Helpers JSON (opções/lista + upload) =====
  function updateSingleOptionsJsonField(block) {
    const list = block.querySelector(".options-list");
    const hidden = block.querySelector("input[name$='-opcoes_json']");
    if (!list || !hidden) return;
    const values = [...list.querySelectorAll("input[type='text']")]
      .map((i) => i.value.trim())
      .filter(Boolean);
    hidden.value = JSON.stringify(values);
    log("opcoes_json atualizado:", values);
  }

  function buildFileValidationJson(card) {
    if (!card) return;
    const hidden = card.querySelector("input[name$='-valid_json']");
    const tipo = getTipoValue(card);
    if (!hidden) return;

    // se não for 'arquivo' → limpa/desabilita
    if (tipo !== "arquivo") {
      const before = hidden.value;
      if (hidden.value) hidden.value = "";
      setDisabled(hidden, true, "tipo!=arquivo");
      log("valid_json LIMPO (tipo!=arquivo)", { prefix: getPrefix(card), tipo, before, disabled: hidden.disabled });
      return;
    }

    // é 'arquivo' → habilita e monta payload
    setDisabled(hidden, false);

    const toggle = card.querySelector(".cfg-tipos-toggle");
    const categorias = [...card.querySelectorAll(".cfg-type-item input:checked")].map((i) => i.value);
    const maxArqsEl = card.querySelector(".cfg-max-arqs");
    const maxMbEl   = card.querySelector(".cfg-max-mb");

    const maxArqs = Math.max(1, parseInt(maxArqsEl?.value || "1", 10) || 1);
    const maxMb   = Math.max(1, parseInt(maxMbEl?.value   || "10", 10) || 10);

    const tiposLivres = toggle ? !toggle.checked : true;

    const payload = {
      tipos_livres: tiposLivres,
      categorias,
      max_arquivos: maxArqs,
      max_mb: maxMb,
    };
    hidden.value = JSON.stringify(payload);

    log("valid_json atualizado:", {
      prefix: getPrefix(card),
      disabled: hidden.disabled,
      toggle_checked: !!toggle?.checked,
      tipos_livres: tiposLivres,
      categorias,
      max_arquivos: maxArqs,
      max_mb: maxMb,
      hidden_value: hidden.value,
    });
  }

  function updateAllHiddenJson() {
    // opções (considerando origem quando tipo=lista)
    qsaFS(".pergunta-card").forEach((card) => {
      const tipo = getTipoValue(card);
      const origem = (card.querySelector("input[name$='-origem_opcoes']")?.value || "manual").trim();
      const hiddenOpts = card.querySelector("input[name$='-opcoes_json']");
      const optsBlock  = card.querySelector(".options-block");
      const showOpts = ["multipla","checkbox"].includes(tipo) || (tipo === "lista" && origem !== "sqlhub");
      if (optsBlock && hiddenOpts) {
        if (showOpts) {
          setDisabled(hiddenOpts, false);
          updateSingleOptionsJsonField(optsBlock);
        } else {
          hiddenOpts.value = "";
          setDisabled(hiddenOpts, true, "sem_opcoes");
        }
      }
    });

    // arquivo (sempre recalcula o JSON – mas só para tipo=arquivo)
    qsaFS(".pergunta-card").forEach((c) => {
      const tipo = getTipoValue(c);
      if (tipo === "arquivo") buildFileValidationJson(c);
    });

    // toolbar toggle → sombra
    const toolbarToggle = document.querySelector(".tb-toggle input");
    const shadow = document.getElementById("aceita_respostas_shadow");
    if (toolbarToggle && shadow) shadow.checked = !!toolbarToggle.checked;
  }

  // ===== Autosave =====
  const triggerAutosave = () => {
    updateAllHiddenJson();
    document.body.dispatchEvent(new Event("autosave", { bubbles: true }));
    log("autosave disparado (from:body).");
  };
  const debouncedTriggerAutosave = debounce(triggerAutosave);
  window.triggerAutosave = triggerAutosave;
  window.debouncedTriggerAutosave = debouncedTriggerAutosave;

  // ===== TOTAL_FORMS + ordem =====
  function syncTotalAndOrder() {
    const wrap = getFormset();
    if (!wrap) return;

    const cards = qsaFS(".pergunta-card");
    const total = document.getElementById(`id_${wrap.dataset.prefix}-TOTAL_FORMS`);
    if (total) total.value = String(cards.length);

    cards.forEach((c, i) => {
      const ord = c.querySelector("input[name$='-ordem']");
      if (ord) ord.value = i + 1;
    });
  }
  document.addEventListener("htmx:afterSwap", syncTotalAndOrder);
  document.addEventListener("rowDeleted", syncTotalAndOrder);
  document.addEventListener("rowDeleted", () => debouncedTriggerAutosave());

  // ===== Sortable =====
  function initSortable() {
    const wrap = getFormset();
    if (wrap && !wrap.sortableReady) {
      Sortable.create(wrap, {
        handle: ".drag-handle",
        draggable: ".pergunta-card",
        animation: 150,
        onEnd() { syncTotalAndOrder(); triggerAutosave(); },
      });
      wrap.sortableReady = true;
      log("Sortable inicializado.");
    }
  }
  document.addEventListener("DOMContentLoaded", initSortable);
  document.addEventListener("htmx:afterSwap", initSortable);

  // ===== Visibilidade + habilitação (inclui origem/sqlhub) =====
  function applyVisibilityAndDisabling(card) {
    if (!card || !card.closest("#campos-formset")) return;

    const tipo    = getTipoValue(card);
    const origemHidden = (card.querySelector("input[name$='-origem_opcoes']")?.value || "manual").trim();
    const originBlk = card.querySelector(".options-origin");
    const sqlBlk    = card.querySelector(".sqlhub-config");
    const optsBlk   = card.querySelector(".options-block");
    const cfgBlk    = card.querySelector(".file-config");

    const hiddenOpts  = card.querySelector("input[name$='-opcoes_json']");
    const hiddenValid = card.querySelector("input[name$='-valid_json']");

    const isLista     = (tipo === "lista");
    const showOrigin  = isLista;
    const showSql     = isLista && origemHidden === "sqlhub";
    const showOpts    = ["multipla","checkbox"].includes(tipo) || (isLista && origemHidden !== "sqlhub");
    const showCfg     = (tipo === "arquivo");

    originBlk?.classList.toggle("hide", !showOrigin);
    sqlBlk?.classList.toggle("hide", !showSql);
    optsBlk?.classList.toggle("hide", !showOpts);
    cfgBlk?.classList.toggle("hide", !showCfg);

    if (hiddenOpts) {
      if (showOpts) setDisabled(hiddenOpts, false);
      else { hiddenOpts.value = ""; setDisabled(hiddenOpts, true, "sem_opcoes"); }
    }
    if (hiddenValid) {
      if (showCfg) setDisabled(hiddenValid, false);
      else { hiddenValid.value = ""; setDisabled(hiddenValid, true, "tipo!=arquivo"); }
    }

    log("toggleBlocks prefix=%s tipo=%s origem=%s → origin=%s sql=%s opts=%s cfg=%s",
      getPrefix(card), tipo, origemHidden, showOrigin, showSql, showOpts, showCfg);

    if (showSql) initSqlhub(card, /*restore*/true);
  }

  // ===== Validação visual por card =====
  function setFieldError(card, fieldName, msg){
    const holder = card.querySelector(`[data-error-holder="${fieldName}"]`);
    const wrap   = card.querySelector(`[data-field="${fieldName}"]`);
    if(holder){ holder.innerHTML = msg ? `<li>${msg}</li>` : ""; }
    if(wrap){ wrap.classList.toggle("erro", !!msg); }
  }
  function setGlobalWarn(card, on) {
    const flag = card.querySelector(".card-flag.warn");
    if (flag) flag.classList.toggle("hide", !on);
  }
  function validateCard(card){
    if(!card) return;

    // limpa avisos anteriores
    ["rotulo","tipo","sqlhub","opcoes","upload"].forEach(k => setFieldError(card, k, ""));
    let problems = 0;

    const tipo   = (card.querySelector("select[name$='-tipo']")?.value || "").trim();
    const rotulo = (card.querySelector("input[name$='-rotulo']")?.value || "").trim();

    // básicos
    if(!tipo){ setFieldError(card, "tipo", "Selecione o tipo."); problems++; }
    if(!rotulo){ setFieldError(card, "rotulo", "Informe o rótulo."); problems++; }

    // Lista: origem manual x sqlhub
    if (tipo === "lista") {
      const origem = (card.querySelector("input[name$='-origem_opcoes']")?.value || "manual").trim();

      if (origem === "sqlhub") {
        const hidConn = (card.querySelector("input[name$='-sqlhub_connection_id']")?.value || "").trim();
        const hidQ    = (card.querySelector("input[name$='-sqlhub_query_id']")?.value || "").trim();
        const hidV    = (card.querySelector("input[name$='-sqlhub_value_field']")?.value || "").trim();
        const hidL    = (card.querySelector("input[name$='-sqlhub_label_field']")?.value || "").trim();

        const faltas = [];
        if(!hidConn) faltas.push("Conexão");
        if(!hidQ)    faltas.push("Consulta");
        if(!hidV)    faltas.push("Campo (valor)");
        if(!hidL)    faltas.push("Campo (rótulo)");

        if (faltas.length){
          setFieldError(card, "sqlhub", "Defina: " + faltas.join(", ") + ".");
          problems++;
        }
      } else {
        // manual
        const qtd = [...(card.querySelectorAll(".options-block .options-list input[type='text']") || [])]
          .map(i => (i.value||"").trim())
          .filter(Boolean).length;
        if (qtd === 0){
          setFieldError(card, "opcoes", "Adicione pelo menos 1 opção.");
          problems++;
        }
      }
    }

    // Upload: quando restringe tipos, precisa marcar pelo menos uma categoria
    if (tipo === "arquivo") {
      const toggle = card.querySelector(".cfg-tipos-toggle");
      const box    = card.querySelector(".cfg-tipos-list");
      const maxArq = parseInt(card.querySelector(".cfg-max-arqs")?.value || "1", 10) || 1;
      const maxMb  = parseInt(card.querySelector(".cfg-max-mb")?.value  || "10",10) || 10;

      if (toggle?.checked) {
        const qtdCats = box ? box.querySelectorAll("input[type='checkbox']:checked").length : 0;
        if (qtdCats === 0){
          setFieldError(card, "upload", "Selecione pelo menos 1 categoria ou desmarque a restrição.");
          problems++;
        }
      }
      if (maxArq < 1 || maxMb < 1){
        setFieldError(card, "upload", "Valores mínimos: 1 arquivo e 1 MB.");
        problems++;
      }
    }

    setGlobalWarn(card, problems > 0);
  }

  // ===== SQLHub (carregadores centralizados) =====
  async function sqlhubLoadConnections(card){
    const selConn = card.querySelector('.sel-conn');
    const sqlBlk  = card.querySelector('.sqlhub-config');
    if (!selConn || !sqlBlk) return;
    try{
      const url = sqlBlk.dataset.connsUrl || "/sqlhub/api/connections/";
      const r = await fetch(url, {headers:{'X-Requested-With':'fetch'}});
      const j = await r.json();
      const items = (j && j.connections) || [];
      fillSelect(selConn, items, 'id', 'name', 'Conexão…');
      const hidConn = card.querySelector("input[name$='-sqlhub_connection_id']");
      if (hidConn?.value) selConn.value = String(hidConn.value);
      log("[SQLHub] connections loaded:", items.length, "selected:", selConn?.value);
    }catch(e){
      fillSelect(card.querySelector('.sel-conn'), [], 'id', 'name', 'Falha ao carregar');
      log("[SQLHub] connections error", e);
    }
  }
  async function sqlhubLoadQueries(card, connId){
    const selQuery = card.querySelector('.sel-query');
    const sqlBlk   = card.querySelector('.sqlhub-config');
    if (!selQuery || !sqlBlk) return;
    try{
      const base = sqlBlk.dataset.queriesUrl || "/sqlhub/api/queries/";
      const url = connId ? `${base}?connection=${encodeURIComponent(connId)}` : base;
      const r = await fetch(url, {headers:{'X-Requested-With':'fetch'}});
      const j = await r.json();
      const items = (j && j.queries) || [];
      fillSelect(
        selQuery, items, 'id', 'name', 'Consulta…',
        (opt, it) => { opt.dataset.conn = it.connection_id ?? it.connection ?? it.connectionId ?? ''; }
      );
      const hidQ = card.querySelector("input[name$='-sqlhub_query_id']");
      if (hidQ?.value) selQuery.value = String(hidQ.value);
      log("[SQLHub] queries loaded:", items.length, "selected:", selQuery?.value, "connId:", connId || "(any)");
    }catch(e){
      fillSelect(selQuery, [], 'id', 'name', 'Falha ao carregar');
      log("[SQLHub] queries error", e);
    }
  }
  async function sqlhubLoadColumns(card, qid){
    const selVal = card.querySelector('.sel-val');
    const selLbl = card.querySelector('.sel-lbl');
    if(!selVal || !selLbl){
      return;
    }
    if(!qid){
      fillSelect(selVal, [], 'name', 'name', 'Valor');
      fillSelect(selLbl, [], 'name', 'name', 'Rótulo');
      log("[SQLHub] columns cleared (no qid)");
      return;
    }
    try{
      const r = await fetch(`/sqlhub/queries/${qid}/columns/`, {headers:{'X-Requested-With':'fetch'}});
      const j = await r.json();
      const cols = (j && j.ok && j.columns) ? j.columns : [];
      const items = cols.map(c => ({name:c}));
      fillSelect(selVal, items, 'name', 'name', 'Valor');
      fillSelect(selLbl, items, 'name', 'name', 'Rótulo');
      const hidV = card.querySelector("input[name$='-sqlhub_value_field']");
      const hidL = card.querySelector("input[name$='-sqlhub_label_field']");
      if (hidV?.value) selVal.value = hidV.value;
      if (hidL?.value) selLbl.value = hidL.value;
      log("[SQLHub] columns loaded:", items.length, "qid:", qid, "val:", selVal?.value, "lbl:", selLbl?.value);
    }catch(e){
      fillSelect(selVal, [], 'name', 'name', 'Falha ao carregar');
      fillSelect(selLbl, [], 'name', 'name', 'Falha ao carregar');
      log("[SQLHub] columns error", e);
    }
  }

  async function sqlhubRestore(card){
    const hidConn = card.querySelector("input[name$='-sqlhub_connection_id']");
    const hidQ    = card.querySelector("input[name$='-sqlhub_query_id']");
    const selConn = card.querySelector(".sel-conn");
    if (hidConn?.value) selConn.value = String(hidConn.value);
    await sqlhubLoadQueries(card, hidConn?.value || '');
    if (hidQ?.value){
      card.querySelector(".sel-query").value = String(hidQ.value);
      await sqlhubLoadColumns(card, hidQ.value);
    }
    const hidV = card.querySelector("input[name$='-sqlhub_value_field']");
    const hidL = card.querySelector("input[name$='-sqlhub_label_field']");
    if (hidV?.value && card.querySelector('.sel-val')) card.querySelector('.sel-val').value = hidV.value;
    if (hidL?.value && card.querySelector('.sel-lbl')) card.querySelector('.sel-lbl').value = hidL.value;
    log("[SQLHub] restore done", {conn:hidConn?.value, qid:hidQ?.value, val:hidV?.value, lbl:hidL?.value});
  }

  function wireSqlhubEvents(card){
    const selConn = card.querySelector('.sel-conn');
    const selQuery= card.querySelector('.sel-query');
    const selVal  = card.querySelector('.sel-val');
    const selLbl  = card.querySelector('.sel-lbl');
    const hidConn = card.querySelector("input[name$='-sqlhub_connection_id']");
    const hidQ    = card.querySelector("input[name$='-sqlhub_query_id']");
    const hidV    = card.querySelector("input[name$='-sqlhub_value_field']");
    const hidL    = card.querySelector("input[name$='-sqlhub_label_field']");

    if (selConn && !selConn._wired){
      selConn._wired = true;
      selConn.addEventListener('change', async (e)=>{
        const cid = (e.target.value || '').trim();
        if(hidConn) hidConn.value = cid;
        await sqlhubLoadQueries(card, cid);
        if(hidQ) hidQ.value = '';
        fillSelect(selVal, [], 'name', 'name', 'Valor');
        fillSelect(selLbl, [], 'name', 'name', 'Rótulo');
        debouncedTriggerAutosave();
        validateCard(card);
      });
    }
    if (selQuery && !selQuery._wired){
      selQuery._wired = true;
      selQuery.addEventListener('change', async (e)=>{
        const qid = (e.target.value || '').trim();
        if(hidQ) hidQ.value = qid;
        const opt = e.target.selectedOptions?.[0];
        const connFromOpt = opt?.dataset?.conn;
        if(connFromOpt){
          if (selConn) selConn.value = String(connFromOpt);
          if (hidConn) hidConn.value = String(connFromOpt);
          log('[SQLHub] query change set conn from option:', connFromOpt);
        }
        await sqlhubLoadColumns(card, qid);
        debouncedTriggerAutosave();
        validateCard(card);
      });
    }
    if (selVal && !selVal._wired){
      selVal._wired = true;
      selVal.addEventListener('change', (e)=>{
        if(hidV){ hidV.value = e.target.value; debouncedTriggerAutosave(); }
        validateCard(card);
      });
    }
    if (selLbl && !selLbl._wired){
      selLbl._wired = true;
      selLbl.addEventListener('change', (e)=>{
        if(hidL){ hidL.value = e.target.value; debouncedTriggerAutosave(); }
        validateCard(card);
      });
    }
  }

  async function initSqlhub(card, restore=false){
    if (!card || card._sqlhubReady) return;
    const sqlBlk = card.querySelector('.sqlhub-config');
    if (!sqlBlk) return;

    card._sqlhubReady = true;

    await sqlhubLoadConnections(card);
    await sqlhubLoadQueries(card, card.querySelector("input[name$='-sqlhub_connection_id']")?.value || '');
    if (restore) await sqlhubRestore(card);

    wireSqlhubEvents(card);
  }

  // ===== ligar eventos do .file-config (UPLOAD) =====
  function wireFileConfigEvents(card){
    const toggle = card.querySelector(".cfg-tipos-toggle");
    const list   = card.querySelector(".cfg-tipos-list");
    const maxArq = card.querySelector(".cfg-max-arqs");
    const maxMb  = card.querySelector(".cfg-max-mb");

    // liga/mostra a lista de categorias
    toggle?.addEventListener("change", (ev)=>{
      list?.classList.toggle("hide", !ev.target.checked);
      log("file-config: toggle change", { prefix: getPrefix(card), checked: !!ev.target.checked });
      buildFileValidationJson(card);
      triggerAutosave();
      validateCard(card);
    });

    // qualquer alteração em checkboxes de tipos
    list?.addEventListener("change", (e)=>{
      if (e.target.matches(".cfg-type-item input")) {
        log("file-config: categoria change", {
          prefix: getPrefix(card),
          name: e.target.value,
          checked: e.target.checked,
          totalMarcados: list.querySelectorAll(".cfg-type-item input:checked").length
        });
        buildFileValidationJson(card);
        triggerAutosave();
        validateCard(card);
      }
    });

    // números → autosave
    const numHandler = (src) => {
      log("file-config: num change", {
        prefix: getPrefix(card),
        field: src.classList.contains("cfg-max-arqs") ? "max_arquivos" : "max_mb",
        value: src.value
      });
      buildFileValidationJson(card);
      debouncedTriggerAutosave();
      validateCard(card);
    };
    maxArq?.addEventListener("input", () => numHandler(maxArq));
    maxMb?.addEventListener("input",  () => numHandler(maxMb));
    maxMb?.addEventListener("change", () => numHandler(maxMb));
  }

  // ===== Inicialização de cada card =====
  function initCard(card) {
    if (!card || card.dataset.ready) return;
    card.dataset.ready = "1";

    // default de origem (hidden)
    const hidOrig = card.querySelector("input[name$='-origem_opcoes']");
    if (hidOrig && !hidOrig.value) hidOrig.value = "manual";

    // sincroniza radios de origem a partir do hidden
    const radiosOrig = card.querySelectorAll(`input[name$='-origem_choice']`);
    if (radiosOrig.length){
      const val = (hidOrig?.value || 'manual').trim();
      radiosOrig.forEach(r => r.checked = (r.value === val));
      radiosOrig.forEach(r => r.addEventListener('change', () => {
        if (hidOrig) hidOrig.value = (Array.from(radiosOrig).find(x=>x.checked)?.value || 'manual');
        applyVisibilityAndDisabling(card);
        if (getTipoValue(card) === 'lista' && (hidOrig?.value === 'sqlhub')) {
          initSqlhub(card, true);
        }
        debouncedTriggerAutosave();
        validateCard(card);
      }));
    }

    applyVisibilityAndDisabling(card);
    validateCard(card);

    // tipo → muda layout e pode ligar SQLHub
    const sel = card.querySelector("select[name$='-tipo']");
    sel?.addEventListener("change", () => {
      applyVisibilityAndDisabling(card);
      validateCard(card);
      debouncedTriggerAutosave();
    });

    // rótulo → validação leve
    const inputRot = card.querySelector("input[name$='-rotulo']");
    inputRot?.addEventListener("input", () => validateCard(card));
    inputRot?.addEventListener("blur",  () => validateCard(card));

    // eventos do bloco de upload
    wireFileConfigEvents(card);

    // se houver config de upload prévia, restaura UI a partir do hidden
    const cfg = card.querySelector(".file-config");
    if (cfg) {
      const hiddenInput = card.querySelector("input[name$='-valid_json']");
      if (hiddenInput && hiddenInput.value) {
        try {
          const data = JSON.parse(hiddenInput.value);
          const toggle = card.querySelector(".cfg-tipos-toggle");
          if (toggle) {
            toggle.checked = !data.tipos_livres;
            card.querySelector(".cfg-tipos-list")?.classList.toggle("hide", data.tipos_livres);
          }
          (data.categorias || []).forEach((cat) => {
            const cb = card.querySelector(`.cfg-type-item input[value="${cat}"]`);
            if (cb) cb.checked = true;
          });
          const maxArqs = card.querySelector(".cfg-max-arqs");
          if (maxArqs && data.max_arquivos) maxArqs.value = data.max_arquivos;
          const maxMb = card.querySelector(".cfg-max-mb");
          if (maxMb && data.max_mb) maxMb.value = data.max_mb;
          log("initCard(upload) ok:", { prefix: getPrefix(card), data });
        } catch (e) {
          log("initCard(upload) parse fail", e);
        }
      }
    }

    // se já abrir como Lista+SQLHub, inicializa imediatamente
    if (getTipoValue(card) === 'lista' && (hidOrig?.value === 'sqlhub')) {
      initSqlhub(card, true);
    }
  }

  function initCards() { qsaFS(".pergunta-card").forEach(initCard); }
  document.addEventListener("DOMContentLoaded", initCards);
  document.addEventListener("htmx:afterSwap", initCards);

  // ===== Delegados de mudança gerais =====
  document.body.addEventListener("change", (e) => {
    const inFS = e.target.closest("#campos-formset");
    if (!inFS) return;

    // editou opções de texto (manuais)
    if (e.target.closest(".options-list")) {
      updateSingleOptionsJsonField(e.target.closest(".options-block"));
      const card = e.target.closest(".pergunta-card");
      validateCard(card); // valida na hora
    }

    // tipo mudou (fallback)
    if (e.target.matches("select[name$='-tipo']")) {
      const card = e.target.closest(".pergunta-card");
      applyVisibilityAndDisabling(card);
      validateCard(card);
    }

    // origem mudou (via radios) – fallback
    if (e.target.matches("input[name$='-origem_choice']")) {
      const card = e.target.closest(".pergunta-card");
      const hid  = card?.querySelector("input[name$='-origem_opcoes']");
      if (hid) hid.value = (e.target.value || "manual");
      applyVisibilityAndDisabling(card);
      validateCard(card);
    }

    // qualquer mudança dentro do file-config (fallback)
    if (e.target.closest(".file-config")) {
      debouncedTriggerAutosave();
      const card = e.target.closest(".pergunta-card");
      validateCard(card);
    }

    debouncedTriggerAutosave();
  });

  // adicionar/remover linhas de opções
  function createOptionRow() {
    const r = document.createElement("div");
    r.className = "opt-row";
    r.innerHTML = '<input class="form-control" type="text" placeholder="Texto da opção">' +
                  '<button type="button" class="opt-del" title="Remover">×</button>';
    return r;
  }
  document.body.addEventListener("click", (e) => {
    const addBtn = e.target.closest("#campos-formset .btn-add-option");
    if (addBtn) {
      e.preventDefault();
      const block = addBtn.closest(".options-block");
      const row = createOptionRow();
      block.querySelector(".options-list").appendChild(row);
      row.querySelector("input").focus();

      const hiddenOpts = block.querySelector("input[name$='-opcoes_json']");
      setDisabled(hiddenOpts, false);

      const card = addBtn.closest(".pergunta-card");
      validateCard(card);
      return;
    }

    const delBtn = e.target.closest("#campos-formset .opt-del");
    if (delBtn) {
      e.preventDefault();
      const blk = delBtn.closest(".options-block");
      const card = delBtn.closest(".pergunta-card");
      delBtn.closest(".opt-row").remove();
      updateSingleOptionsJsonField(blk);
      debouncedTriggerAutosave();
      validateCard(card);
    }
  });

  // ===== autosave título/descrição =====
  document.addEventListener("input", (e) => { if (e.target.closest(".header-card")) debouncedTriggerAutosave(); });
  document.addEventListener("change", (e) => { if (e.target.closest(".header-card")) debouncedTriggerAutosave(); });

  // ===== syncIds =====
  document.body.addEventListener("syncIds", (e) => {
    for (const [p, pk] of Object.entries(e.detail)) {
      const idInput = document.querySelector(`input[name='${p}-id']`);
      if (idInput && !idInput.value) idInput.value = pk;
    }
  });

  // ===== HTMX 204 → INITIAL_FORMS =====
  document.body.addEventListener("htmx:afterOnLoad", (e) => {
    if (e.detail.elt === document.getElementById("form-main") && e.detail.xhr.status === 204) {
      const wrap = getFormset(); if (!wrap) return;
      const p = wrap.dataset.prefix;
      document.getElementById(`id_${p}-INITIAL_FORMS`).value =
        document.getElementById(`id_${p}-TOTAL_FORMS`).value;
      log("204 → INITIAL_FORMS atualizado.");
    }
  });

  // ===== botão “+ Adicionar pergunta” =====
  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("btn-add-question");
    const wrap = getFormset();
    if (!btn || !wrap) return;

    let tpl = "";
    fetch(btn.dataset.endpoint)
      .then((r) => { if (!r.ok) throw 0; return r.text(); })
      .then((t) => { tpl = t; btn.disabled = false; })
      .catch(() => (btn.textContent = "Erro ao carregar"));

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      if (!tpl) return;
      const p = wrap.dataset.prefix;
      const total = document.getElementById(`id_${p}-TOTAL_FORMS`);
      const idx = parseInt(total.value, 10);
      wrap.insertAdjacentHTML("beforeend", tpl.replace(/__prefix__/g, idx));
      total.value = idx + 1;
      initCards();          // inicializa tudo (inclui SQLHub/validações)
      initSortable();
      syncTotalAndOrder();
      wrap.dispatchEvent(new Event("newCardAdded", { bubbles: true }));
    });
  });

  // ===== Abas da toolbar (não bloquear HTMX) =====
  document.addEventListener("click", (e) => {
    const link = e.target.closest(".tb-link");
    if (!link) return;
    const hasHx = ["hx-get","hx-post","hx-put","hx-delete","hx-patch"].some(a => link.hasAttribute(a));
    if (!hasHx) e.preventDefault();

    document.querySelectorAll(".tb-link").forEach((l) => l.classList.remove("active"));
    link.classList.add("active");

    const tab = link.dataset.tab;
    ["edit","resp","conf"].forEach((id) => {
      document.getElementById(`${id}-section`)?.classList.toggle("hide", id !== tab);
    });
  });

  // ===== Toggle “Aceitando respostas” =====
  document.addEventListener("change", (e) => {
    if (!e.target.matches(".tb-toggle input")) return;
    const shadow = document.getElementById("aceita_respostas_shadow");
    if (shadow) shadow.checked = e.target.checked;
    e.target.closest(".tb-toggle").style.opacity = e.target.checked ? "1" : ".45";
    triggerAutosave();
  });

  // ===== Dump (debug) no envio =====
  document.body.addEventListener("htmx:configRequest", (e) => {
    const src = e.detail && e.detail.elt;
    if (!src) return;
    if (src.closest && src.closest("#form-main")) {
      updateAllHiddenJson();
      try {
        const form = src.closest("form");
        const fd = new FormData(form);
        const arr = [];
        for (const [k, v] of fd.entries()) {
          if (/-valid_json$/.test(k) || /-tipo$/.test(k)) {
            arr.push([k, v]);
          }
        }
        log("[CLIENT/htmx:configRequest] keys(-tipo/-valid_json)=", arr);
      } catch {}
    }
  });

  // Helper para debug manual no console:
  window.__dumpUploadCards = function(){
    qsaFS(".pergunta-card").forEach((c)=>{
      const prefix = getPrefix(c);
      const tipo = getTipoValue(c);
      if (tipo === "arquivo") {
        const hidden = c.querySelector("input[name$='-valid_json']");
        const toggle = c.querySelector(".cfg-tipos-toggle");
        const cats = [...c.querySelectorAll(".cfg-type-item input:checked")].map(i=>i.value);
        const maxArqs = c.querySelector(".cfg-max-arqs")?.value;
        const maxMb   = c.querySelector(".cfg-max-mb")?.value;
        console.table([{ prefix, tipo, hidden_disabled: hidden?.disabled, hidden_value: hidden?.value, toggle_checked: !!toggle?.checked, categorias: cats.join(","), maxArqs, maxMb }]);
      }
    });
  };
})();
