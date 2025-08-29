document.addEventListener("DOMContentLoaded", () => {
  const lista = document.getElementById("lista-campos");
  if (!lista) return;

  Sortable.create(lista, {
    handle: ".drag-handle",
    animation: 150,
    onEnd: () => {
      // dispara HTMX 'end' → POST automático já configurado no template
      if (window.htmx) htmx.trigger(lista, "end");
    }
  });
});
