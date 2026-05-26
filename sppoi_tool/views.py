import json
import logging
import os
import re
import shutil
import time
import unicodedata
from datetime import datetime

from django.conf import settings
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.middleware.csrf import get_token

from langchain_chroma import Chroma
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI

from .models import Projeto, Sistema, Interface, EstiloIntegracao, ChatMessage

DATA_PATH = os.path.join(settings.BASE_DIR, 'dataset_rag')
CHROMA_PATH = os.path.join(settings.BASE_DIR, 'chroma_db')
os.environ.setdefault('ANONYMIZED_TELEMETRY', 'False')

os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(CHROMA_PATH, exist_ok=True)
_EMBEDDINGS = None


def _get_env_float(name, default):
	raw_value = os.environ.get(name)
	if raw_value in (None, ''):
		return default
	try:
		return float(raw_value)
	except (TypeError, ValueError):
		return default


def _get_env_int(name, default):
	raw_value = os.environ.get(name)
	if raw_value in (None, ''):
		return default
	try:
		return int(raw_value)
	except (TypeError, ValueError):
		return default


HF_CHAT_MODEL = os.environ.get('HF_CHAT_MODEL', 'meta-llama/Llama-3.3-70B-Instruct:hyperbolic')
HF_CHAT_TEMPERATURE = _get_env_float('HF_CHAT_TEMPERATURE', 0.15)
HF_CHAT_TOP_P = _get_env_float('HF_CHAT_TOP_P', 0.7)
HF_CHAT_MAX_TOKENS = _get_env_int('HF_CHAT_MAX_TOKENS', 2600)
HF_CHAT_TIMEOUT = _get_env_int('HF_CHAT_TIMEOUT', 180)


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
		request.session['captcha_passed'] = True
		return view_func(request, *args, **kwargs)
	return _wrapped


def ensure_session_key(request):
	if not request.session.session_key:
		request.session.save()
	return request.session.session_key


def _project_scope_qs(session_key):
	if getattr(settings, 'SPPOI_DEV_PERSIST_PROJECTS', False):
		return Projeto.objects.all()
	return Projeto.objects.filter(session_key=session_key)


def _get_scoped_project_or_404(project_id, session_key):
	return get_object_or_404(_project_scope_qs(session_key), pk=project_id)


def index(request):
	return render(request, 'index.html')


def chrome_devtools_probe(request):
	return HttpResponse(status=204)

@require_captcha
def new_chat(request):
	session_key = ensure_session_key(request)
	projeto = Projeto.objects.create(nome=f"Chat {datetime.now().strftime('%d/%m %H:%M:%S')}", session_key=session_key)
	request.session['current_project_id'] = projeto.id
	return redirect('chat_view')


@require_captcha
def chat_view(request):
	session_key = ensure_session_key(request)
	projects_qs = _project_scope_qs(session_key).order_by('-criado_em')
	project_id = request.session.get('current_project_id')
	projeto = None
	if project_id:
		projeto = projects_qs.filter(pk=project_id).first()

	if not projeto:
		projeto = projects_qs.first()

	if not projeto:
		return redirect('chat_new')

	request.session['current_project_id'] = projeto.id
	projects = projects_qs
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
	projeto = _get_scoped_project_or_404(project_id, session_key)
	request.session['current_project_id'] = projeto.id
	return redirect('chat_view')


@require_captcha
def chat_list_api(request):
	session_key = ensure_session_key(request)
	projects = _project_scope_qs(session_key).order_by('-criado_em')
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
	projeto = _get_scoped_project_or_404(project_id, session_key)
	request.session['current_project_id'] = projeto.id
	return JsonResponse({'success': True})


@require_http_methods(["POST"])
@require_captcha
def chat_clear_api(request, project_id):
	session_key = ensure_session_key(request)
	projeto = _get_scoped_project_or_404(project_id, session_key)
	ChatMessage.objects.filter(projeto=projeto).delete()
	return JsonResponse({'success': True})


@require_http_methods(["POST"])
@require_captcha
def chat_delete_api(request, project_id):
	session_key = ensure_session_key(request)
	projeto = _get_scoped_project_or_404(project_id, session_key)
	projeto.delete()
	return JsonResponse({'success': True})


@require_http_methods(["GET", "POST"])
@require_captcha
def systems_api(request, project_id):
	session_key = ensure_session_key(request)
	projeto = _get_scoped_project_or_404(project_id, session_key)

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
	projeto = _get_scoped_project_or_404(project_id, session_key)
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
	projeto = _get_scoped_project_or_404(project_id, session_key)

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
	projeto = _get_scoped_project_or_404(project_id, session_key)
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
	projeto = _get_scoped_project_or_404(project_id, session_key)

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
	projeto = _get_scoped_project_or_404(project_id, session_key)
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

def get_embeddings_model():
	global _EMBEDDINGS
	if _EMBEDDINGS is None:
		_EMBEDDINGS = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
	return _EMBEDDINGS


def _has_meaningful_value(value):
	if value is None:
		return False
	if isinstance(value, str):
		text = value.strip()
		return text not in ('', 'N/A', 'None', '{}', '[]')
	if isinstance(value, (list, tuple, set)):
		return any(_has_meaningful_value(item) for item in value)
	if isinstance(value, dict):
		return any(_has_meaningful_value(item) for item in value.values())
	return True


def _clean_text(value, limit=None):
	if value is None:
		return ''
	text = value if isinstance(value, str) else str(value)
	text = re.sub(r'\s+', ' ', text).strip()
	if text in ('', 'N/A', 'None', '{}', '[]'):
		return ''
	if limit and len(text) > limit:
		text = text[:limit].rsplit(' ', 1)[0].rstrip(' ,;:.') + '...'
	return text


def _split_csv(value):
	if not value:
		return []
	if isinstance(value, (list, tuple, set)):
		items = value
	else:
		items = str(value).split(',')
	return [item.strip() for item in items if _clean_text(item)]


def _unique_preserve(items):
	seen = set()
	result = []
	for item in items:
		key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
		if key in seen:
			continue
		seen.add(key)
		result.append(item)
	return result


def _clean_mapping(data):
	cleaned = {}
	for key, value in data.items():
		if isinstance(value, dict):
			nested = _clean_mapping(value)
			if nested:
				cleaned[key] = nested
		elif isinstance(value, (list, tuple, set)):
			items = []
			for item in value:
				if isinstance(item, dict):
					nested = _clean_mapping(item)
					if nested:
						items.append(nested)
				else:
					text = _clean_text(item)
					if text:
						items.append(text)
			items = _unique_preserve(items)
			if items:
				cleaned[key] = items
		else:
			text = _clean_text(value)
			if text:
				cleaned[key] = text
	return cleaned


def _packet_to_json(data):
	return json.dumps(data, ensure_ascii=False, indent=2)


def _serialize_system(system):
	protocols = _unique_preserve(_split_csv(system.protocolos_suportados) + _split_csv(system.protocolos_suportados_outro))
	data_formats = _unique_preserve(_split_csv(system.capacidades_dados) + _split_csv(system.capacidades_dados_outro))
	auth = _unique_preserve(_split_csv(system.requisitos_autenticacao) + _split_csv(system.requisitos_autenticacao_outro))
	return _clean_mapping({
		'id': system.system_identifier or f'SYS-{system.id}',
		'name': system.nome,
		'type': system.tipo,
		'type_other': system.tipo_outro,
		'description': system.descricao,
		'integration_role': system.integration_role,
		'primary_function_in_flow': system.primary_function_in_flow,
		'supported_protocols': protocols,
		'supported_data_formats': data_formats,
		'authentication_requirements': auth,
		'version': system.versao,
		'technical_contact': system.technical_contact,
		'architectural_notes': system.architectural_notes,
	})


def _serialize_interface(interface):
	details = _clean_mapping(interface.detalhes or {})
	allowed_methods = _unique_preserve(_split_csv(interface.metodos_permitidos) + details.get('http_methods', []))
	authentication = _unique_preserve(_split_csv(interface.autenticacao) + _split_csv(details.get('autenticacao_outro')))
	data_format = interface.formato_dados or details.get('formato_dados') or details.get('message_format')
	primary_endpoint = interface.endpoint or details.get('connection_endpoint')
	rate_limits = _clean_mapping({
		'value': interface.throttling,
		'unit': interface.throttling_unit,
	})
	return _clean_mapping({
		'id': interface.interface_identifier or f'INT-{interface.id}',
		'name': interface.nome,
		'related_system': interface.sistema.nome if interface.sistema else '',
		'type': interface.tipo,
		'type_other': interface.tipo_outro,
		'primary_endpoint': primary_endpoint,
		'data_format': data_format,
		'allowed_methods': allowed_methods,
		'authentication': authentication,
		'supported_operations': interface.operacoes_suportadas,
		'rate_limits': rate_limits,
		'technical_notes': interface.technical_interface_notes,
		'data_schema': interface.esquema or details.get('json_schema') or details.get('schema'),
		'data_example': interface.exemplo_dados or details.get('example_payload') or details.get('example'),
		'technical_characteristics': details,
	})


def _serialize_integration(style):
	details = _clean_mapping(style.detalhes or {})
	interfaces_used = [interface.nome for interface in style.interfaces_usadas.all() if _clean_text(interface.nome)]
	source_name = style.sistema_origem.nome if style.sistema_origem else ''
	target_name = style.sistema_destino.nome if style.sistema_destino else ''
	return _clean_mapping({
		'style': style.estilo,
		'style_other': style.estilo_outro,
		'flow': f'{source_name} -> {target_name}',
		'source_system': source_name,
		'target_system': target_name,
		'interfaces_used': interfaces_used,
		'architectural_rationale': style.architectural_rationale,
		'technical_characteristics': details,
	})


def _build_evidence_highlights(system_records, interface_records, integration_records):
	authentication = []
	contracts = []
	reliability = []
	topology = []
	evolution = []

	for system in system_records:
		name = system.get('name', 'System')
		auth = [item for item in system.get('authentication_requirements', []) if item.lower() not in ('none', 'nenhuma')]
		if auth:
			authentication.append(f'{name}: mecanismos de autenticaÃ§Ã£o declarados ({", ".join(auth)})')
		if system.get('supported_protocols'):
			topology.append(f'{name}: protocolos {", ".join(system["supported_protocols"])}')
		if system.get('supported_data_formats'):
			contracts.append(f'{name}: formatos de dados {", ".join(system["supported_data_formats"])}')
		if system.get('architectural_notes'):
			evolution.append(f'{name}: {_clean_text(system["architectural_notes"], 180)}')

	for interface in interface_records:
		name = interface.get('name', 'Interface')
		system_name = interface.get('related_system', 'System')
		auth = [item for item in interface.get('authentication', []) if item.lower() not in ('none', 'nenhuma')]
		if auth:
			authentication.append(f'{name} ({system_name}): autenticaÃ§Ã£o {", ".join(auth)}')
		if interface.get('data_schema') or interface.get('data_example') or interface.get('data_format'):
			contracts.append(
				f'{name} ({system_name}): contrato de dados com formato {interface.get("data_format", "nÃ£o informado")}'
			)
		rate_limits = interface.get('rate_limits', {})
		if rate_limits:
			reliability.append(
				f'{name} ({system_name}): throttling {rate_limits.get("value", "")} {rate_limits.get("unit", "")}'.strip()
			)
		details = interface.get('technical_characteristics', {})
		for key in ('delivery_guarantees', 'reconnection_policy', 'processing_mode', 'statefulness'):
			if details.get(key):
				reliability.append(f'{name} ({system_name}): {key} = {details[key]}')
		topology.append(f'{name} ({system_name}): interface do tipo {interface.get("type", "nÃ£o informado")}')
		if interface.get('technical_notes'):
			evolution.append(f'{name} ({system_name}): {_clean_text(interface["technical_notes"], 180)}')

	for integration in integration_records:
		flow = integration.get('flow', 'Fluxo')
		topology.append(f'{flow}: estilo {integration.get("style", "nÃ£o informado")}')
		if integration.get('interfaces_used'):
			topology.append(f'{flow}: interfaces {", ".join(integration["interfaces_used"])}')
		if integration.get('architectural_rationale'):
			evolution.append(f'{flow}: {_clean_text(integration["architectural_rationale"], 180)}')
		details = integration.get('technical_characteristics', {})
		for key in ('processing_guarantees', 'sync_mode', 'rpc_mode', 'transformation_type'):
			if details.get(key):
				reliability.append(f'{flow}: {key} = {details[key]}')
		for key in ('database_type', 'shared_tables_or_views', 'message_format', 'topic_or_queue'):
			if details.get(key):
				contracts.append(f'{flow}: {key} = {_clean_text(details[key], 140)}')
		if details.get('broker'):
			topology.append(f'{flow}: broker {details["broker"]}')

	return _clean_mapping({
		'authentication_evidence': _unique_preserve(authentication)[:6],
		'contracts_and_semantics': _unique_preserve(contracts)[:6],
		'reliability_and_runtime_controls': _unique_preserve(reliability)[:6],
		'topology_and_coupling': _unique_preserve(topology)[:8],
		'evolution_and_operational_notes': _unique_preserve(evolution)[:6],
	})


def _build_analysis_packet(project, systems, interfaces, integration_styles):
	system_records = [_serialize_system(system) for system in systems]
	interface_records = [_serialize_interface(interface) for interface in interfaces]
	integration_records = [_serialize_integration(style) for style in integration_styles]
	evidence_highlights = _build_evidence_highlights(system_records, interface_records, integration_records)

	coverage_snapshot = {
		'systems_registered': len(system_records),
		'interfaces_registered': len(interface_records),
		'integration_styles_registered': len(integration_records),
		'systems_with_authentication': sum(1 for item in system_records if item.get('authentication_requirements')),
		'interfaces_with_contract_artifacts': sum(1 for item in interface_records if item.get('data_schema') or item.get('data_example')),
		'interfaces_with_runtime_limits': sum(1 for item in interface_records if item.get('rate_limits')),
		'integration_styles_with_rationale': sum(1 for item in integration_records if item.get('architectural_rationale')),
	}

	return {
		'project': {
			'name': project.nome,
			'main_registered_flows': [item.get('flow') for item in integration_records if item.get('flow')],
		},
		'coverage_snapshot': coverage_snapshot,
		'systems': system_records,
		'interfaces': interface_records,
		'integration_styles': integration_records,
		'explicit_evidence_highlights': evidence_highlights,
		'analysis_priority_dimensions': [
			'contratos e semÃ¢ntica de dados entre sistemas',
			'acoplamento, topologia e dependÃªncias entre interfaces',
			'transformaÃ§Ãµes, sincronizaÃ§Ã£o e compatibilidade entre formatos',
			'governanÃ§a de versionamento e evoluÃ§Ã£o de interfaces',
			'impactos operacionais de entrega, processamento e consistÃªncia do fluxo',
		],
		'collected_dimensions': [
			'sistemas envolvidos',
			'papel no fluxo',
			'protocolos e formatos de dados',
			'mecanismos de autenticaÃ§Ã£o declarados por sistema e interface',
			'throttling',
			'operaÃ§Ãµes suportadas',
			'schemas e exemplos de dados',
			'justificativa arquitetural',
			'detalhes tÃ©cnicos especÃ­ficos do estilo de integraÃ§Ã£o',
		],
		'non_collected_dimensions_by_default': [
			'polÃ­tica corporativa de seguranÃ§a',
			'polÃ­tica corporativa de retries',
			'dlq',
			'stack de observabilidade',
			'procedimentos de incident response',
			'encryption at rest',
			'sla formal',
		],
	}


def _build_retrieval_query(analysis_packet):
	terms = []
	for integration in analysis_packet.get('integration_styles', []):
		for key in ('style', 'source_system', 'target_system'):
			value = integration.get(key)
			if value:
				terms.append(value)
		details = integration.get('technical_characteristics', {})
		for key in ('broker', 'database_type', 'message_format', 'transformation_type'):
			value = details.get(key)
			if value:
				terms.append(value)

	for interface in analysis_packet.get('interfaces', []):
		for key in ('type', 'data_format'):
			value = interface.get(key)
			if value:
				terms.append(value)
		for value in interface.get('allowed_methods', []):
			terms.append(value)
		for value in interface.get('authentication', []):
			if value.lower() not in ('none', 'nenhuma'):
				terms.append(value)

	for system in analysis_packet.get('systems', []):
		for value in system.get('supported_protocols', []):
			terms.append(value)
		for value in system.get('supported_data_formats', []):
			terms.append(value)

	base_terms = _unique_preserve([_clean_text(term, 40) for term in terms if _clean_text(term)])
	base_terms = base_terms[:18]
	query_terms = ' '.join(base_terms)
	if not query_terms:
		query_terms = 'systems integration interoperability architecture planning'
	return f'{query_terms} integration interoperability architecture best practices risk analysis'


def create_prompt(project, systems, interfaces, integration_styles, lang='pt'):
	selected_lang = 'en' if lang == 'en' else 'pt'
	analysis_packet = _build_analysis_packet(project, systems, interfaces, integration_styles)
	retrieval_query = _build_retrieval_query(analysis_packet)

	if selected_lang == 'pt':
		system_prompt = """
Voce atua como um arquiteto senior de integracao e interoperabilidade especializado em analise e planejamento.

CONTEXTO DE PAPEL:
- O usuario cadastrou dados tecnicos reais sobre sistemas, interfaces e estilos de integracao.
- Sua tarefa e avaliar somente a arquitetura da integracao entre esses sistemas.
- Nunca descreva a SPPOI Tool como se ela fosse um dos sistemas analisados.

TECNICAS DE RACIOCINIO:
- Use role-playing context provisioning: responda como revisor tecnico de integracoes corporativas.
- Use chain-of-thought de forma privada: raciocine passo a passo internamente, mas nao exponha esse raciocinio.
- Use zero-shot para a estrutura global e few-shot para calibrar profundidade de riscos e recomendacoes com os exemplos fornecidos.

REGRAS CRITICAS:
- Analise apenas o cenario de integracao e interoperabilidade dos sistemas cadastrados.
- Nao invente componentes, controles, politicas ou falhas nao sustentadas pelas evidencias.
- Nao cite a ausencia de dimensoes que a ferramenta nao coleta por padrao como se isso fosse, por si so, o principal risco.
- Priorize, nesta ordem, contratos e semantica de dados, acoplamento entre sistemas e interfaces, transformacoes e sincronizacao do fluxo, governanca de versao e evolucao arquitetural.
- Politica corporativa de seguranca, politica corporativa de retries, DLQ, observabilidade formal, SLA e encryption at rest so podem virar foco de risco se aparecerem explicitamente nas evidencias.
- Quando houver autenticacao, protocolos, schemas, throttling, contratos de dados, garantias de entrega ou justificativas arquiteturais declaradas, priorize essas evidencias sem extrapolar para politicas corporativas nao informadas.
- Se a evidencia de seguranca se limitar a mecanismos de autenticacao declarados, trate isso apenas como contexto secundario e nunca como eixo dominante das secoes 3 e 4.
- O sumario executivo nao pode repetir a analise arquitetonica.
- Os riscos devem ser profundos, concretos e diferentes entre si.
- As recomendacoes devem ser profundas, concretas e diferentes entre si.
- O relatorio final deve estar integralmente em portugues do Brasil, exceto nomes proprios, produtos, protocolos e jargoes tecnicos.
- Nao deixe rotulos, frases completas ou campos inteiros em ingles.

EXEMPLO CURTO DE RISCO SUPERFICIAL A EVITAR:
- "Falta uma politica de seguranca robusta e consistente entre os sistemas."

EXEMPLO CURTO DE RISCO ADEQUADO:
- "A convivencia entre contratos de dados heterogeneos e transformacoes sem evidencia de governanca de schema cria risco de divergencia semantica entre produtor e consumidor, porque o mesmo atributo pode circular com significado, cardinalidade ou formato diferente em interfaces distintas, gerando integracao funcionalmente operante, mas semanticamente inconsistente."

EXEMPLO CURTO DE RECOMENDACAO ADEQUADA:
- "Padronizar contratos versionados por interface, com validacao obrigatoria no ponto de publicacao e criterios claros de compatibilidade regressiva, reduz ruptura silenciosa entre produtores e consumidores ao custo de maior governanca sobre evolucao de schemas, testes de contrato e pipeline de deploy."

FORMATO DE SAIDA:
- Retorne somente JSON valido, sem markdown, sem cercas de codigo e sem texto extra.
- Use exatamente esta estrutura:
{
  "sumario_executivo": "texto",
  "analise_arquitetonica": ["paragrafo 1", "paragrafo 2", "paragrafo 3", "paragrafo 4"],
  "riscos": [
    {
      "titulo": "nome objetivo do risco",
      "classe_de_falha": "texto",
      "elementos_afetados": "texto",
      "evidencia_do_cadastro": "texto",
      "decisao_arquitetural_ou_suposicao_implicita": "texto",
      "mecanismo_causal": "texto",
      "manifestacao_da_falha": "texto",
      "impacto_na_interoperabilidade": "texto",
      "consequencias_operacionais": "texto"
    },
    {
      "titulo": "nome objetivo do risco",
      "classe_de_falha": "texto",
      "elementos_afetados": "texto",
      "evidencia_do_cadastro": "texto",
      "decisao_arquitetural_ou_suposicao_implicita": "texto",
      "mecanismo_causal": "texto",
      "manifestacao_da_falha": "texto",
      "impacto_na_interoperabilidade": "texto",
      "consequencias_operacionais": "texto"
    }
  ],
  "melhorias_padronizacao": [
    {
      "titulo": "nome objetivo da recomendacao",
      "objetivo_arquitetural": "texto",
      "correcao_ou_padronizacao_necessaria": "texto",
      "principio_ou_padrao_aplicavel": "texto",
      "aplicacao_no_cenario": "texto",
      "fraqueza_arquitetural_mitigada": "texto",
      "impacto_esperado_na_interoperabilidade": "texto",
      "primeiro_passo_pratico": "texto",
      "trade_off_introduzido": "texto"
    },
    {
      "titulo": "nome objetivo da recomendacao",
      "objetivo_arquitetural": "texto",
      "correcao_ou_padronizacao_necessaria": "texto",
      "principio_ou_padrao_aplicavel": "texto",
      "aplicacao_no_cenario": "texto",
      "fraqueza_arquitetural_mitigada": "texto",
      "impacto_esperado_na_interoperabilidade": "texto",
      "primeiro_passo_pratico": "texto",
      "trade_off_introduzido": "texto"
    }
  ],
  "consideracoes_finais": "texto"
}
""".strip()

		user_prompt = f"""
OBJETIVO:
Gerar uma analise tecnica util para arquitetos e desenvolvedores de integracao, com foco em planejamento, interoperabilidade e riscos reais do fluxo cadastrado.

EVIDENCIAS PRIMARIAS:
{_packet_to_json(analysis_packet)}

INSTRUCOES DE PROFUNDIDADE:
- "sumario_executivo": no maximo 4 frases e sem repetir a secao analitica.
- "analise_arquitetonica": exatamente 4 paragrafos densos, cada um com foco diferente:
  1. topologia, acoplamento, coesao e semantica de comunicacao;
  2. contratos, schemas, versionamento, transformacoes e consistencia semantica;
  3. confiabilidade operacional, sincronizacao do fluxo, ordenacao, idempotencia quando materialmente inferivel, detectabilidade e propagacao de falhas;
  4. governanca de contratos, escalabilidade, evolucao futura e capacidade de padronizacao entre sistemas.
- "riscos": exatamente 2 riscos, cada um de classe diferente, com cadeia causal clara, evidencia concreta do cadastro e impacto operacional concreto.
- "melhorias_padronizacao": exatamente 2 recomendacoes, cada uma respondendo a uma fraqueza diferente, com acao aplicavel, impacto arquitetural real, primeiro passo pratico e trade-off.
- "consideracoes_finais": 1 paragrafo conclusivo, sem recontar a secao 2.

RESTRICOES ADICIONAIS:
- Nao trate a ausencia de politica corporativa de seguranca como risco central, porque essa dimensao nao e coletada diretamente pela ferramenta.
- Nao trate a ausencia de politica corporativa de retries como risco central, a menos que as evidencias indiquem fragilidade concreta do fluxo.
- Nas secoes 3 e 4, prefira riscos e melhorias ligados a contrato de dados, compatibilidade semantica, transformacoes, compartilhamento de banco, acoplamento, sincronizacao, entrega, versionamento e evolucao de interfaces.
- Nao use frases vagas. Cada campo das secoes 3 e 4 deve ter 1 ou 2 frases completas e tecnicas.
- Em "evidencia_do_cadastro", cite explicitamente sistemas, interfaces, estilos de integracao, protocolos, formatos, throttling, schemas, filas, tabelas ou justificativas arquiteturais realmente presentes nas evidencias.
- Em "mecanismo_causal", explique a cadeia tecnica entre a decisao arquitetural e o risco observado.
- Em "impacto_na_interoperabilidade", explique o efeito sobre compatibilidade semantica, acoplamento, sincronizacao, entrega ou evolucao do ecossistema.
- Em "aplicacao_no_cenario" e "primeiro_passo_pratico", descreva onde a recomendacao entra no fluxo cadastrado e qual seria a primeira acao concreta de adocao.
- As recomendacoes nao podem apenas reescrever os riscos em tom positivo; elas devem explicar o que padronizar, onde, por que e com qual efeito esperado.
- Use as referencias RAG apenas para reforcar boas praticas, nao para inventar o cenario.
""".strip()
	else:
		system_prompt = """
You are a senior integration and interoperability architect focused on analysis and planning.

Return only valid JSON with no markdown and no extra text.
Do not mention SPPOI Tool as an analyzed system.
Do not invent controls or risks unsupported by evidence.
Executive summary must not repeat the architectural analysis.
Architectural analysis must contain exactly 4 dense paragraphs.
Return exactly 2 distinct risks and 2 distinct recommendations.
""".strip()

		user_prompt = f"""
PRIMARY EVIDENCE:
{_packet_to_json(analysis_packet)}
""".strip()

	full_prompt = system_prompt + "\n\n" + user_prompt
	return system_prompt, user_prompt, full_prompt, retrieval_query, analysis_packet


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
		chunk_size=1200,
		chunk_overlap=150,
		length_function=len,
		add_start_index=True,
	)

	chunks = text_splitter.split_documents(documents)
	embeddings = get_embeddings_model()
	Chroma.from_documents(chunks, embedding=embeddings, persist_directory=CHROMA_PATH)


def get_rag_context(reference_query):
	db_file = os.path.join(CHROMA_PATH, 'chroma.sqlite3')
	embeddings = get_embeddings_model()

	if not os.path.exists(db_file):
		prepare_chroma_db()

	try:
		db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
		results = db.similarity_search_with_relevance_scores(reference_query, k=4)
	except Exception:
		if os.path.exists(CHROMA_PATH):
			shutil.rmtree(CHROMA_PATH, ignore_errors=True)
		prepare_chroma_db()
		db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
		results = db.similarity_search_with_relevance_scores(reference_query, k=4)

	relevant_docs = [(doc, score) for doc, score in results if score >= 0.22][:2]
	if not relevant_docs:
		return "Nenhuma referÃªncia adicional relevante recuperada."

	references = []
	for index, (doc, score) in enumerate(relevant_docs, start=1):
		source = os.path.basename(doc.metadata.get('source', f'reference_{index}'))
		snippet = _clean_text(doc.page_content, 900)
		references.append(f'[Ref {index} | {source} | score={score:.2f}] {snippet}')
	return "\n\n".join(references)


def _compose_model_input(user_prompt, rag_context, user_message):
	request_focus = _clean_text(user_message) or 'Analyze the registered integration scenario.'
	return f"""
[REQUEST FOCUS]
{request_focus}

[SCIENTIFIC REFERENCE NOTES - SECONDARY SOURCE]
{rag_context}

[PROJECT EVIDENCE AND OUTPUT CONTRACT - PRIMARY SOURCE]
{user_prompt}
""".strip()


def _extract_json_block(text):
	if not text:
		raise ValueError('Empty model response.')

	fenced_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
	if fenced_match:
		return fenced_match.group(1)

	start = text.find('{')
	end = text.rfind('}')
	if start == -1 or end == -1 or end <= start:
		raise ValueError('JSON block not found in model response.')
	return text[start:end + 1]


def _parse_json_response(text):
	json_block = _extract_json_block(text)
	return json.loads(json_block)


def _normalize_analysis_payload(payload):
	if not isinstance(payload, dict):
		raise ValueError('Analysis payload must be a JSON object.')

	summary = _clean_text(payload.get('sumario_executivo'))
	analysis_paragraphs = payload.get('analise_arquitetonica') or []
	risks = payload.get('riscos') or []
	improvements = payload.get('melhorias_padronizacao') or []
	final_considerations = _clean_text(payload.get('consideracoes_finais'))

	if not isinstance(analysis_paragraphs, list):
		analysis_paragraphs = [analysis_paragraphs]
	if not isinstance(risks, list):
		risks = [risks]
	if not isinstance(improvements, list):
		improvements = [improvements]

	normalized = {
		'sumario_executivo': summary,
		'analise_arquitetonica': [_clean_text(item) for item in analysis_paragraphs if _clean_text(item)],
		'riscos': [],
		'melhorias_padronizacao': [],
		'consideracoes_finais': final_considerations,
	}

	risk_key_aliases = {
		'titulo': 'titulo',
		'classe_de_falha': 'classe_de_falha',
		'elementos_afetados': 'elementos_afetados',
		'evidencia_do_cadastro': 'evidencia_do_cadastro',
		'decisao_arquitetural_ou_suposicao_implicita': 'decisao_arquitetural_ou_suposicao_implicita',
		'decisao_arquitetural_ou_supisicao_implicita': 'decisao_arquitetural_ou_suposicao_implicita',
		'mecanismo_causal': 'mecanismo_causal',
		'manifestacao_da_falha': 'manifestacao_da_falha',
		'impacto_na_interoperabilidade': 'impacto_na_interoperabilidade',
		'consequencias_operacionais': 'consequencias_operacionais',
	}
	for risk in risks[:2]:
		if not isinstance(risk, dict):
			continue
		item = {}
		for key, normalized_key in risk_key_aliases.items():
			value = _clean_text(risk.get(key))
			if value:
				item[normalized_key] = value
		if item:
			normalized['riscos'].append(item)

	improvement_key_aliases = {
		'titulo': 'titulo',
		'objetivo_arquitetural': 'objetivo_arquitetural',
		'correcao_ou_padronizacao_necessaria': 'correcao_ou_padronizacao_necessaria',
		'principio_ou_padrao_aplicavel': 'principio_ou_padrao_aplicavel',
		'onde_se_aplica': 'aplicacao_no_cenario',
		'aplicacao_no_cenario': 'aplicacao_no_cenario',
		'fraqueza_arquitetural_mitigada': 'fraqueza_arquitetural_mitigada',
		'impacto_esperado_na_interoperabilidade': 'impacto_esperado_na_interoperabilidade',
		'primeiro_passo_pratico': 'primeiro_passo_pratico',
		'trade_off_introduzido': 'trade_off_introduzido',
	}
	for improvement in improvements[:2]:
		if not isinstance(improvement, dict):
			continue
		item = {}
		for key, normalized_key in improvement_key_aliases.items():
			value = _clean_text(improvement.get(key))
			if value:
				item[normalized_key] = value
		if item:
			normalized['melhorias_padronizacao'].append(item)

	return normalized


RISK_REQUIRED_KEYS = (
	'titulo',
	'classe_de_falha',
	'elementos_afetados',
	'evidencia_do_cadastro',
	'decisao_arquitetural_ou_suposicao_implicita',
	'mecanismo_causal',
	'manifestacao_da_falha',
	'impacto_na_interoperabilidade',
	'consequencias_operacionais',
)

IMPROVEMENT_REQUIRED_KEYS = (
	'titulo',
	'objetivo_arquitetural',
	'correcao_ou_padronizacao_necessaria',
	'principio_ou_padrao_aplicavel',
	'aplicacao_no_cenario',
	'fraqueza_arquitetural_mitigada',
	'impacto_esperado_na_interoperabilidade',
	'primeiro_passo_pratico',
	'trade_off_introduzido',
)


def _item_has_required_depth(item, required_keys, min_chars):
	if not isinstance(item, dict):
		return False
	for key in required_keys:
		if not _clean_text(item.get(key)):
			return False
	total_chars = sum(len(_clean_text(item.get(key))) for key in required_keys)
	return total_chars >= min_chars


def _sections_34_need_enrichment(payload):
	risks = payload.get('riscos', [])
	improvements = payload.get('melhorias_padronizacao', [])
	if len(risks) != 2 or len(improvements) != 2:
		return True
	if any(not _item_has_required_depth(risk, RISK_REQUIRED_KEYS, 520) for risk in risks):
		return True
	if any(not _item_has_required_depth(improvement, IMPROVEMENT_REQUIRED_KEYS, 560) for improvement in improvements):
		return True
	risk_text = ' '.join(' '.join(_clean_text(risk.get(key)) for key in RISK_REQUIRED_KEYS) for risk in risks)
	improvement_text = ' '.join(
		' '.join(_clean_text(improvement.get(key)) for key in IMPROVEMENT_REQUIRED_KEYS)
		for improvement in improvements
	)
	return _token_overlap_ratio(risk_text, improvement_text) > 0.78


def _render_analysis_markdown(payload, lang='pt'):
	if lang == 'pt':
		lines = [
			'## 1. SumÃ¡rio',
			payload.get('sumario_executivo', ''),
			'',
			'## 2. AnÃ¡lise ArquitetÃ´nica',
		]
		for paragraph in payload.get('analise_arquitetonica', []):
			lines.extend([paragraph, ''])

		lines.append('## 3. Riscos CrÃ­ticos de IntegraÃ§Ã£o e Interoperabilidade')
		for index, risk in enumerate(payload.get('riscos', []), start=1):
			lines.extend([
				f'### Risco {index}: {risk.get("titulo", "")}'.rstrip(': '),
				f'- Classe de falha: {risk.get("classe_de_falha", "")}',
				f'- Elementos afetados: {risk.get("elementos_afetados", "")}',
				f'- EvidÃªncia do cadastro: {risk.get("evidencia_do_cadastro", "")}',
				f'- DecisÃ£o arquitetural ou suposiÃ§Ã£o implÃ­cita: {risk.get("decisao_arquitetural_ou_suposicao_implicita", "")}',
				f'- Mecanismo causal: {risk.get("mecanismo_causal", "")}',
				f'- ManifestaÃ§Ã£o da falha: {risk.get("manifestacao_da_falha", "")}',
				f'- Impacto na interoperabilidade: {risk.get("impacto_na_interoperabilidade", "")}',
				f'- ConsequÃªncias operacionais: {risk.get("consequencias_operacionais", "")}',
				'',
			])

		lines.append('## 4. Melhorias e PadronizaÃ§Ã£o')
		for index, improvement in enumerate(payload.get('melhorias_padronizacao', []), start=1):
			lines.extend([
				f'### RecomendaÃ§Ã£o {index}: {improvement.get("titulo", "")}'.rstrip(': '),
				f'- Objetivo arquitetural: {improvement.get("objetivo_arquitetural", "")}',
				f'- CorreÃ§Ã£o ou padronizaÃ§Ã£o necessÃ¡ria: {improvement.get("correcao_ou_padronizacao_necessaria", "")}',
				f'- PrincÃ­pio ou padrÃ£o de integraÃ§Ã£o aplicÃ¡vel: {improvement.get("principio_ou_padrao_aplicavel", "")}',
				f'- AplicaÃ§Ã£o no cenÃ¡rio: {improvement.get("aplicacao_no_cenario", "")}',
				f'- Fraqueza arquitetural mitigada: {improvement.get("fraqueza_arquitetural_mitigada", "")}',
				f'- Impacto esperado na interoperabilidade: {improvement.get("impacto_esperado_na_interoperabilidade", "")}',
				f'- Primeiro passo prÃ¡tico: {improvement.get("primeiro_passo_pratico", "")}',
				f'- Trade-off introduzido: {improvement.get("trade_off_introduzido", "")}',
				'',
			])

		lines.extend([
			'## 5. ConsideraÃ§Ãµes Finais',
			payload.get('consideracoes_finais', ''),
		])
		return '\n'.join(lines).strip()

	lines = [
		'## 1. Executive Summary',
		payload.get('sumario_executivo', ''),
		'',
		'## 2. Architectural Analysis',
	]
	for paragraph in payload.get('analise_arquitetonica', []):
		lines.extend([paragraph, ''])

	lines.append('## 3. Critical Integration and Interoperability Risks')
	for index, risk in enumerate(payload.get('riscos', []), start=1):
		lines.extend([
			f'### Risk {index}: {risk.get("titulo", "")}'.rstrip(': '),
			f'- Failure class: {risk.get("classe_de_falha", "")}',
			f'- Affected elements: {risk.get("elementos_afetados", "")}',
			f'- Evidence from registration: {risk.get("evidencia_do_cadastro", "")}',
			f'- Architectural decision or implicit assumption: {risk.get("decisao_arquitetural_ou_suposicao_implicita", "")}',
			f'- Causal mechanism: {risk.get("mecanismo_causal", "")}',
			f'- Failure manifestation: {risk.get("manifestacao_da_falha", "")}',
			f'- Interoperability impact: {risk.get("impacto_na_interoperabilidade", "")}',
			f'- Operational consequences: {risk.get("consequencias_operacionais", "")}',
			'',
		])

	lines.append('## 4. Improvements and Standardization')
	for index, improvement in enumerate(payload.get('melhorias_padronizacao', []), start=1):
		lines.extend([
			f'### Recommendation {index}: {improvement.get("titulo", "")}'.rstrip(': '),
			f'- Architectural objective: {improvement.get("objetivo_arquitetural", "")}',
			f'- Required correction or standardization: {improvement.get("correcao_ou_padronizacao_necessaria", "")}',
			f'- Applicable integration principle or pattern: {improvement.get("principio_ou_padrao_aplicavel", "")}',
			f'- Application in this scenario: {improvement.get("aplicacao_no_cenario", "")}',
			f'- Architectural weakness mitigated: {improvement.get("fraqueza_arquitetural_mitigada", "")}',
			f'- Expected interoperability impact: {improvement.get("impacto_esperado_na_interoperabilidade", "")}',
			f'- First practical step: {improvement.get("primeiro_passo_pratico", "")}',
			f'- Trade-off introduced: {improvement.get("trade_off_introduzido", "")}',
			'',
		])

	lines.extend([
		'## 5. Final Considerations',
		payload.get('consideracoes_finais', ''),
	])
	return '\n'.join(lines).strip()


def _analysis_payload_is_complete(payload):
	if not payload.get('sumario_executivo') or not payload.get('consideracoes_finais'):
		return False
	if len(payload.get('analise_arquitetonica', [])) != 4:
		return False
	return not _sections_34_need_enrichment(payload)


def _request_model_text(client, system_prompt, user_prompt, temperature=None, top_p=None, max_tokens=None):
	response = client.chat.completions.create(
		model=HF_CHAT_MODEL,
		messages=[
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": user_prompt},
		],
		temperature=HF_CHAT_TEMPERATURE if temperature is None else temperature,
		top_p=HF_CHAT_TOP_P if top_p is None else top_p,
		max_tokens=HF_CHAT_MAX_TOKENS if max_tokens is None else max_tokens,
		seed=42,
		timeout=HF_CHAT_TIMEOUT,
	)
	if not response.choices:
		raise ValueError('Empty model response.')
	return (response.choices[0].message.content or '').strip()


def _repair_json_response(client, raw_text, analysis_packet, lang='pt'):
	if lang == 'pt':
		repair_system_prompt = "Voce corrige saidas de modelo para JSON valido em portugues do Brasil."
		repair_user_prompt = f"""
Converta a resposta abaixo em JSON valido, sem markdown e sem texto extra.

REGRAS:
- Nao adicione fatos novos.
- Preserve apenas informacoes coerentes com as evidencias.
- Use exatamente as chaves esperadas:
  sumario_executivo
  analise_arquitetonica
  riscos
  melhorias_padronizacao
  consideracoes_finais
- Em cada risco, preserve e preencha:
  titulo
  classe_de_falha
  elementos_afetados
  evidencia_do_cadastro
  decisao_arquitetural_ou_suposicao_implicita
  mecanismo_causal
  manifestacao_da_falha
  impacto_na_interoperabilidade
  consequencias_operacionais
- Em cada recomendacao, preserve e preencha:
  titulo
  objetivo_arquitetural
  correcao_ou_padronizacao_necessaria
  principio_ou_padrao_aplicavel
  aplicacao_no_cenario
  fraqueza_arquitetural_mitigada
  impacto_esperado_na_interoperabilidade
  primeiro_passo_pratico
  trade_off_introduzido
- Use 4 paragrafos em analise_arquitetonica, 2 riscos e 2 recomendacoes.
- Cada campo das secoes 3 e 4 deve ter 1 ou 2 frases tecnicas completas, sem superficialidade.
- Nao escreva frases completas em ingles.
- Nao mencione SPPOI Tool no conteudo do relatorio.
- Nao transforme ausencia de politica corporativa de seguranca em risco central se isso nao estiver nas evidencias.
- Nao transforme autenticacao declarada, por si so, em politica de seguranca corporativa.
- Se houver duvida entre enfatizar seguranca ou interoperabilidade, priorize interoperabilidade, contratos, acoplamento, transformacoes e evolucao de interfaces.

EVIDENCIAS RESUMIDAS:
{_packet_to_json({
	'project': analysis_packet.get('project', {}),
	'explicit_evidence_highlights': analysis_packet.get('explicit_evidence_highlights', {}),
})}

RESPOSTA ORIGINAL:
{raw_text}
""".strip()
	else:
		repair_system_prompt = "You repair model outputs into valid JSON."
		repair_user_prompt = f"Convert the following output into valid JSON only:\n\n{raw_text}"

	repaired_text = _request_model_text(
		client,
		repair_system_prompt,
		repair_user_prompt,
		temperature=0.05,
		top_p=0.4,
	)
	return _parse_json_response(repaired_text)


def _enrich_risks_and_improvements(client, analysis_packet, payload, lang='pt'):
	if lang == 'pt':
		enrichment_system_prompt = "Voce aprofunda riscos e recomendacoes de integracao em JSON valido, sem inventar fatos."
		enrichment_user_prompt = f"""
Reescreva apenas as secoes "riscos" e "melhorias_padronizacao" do JSON abaixo, mantendo total fidelidade as evidencias cadastradas.

REGRAS:
- Nao altere o sumario, a analise arquitetonica nem as consideracoes finais.
- Retorne somente JSON valido com exatamente duas chaves de topo:
  riscos
  melhorias_padronizacao
- Preserve exatamente 2 riscos e 2 recomendacoes.
- Cada risco deve conter e aprofundar:
  titulo
  classe_de_falha
  elementos_afetados
  evidencia_do_cadastro
  decisao_arquitetural_ou_suposicao_implicita
  mecanismo_causal
  manifestacao_da_falha
  impacto_na_interoperabilidade
  consequencias_operacionais
- Cada recomendacao deve conter e aprofundar:
  titulo
  objetivo_arquitetural
  correcao_ou_padronizacao_necessaria
  principio_ou_padrao_aplicavel
  aplicacao_no_cenario
  fraqueza_arquitetural_mitigada
  impacto_esperado_na_interoperabilidade
  primeiro_passo_pratico
  trade_off_introduzido
- Cada campo das secoes 3 e 4 deve ter 1 ou 2 frases completas, tecnicas e especificas.
- Em evidencia_do_cadastro, mencione explicitamente sistemas, interfaces, estilos, contratos, formatos, filas, tabelas, protocolos, throttling ou justificativas realmente presentes nas evidencias.
- Em mecanismo_causal, explique a cadeia tecnica que conecta a decisao arquitetural ao problema observado.
- Em aplicacao_no_cenario e primeiro_passo_pratico, descreva onde agir no cenario cadastrado e qual seria a primeira medida concreta.
- As recomendacoes nao podem repetir os riscos em tom positivo; devem prescrever mudanca arquitetural aplicavel.
- Nao trate ausencia de politica corporativa de seguranca como eixo central.
- Se houver disputa de foco, priorize interoperabilidade, semantica de dados, acoplamento, sincronizacao, entrega, versionamento e evolucao de interfaces.

EVIDENCIAS:
{_packet_to_json({
	'project': analysis_packet.get('project', {}),
	'coverage_snapshot': analysis_packet.get('coverage_snapshot', {}),
	'explicit_evidence_highlights': analysis_packet.get('explicit_evidence_highlights', {}),
	'systems': analysis_packet.get('systems', []),
	'interfaces': analysis_packet.get('interfaces', []),
	'integration_styles': analysis_packet.get('integration_styles', []),
})}

JSON ATUAL:
{_packet_to_json(payload)}
""".strip()
	else:
		enrichment_system_prompt = "You deepen integration risks and recommendations into valid JSON without inventing facts."
		enrichment_user_prompt = f"Rewrite only the risks and recommendations in valid JSON using the provided evidence.\n\n{_packet_to_json(payload)}"

	try:
		enriched_text = _request_model_text(
			client,
			enrichment_system_prompt,
			enrichment_user_prompt,
			temperature=0.08,
			top_p=0.45,
		)
		enriched_sections = _parse_json_response(enriched_text)
		merged_payload = dict(payload)
		merged_payload['riscos'] = enriched_sections.get('riscos', payload.get('riscos', []))
		merged_payload['melhorias_padronizacao'] = enriched_sections.get('melhorias_padronizacao', payload.get('melhorias_padronizacao', []))
		return _normalize_analysis_payload(merged_payload)
	except Exception:
		return payload


def _split_paragraphs(text):
	return [item.strip() for item in re.split(r'\n\s*\n+', text or '') if item.strip()]


def _extract_numbered_sections(text):
	pattern = re.compile(r'(?m)^##\s*(\d+)\.\s*.*$')
	matches = list(pattern.finditer(text or ''))
	sections = {}
	for index, match in enumerate(matches):
		start = match.end()
		end = matches[index + 1].start() if index + 1 < len(matches) else len(text or '')
		sections[match.group(1)] = (text or '')[start:end].strip()
	return sections


def _extract_subsections(section_text):
	pattern = re.compile(r'(?m)^###\s+.*$')
	matches = list(pattern.finditer(section_text or ''))
	blocks = []
	for index, match in enumerate(matches):
		start = match.end()
		end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text or '')
		blocks.append((match.group(0).strip(), (section_text or '')[start:end].strip()))
	return blocks


def _normalize_for_comparison(text):
	normalized = unicodedata.normalize('NFKD', (text or '').strip().lower())
	normalized = ''.join(char for char in normalized if not unicodedata.combining(char))
	return re.sub(r'\s+', ' ', normalized)


def _token_overlap_ratio(text_a, text_b):
	tokens_a = set(re.findall(r'[a-z0-9]{5,}', _normalize_for_comparison(text_a)))
	tokens_b = set(re.findall(r'[a-z0-9]{5,}', _normalize_for_comparison(text_b)))
	if not tokens_a or not tokens_b:
		return 0.0
	return len(tokens_a & tokens_b) / float(min(len(tokens_a), len(tokens_b)))


def _has_english_template_markers(text):
	patterns = [
		r'(?im)^###\s*risk\s+\d+',
		r'(?im)^###\s*recommendation\s+\d+',
		r'(?im)^-\s*affected elements:',
		r'(?im)^-\s*architectural decision or implicit assumption:',
		r'(?im)^-\s*failure manifestation:',
		r'(?im)^-\s*operational consequences:',
		r'(?im)^-\s*required correction or standardization:',
		r'(?im)^-\s*applicable integration principle or pattern:',
		r'(?im)^-\s*where it applies:',
		r'(?im)^-\s*architectural weakness removed:',
		r'(?im)^-\s*trade-off introduced:',
	]
	return any(re.search(pattern, text or '') for pattern in patterns)


def _localize_pt_report_labels(text):
	if not text:
		return text

	replacements = [
		(r'(?im)^##\s*1\.\s*Sumario Executivo\s*$', '## 1. SumÃ¡rio'),
		(r'(?im)^##\s*2\.\s*Analise Arquitetonica\s*$', '## 2. AnÃ¡lise ArquitetÃ´nica'),
		(r'(?im)^##\s*3\.\s*Riscos Criticos de Integracao e Interoperabilidade\s*$', '## 3. Riscos CrÃ­ticos de IntegraÃ§Ã£o e Interoperabilidade'),
		(r'(?im)^##\s*4\.\s*Melhorias e Padronizacao\s*$', '## 4. Melhorias e PadronizaÃ§Ã£o'),
		(r'(?im)^##\s*5\.\s*Consideracoes Finais\s*$', '## 5. ConsideraÃ§Ãµes Finais'),
		(r'(?im)^###\s*Risk\s+(\d+):\s*(.+?)\s*$', r'### Risco \1: \2'),
		(r'(?im)^##\s*1\.\s*Executive Summary\s*$', '## 1. SumÃ¡rio Executivo'),
		(r'(?im)^##\s*2\.\s*Architectural Analysis\s*$', '## 2. AnÃ¡lise ArquitetÃ´nica'),
		(r'(?im)^##\s*3\.\s*Critical Integration and Interoperability Risks\s*$', '## 3. Riscos CrÃ­ticos de IntegraÃ§Ã£o e Interoperabilidade'),
		(r'(?im)^##\s*4\.\s*Improvements and Standardization\s*$', '## 4. Melhorias e PadronizaÃ§Ã£o'),
		(r'(?im)^##\s*5\.\s*Final Considerations\s*$', '## 5. ConsideraÃ§Ãµes Finais'),
		(r'(?im)^###\s*Recommendation\s+(\d+):\s*(.+?)\s*$', r'### RecomendaÃ§Ã£o \1: \2'),
		(r'(?im)^###\s*Recomendacao\s+(\d+):\s*(.+?)\s*$', r'### RecomendaÃ§Ã£o \1: \2'),
		(r'(?im)^###\s*Risk\s+(\d+)\s*$', r'### Risco \1'),
		(r'(?im)^###\s*Recommendation\s+(\d+)\s*$', r'### RecomendaÃ§Ã£o \1'),
		(r'(?im)^###\s*Recomendacao\s+(\d+)\s*$', r'### RecomendaÃ§Ã£o \1'),
		(r'(?im)^-\s*Affected elements:', '- Elementos afetados:'),
		(r'(?im)^-\s*Evidence from registration:', '- EvidÃªncia do cadastro:'),
		(r'(?im)^-\s*Architectural decision or implicit assumption:', '- DecisÃ£o arquitetural ou suposiÃ§Ã£o implÃ­cita:'),
		(r'(?im)^-\s*Causal mechanism:', '- Mecanismo causal:'),
		(r'(?im)^-\s*Failure manifestation:', '- ManifestaÃ§Ã£o da falha:'),
		(r'(?im)^-\s*Interoperability impact:', '- Impacto na interoperabilidade:'),
		(r'(?im)^-\s*Operational consequences:', '- ConsequÃªncias operacionais:'),
		(r'(?im)^-\s*Architectural objective:', '- Objetivo arquitetural:'),
		(r'(?im)^-\s*Required correction or standardization:', '- CorreÃ§Ã£o ou padronizaÃ§Ã£o necessÃ¡ria:'),
		(r'(?im)^-\s*Applicable integration principle or pattern:', '- PrincÃ­pio ou padrÃ£o de integraÃ§Ã£o aplicÃ¡vel:'),
		(r'(?im)^-\s*Where it applies:', '- AplicaÃ§Ã£o no cenÃ¡rio:'),
		(r'(?im)^-\s*Application in this scenario:', '- AplicaÃ§Ã£o no cenÃ¡rio:'),
		(r'(?im)^-\s*Architectural weakness removed:', '- Fraqueza arquitetural mitigada:'),
		(r'(?im)^-\s*Expected interoperability impact:', '- Impacto esperado na interoperabilidade:'),
		(r'(?im)^-\s*First practical step:', '- Primeiro passo prÃ¡tico:'),
		(r'(?im)^-\s*Trade-off introduced:', '- Trade-off introduzido:'),
		(r'(?im)^-\s*Evidencia do cadastro:', '- EvidÃªncia do cadastro:'),
		(r'(?im)^-\s*Decisao arquitetural ou suposicao implicita:', '- DecisÃ£o arquitetural ou suposiÃ§Ã£o implÃ­cita:'),
		(r'(?im)^-\s*Mecanismo causal:', '- Mecanismo causal:'),
		(r'(?im)^-\s*Manifestacao da falha:', '- ManifestaÃ§Ã£o da falha:'),
		(r'(?im)^-\s*Impacto na interoperabilidade:', '- Impacto na interoperabilidade:'),
		(r'(?im)^-\s*Consequencias operacionais:', '- ConsequÃªncias operacionais:'),
		(r'(?im)^-\s*Objetivo arquitetural:', '- Objetivo arquitetural:'),
		(r'(?im)^-\s*Correcao ou padronizacao necessaria:', '- CorreÃ§Ã£o ou padronizaÃ§Ã£o necessÃ¡ria:'),
		(r'(?im)^-\s*Principio ou padrao de integracao aplicavel:', '- PrincÃ­pio ou padrÃ£o de integraÃ§Ã£o aplicÃ¡vel:'),
		(r'(?im)^-\s*Aplicacao no cenario:', '- AplicaÃ§Ã£o no cenÃ¡rio:'),
		(r'(?im)^-\s*Impacto esperado na interoperabilidade:', '- Impacto esperado na interoperabilidade:'),
		(r'(?im)^-\s*Primeiro passo pratico:', '- Primeiro passo prÃ¡tico:'),
	]
	for pattern, replacement in replacements:
		text = re.sub(pattern, replacement, text)
	return text


def _analysis_needs_revision(text):
	if not _clean_text(text):
		return True

	sections = _extract_numbered_sections(text)
	if len(sections) < 5:
		return True

	paragraphs = _split_paragraphs(text)
	normalized_paragraphs = [_normalize_for_comparison(item) for item in paragraphs]
	if len(normalized_paragraphs) != len(set(normalized_paragraphs)):
		return True

	if _has_english_template_markers(text):
		return True

	if 'sppoi tool' in _normalize_for_comparison(text):
		return True

	summary_text = sections.get('1', '')
	analysis_text = sections.get('2', '')
	risks_text = sections.get('3', '')
	improvements_text = sections.get('4', '')

	if len(_split_paragraphs(analysis_text)) < 4:
		return True

	if _token_overlap_ratio(summary_text, analysis_text) > 0.72:
		return True

	risk_blocks = _extract_subsections(risks_text)
	if len(risk_blocks) < 2:
		return True
	if any(len(_clean_text(block_text)) < 420 for _, block_text in risk_blocks):
		return True

	recommendation_blocks = _extract_subsections(improvements_text)
	if len(recommendation_blocks) < 2:
		return True
	if any(len(_clean_text(block_text)) < 460 for _, block_text in recommendation_blocks):
		return True
	for (_, risk_block), (_, recommendation_block) in zip(risk_blocks, recommendation_blocks):
		if _token_overlap_ratio(risk_block, recommendation_block) > 0.8:
			return True

	normalized_text = _normalize_for_comparison(text)
	repetition_markers = [
		'falta de detalhes',
		'gestao de erros',
		'seguranca',
		'sppoi tool',
		'insufficient information',
		'more details are needed',
	]
	for marker in repetition_markers:
		if normalized_text.count(marker) > 1:
			return True

	security_overfocus_markers = [
		'politica de seguranca',
		'padronizacao de seguranca',
		'seguranca robusta e consistente',
	]
	if any(marker in normalized_text for marker in security_overfocus_markers):
		return True

	return False


def _revise_analysis_output(client, draft_text, analysis_packet, lang='pt'):
	if not _clean_text(draft_text):
		return draft_text

	if lang == 'pt':
		review_prompt = f"""
Reescreva o relatorio abaixo da SPPOI Tool sem adicionar fatos novos.

OBJETIVO EDITORIAL:
- Eliminar repeticao entre a secao 1 e a secao 2.
- Garantir profundidade tecnica real nas secoes 3 e 4.
- Corrigir qualquer rotulo, frase ou trecho inteiro em ingles, preservando apenas nomes proprios, protocolos, padroes e jargoes tecnicos.
- Manter fidelidade total as evidencias cadastradas.

REGRAS OBRIGATORIAS:
- Use exatamente 5 secoes.
- A secao 1 deve ser mais sintetica que a secao 2 e nao pode reutilizar frases da secao 2.
- A secao 2 deve ter exatamente 4 paragrafos densos.
- A secao 3 deve conter exatamente 2 riscos de classes diferentes.
- A secao 4 deve conter exatamente 2 recomendacoes de classes diferentes.
- Mantenha a estrutura em subtitulos "### Risco X" e "### Recomendacao X" com bullets tecnicos abaixo de cada item.
- Cada campo das secoes 3 e 4 deve ser uma frase completa, tecnica e concreta, evitando respostas telegrÃ¡ficas.
- Em cada risco, aprofunde evidencia do cadastro, mecanismo causal, impacto na interoperabilidade e consequencias operacionais.
- Em cada recomendacao, aprofunde objetivo arquitetural, aplicacao no cenario, impacto esperado e primeiro passo pratico.
- Nao deixe rotulos em ingles como Risk, Recommendation, Affected elements, Required correction ou equivalentes.
- Nao mencione SPPOI Tool como elemento da arquitetura analisada.
- Nao transforme ausencia de politica corporativa de seguranca em risco central quando isso nao estiver nas evidencias.
- Nao transforme autenticacao declarada, por si so, em politica de seguranca corporativa.
- Nao repita a mesma fragilidade como justificativa dominante em todas as secoes.
- Quando houver disputa de foco, prefira aprofundar contrato de dados, compatibilidade semantica, acoplamento, transformacoes, sincronizacao, versionamento e evolucao das interfaces.
- Nao invente controles, tecnologias ou detalhes de implementacao.

EVIDENCIAS RESUMIDAS:
{_packet_to_json({
	'project': analysis_packet.get('project', {}),
	'coverage_snapshot': analysis_packet.get('coverage_snapshot', {}),
	'explicit_evidence_highlights': analysis_packet.get('explicit_evidence_highlights', {}),
})}

RASCUNHO:
{draft_text}
""".strip()
	else:
		review_prompt = f"""
Rewrite the draft report below for SPPOI Tool without adding new facts.

EDITORIAL GOAL:
- Remove repetition between sections 1 and 2.
- Ensure section 2 contains exactly 4 dense paragraphs.
- Deepen sections 3 and 4 while keeping them evidence-based.

MANDATORY RULES:
- Keep exactly 5 sections.
- Keep exactly 2 risks and 2 recommendations.
- Do not reintroduce the same caveat in multiple sections.
- Do not invent controls, products, or implementation details.

EVIDENCE SNAPSHOT:
{_packet_to_json({
	'project': analysis_packet.get('project', {}),
	'coverage_snapshot': analysis_packet.get('coverage_snapshot', {}),
	'explicit_evidence_highlights': analysis_packet.get('explicit_evidence_highlights', {}),
})}

DRAFT REPORT:
{draft_text}
""".strip()

	try:
		review_system_message = (
			"Voce revisa relatorios tecnicos estruturados em portugues do Brasil."
			if lang == 'pt'
			else "You revise structured technical reports."
		)
		response = client.chat.completions.create(
			model=HF_CHAT_MODEL,
			messages=[
				{"role": "system", "content": review_system_message},
				{"role": "user", "content": review_prompt},
			],
			temperature=0.05,
			top_p=0.5,
			max_tokens=HF_CHAT_MAX_TOKENS,
			seed=42,
			timeout=HF_CHAT_TIMEOUT,
		)
	except Exception:
		return draft_text

	if not response.choices:
		return draft_text

	revised_text = (response.choices[0].message.content or '').strip()
	if lang == 'pt':
		revised_text = _localize_pt_report_labels(revised_text)
	return revised_text or draft_text


def _yield_text_chunks(text, chunk_size=160):
	for start in range(0, len(text), chunk_size):
		yield text[start:start + chunk_size]


def _chat_stream_for_project(request, projeto):
	systems = list(Sistema.objects.filter(projeto=projeto))
	interfaces = list(Interface.objects.filter(projeto=projeto).select_related('sistema'))
	integration_styles = list(
		EstiloIntegracao.objects.filter(projeto=projeto)
		.select_related('sistema_origem', 'sistema_destino')
		.prefetch_related('interfaces_usadas')
	)

	if len(systems) < 2 or len(interfaces) < 1 or len(integration_styles) < 1:
		return JsonResponse({'error': 'Preencha pelo menos 2 sistemas, 1 interface e 1 integracao antes da consulta.'}, status=400)

	if not settings.HF_API_TOKEN:
		return JsonResponse({'error': 'HF_API_TOKEN nao configurado no ambiente.'}, status=400)

	data = json.loads(request.body.decode('utf-8'))
	lang = data.get('lang', 'pt')
	user_message = data.get('message', '').strip()
	if not user_message:
		user_message = 'Analisar integracao com base nos dados fornecidos.'

	system_prompt, user_prompt, full_prompt, retrieval_query, analysis_packet = create_prompt(
		projeto,
		systems,
		interfaces,
		integration_styles,
		lang=lang,
	)

	client = OpenAI(
		base_url="https://router.huggingface.co/v1",
		api_key=settings.HF_API_TOKEN,
	)

	def event_stream():
		analysis_start = time.time()
		ChatMessage.objects.create(projeto=projeto, role='user', content=user_message)
		yield f"event: prompt\ndata: {json.dumps(full_prompt)}\n\n"
		yield f"event: status\ndata: {json.dumps('Preparando contexto RAG...')}\n\n"

		try:
			rag_context = get_rag_context(retrieval_query)
		except Exception:
			rag_context = "Nenhuma referÃªncia adicional relevante recuperada."

		model_input = _compose_model_input(user_prompt, rag_context, user_message)
		revision_applied = False
		structured_generation_retried = False
		assistant_content = ""

		try:
			yield f"event: status\ndata: {json.dumps('Estruturando evidÃªncias tÃ©cnicas...')}\n\n"
			yield f"event: status\ndata: {json.dumps('Gerando anÃ¡lise arquitetural...')}\n\n"
			raw_response = _request_model_text(client, system_prompt, model_input)

			try:
				analysis_payload = _normalize_analysis_payload(_parse_json_response(raw_response))
			except Exception:
				structured_generation_retried = True
				yield f"event: status\ndata: {json.dumps('Corrigindo estrutura da resposta...')}\n\n"
				analysis_payload = _normalize_analysis_payload(
					_repair_json_response(client, raw_response, analysis_packet, lang=lang)
				)

			if not _analysis_payload_is_complete(analysis_payload):
				structured_generation_retried = True
				yield f"event: status\ndata: {json.dumps('ReforÃ§ando profundidade analÃ­tica...')}\n\n"
				analysis_payload = _normalize_analysis_payload(
					_repair_json_response(client, _packet_to_json(analysis_payload), analysis_packet, lang=lang)
				)

			if _sections_34_need_enrichment(analysis_payload):
				structured_generation_retried = True
				yield f"event: status\ndata: {json.dumps('Aprofundando riscos e melhorias...')}\n\n"
				analysis_payload = _enrich_risks_and_improvements(client, analysis_packet, analysis_payload, lang=lang)

			assistant_content = _render_analysis_markdown(analysis_payload, lang=lang)
			if lang == 'pt':
				assistant_content = _localize_pt_report_labels(assistant_content)

			should_review = _analysis_needs_revision(assistant_content)
			if should_review:
				yield f"event: status\ndata: {json.dumps('Revisando consistÃªncia e removendo repetiÃ§Ãµes...')}\n\n"
				assistant_content = _revise_analysis_output(client, assistant_content, analysis_packet, lang=lang)
				if lang == 'pt':
					assistant_content = _localize_pt_report_labels(assistant_content)
				revision_applied = True

			for chunk in _yield_text_chunks(assistant_content):
				yield f"event: token\ndata: {json.dumps(chunk)}\n\n"

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
				'revision_applied': revision_applied,
				'structured_generation_retried': structured_generation_retried,
				'ip': _get_client_ip(request),
				'user_agent': request.META.get('HTTP_USER_AGENT'),
				'referer': request.META.get('HTTP_REFERER'),
			}
			analysis_logger.info(json.dumps(analysis_payload, ensure_ascii=False))

			yield "event: done\ndata: {}\n\n"
		except Exception as e:
			duration_ms = int((time.time() - analysis_start) * 1000)
			analysis_logger = logging.getLogger('chat.analysis')
			analysis_payload = {
				'event': 'chat_analysis_error',
				'project_id': projeto.id,
				'project_name': projeto.nome,
				'session_key': request.session.session_key,
				'lang': lang,
				'status_code': 500,
				'duration_ms': duration_ms,
				'response_chars': len(assistant_content),
				'error_type': type(e).__name__,
				'error_message': str(e),
				'ip': _get_client_ip(request),
				'user_agent': request.META.get('HTTP_USER_AGENT'),
				'referer': request.META.get('HTTP_REFERER'),
			}
			analysis_logger.exception(json.dumps(analysis_payload, ensure_ascii=False))
			error_message = str(e) or 'Connection error.'
			yield f"event: error\ndata: {json.dumps(error_message)}\n\n"

	response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
	response['Cache-Control'] = 'no-cache'
	response['X-Accel-Buffering'] = 'no'
	return response


@require_http_methods(["POST"])
@require_captcha
def chat_stream(request, project_id):
	session_key = ensure_session_key(request)
	projeto = _get_scoped_project_or_404(project_id, session_key)
	return _chat_stream_for_project(request, projeto)


@require_http_methods(["POST"])
@require_captcha
def chat_stream_current(request):
	session_key = ensure_session_key(request)
	projects_qs = _project_scope_qs(session_key).order_by('-criado_em')
	project_id = request.session.get('current_project_id')
	projeto = None
	if project_id:
		projeto = projects_qs.filter(pk=project_id).first()
	if not projeto:
		projeto = projects_qs.first()
	if not projeto:
		return JsonResponse({'error': 'Conversa nÃ£o encontrada.'}, status=404)
	request.session['current_project_id'] = projeto.id
	return _chat_stream_for_project(request, projeto)
