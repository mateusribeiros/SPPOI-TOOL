import json
import logging
import os
import shutil
import time
from datetime import datetime

import requests
from django.conf import settings
from django.http import JsonResponse, HttpResponseForbidden, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.middleware.csrf import get_token

from langchain_chroma import Chroma
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI

from .models import Projeto, Sistema, Interface, EstiloIntegracao, ChatMessage

DATA_PATH = os.path.join(settings.BASE_DIR, 'dados')
CHROMA_PATH = os.path.join(settings.BASE_DIR, 'chroma_db')

os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(CHROMA_PATH, exist_ok=True)


def _get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def normalize_multi(value):
    if isinstance(value, list):
        return ", ".join([v for v in value if v])
    return value or ""


def require_captcha(view_func):
    def _wrapped(request, *args, **kwargs):
        if not settings.TURNSTILE_ENABLED or settings.DEBUG:
            request.session['captcha_passed'] = True
            return view_func(request, *args, **kwargs)

        if not request.session.get('captcha_passed'):
            return redirect('index')
        return view_func(request, *args, **kwargs)
    return _wrapped


def ensure_session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def index(request):
    context = {
        'turnstile_site_key': settings.TURNSTILE_SITE_KEY,
        'turnstile_enabled': settings.TURNSTILE_ENABLED and not settings.DEBUG,
    }
    return render(request, 'index.html', context)


@require_http_methods(["POST"])
def captcha_verify(request):
    if not settings.TURNSTILE_ENABLED or settings.DEBUG:
        request.session['captcha_passed'] = True
        return JsonResponse({'success': True})

    token = request.POST.get('cf-turnstile-response')
    if not token:
        return JsonResponse({'success': False, 'error': 'Token ausente.'}, status=400)

    secret_key = settings.TURNSTILE_SECRET_KEY
    if not secret_key:
        return JsonResponse({'success': False, 'error': 'Chave Turnstile não configurada.'}, status=500)

    try:
        response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret_key, 'response': token, 'remoteip': request.META.get('REMOTE_ADDR')},
            timeout=10
        )
        data = response.json()
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Falha ao validar captcha: {e}'}, status=500)

    if data.get('success'):
        request.session['captcha_passed'] = True
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Captcha inválido.'}, status=400)


@require_captcha
def new_chat(request):
    session_key = ensure_session_key(request)
    projeto = Projeto.objects.create(nome=f"Chat {datetime.now().strftime('%d/%m %H:%M:%S')}", session_key=session_key)
    request.session['current_project_id'] = projeto.id
    return redirect('chat_view')


@require_captcha
def chat_view(request):
    session_key = ensure_session_key(request)
    project_id = request.session.get('current_project_id')
    projeto = None
    if project_id:
        projeto = Projeto.objects.filter(pk=project_id, session_key=session_key).first()

    if not projeto:
        projeto = Projeto.objects.filter(session_key=session_key).order_by('-criado_em').first()

    if not projeto:
        return redirect('chat_new')

    request.session['current_project_id'] = projeto.id
    projects = Projeto.objects.filter(session_key=session_key).order_by('-criado_em')
    systems = list(Sistema.objects.filter(projeto=projeto).values())
    interfaces = list(Interface.objects.filter(projeto=projeto).values())
    integrations = []
    for integ in EstiloIntegracao.objects.filter(projeto=projeto):
        integrations.append({
            'id': integ.id,
            'sistema_origem_id': integ.sistema_origem_id,
            'sistema_destino_id': integ.sistema_destino_id,
            'estilo': integ.estilo,
            'estilo_outro': integ.estilo_outro,
            'architectural_rationale': integ.architectural_rationale,
            'detalhes': integ.detalhes,
            'interfaces_usadas': list(integ.interfaces_usadas.values_list('id', flat=True)),
        })
    messages = list(ChatMessage.objects.filter(projeto=projeto).values('role', 'content', 'prompt_used', 'created_at'))

    context = {
        'project': projeto,
        'projects': projects,
        'systems': systems,
        'interfaces': interfaces,
        'integrations': integrations,
        'messages': messages,
        'csrf_token': get_token(request),
    }
    return render(request, 'chat.html', context)


@require_captcha
def chat_view_redirect(request, project_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)
    request.session['current_project_id'] = projeto.id
    return redirect('chat_view')


@require_captcha
def chat_list_api(request):
    session_key = ensure_session_key(request)
    projects = Projeto.objects.filter(session_key=session_key).order_by('-criado_em')
    data = [{
        'id': p.id,
        'nome': p.nome,
        'criado_em': p.criado_em.isoformat()
    } for p in projects]
    return JsonResponse({'projects': data})


@require_http_methods(["POST"])
@require_captcha
def chat_select_api(request, project_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)
    request.session['current_project_id'] = projeto.id
    return JsonResponse({'success': True})


@require_http_methods(["POST"])
@require_captcha
def chat_clear_api(request, project_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)
    ChatMessage.objects.filter(projeto=projeto).delete()
    return JsonResponse({'success': True})


@require_http_methods(["POST"])
@require_captcha
def chat_delete_api(request, project_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)
    projeto.delete()
    return JsonResponse({'success': True})


@require_http_methods(["GET", "POST"])
@require_captcha
def systems_api(request, project_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)

    if request.method == "GET":
        systems = list(Sistema.objects.filter(projeto=projeto).values())
        return JsonResponse({'systems': systems})

    data = json.loads(request.body.decode('utf-8'))
    system = Sistema.objects.create(
        projeto=projeto,
        system_identifier=data.get('system_identifier', ''),
        nome=data.get('nome', ''),
        tipo=data.get('tipo', ''),
        tipo_outro=data.get('tipo_outro', ''),
        descricao=data.get('descricao', ''),
        integration_role=data.get('integration_role', ''),
        primary_function_in_flow=data.get('primary_function_in_flow', ''),
        versao=data.get('versao', ''),
        protocolos_suportados=normalize_multi(data.get('protocolos_suportados')),
        protocolos_suportados_outro=data.get('protocolos_suportados_outro', ''),
        capacidades_dados=normalize_multi(data.get('capacidades_dados')),
        capacidades_dados_outro=data.get('capacidades_dados_outro', ''),
        email_responsavel=data.get('email_responsavel', ''),
        contato_responsavel=data.get('contato_responsavel', ''),
        mantenedor=data.get('mantenedor', ''),
        requisitos_autenticacao=normalize_multi(data.get('requisitos_autenticacao')),
        requisitos_autenticacao_outro=data.get('requisitos_autenticacao_outro', ''),
        technical_contact=data.get('technical_contact', ''),
        architectural_notes=data.get('architectural_notes', ''),
    )
    return JsonResponse({'system': {
        'id': system.id,
        'nome': system.nome,
        'tipo': system.tipo,
        'versao': system.versao,
    }})


@require_http_methods(["POST", "DELETE"])
@require_captcha
def system_detail_api(request, project_id, system_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)
    system = get_object_or_404(Sistema, pk=system_id, projeto=projeto)

    if request.method == "DELETE":
        system.delete()
        return JsonResponse({'success': True})

    data = json.loads(request.body.decode('utf-8'))
    for field in [
        'system_identifier', 'nome', 'descricao', 'tipo', 'tipo_outro',
        'integration_role', 'primary_function_in_flow', 'versao',
        'protocolos_suportados', 'protocolos_suportados_outro',
        'capacidades_dados', 'capacidades_dados_outro',
        'email_responsavel', 'contato_responsavel', 'mantenedor',
        'requisitos_autenticacao', 'requisitos_autenticacao_outro',
        'technical_contact', 'architectural_notes'
    ]:
        if field in data:
            if field in ['protocolos_suportados', 'capacidades_dados', 'requisitos_autenticacao']:
                setattr(system, field, normalize_multi(data[field]))
            else:
                setattr(system, field, data[field])
    system.save()
    return JsonResponse({'success': True})


@require_http_methods(["GET", "POST"])
@require_captcha
def interfaces_api(request, project_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)

    if request.method == "GET":
        interfaces = list(Interface.objects.filter(projeto=projeto).values())
        return JsonResponse({'interfaces': interfaces})

    data = json.loads(request.body.decode('utf-8'))
    sistema = get_object_or_404(Sistema, pk=data.get('sistema_id'), projeto=projeto)

    interface = Interface.objects.create(
        projeto=projeto,
        sistema=sistema,
        interface_identifier=data.get('interface_identifier', ''),
        nome=data.get('nome', ''),
        tipo=data.get('tipo', ''),
        tipo_outro=data.get('tipo_outro', ''),
        endpoint=data.get('endpoint', ''),
        formato_dados=data.get('formato_dados', ''),
        metodos_permitidos=data.get('metodos_permitidos', ''),
        autenticacao=normalize_multi(data.get('autenticacao')),
        operacoes_suportadas=data.get('operacoes_suportadas', ''),
        throttling=data.get('throttling', ''),
        throttling_unit=data.get('throttling_unit', ''),
        technical_interface_notes=data.get('technical_interface_notes', ''),
        detalhes=data.get('detalhes', None),
        exemplo_dados=data.get('exemplo_dados', ''),
        esquema=data.get('esquema', ''),
    )
    return JsonResponse({'interface': {'id': interface.id, 'nome': interface.nome}})


@require_http_methods(["POST", "DELETE"])
@require_captcha
def interface_detail_api(request, project_id, interface_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)
    interface = get_object_or_404(Interface, pk=interface_id, projeto=projeto)

    if request.method == "DELETE":
        interface.delete()
        return JsonResponse({'success': True})

    data = json.loads(request.body.decode('utf-8'))
    if 'sistema_id' in data:
        interface.sistema = get_object_or_404(Sistema, pk=data['sistema_id'], projeto=projeto)

    for field in [
        'interface_identifier', 'nome', 'tipo', 'tipo_outro', 'endpoint',
        'formato_dados', 'metodos_permitidos', 'autenticacao',
        'operacoes_suportadas', 'exemplo_dados', 'esquema', 'throttling',
        'throttling_unit', 'technical_interface_notes', 'detalhes'
    ]:
        if field in data:
            if field == 'autenticacao':
                setattr(interface, field, normalize_multi(data[field]))
            else:
                setattr(interface, field, data[field])
    interface.save()
    return JsonResponse({'success': True})


@require_http_methods(["GET", "POST"])
@require_captcha
def integrations_api(request, project_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)

    if request.method == "GET":
        integrations = []
        for integ in EstiloIntegracao.objects.filter(projeto=projeto):
            integrations.append({
                'id': integ.id,
                'sistema_origem_id': integ.sistema_origem_id,
                'sistema_destino_id': integ.sistema_destino_id,
                'estilo': integ.estilo,
                'estilo_outro': integ.estilo_outro,
                'architectural_rationale': integ.architectural_rationale,
                'detalhes': integ.detalhes,
                'interfaces_usadas': list(integ.interfaces_usadas.values_list('id', flat=True)),
            })
        return JsonResponse({'integrations': integrations})

    data = json.loads(request.body.decode('utf-8'))
    origem = get_object_or_404(Sistema, pk=data.get('sistema_origem_id'), projeto=projeto)
    destino = get_object_or_404(Sistema, pk=data.get('sistema_destino_id'), projeto=projeto)

    detalhes = data.get('detalhes')
    try:
        detalhes_json = json.loads(detalhes) if isinstance(detalhes, str) else detalhes
    except Exception:
        detalhes_json = {'raw': detalhes}

    integration = EstiloIntegracao.objects.create(
        projeto=projeto,
        sistema_origem=origem,
        sistema_destino=destino,
        estilo=data.get('estilo', ''),
        estilo_outro=data.get('estilo_outro', ''),
        architectural_rationale=data.get('architectural_rationale', ''),
        detalhes=detalhes_json,
    )
    interfaces_usadas = data.get('interfaces_usadas') or []
    if interfaces_usadas:
        integration.interfaces_usadas.set(Interface.objects.filter(id__in=interfaces_usadas, projeto=projeto))
    return JsonResponse({'integration': {'id': integration.id, 'estilo': integration.estilo}})


@require_http_methods(["POST", "DELETE"])
@require_captcha
def integration_detail_api(request, project_id, integration_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)
    integration = get_object_or_404(EstiloIntegracao, pk=integration_id, projeto=projeto)

    if request.method == "DELETE":
        integration.delete()
        return JsonResponse({'success': True})

    data = json.loads(request.body.decode('utf-8'))
    if 'sistema_origem_id' in data:
        integration.sistema_origem = get_object_or_404(Sistema, pk=data['sistema_origem_id'], projeto=projeto)
    if 'sistema_destino_id' in data:
        integration.sistema_destino = get_object_or_404(Sistema, pk=data['sistema_destino_id'], projeto=projeto)

    if 'estilo' in data:
        integration.estilo = data['estilo']
    if 'estilo_outro' in data:
        integration.estilo_outro = data['estilo_outro']
    if 'architectural_rationale' in data:
        integration.architectural_rationale = data['architectural_rationale']

    if 'detalhes' in data:
        try:
            integration.detalhes = json.loads(data['detalhes']) if isinstance(data['detalhes'], str) else data['detalhes']
        except Exception:
            integration.detalhes = {'raw': data['detalhes']}

    if 'interfaces_usadas' in data:
        interfaces_usadas = data.get('interfaces_usadas') or []
        integration.interfaces_usadas.set(Interface.objects.filter(id__in=interfaces_usadas, projeto=projeto))

    integration.save()
    return JsonResponse({'success': True})


# ===== PROMPT / RAG =====

def create_prompt(project, systems, interfaces, integration_styles, lang='pt'):
    system_prompt = (
    """
You will act as a senior architect/researcher for systems integration and interoperability.

MAIN OBJECTIVE:
To produce a structured technical assessment, focused on integration and interoperability risks, points of failure, 
and suggestions for improvements.

MANDATORY:
- DO NOT repeat obvious facts already present in the input.
- DO NOT mechanically enumerate missing information.
- Prioritize critical weaknesses over completeness.
- Focus on what can realistically fail in production environments.
- Use risk-based reasoning, grounded in real-world integration patterns.
- Missing or undefined aspects MUST be analyzed as technical risks, and not merely stated as missing.
- Focus on the 3 and 4 sections, as they are the core of the analysis.
- Do not repeat the Project Context (Observed Data).
- The 5 sections are mandatory upon departure.

OUTPUT:
- The output MUST be in valid Markdown format (.md).
- Use clear section titles.
- Limit yourself to a maximum of 2 risks and 2 recommendations.
- Avoid repeating generic impacts (e.g., "data loss or inconsistency"). Consolidate impacts when appropriate.


SCOPE:
- Analyze ONLY the explicitly described main integration flow.
- Ignore secondary or symmetrical paths unless they present distinct risks.
- DO NOT assume technical information not mentioned in the systems, interfaces, or integration styles.

STYLE:
- Write as a technical review intended for a senior integration/interoperability specialist.
- Be concise, direct, and judgment-based.

CRITICAL:
If the input does NOT contain at least ONE system AND at least ONE interface AND at least ONE integration style,
then the analysis task is INVALID.

In this case:
- Do NOT perform any architectural analysis.
- Do NOT identify risks.
- Do NOT propose improvements.
- Do NOT create sections.
- Do NOT apply the main objective.

Return ONLY the following message, verbatim, and NOTHING else:

Title: "Informações insuficientes para análise técnica"
Message:
"Devido à falta de informações sobre sistemas,
interfaces e/ou estilos de integração, não é possível realizar uma análise detalhada
da integração e interoperabilidade do projeto."
""".strip()
    )

    language_block = """
LANGUAGE:
- Conduct all reasoning internally in English.
- Produce the final result exclusively in Brazilian Portuguese.
- Keep established technical terms in English.
- Do not include greetings, filler text, or self-references.
""".strip()

    user_prompt = f"""
    ## Project Context (Observed Data)

    Project name: {project.nome}
    """

    user_prompt += "\n--- \n## Systems\n"
    for system in systems:
        user_prompt += (
            f"\n### {system.nome}\n"
            f"- System ID: {system.system_identifier or 'N/A'}\n"
            f"- Description: {system.descricao or 'N/A'}\n"
            f"- Type: {system.tipo or 'N/A'}\n"
            f"- Type (Other): {system.tipo_outro or 'N/A'}\n"
            f"- Version: {system.versao or 'N/A'}\n"
            f"- Integration Role: {system.integration_role or 'N/A'}\n"
            f"- Primary Function: {system.primary_function_in_flow or 'N/A'}\n"
            f"- Supported Protocols: {system.protocolos_suportados or 'N/A'}\n"
            f"- Supported Protocols (Other): {system.protocolos_suportados_outro or 'N/A'}\n"
            f"- Data Capabilities: {system.capacidades_dados or 'N/A'}\n"
            f"- Data Capabilities (Other): {system.capacidades_dados_outro or 'N/A'}\n"
            f"- Authentication Requirements: {system.requisitos_autenticacao or 'N/A'}\n"
            f"- Authentication Requirements (Other): {system.requisitos_autenticacao_outro or 'N/A'}\n"
            f"- Maintainer: {system.mantenedor or 'N/A'}\n"
            f"- Technical Contact: {system.technical_contact or 'N/A'}\n"
            f"- Architectural Notes: {system.architectural_notes or 'N/A'}\n"
        )

    user_prompt += "\n--- \n## Interfaces\n"
    for interface in interfaces:
        sys_name = interface.sistema.nome if interface.sistema else "Unknown System"
        user_prompt += (
            f"\n### {interface.nome} (System: {sys_name})\n"
            f"- Interface ID: {interface.interface_identifier or 'N/A'}\n"
            f"- Type: {interface.tipo or 'N/A'}\n"
            f"- Type (Other): {interface.tipo_outro or 'N/A'}\n"
            f"- Endpoint: {interface.endpoint or 'N/A'}\n"
            f"- Data Format: {interface.formato_dados or 'N/A'}\n"
            f"- Allowed Methods: {interface.metodos_permitidos or 'N/A'}\n"
            f"- Authentication: {interface.autenticacao or 'N/A'}\n"
            f"- Supported Operations: {interface.operacoes_suportadas or 'N/A'}\n"
            f"- Throttling: {interface.throttling or 'N/A'}\n"
            f"- Throttling Unit: {interface.throttling_unit or 'N/A'}\n"
            f"- Technical Notes: {interface.technical_interface_notes or 'N/A'}\n"
            f"- Data Schema: {interface.esquema or 'N/A'}\n"
            f"- Data Example: {interface.exemplo_dados or 'N/A'}\n"
            f"- Details: {interface.detalhes or 'N/A'}\n"
        )

    user_prompt += "\n--- \n## Integration Styles\n"
    for style in integration_styles:
        origem = style.sistema_origem.nome if style.sistema_origem else "Unknown"
        destino = style.sistema_destino.nome if style.sistema_destino else "Unknown"
        interfaces_usadas = ", ".join([i.nome for i in style.interfaces_usadas.all()]) or "N/A"
        user_prompt += (
            f"\n### {style.estilo}\n"
            f"- From: {origem}\n"
            f"- To: {destino}\n"
            f"- Style (Other): {style.estilo_outro or 'N/A'}\n"
            f"- Interfaces Used: {interfaces_usadas}\n"
            f"- Architectural Rationale: {style.architectural_rationale or 'N/A'}\n"
            f"- Details: {style.detalhes or 'N/A'}\n"
        )

    user_prompt += """

---

### 1. Summary

Provide a high-level conclusion.

- Most serious structural architectural flaw identified
- The first and most likely failure to occur
- Primary threat to long-term evolvability

- Whether the integration can be considered secure and reliable as a data
exchange mechanism - Low / Medium / High / Critical (justify concisely)
- Whether failures will tend to be detectable or silent
- Whether the current design supports future evolution without significant rework

Constraints:
- Be explicit, technical, and judgment-based.

---

### 2. Architectural Analysis
Perform a **detailed technical validation** of the integration and interoperability
based on modern integration and interoperability principles.

This section must evaluate **how well the current design aligns or diverges**
from established architectural expectations for integrations of this nature.
Produce a **continuous, dense architectural analysis** of the described integration/interoperability.

Validate, in a technically grounded manner:
- How coupling and cohesion are affected by the chosen integration style
- How communication semantics (sync vs async, statefulness, temporal coupling) behave
- How data mapping and transformation support or weaken semantic consistency
- How reliability expectations are shaped by transport and storage choices
- How failure propagation and observability are (or are not) supported
- How security boundaries are defined and enforced across the flow
- How scalable and evolvable this architecture is under growth and change
Use these dimensions as **validation criteria**, not as explicit sections.
- Do not translate the dimension names from section 2

This section must have at least 7 paragraphs.

---

### 3. Critical Integration & Interoperability Risks

For each risk, use the structure below. 
Affected elements: 
Architectural decision or implicit assumption: 
Failure manifestation: 
Operational consequences: 

This section should be rich in technical details.
Focus in detail on the important information gaps or weaknesses identified in section 2, technically justifying each risk.

---

### 4. Improvements & Standardization Suggestion

For each identified Recommendation:
- Required correction or standardization
- Which integration principle or pattern should apply
- Where the correction applies
- Architectural weakness eliminated
- Trade-off introduced

This section should be rich in technical details.
Utilize de modern integration and interoperability principles as a foundation for each recommendation. And the
context of RAG (Retrieval-Augmented Generation).

---

### 5. Final Considerations

This section MUST be written LAST and MUST NOT be omitted or truncated.

Explicitly address:
- The integration/interoperability related to the highlighted scenarios, aiming to
strengthen the user's understanding of the entire scenario presented.

This section MUST contain at least a complete paragraph.
DO NOT end the response before concluding this section.

---

""".strip()

    final_constraints_block = """
FINAL CONSTRAINTS:
- Plan the output structure to be limited to 2000 tokens, with all sections visible and without abrupt cuts.
- No repetition, only section 5 can be repeated.
- No generic statements.
- Respond exclusively in Brazilian Portuguese.
""".strip()

    if lang == 'pt':
        system_prompt = system_prompt + "\n\n" + language_block
        user_prompt = user_prompt + "\n\n" + final_constraints_block

    full_prompt = system_prompt + "\n\n" + user_prompt
    return system_prompt, user_prompt, full_prompt


def prepare_chroma_db():
    if not os.path.exists(DATA_PATH):
        return

    loader = DirectoryLoader(
        DATA_PATH,
        glob="*.md",
        loader_cls=TextLoader,
        loader_kwargs={'encoding': 'utf-8'}
    )

    documents = loader.load()
    if not documents:
        return

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=500,
        length_function=len,
        add_start_index=True,
    )

    chunks = text_splitter.split_documents(documents)
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    Chroma.from_documents(chunks, embedding=embeddings, persist_directory=CHROMA_PATH)


def get_rag_context(user_prompt):
    db_file = os.path.join(CHROMA_PATH, 'chroma.sqlite3')
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

    if not os.path.exists(db_file):
        prepare_chroma_db()

    try:
        db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        results = db.similarity_search_with_relevance_scores(user_prompt, k=3)
    except Exception:
        # Tenta autocurar se o índice estiver corrompido
        if os.path.exists(CHROMA_PATH):
            shutil.rmtree(CHROMA_PATH, ignore_errors=True)
        prepare_chroma_db()
        db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        results = db.similarity_search_with_relevance_scores(user_prompt, k=3)

    relevant_docs = [doc for doc, score in results if score >= 0.2]
    context_text = (
        "\n\n--\n\n".join([doc.page_content for doc in relevant_docs])
        if relevant_docs else "Nenhum contexto relevante encontrado."
    )
    return context_text


def _chat_stream_for_project(request, projeto):
    if Sistema.objects.filter(projeto=projeto).count() == 0 or \
       Interface.objects.filter(projeto=projeto).count() == 0 or \
       EstiloIntegracao.objects.filter(projeto=projeto).count() == 0:
        return JsonResponse({'error': 'Preencha sistemas, interfaces e integrações antes da consulta.'}, status=400)

    data = json.loads(request.body.decode('utf-8'))
    lang = data.get('lang', 'pt')
    user_message = data.get('message', '').strip()
    if not user_message:
        user_message = 'Analisar integração com base nos dados fornecidos.'

    system_prompt, user_prompt, full_prompt = create_prompt(
        projeto,
        Sistema.objects.filter(projeto=projeto),
        Interface.objects.filter(projeto=projeto),
        EstiloIntegracao.objects.filter(projeto=projeto),
        lang=lang,
    )

    rag_context = get_rag_context(user_prompt)
    prompt = f"""
    [CONTEXT START]
    {rag_context}
    [CONTEXT END]

    {user_prompt}
    """

    client = OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=settings.HF_API_TOKEN,
    )

    def event_stream():
        analysis_start = time.time()
        ChatMessage.objects.create(projeto=projeto, role='user', content=user_message)
        yield f"event: prompt\ndata: {json.dumps(full_prompt)}\n\n"

        assistant_content = ""
        try:
            completion = client.chat.completions.create(
                model="meta-llama/Llama-3.3-70B-Instruct:hyperbolic",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                top_p=0.8,
                max_tokens=2000,
                seed=42,
                stream=True,
            )

            for chunk in completion:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    assistant_content += delta
                    yield f"event: token\ndata: {json.dumps(delta)}\n\n"

            ChatMessage.objects.create(
                projeto=projeto,
                role='assistant',
                content=assistant_content,
                prompt_used=full_prompt,
            )

            duration_ms = int((time.time() - analysis_start) * 1000)
            analysis_logger = logging.getLogger('chat.analysis')
            analysis_payload = {
                'event': 'chat_analysis',
                'project_id': projeto.id,
                'project_name': projeto.nome,
                'session_key': request.session.session_key,
                'lang': lang,
                'status_code': 200,
                'duration_ms': duration_ms,
                'response_chars': len(assistant_content),
                'ip': _get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT'),
                'referer': request.META.get('HTTP_REFERER'),
            }
            analysis_logger.info(json.dumps(analysis_payload, ensure_ascii=False))

            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps(str(e))}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response


@require_http_methods(["POST"])
@require_captcha
def chat_stream(request, project_id):
    session_key = ensure_session_key(request)
    projeto = get_object_or_404(Projeto, pk=project_id, session_key=session_key)
    return _chat_stream_for_project(request, projeto)


@require_http_methods(["POST"])
@require_captcha
def chat_stream_current(request):
    session_key = ensure_session_key(request)
    project_id = request.session.get('current_project_id')
    projeto = None
    if project_id:
        projeto = Projeto.objects.filter(pk=project_id, session_key=session_key).first()
    if not projeto:
        projeto = Projeto.objects.filter(session_key=session_key).order_by('-criado_em').first()
    if not projeto:
        return JsonResponse({'error': 'Conversa não encontrada.'}, status=404)
    request.session['current_project_id'] = projeto.id
    return _chat_stream_for_project(request, projeto)
