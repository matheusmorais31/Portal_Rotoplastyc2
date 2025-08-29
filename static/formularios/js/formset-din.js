/*****************************************************************
 * formset-din.js  –  Builder de Formulários
 * --------------------------------------------------------------
 * • Sortable + Autosave via HTMX
 * • Campos multipla / checkbox / lista  →  opcoes_json
 * • Campo Upload (arquivo)              →  valid_json
 * • ESCOPADO ao #campos-formset
 * • Habilita/Desabilita inputs para não irem ao POST indevidamente
 * • Logs detalhados [CLIENT]
 *****************************************************************/

(function () {
  const LOG = true;
  const log = (...args) => LOG && console.debug("[CLIENT]", ...args);

  /* ===============================================================
     0. Utilidades + Escopo Formset
     =============================================================== */
  const getFormset = () => document.getElementById("campos-formset");
  const qsaFS = (sel) => (getFormset() ? getFormset().querySelectorAll(sel) : []);
  const qsFS = (sel) => (getFormset() ? getFormset().querySelector(sel) : null);

  const debounce = (fn, ms = 400) => {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  };

  const setDisabled = (el, disabled, reason = "") => {
    if (!el) return;
    el.disabled = !!disabled;
    if (disabled) {
      el.setAttribute("data-disabled-by", reason || "formset-din");
    } else {
      el.removeAttribute("data-disabled-by");
    }
  };

  const getPrefix = (card) => {
    if (card?.dataset?.prefix) return card.dataset.prefix;
    const any = card?.querySelector("[name^='campo_set-']");
    const m = any?.name?.match?.(/^(campo_set-\d+)-/);
    return m ? m[1] : "";
  };

  /* ===============================================================
     1. Helpers JSON  (Opções + Arquivo)
     =============================================================== */
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
    const hidden = card.querySelector("input[name$='-valid_json']");
    if (!hidden) return;

    const sel = card.querySelector("select[name$='-tipo']");
    const tipo = sel?.value;

    // Se NÃO for 'arquivo' → garante desabilitado e limpo
    if (tipo !== "arquivo") {
      if (hidden.value) {
        hidden.value = "";
      }
      setDisabled(hidden, true, "tipo!=arquivo");
      return;
    }

    // É 'arquivo' → habilita e monta payload
    setDisabled(hidden, false);
    const toggle = card.querySelector(".cfg-tipos-toggle");
    const categorias = [...card.querySelectorAll(".cfg-type-item input:checked")].map((i) => i.value);

    const maxArqs = parseInt(card.querySelector(".cfg-max-arqs")?.value || 1, 10);
    const maxMb = parseInt(card.querySelector(".cfg-max-mb")?.value || 10, 10);

    const payload = {
      tipos_livres: toggle ? !toggle.checked : true,
      categorias,
      max_arquivos: maxArqs,
      max_mb: maxMb,
    };
    hidden.value = JSON.stringify(payload);
    log("valid_json atualizado:", payload);
  }

  function updateAllHiddenJson() {
    // opções
    qsaFS(".pergunta-card").forEach((card) => {
      const sel = card.querySelector("select[name$='-tipo']");
      const tipo = sel?.value;
      const optsBlock = card.querySelector(".options-block");
      const hiddenOpts = card.querySelector("input[name$='-opcoes_json']");

      const showOpts = ["multipla", "checkbox", "lista"].includes(tipo);
      if (optsBlock && hiddenOpts) {
        if (showOpts) {
          setDisabled(hiddenOpts, false);
          updateSingleOptionsJsonField(optsBlock);
        } else {
          hiddenOpts.value = "";
          setDisabled(hiddenOpts, true, "tipo_sem_opcoes");
        }
      }
    });

    // arquivo
    qsaFS(".pergunta-card").forEach((c) => buildFileValidationJson(c));

    // sync toggle toolbar → shadow checkbox
    const toolbarToggle = document.querySelector(".tb-toggle input");
    const shadow = document.getElementById("aceita_respostas_shadow");
    if (toolbarToggle && shadow) {
      shadow.checked = !!toolbarToggle.checked;
    }
  }

  /* ===============================================================
     2. Autosave
     =============================================================== */
  const triggerAutosave = () => {
    updateAllHiddenJson();
    // Dispare no <body> porque o hx-trigger é "autosave from:body"
    document.body.dispatchEvent(new Event("autosave", { bubbles: true }));
    log("autosave disparado (from:body).");
  };
  const debouncedTriggerAutosave = debounce(triggerAutosave);

  // Deixe acessível globalmente (para onclick inline e outros scripts)
  window.triggerAutosave = triggerAutosave;
  window.debouncedTriggerAutosave = debouncedTriggerAutosave;

  /* ===============================================================
     3. TOTAL_FORMS + ordem
     =============================================================== */
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
  // Se deletou uma linha, também autosave (corrige caso do botão 🗑️)
  document.addEventListener("rowDeleted", () => debouncedTriggerAutosave());

  /* ===============================================================
     4. SortableJS
     =============================================================== */
  function initSortable() {
    const wrap = getFormset();
    if (wrap && !wrap.sortableReady) {
      Sortable.create(wrap, {
        handle: ".drag-handle",
        draggable: ".pergunta-card",
        animation: 150,
        onEnd() {
          syncTotalAndOrder();
          triggerAutosave();
        },
      });
      wrap.sortableReady = true;
      log("Sortable inicializado.");
    }
  }
  document.addEventListener("DOMContentLoaded", initSortable);
  document.addEventListener("htmx:afterSwap", initSortable);

  /* ===============================================================
     5. Eventos de mudança (escopados ao formset)
     =============================================================== */
  document.body.addEventListener("change", (e) => {
    const inFS = e.target.closest("#campos-formset");
    if (!inFS) return;

    // Editou uma opção de texto
    if (e.target.closest(".options-list")) {
      updateSingleOptionsJsonField(e.target.closest(".options-block"));
    }

    // Troca de tipo exige reavaliar habilitados
    if (e.target.matches("select[name$='-tipo']")) {
      const card = e.target.closest(".pergunta-card");
      applyVisibilityAndDisabling(card);
    }

    debouncedTriggerAutosave();
  });

  /* ===============================================================
     6. Linha de opções (+ / ×) – escopo formset
     =============================================================== */
  function createOptionRow() {
    const r = document.createElement("div");
    r.className = "opt-row";
    r.innerHTML =
      '<input class="form-control" type="text" placeholder="Texto da opção">' +
      '<button type="button" class="opt-del" title="Remover">×</button>';
    return r;
  }

  document.body.addEventListener("click", (e) => {
    // + Adicionar opção
    const addBtn = e.target.closest("#campos-formset .btn-add-option");
    if (addBtn) {
      e.preventDefault();
      const block = addBtn.closest(".options-block");
      const row = createOptionRow();
      block.querySelector(".options-list").appendChild(row);
      row.querySelector("input").focus();

      // Garante hidden habilitado (pois só aparece quando showOpts=true)
      const hiddenOpts = block.querySelector("input[name$='-opcoes_json']");
      setDisabled(hiddenOpts, false);

      return;
    }

    // Remover opção
    const delBtn = e.target.closest("#campos-formset .opt-del");
    if (delBtn) {
      e.preventDefault();
      const blk = delBtn.closest(".options-block");
      delBtn.closest(".opt-row").remove();
      updateSingleOptionsJsonField(blk);
      debouncedTriggerAutosave();
    }
  });

  /* ===============================================================
     7. Visibilidade + Habilitação (por card)
     =============================================================== */
  function applyVisibilityAndDisabling(card) {
    if (!card || !card.closest("#campos-formset")) return;

    const sel = card.querySelector("select[name$='-tipo']");
    const opts = card.querySelector(".options-block");
    const cfg = card.querySelector(".file-config");
    const hiddenOpts = card.querySelector("input[name$='-opcoes_json']");
    const hiddenValid = card.querySelector("input[name$='-valid_json']");
    const tipo = sel?.value;

    const showOpts = ["multipla", "checkbox", "lista"].includes(tipo);
    const showCfg = tipo === "arquivo";

    // Mostrar/Esconder blocos
    opts?.classList.toggle("hide", !showOpts);
    cfg?.classList.toggle("hide", !showCfg);

    // HABILITAR/DESABILITAR os hiddens para controlar o POST
    if (hiddenOpts) {
      if (showOpts) {
        setDisabled(hiddenOpts, false);
      } else {
        hiddenOpts.value = "";
        setDisabled(hiddenOpts, true, "tipo_sem_opcoes");
      }
    }
    if (hiddenValid) {
      if (showCfg) {
        setDisabled(hiddenValid, false);
      } else {
        hiddenValid.value = "";
        setDisabled(hiddenValid, true, "tipo!=arquivo");
      }
    }

    log(
      "toggleBlocks prefix=%s tipo=%s → showOpts=%s showCfg=%s",
      getPrefix(card),
      tipo,
      showOpts,
      showCfg
    );
  }

  function initCard(card) {
    if (!card || card.dataset.ready) return;
    card.dataset.ready = "1";

    applyVisibilityAndDisabling(card);

    const sel = card.querySelector("select[name$='-tipo']");
    sel?.addEventListener("change", () => {
      applyVisibilityAndDisabling(card);
      debouncedTriggerAutosave();
    });

    // Se for bloco de arquivo, inicializa UI a partir do hidden
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
          if (Array.isArray(data.categorias)) {
            data.categorias.forEach((cat) => {
              const cb = card.querySelector(`.cfg-type-item input[value="${cat}"]`);
              if (cb) cb.checked = true;
            });
          }
          const maxArqs = card.querySelector(".cfg-max-arqs");
          if (maxArqs && data.max_arquivos) maxArqs.value = data.max_arquivos;
          const maxMb = card.querySelector(".cfg-max-mb");
          if (maxMb && data.max_mb) maxMb.value = data.max_mb;

          log("initCards (arquivo) prefix=%s carregado de hidden:", getPrefix(card), data);
        } catch (e) {
          log("valid_json inválido:", hiddenInput.value, e);
        }
      }

      card.querySelector(".cfg-tipos-toggle")?.addEventListener("change", (ev) => {
        card.querySelector(".cfg-tipos-list").classList.toggle("hide", !ev.target.checked);
        debouncedTriggerAutosave();
      });
    }
  }

  function initCards() {
    qsaFS(".pergunta-card").forEach(initCard);
  }
  document.addEventListener("DOMContentLoaded", initCards);
  document.addEventListener("htmx:afterSwap", initCards);

  /* ===============================================================
     8. Autosave para TÍTULO/DESCRIÇÃO (header-card)
     =============================================================== */
  document.addEventListener("input", (e) => {
    if (e.target.closest(".header-card")) {
      debouncedTriggerAutosave();
    }
  });
  document.addEventListener("change", (e) => {
    if (e.target.closest(".header-card")) {
      debouncedTriggerAutosave();
    }
  });

  /* ===============================================================
     9. syncIds  (HTMX trigger → preenche PK nos inputs -id)
     =============================================================== */
  document.body.addEventListener("syncIds", (e) => {
    for (const [p, pk] of Object.entries(e.detail)) {
      const idInput = document.querySelector(`input[name='${p}-id']`);
      if (idInput && !idInput.value) idInput.value = pk;
    }
  });

  /* ===============================================================
     10. HTMX 204 → incrementa INITIAL_FORMS
     =============================================================== */
  document.body.addEventListener("htmx:afterOnLoad", (e) => {
    if (e.detail.elt === document.getElementById("form-main") && e.detail.xhr.status === 204) {
      const wrap = getFormset();
      if (!wrap) return;
      const p = wrap.dataset.prefix;
      document.getElementById(`id_${p}-INITIAL_FORMS`).value =
        document.getElementById(`id_${p}-TOTAL_FORMS`).value;
      log("204 recebido → INITIAL_FORMS=%s", document.getElementById(`id_${p}-INITIAL_FORMS`).value);
    }
  });

  /* ===============================================================
     11. Botão + Adicionar pergunta
     =============================================================== */
  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("btn-add-question");
    const wrap = getFormset();
    if (!btn || !wrap) return;

    let tpl = "";
    fetch(btn.dataset.endpoint)
      .then((r) => {
        if (!r.ok) throw 0;
        return r.text();
      })
      .then((t) => {
        tpl = t;
        btn.disabled = false;
        log("template de campo_vazio carregado.");
      })
      .catch(() => (btn.textContent = "Erro ao carregar"));

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      if (!tpl) return;
      const p = wrap.dataset.prefix;
      const total = document.getElementById(`id_${p}-TOTAL_FORMS`);
      const idx = parseInt(total.value, 10);
      wrap.insertAdjacentHTML("beforeend", tpl.replace(/__prefix__/g, idx));
      total.value = idx + 1;
      initCards();
      initSortable();
      syncTotalAndOrder();
      wrap.dispatchEvent(new Event("newCardAdded", { bubbles: true }));
    });
  });

  /* ===============================================================
     12. Abas da toolbar  (não bloquear links HTMX)
     =============================================================== */
  document.addEventListener("click", (e) => {
    const link = e.target.closest(".tb-link");
    if (!link) return;

    const hasHx =
      link.hasAttribute("hx-get") ||
      link.hasAttribute("hx-post") ||
      link.hasAttribute("hx-put") ||
      link.hasAttribute("hx-delete") ||
      link.hasAttribute("hx-patch");
    if (!hasHx) e.preventDefault();

    document.querySelectorAll(".tb-link").forEach((l) => l.classList.remove("active"));
    link.classList.add("active");

    const tab = link.dataset.tab;
    ["edit", "resp", "conf"].forEach((id) => {
      document.getElementById(`${id}-section`)?.classList.toggle("hide", id !== tab);
    });
  });

  /* ===============================================================
     13. Toggle “Aceitando respostas” (shadow + autosave)
     =============================================================== */
  document.addEventListener("change", (e) => {
    if (!e.target.matches(".tb-toggle input")) return;
    const shadow = document.getElementById("aceita_respostas_shadow");
    if (shadow) shadow.checked = e.target.checked;
    e.target.closest(".tb-toggle").style.opacity = e.target.checked ? "1" : ".45";
    triggerAutosave();
  });

  /* ===============================================================
     14. HTMX – dump de chaves (-tipo/-valid_json) antes do envio
     =============================================================== */
  document.body.addEventListener("htmx:configRequest", (e) => {
    const src = e.detail && e.detail.elt;
    if (!src) return;
    if (src.closest && src.closest("#form-main")) {
      updateAllHiddenJson(); // garante habilitados/desabilitados certos

      try {
        const form = src.closest("form");
        const fd = new FormData(form);
        const arr = [];
        for (const [k, v] of fd.entries()) {
          if (/-valid_json$/.test(k) || /-tipo$/.test(k)) {
            arr.push([k, v]);
          }
        }
        log("[CLIENT/htmx:configRequest] payload(keys -tipo/-valid_json)=", arr);
      } catch (err) {
        log("Falha ao inspecionar FormData:", err);
      }
    }
  });

  /* ===============================================================
     15. Autosave para CABEÇALHO (fallback para teclas fora de input)
     =============================================================== */
  document.addEventListener("keyup", (e) => {
    if (e.target.closest && e.target.closest(".header-card")) {
      debouncedTriggerAutosave();
    }
  });
})();
