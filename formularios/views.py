from __future__ import annotations

import csv
import io
import json
import hashlib
import logging
import zipfile
from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.paginator import Paginator, EmptyPage
from django.db import transaction
from django.db.models import Q, Count
from django.http import Http404, HttpResponse, HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, FormView, ListView, UpdateView

from .forms import CampoForm, CampoFormSetBuilder, CampoFormSetCreate, FormularioForm
from .models import (
    Campo, Formulario, OpcaoCampo, Resposta, ValorResposta,
    FILE_CATS, Colaborador
)

logger = logging.getLogger(__name__)

UserModel = get_user_model()

# Se True, anônimos veem a tela "obrigado" após o envio (em vez do detalhe)
SHOW_THANKYOU_PAGE_FOR_ANON = True

FILE_CAT_LABELS: list[str] = [
    "Documento", "Apresentação", "Planilha", "Desenho",
    "PDF", "Imagem", "Vídeo", "Áudio"
]


def _fmt_local(dt, fmt="%Y-%m-%d %H:%M:%S") -> str:
    if not dt:
        return ""
    try:
        if timezone.is_aware(dt):
            return timezone.localtime(dt).strftime(fmt)
        return dt.strftime(fmt)
    except Exception:
        return str(dt)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _ip(req: HttpRequest) -> str:
    return req.META.get("HTTP_X_FORWARDED_FOR", req.META.get("REMOTE_ADDR", ""))


def _is_htmx(req: HttpRequest) -> bool:
    # compat: cabeçalho padrão do HTMX
    return bool(req.headers.get("HX-Request"))


def _dump_request(req: HttpRequest, note: str = ""):
    """Loga um resumo seguro do request para debug."""
    try:
        post_keys = list(req.POST.keys())
        files_info = {
            k: [getattr(f, "name", "?") for f in req.FILES.getlist(k)]
            for k in req.FILES.keys()
        }
        logger.debug(
            "REQ %s%s %s | user=%s auth=%s ip=%s | HTMX=%s | POST keys=%s | FILES=%s",
            f"[{note}] " if note else "",
            req.method,
            req.path,
            getattr(req.user, "username", None),
            req.user.is_authenticated,
            _ip(req),
            _is_htmx(req),
            post_keys,
            files_info,
        )
    except Exception:
        logger.exception("Falha ao fazer dump do request")


def _calc_form_signature(form: Formulario) -> str:
    """
    Hash determinístico da estrutura atual (apenas campos ATIVOS),
    considerando ordem, tipo, rótulo, obrigatoriedade, ajuda, opções e validação de arquivo.
    """
    items = []
    for c in form.campos.filter(ativo=True).order_by("ordem", "id"):
        d = {
            "tipo": c.tipo,
            "rotulo": c.rotulo or "",
            "obrigatorio": bool(c.obrigatorio),
            "ajuda": c.ajuda or "",
        }
        if c.tipo in {"multipla", "checkbox", "lista"}:
            d["opcoes"] = list(c.opcoes.order_by("id").values_list("texto", flat=True))
        if c.tipo == "arquivo":
            d["valid"] = c.validacao_json or {}
        items.append(d)
    blob = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# LISTAGENS                                                                   #
# --------------------------------------------------------------------------- #
class MeusFormulariosView(LoginRequiredMixin, ListView):
    template_name = "formularios/listar_meus.html"
    context_object_name = "formularios"

    def get_queryset(self):
        return Formulario.objects.filter(dono=self.request.user)

    def get_context_data(self, **kw):
        """
        Inclui também formulários compartilhados comigo (como editor ou somente responder).
        Anexa em cada instância um atributo `my_role` = 'editor' | 'view'.
        """
        ctx = super().get_context_data(**kw)
        compartilhados = (
            Formulario.objects
            .filter(colaboradores__usuario=self.request.user)
            .select_related("dono")
            .prefetch_related("colaboradores", "colaboradores__usuario")
            .distinct()
        )
        for f in compartilhados:
            my = next((c for c in f.colaboradores.all()
                       if c.usuario_id == self.request.user.id), None)
            setattr(f, "my_role", "editor" if (my and my.pode_editar) else "view")
        ctx["compartilhados"] = compartilhados
        logger.debug(
            "Listando meus formulários: meus=%s, compartilhados=%s",
            ctx["formularios"].count(), len(compartilhados)
        )
        return ctx


class TodosFormulariosView(PermissionRequiredMixin, ListView):
    permission_required = "formularios.pode_gerenciar"
    template_name = "formularios/listar_todos.html"
    context_object_name = "formularios"
    queryset = Formulario.objects.all()


# --------------------------------------------------------------------------- #
# CRIAÇÃO                                                                     #
# --------------------------------------------------------------------------- #
class CriarFormularioView(LoginRequiredMixin, FormView):
    template_name = "formularios/criar.html"
    form_class = FormularioForm

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["campos_formset"] = CampoFormSetCreate(
            self.request.POST or None, prefix="campo_set"
        )
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        _dump_request(self.request, "CRIAR")
        form.instance.dono = self.request.user
        self.object = form.save()
        logger.info("Formulário criado id=%s por user=%s",
                    self.object.pk, self.request.user)

        fset = CampoFormSetCreate(
            self.request.POST, instance=self.object, prefix="campo_set"
        )
        if fset.is_valid():
            fset.save()
            logger.debug("Formset inicial salvo com %s campos", len(fset.forms))
        else:
            logger.warning("Formset inicial inválido: %s", fset.errors)

        if _is_htmx(self.request):
            resp = HttpResponse(status=204)
            resp["HX-Redirect"] = reverse(
                "formularios:construtor_formulario", kwargs={"pk": self.object.pk}
            )
            return resp
        return redirect("formularios:construtor_formulario", self.object.pk)


# --------------------------------------------------------------------------- #
# EDITAR (BUILDER)                                                            #
# --------------------------------------------------------------------------- #
# views.py (trecho) — EditarFormularioView reforçada + logs
class EditarFormularioView(LoginRequiredMixin, UpdateView):
    model = Formulario
    form_class = FormularioForm
    template_name = "formularios/builder.html"
    pk_url_kwarg = "pk"
    context_object_name = "formulario"

    def get_queryset(self):
        u = self.request.user
        if not u.is_authenticated:
            return Formulario.objects.none()
        return (
            Formulario.objects
            .filter(Q(dono=u) | Q(colaboradores__usuario=u, colaboradores__pode_editar=True))
            .distinct()
        )

    def get_formset_class(self):
        return CampoFormSetBuilder

    def get_context_data(self, **kw):
        """
        O builder lista APENAS campos ATIVOS.
        Log extra: imprime o valid_json inicial dos campos de arquivo.
        """
        ctx = super().get_context_data(**kw)
        FS = self.get_formset_class()
        qs_campos = self.object.campos.filter(ativo=True).order_by("ordem")

        if self.request.method == "POST":
            fset = FS(self.request.POST, instance=self.object, prefix="campo_set", queryset=qs_campos)
        else:
            fset = FS(instance=self.object, prefix="campo_set", queryset=qs_campos)

        # LOG detalhado dos campos de upload (estado inicial renderizado)
        try:
            for f in fset.forms:
                inst = getattr(f, "instance", None)
                if getattr(inst, "tipo", None) == "arquivo":
                    vi = f.fields["valid_json"].initial if "valid_json" in f.fields else None
                    logger.debug(
                        "GET builder: campo id=%s tipo=%s valid_json.initial=%s",
                        inst.id, inst.tipo, json.dumps(vi, ensure_ascii=False)
                    )
        except Exception:
            logger.exception("Falhou logar valid_json.initial no GET do builder")

        ctx["campos_formset"] = fset
        ctx["FILE_CAT_LABELS"] = FILE_CAT_LABELS
        logger.debug("Abrindo builder form=%s campos_ativos=%s", self.object.pk, qs_campos.count())
        return ctx

    def _salvar_opcoes_escolha(self, form: CampoForm, campo: Campo):
        if campo.tipo not in {"multipla", "checkbox", "lista"}:
            return
        OpcaoCampo.objects.filter(campo=campo).delete()
        raw = form.data.get(form.prefix + "-opcoes_json", "[]")
        try:
            itens = json.loads(raw)
            if isinstance(itens, list):
                OpcaoCampo.objects.bulk_create(
                    [OpcaoCampo(campo=campo, texto=str(v)) for v in itens if v]
                )
                logger.debug("Opções atualizadas p/ campo=%s (%s itens)", campo.pk, len(itens))
        except json.JSONDecodeError:
            logger.error("JSON opcoes inválido para campo %s – %s", campo.pk, raw)

    @transaction.atomic
    def post(self, request: HttpRequest, *args, **kw):
        _dump_request(request, "BUILDER-SAVE")
        self.object = self.get_object()

        prev_sig = _calc_form_signature(self.object)

        hdr_form = self.get_form()
        FS = self.get_formset_class()
        qs_campos = self.object.campos.filter(ativo=True).order_by("ordem")
        fset = FS(request.POST, instance=self.object, prefix="campo_set", queryset=qs_campos)

        # LOG: quantos -valid_json vieram no payload
        try:
            vkeys = [k for k in request.POST.keys() if k.endswith("-valid_json")]
            logger.debug("POST builder: %s campos com -valid_json no payload: %s",
                         len(vkeys), vkeys)
        except Exception:
            pass

        if not hdr_form.is_valid():
            logger.warning("Cabeçalho inválido: %s", hdr_form.errors)
            return self.render_to_response(
                self.get_context_data(form=hdr_form, campos_formset=fset)
            )

        self.object = hdr_form.save()
        logger.info("Formulário %s atualizado", self.object.pk)

        saved = []
        KNOWN_CATS = set(FILE_CATS.keys())

        for form in fset:
            pfx = form.prefix

            # Exclusão?
            if form.data.get(pfx + "-DELETE") == "on":
                inst = form.instance
                if inst and inst.pk:
                    if ValorResposta.objects.filter(campo=inst).exists():
                        inst.ativo = False
                        inst.save(update_fields=["ativo"])
                        logger.info("Campo %s arquivado (havia respostas)", inst.pk)
                    else:
                        logger.info("Deletando campo %s (sem respostas)", inst.pk)
                        inst.delete()
                continue

            rot = (form.data.get(pfx + "-rotulo") or "").strip()
            tipo = (form.data.get(pfx + "-tipo") or "").strip()
            if not rot or not tipo:
                continue

            inst = form.instance
            inst.formulario = self.object
            inst.rotulo = rot
            inst.tipo = tipo
            inst.ajuda = (form.data.get(pfx + "-ajuda") or "").strip()
            inst.ordem = form.data.get(pfx + "-ordem")
            inst.obrigatorio = form.data.get(pfx + "-obrigatorio") == "on"
            inst.ativo = True  # está no builder => ativo

            if tipo == "arquivo":
                raw = form.data.get(pfx + "-valid_json", "{}")
                try:
                    cfg_in = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    logger.warning("valid_json inválido p/ campo %s – %s (mantendo antigo)", inst.pk, raw)
                    cfg_in = {}

                # Normalização + guarda-corpos
                if not isinstance(cfg_in, dict):
                    cfg_in = {}

                tipos_livres = bool(cfg_in.get("tipos_livres", True))
                try:
                    max_arqs = int(cfg_in.get("max_arquivos", 1) or 1)
                except Exception:
                    max_arqs = 1
                try:
                    max_mb = int(cfg_in.get("max_mb", 10) or 10)
                except Exception:
                    max_mb = 10

                categorias = []
                for c in (cfg_in.get("categorias") or []):
                    ckey = str(c).strip().lower()
                    if ckey in KNOWN_CATS:
                        categorias.append(ckey)
                    else:
                        logger.debug("Categoria desconhecida '%s' p/ campo %s; ignorando. (known=%s)",
                                     c, inst.pk, sorted(KNOWN_CATS))

                # Se veio “apenas específicos” mas sem categorias, preserva as antigas (protege contra overwrite do autosave)
                if not tipos_livres and not categorias:
                    old = (inst.validacao_json or {}).get("categorias") or []
                    if old:
                        logger.warning(
                            "valid_json com tipos_livres=False e categorias vazias no POST (prefix=%s id=%s). "
                            "Preservando antigas: %s", pfx, inst.pk, old
                        )
                        categorias = [c for c in old if c in KNOWN_CATS]

                inst.validacao_json = {
                    "tipos_livres": tipos_livres,
                    "categorias": categorias,
                    "max_arquivos": max_arqs,
                    "max_mb": max_mb,
                }
                logger.debug("Salvando validacao_json (id=%s): %s", inst.pk, inst.validacao_json)
            else:
                # Em alguns frontends o hidden -valid_json vem para todos os campos.
                raw_ghost = form.data.get(pfx + "-valid_json")
                if raw_ghost:
                    logger.debug(
                        "Ignorando valid_json recebido para tipo != arquivo (prefix=%s id=%s raw=%r)",
                        pfx, getattr(form.instance, "pk", None), raw_ghost
                    )

            inst.save()
            self._salvar_opcoes_escolha(form, inst)
            saved.append(form)

        logger.debug("Campos salvos(ids): %s", [f.instance.pk for f in saved])

        new_sig = _calc_form_signature(self.object)
        if new_sig != prev_sig:
            self.object.versao = (self.object.versao or 1) + 1
            self.object.save(update_fields=["versao"])
            logger.info("Versão do formulário %s => %s", self.object.pk, self.object.versao)

        if _is_htmx(request):
            resp = HttpResponse(status=204)
            resp["HX-Trigger"] = json.dumps({"syncIds": {f.prefix: f.instance.pk for f in saved}})
            return resp
        return redirect("formularios:construtor_formulario", self.object.pk)



# --------------------------------------------------------------------------- #
# HTMX – Form “vazio”                                                         #
# --------------------------------------------------------------------------- #
@login_required
def campo_vazio(request: HttpRequest):
    prefix = "campo_set"
    fs = CampoFormSetBuilder(prefix=prefix)
    empty = fs.empty_form
    empty.prefix = f"{prefix}-__prefix__"
    html = render_to_string(
        "formularios/partials/campo_inline.html",
        {"subform": empty, "FILE_CAT_LABELS": FILE_CAT_LABELS},
        request=request
    )
    logger.debug("campo_vazio renderizado para prefix=%s", empty.prefix)
    return HttpResponse(html)


# --------------------------------------------------------------------------- #
# EXIBIR FORMULÁRIO                                                           #
# --------------------------------------------------------------------------- #
def exibir_formulario(request: HttpRequest, pk: int):
    """
    Exibe o formulário para resposta.
    - Se o formulário estiver indisponível (pausado, ainda não abriu, já fechou
      ou atingiu limite), renderiza um template informativo.
    - Se for privado e o usuário não estiver autenticado, redireciona para login.
    - Suporta modo embed (?embed=1).
    """
    form = get_object_or_404(Formulario, pk=pk)
    now = timezone.now()

    # Acesso (público/privado)
    if not form.publico and not request.user.is_authenticated:
        login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")
        logger.info("Bloqueando anônimo no form %s (publico=False), redirecionando.", form.pk)
        return redirect(f"{login_url}?next={request.path}")

    # Estado / disponibilidade
    motivo = None
    if hasattr(form, "aceita_respostas") and not form.aceita_respostas:
        motivo = "paused"
        logger.info("Form %s não aceita respostas (pausado).", form.pk)
    elif form.abre_em and form.abre_em > now:
        motivo = "not_open"
        logger.info("Form %s ainda não abriu (%s > %s).", form.pk, form.abre_em, now)
    elif form.fecha_em and form.fecha_em < now:
        motivo = "closed"
        logger.info("Form %s já fechou (%s < %s).", form.pk, form.fecha_em, now)
    elif form.limite_resps and form.respostas.count() >= form.limite_resps:
        motivo = "limit"
        logger.info("Form %s atingiu limite de respostas.", form.pk)

    embed = (request.GET.get("embed") == "1")

    # Se indisponível → mostra página informativa
    if motivo:
        return render(
            request,
            "formularios/formulario_fechado.html",
            {"formulario": form, "motivo": motivo, "embed": embed},
            status=200,
        )

    # Disponível → render normal (embed ou página cheia)
    template = "formularios/responder_embed.html" if embed else "formularios/responder.html"
    logger.debug("Render exibir_formulario form=%s embed=%s", form.pk, embed)
    return render(request, template, {"formulario": form, "embed": embed})


# --------------------------------------------------------------------------- #
# ENVIAR RESPOSTA                                                             #
# --------------------------------------------------------------------------- #
@transaction.atomic
def enviar_resposta_formulario(request: HttpRequest, pk: int):
    """
    Recebe e valida o POST de respostas de um formulário.

    Regras:
      - Respeita disponibilidade (pausado, abre_em, fecha_em, limite_resps).
      - Valida obrigatoriedade por tipo de campo.
      - Upload: valida quantidade, tamanho (MB) e extensões por categoria (FILE_CATS).
      - coletar_nome=True: exige __nome__ para anônimo; logado coleta do usuário.
      - Bloqueia envio se NENHUMA pergunta ativa tiver sido respondida.
      - Em caso de erro, re-renderiza o mesmo template (embed ou página cheia)
        com valores “ecoados” e mensagens por campo.
      - Sucesso:
          • EMBED: renderiza "formularios/obrigado_embed.html"
          • PÁGINA: renderiza "formularios/obrigado.html"
    """
    form = get_object_or_404(Formulario, pk=pk)
    if request.method != "POST":
        return redirect("formularios:exibir_formulario", form.pk)

    _dump_request(request, "ENVIAR-RESP")

    dados = request.POST
    arquivos_req = request.FILES
    embed_mode = (dados.get("__embed") == "1")

    # Campos do formulário (ordem de exibição original)
    campos = list(form.campos.all().order_by("ordem"))

    erros_globais: list[str] = []
    nome_erros: list[str] = []
    erros_por_campo: dict[str, list[str]] = {}

    def add_err(campo_obj: Optional[Campo], msg: str):
        erros_globais.append(msg)
        if campo_obj is not None:
            cid = str(campo_obj.id)
            erros_por_campo.setdefault(cid, []).append(msg)

    # Prepara "echo" dos valores postados (para re-render em caso de erro)
    for c in campos:
        cid = str(c.id)
        if c.tipo == "checkbox":
            setattr(c, "posted_multi", dados.getlist(cid))
            setattr(c, "posted", "")
        else:
            setattr(c, "posted", (dados.get(cid) or "").strip())
            setattr(c, "posted_multi", [])
        setattr(c, "errors", [])

    # Coleta de nome (apenas para anônimo quando ativado)
    nome_informado = (dados.get("__nome__") or "").strip()
    if getattr(form, "coletar_nome", False) and not request.user.is_authenticated:
        if not nome_informado:
            msg = "Informe seu nome para enviar este formulário."
            nome_erros.append(msg)
            erros_globais.append(msg)

    # Disponibilidade (dupla checagem no servidor)
    now = timezone.now()
    if hasattr(form, "aceita_respostas") and not form.aceita_respostas:
        add_err(None, "Este formulário não está aceitando respostas no momento.")
    if form.abre_em and form.abre_em > now:
        add_err(None, "Este formulário ainda não está disponível.")
    if form.fecha_em and form.fecha_em < now:
        add_err(None, "Este formulário foi encerrado.")
    if form.limite_resps and form.respostas.count() >= form.limite_resps:
        add_err(None, "O limite de respostas foi atingido.")

    # ===================== Validação por campo + regra "pelo menos 1" =====================
    active_campos = [c for c in campos if getattr(c, "ativo", True)]
    any_answered = False

    for c in campos:
        if not getattr(c, "ativo", True):
            continue
        cid = str(c.id)

        # ----- ARQUIVO -----
        if c.tipo == "arquivo":
            arqs = arquivos_req.getlist(cid)
            if arqs:
                any_answered = True

            cfg = c.validacao_json or {}
            try:
                max_arqs = int(cfg.get("max_arquivos", 1) or 1)
            except Exception:
                max_arqs = 1
            try:
                max_mb = int(cfg.get("max_mb", 10) or 10)
            except Exception:
                max_mb = 10
            tipos_livres = bool(cfg.get("tipos_livres", True))

            if c.obrigatorio and not arqs:
                add_err(c, f"O campo “{c.rotulo}” é obrigatório.")

            allowed_extensions = set()
            if not tipos_livres:
                for cat in (cfg.get("categorias") or []):
                    allowed_extensions.update(FILE_CATS.get(cat, set()))

            if arqs and len(arqs) > max_arqs:
                add_err(c, f"Máximo {max_arqs} arquivo(s) em “{c.rotulo}”.")
            for f in arqs:
                try:
                    if f.size > max_mb * 1024 * 1024:
                        add_err(c, f"“{getattr(f,'name','arquivo')}” excede {max_mb} MB (campo {c.rotulo}).")
                    if not tipos_livres:
                        nome = getattr(f, "name", "")
                        ext = nome.split(".")[-1].lower() if "." in nome else ""
                        if not ext or ext not in allowed_extensions:
                            add_err(c, f"Extensão “.{ext or '?'}” não é permitida em “{c.rotulo}”.")
                except Exception:
                    add_err(c, f"Falha ao validar arquivo em “{c.rotulo}”.")
            continue

        # ----- CHECKBOX -----
        if c.tipo == "checkbox":
            marcados = dados.getlist(cid)
            if marcados:
                any_answered = True
            if c.obrigatorio and not marcados:
                add_err(c, f"O campo “{c.rotulo}” é obrigatório.")
            continue

        # ----- DEMAIS TIPOS (texto, parágrafo, multipla, lista, escala, data, hora) -----
        val = (dados.get(cid) or "").strip()
        if val:
            any_answered = True
        if c.obrigatorio and not val:
            add_err(c, f"O campo “{c.rotulo}” é obrigatório.")

    # Se houver perguntas ativas e nenhuma foi respondida, bloqueia envio
    if active_campos and not any_answered:
        add_err(None, "Preencha pelo menos uma pergunta antes de enviar.")

    # Anexa erros nos objetos Campo (para renderizar no template)
    for c in campos:
        cid = str(c.id)
        setattr(c, "errors", erros_por_campo.get(cid, []))

    # Injeta os "campos" no cache de prefetch do form (para template reaproveitar a mesma instância)
    try:
        cache = getattr(form, "_prefetched_objects_cache", {}) or {}
        cache["campos"] = campos
        setattr(form, "_prefetched_objects_cache", cache)
    except Exception:
        pass

    # Se houve erros, re-renderiza o formulário
    if erros_globais or nome_erros:
        template = "formularios/responder_embed.html" if embed_mode else "formularios/responder.html"
        logger.debug("Validação falhou form=%s erros=%s", form.pk, len(erros_globais))
        return render(
            request, template,
            {
                "formulario": form,
                "erros": erros_globais,
                "nome_informado": nome_informado,
                "nome_erros": nome_erros,
                "embed": bool(embed_mode),
            }
        )

    # ===================== SALVAR =====================
    resposta = Resposta.objects.create(
        formulario=form,
        enviado_por=(request.user if request.user.is_authenticated else None),
        ip=_ip(request),
        versao_form=form.versao,
    )

    # Preencher nome_coletado quando coletar_nome=True
    if getattr(form, "coletar_nome", False) and hasattr(resposta, "nome_coletado"):
        if request.user.is_authenticated:
            u = request.user
            nome_auto = (
                (u.get_full_name() or "").strip()
                or (" ".join([u.first_name or "", u.last_name or ""]).strip())
                or getattr(u, "username", "")
                or getattr(u, "email", "")
            )
            if nome_auto:
                resposta.nome_coletado = nome_auto
                resposta.save(update_fields=["nome_coletado"])
        else:
            if nome_informado:
                resposta.nome_coletado = nome_informado
                resposta.save(update_fields=["nome_coletado"])

    # Persistir valores por campo
    for c in campos:
        if not getattr(c, "ativo", True):
            continue
        cid = str(c.id)
        if c.tipo == "arquivo":
            for f in arquivos_req.getlist(cid):
                ValorResposta.objects.create(resposta=resposta, campo=c, valor_arquivo=f)
        elif c.tipo == "checkbox":
            ValorResposta.objects.create(
                resposta=resposta, campo=c,
                valor_texto=", ".join(dados.getlist(cid))
            )
        else:
            ValorResposta.objects.create(
                resposta=resposta, campo=c,
                valor_texto=dados.get(cid, "")
            )

    logger.info("Resposta %s salva no form %s (embed=%s)", resposta.pk, form.pk, embed_mode)

    # ===================== RESPOSTA AO CLIENTE =====================
    if embed_mode:
        # Página compacta para uso embutido
        return render(
            request,
            "formularios/obrigado_embed.html",
            {"formulario": form, "resposta": resposta},
        )

    # Página completa (sempre "obrigado")
    return render(
        request,
        "formularios/obrigado.html",
        {"formulario": form, "resposta": resposta},
    )



# --------------------------------------------------------------------------- #
# DETALHE RESPOSTA                                                            #
# --------------------------------------------------------------------------- #
class DetalheRespostaView(DetailView):
    model = Resposta
    template_name = "formularios/detalhe_resposta.html"
    context_object_name = "resposta"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        is_owner = (obj.formulario.dono_id == getattr(self.request.user, "id", None))
        is_sender = (obj.enviado_por_id == getattr(self.request.user, "id", None))
        sess_key = f"can_view_resp_{obj.pk}"
        has_ticket = self.request.session.get(sess_key)

        logger.debug(
            "DetalheResposta id=%s | owner=%s sender=%s ticket=%s",
            obj.pk, is_owner, is_sender, bool(has_ticket)
        )

        if is_owner or is_sender or has_ticket:
            if has_ticket:
                try:
                    del self.request.session[sess_key]
                    self.request.session.modified = True
                except KeyError:
                    pass
            return obj
        raise Http404

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        r: Resposta = ctx["resposta"]

        # Todos os valores (para os filtros de template funcionarem)
        valores = list(r.valores.select_related("campo").all())

        # >>> AQUI A MUDANÇA: passar TODOS os campos do formulário (ordem original).
        # Inclui arquivados para manter histórico; o template já marca "Deletado".
        campos_do_form = list(r.formulario.campos.all().order_by("ordem"))

        ctx.update({
            "valores_resposta": valores,
            "campos_da_resposta": campos_do_form,
        })
        logger.debug(
            "DetalheResposta ctx: valores=%s campos(total)=%s",
            len(valores), len(campos_do_form)
        )
        return ctx

# --------------------------------------------------------------------------- #
# HELPERS – acesso + filtros compartilhados                                   #
# --------------------------------------------------------------------------- #
def _get_form_or_404(pk: int, user, for_edit: bool = False) -> Formulario:
    form = get_object_or_404(Formulario, pk=pk)
    allowed = form.can_user_edit(user) if for_edit else form.can_user_view(user)
    if not allowed:
        logger.warning("Acesso negado ao formulário %s por user=%s",
                       pk, getattr(user, "username", None))
        raise Http404
    return form


def _filtrar_respostas(request: HttpRequest, form: Formulario):
    qs = form.respostas.select_related("enviado_por").prefetch_related("valores", "valores__campo")

    q = (request.GET.get("q") or "").strip()
    if q:
        q_id = None
        try:
            q_id = int(q)
        except Exception:
            pass
        cond = (
            Q(valores__valor_texto__icontains=q) |
            Q(enviado_por__username__icontains=q) |
            Q(enviado_por__first_name__icontains=q) |
            Q(enviado_por__last_name__icontains=q) |
            Q(ip__icontains=q)
        )
        if q_id:
            cond = cond | Q(pk=q_id)
        qs = qs.filter(cond)

    de = request.GET.get("de")
    ate = request.GET.get("ate")

    def _to_dt(s):
        if not s:
            return None
        try:
            if len(s) == 10:
                return datetime.strptime(s, "%Y-%m-%d")
            return parse_datetime(s)
        except Exception:
            return None

    dt_de = _to_dt(de)
    dt_ate = _to_dt(ate)
    if dt_de:
        qs = qs.filter(enviado_em__gte=dt_de)
    if dt_ate:
        qs = qs.filter(enviado_em__lte=dt_ate)

    tem_anexo = (request.GET.get("tem_anexo") or "").lower()
    if tem_anexo == "s":
        qs = qs.filter(valores__valor_arquivo__isnull=False)
    elif tem_anexo == "n":
        qs = qs.exclude(valores__valor_arquivo__isnull=False)

    campo_id = request.GET.get("campo")
    valor = (request.GET.get("valor") or "").strip()
    if campo_id and valor:
        qs = qs.filter(valores__campo_id=campo_id, valores__valor_texto__icontains=valor)

    allowed = {"id", "-id", "enviado_em", "-enviado_em", "enviado_por__username",
               "-enviado_por__username", "ip", "-ip"}
    ord_ = request.GET.get("ord") or "-enviado_em"
    if ord_ not in allowed:
        ord_ = "-enviado_em"
    qs = qs.order_by(ord_).distinct()

    logger.debug(
        "Filtro respostas: q=%s de=%s ate=%s anexo=%s campo=%s valor='%s' ord=%s total=%s",
        q, de, ate, tem_anexo, campo_id, valor, ord_, qs.count()
    )
    return qs


# --------------------------------------------------------------------------- #
# ABA DE RESPOSTAS (HTMX)                                                     #
# --------------------------------------------------------------------------- #
class AbaRespostasView(LoginRequiredMixin, DetailView):
    model = Formulario
    template_name = "formularios/aba_respostas.html"
    pk_url_kwarg = "pk"
    context_object_name = "formulario"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not obj.can_user_view(self.request.user):
            raise Http404
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ctx["formulario"]

        qs = _filtrar_respostas(self.request, form)

        page_size = int(self.request.GET.get("pp", 10) or 10)
        paginator = Paginator(qs, page_size)
        page = self.request.GET.get("page") or 1
        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            page_obj = paginator.page(1)

        total = qs.count()
        ult_24h = form.respostas.filter(
            enviado_em__gte=timezone.now() - timedelta(hours=24)
        ).count()

        dist_por_campo = {}
        medias_escala = {}
        dist_escala_por_campo = {}

        # Inclui todos os campos (ativos e arquivados) para manter o histórico
        campos_resumo = list(form.campos.all().order_by("ordem"))

        for c in campos_resumo:
            if c.tipo in {"multipla", "checkbox", "lista"}:
                agg = (
                    ValorResposta.objects
                    .filter(resposta__in=qs, campo=c, valor_texto__isnull=False)
                    .values("valor_texto")
                    .annotate(qtd=Count("id"))
                    .order_by("-qtd", "valor_texto")
                )
                dist_por_campo[c.id] = list(agg)

            elif c.tipo == "escala":
                vals = (
                    ValorResposta.objects
                    .filter(resposta__in=qs, campo=c)
                    .exclude(valor_texto__exact="")
                    .values_list("valor_texto", flat=True)
                )
                nums = []
                for v in vals:
                    try:
                        nums.append(int(str(v).strip()))
                    except Exception:
                        pass
                medias_escala[c.id] = round(sum(nums) / len(nums), 2) if nums else None

                base = {str(i): 0 for i in range(1, 11)}
                if nums:
                    cont = (
                        ValorResposta.objects
                        .filter(resposta__in=qs, campo=c)
                        .exclude(valor_texto__exact="")
                        .values("valor_texto")
                        .annotate(qtd=Count("id"))
                    )
                    for row in cont:
                        k = str(row["valor_texto"]).strip()
                        if k in base:
                            base[k] += row["qtd"]
                dist_escala_por_campo[c.id] = [{"valor": k, "qtd": v} for k, v in base.items()]

            elif c.tipo != "arquivo":
                qv = (
                    ValorResposta.objects
                    .filter(resposta__in=qs, campo=c)
                    .exclude(valor_texto__exact="")
                    .values_list("valor_texto", flat=True)
                    .order_by("id")
                )
                LIMITE = 1000
                valores = list(qv[:LIMITE])
                c.text_vals = valores
                c.text_count = qv.count()
            else:
                c.text_vals = []
                c.text_count = 0

        ctx.update({
            "qs_page": page_obj,
            "total_filtrado": total,
            "ult_24h": ult_24h,
            "dist_por_campo": dist_por_campo,
            "medias_escala": medias_escala,
            "dist_escala_por_campo": dist_escala_por_campo,
            "page_size": page_size,
            "page_size_options": [10, 20, 50, 100],
            "campos_resumo": campos_resumo,  # inclui arquivados
        })
        logger.debug("AbaRespostas: total_filtrado=%s ult_24h=%s", total, ult_24h)
        return ctx


# --------------------------------------------------------------------------- #
# EXPORTAR CSV                                                                #
# --------------------------------------------------------------------------- #
@login_required
def exportar_respostas_csv(request: HttpRequest, pk: int):
    form = _get_form_or_404(pk, request.user, for_edit=False)
    qs = _filtrar_respostas(request, form)

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    fname = f'{slugify(form.titulo)}.csv'
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'

    writ = csv.writer(resp)
    campos = list(form.campos.order_by("ordem"))
    writ.writerow(["ID", "Enviado em", "Usuário", "Nome (informado)", "IP", *[c.rotulo for c in campos]])

    for r in qs:
        linha = [
            r.pk,
            _fmt_local(r.enviado_em),
            getattr(r.enviado_por, "username", "") or "",
            getattr(r, "nome_coletado", "") or "",
            r.ip or "",
        ]
        for c in campos:
            v = r.valores.filter(campo=c).first()
            linha.append(
                v.valor_texto if v and not v.valor_arquivo else
                (v.valor_arquivo.url if v and v.valor_arquivo else "")
            )
        writ.writerow(linha)

    logger.debug("CSV exportado: %s linhas", qs.count())
    return resp


# --------------------------------------------------------------------------- #
# EXPORTAR ANEXOS (ZIP)                                                       #
# --------------------------------------------------------------------------- #
@login_required
def exportar_anexos_zip(request: HttpRequest, pk: int):
    form = _get_form_or_404(pk, request.user, for_edit=False)
    qs = _filtrar_respostas(request, form)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        base = slugify(form.titulo) or f"form-{form.pk}"
        for r in qs:
            for v in r.valores.select_related("campo").all():
                if not v.valor_arquivo:
                    continue
                nome = v.valor_arquivo.name.split("/")[-1]
                rot = slugify(getattr(v.campo, "rotulo", "arquivo"))[:40] if v.campo_id else "campo-removido"
                arc = f"{base}/resp_{r.pk}/{rot}__{nome}"
                try:
                    with v.valor_arquivo.open("rb") as f:
                        zf.writestr(arc, f.read())
                except Exception as e:
                    logger.warning("Falha lendo arquivo %s: %s", v.valor_arquivo.name, e)

    buffer.seek(0)
    resp = HttpResponse(buffer.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="{slugify(form.titulo)}-anexos.zip"'
    logger.debug("ZIP exportado com %s respostas", qs.count())
    return resp


# --------------------------------------------------------------------------- #
# EXCLUSÃO EM MASSA                                                           #
# --------------------------------------------------------------------------- #
@login_required
@transaction.atomic
def excluir_respostas(request: HttpRequest, pk: int):
    if request.method != "POST":
        return HttpResponse(status=405)

    form = _get_form_or_404(pk, request.user, for_edit=True)
    ids_raw = request.POST.get("ids", "")
    ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
    if not ids:
        return HttpResponse("Nenhuma resposta selecionada.", status=400)

    deletadas = form.respostas.filter(pk__in=ids).delete()[0]
    logger.info("Excluídas %s respostas do formulário %s", deletadas, form.pk)

    if _is_htmx(request):
        url = reverse("formularios:aba_respostas", kwargs={"pk": form.pk})
        return HttpResponse(status=204, headers={"HX-Redirect": url})
    return redirect("formularios:aba_respostas", form.pk)


# --------------------------------------------------------------------------- #
# ==== NOVO: Compartilhamento (liberação direta) ============================ #
# --------------------------------------------------------------------------- #
@login_required
def colabs_fragment(request: HttpRequest, pk: int):
    form = _get_form_or_404(pk, request.user, for_edit=True)
    colabs = form.colaboradores.select_related("usuario").all()
    logger.debug(
        "colabs_fragment form_id=%s total=%s ids=%s",
        form.pk, colabs.count(),
        list(colabs.values_list("id", flat=True))
    )
    html = render_to_string(
        "formularios/partials/colabs.html",
        {"formulario": form, "colabs": colabs},
        request=request,
    )
    return HttpResponse(html)


@login_required
@require_POST
@transaction.atomic
def add_colab(request: HttpRequest, pk: int):
    form = _get_form_or_404(pk, request.user, for_edit=True)
    role = (request.POST.get("role") or "view").strip()  # "edit" | "view"
    ref  = (request.POST.get("user_ref") or "").strip()

    usuario = _find_user_by_ref(ref)
    if not usuario:
        logger.info("add_colab form_id=%s ref=%s -> não encontrado", form.pk, ref)
        return HttpResponse("Usuário não encontrado.", status=400)
    if usuario.id == form.dono_id:
        return HttpResponse("Este usuário já é o dono.", status=400)

    obj, created = Colaborador.objects.get_or_create(
        formulario=form,
        usuario=usuario,
        defaults={"pode_ver": True, "pode_editar": (role == "edit")},
    )
    if not created:
        obj.pode_ver = True
        obj.pode_editar = (role == "edit")
        obj.save(update_fields=["pode_ver", "pode_editar"])

    logger.info(
        "add_colab form_id=%s user_id=%s papel=%s created=%s",
        form.pk, usuario.id, "edit" if obj.pode_editar else "view", created
    )

    colabs = form.colaboradores.select_related("usuario").all()
    html = render_to_string(
        "formularios/partials/colabs_list.html",
        {"formulario": form, "colabs": colabs},
        request=request,
    )
    return HttpResponse(html)


@login_required
@require_POST
@transaction.atomic
def set_colab_role(request: HttpRequest, pk: int, colab_id: int):
    form = _get_form_or_404(pk, request.user, for_edit=True)

    role = (request.POST.get("role") or "").strip().lower()
    if role not in {"edit", "view"}:
        logger.warning(
            "set_colab_role: role inválido '%s' (form=%s colab=%s)",
            role, form.pk, colab_id
        )
        return HttpResponse("Papel inválido.", status=400)

    colab = get_object_or_404(Colaborador, pk=colab_id, formulario=form)
    colab.pode_ver = True
    colab.pode_editar = (role == "edit")
    colab.save(update_fields=["pode_ver", "pode_editar"])

    logger.info(
        "set_colab_role: form=%s user=%s -> role=%s",
        form.pk, colab.usuario_id, role
    )

    html = render_to_string(
        "formularios/partials/colabs_list.html",
        {"formulario": form},
        request=request
    )
    return HttpResponse(html)



@login_required
@require_POST
@transaction.atomic
def remove_colab(request: HttpRequest, pk: int, colab_id: int):
    form = _get_form_or_404(pk, request.user, for_edit=True)
    logger.info("remove_colab form_id=%s colab_id=%s", form.pk, colab_id)
    Colaborador.objects.filter(pk=colab_id, formulario=form).delete()

    colabs = form.colaboradores.select_related("usuario").all()
    html = render_to_string(
        "formularios/partials/colabs_list.html",
        {"formulario": form, "colabs": colabs},
        request=request,
    )
    return HttpResponse(html)





    # --------------------------------------------------------------------------- #
# Helper: localizar usuário por ID, username ou e-mail
# --------------------------------------------------------------------------- #
def _find_user_by_ref(ref: str):
    """
    Aceita:
      - ID numérico (pk)
      - username (case-insensitive)
      - e-mail (case-insensitive)

    Retorna instância do usuário ou None.
    """
    ref = (ref or "").strip()
    if not ref:
        logger.debug("_find_user_by_ref: vazio")
        return None

    # ID numérico direto
    if ref.isdigit():
        try:
            u = UserModel.objects.get(pk=int(ref))
            logger.debug("_find_user_by_ref: pk=%s -> %s", ref, u.pk)
            return u
        except UserModel.DoesNotExist:
            logger.debug("_find_user_by_ref: pk=%s não encontrado", ref)

    # username / email
    u = (
        UserModel.objects
        .filter(Q(username__iexact=ref) | Q(email__iexact=ref))
        .first()
    )
    logger.debug("_find_user_by_ref: lookup '%s' -> %s", ref, getattr(u, "pk", None))
    return u


