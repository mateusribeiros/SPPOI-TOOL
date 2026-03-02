from django.db import models


class Projeto(models.Model):
	nome = models.CharField(max_length=100, default="Projeto Temporário")
	criado_em = models.DateTimeField(auto_now_add=True)
	session_key = models.CharField(max_length=100, null=False, blank=False, db_index=True)

	def __str__(self):
		return f"Projeto {self.nome} - {self.session_key}"


class Sistema(models.Model):
	projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name='sistemas')
	system_identifier = models.CharField(max_length=50, blank=True)
	nome = models.CharField(max_length=100)
	tipo = models.CharField(max_length=50)
	tipo_outro = models.CharField(max_length=80, blank=True)
	descricao = models.TextField(blank=True)

	integration_role = models.CharField(max_length=20, blank=True)
	primary_function_in_flow = models.CharField(max_length=120, blank=True)

	protocolos_suportados = models.CharField(max_length=200, blank=True)
	protocolos_suportados_outro = models.CharField(max_length=120, blank=True)
	capacidades_dados = models.CharField(max_length=200, blank=True)
	capacidades_dados_outro = models.CharField(max_length=120, blank=True)
	requisitos_autenticacao = models.CharField(max_length=200, blank=True)
	requisitos_autenticacao_outro = models.CharField(max_length=120, blank=True)

	versao = models.CharField(max_length=20, blank=True)
	technical_contact = models.CharField(max_length=120, blank=True)
	architectural_notes = models.TextField(blank=True)

	email_responsavel = models.CharField(max_length=100, blank=True)
	contato_responsavel = models.CharField(max_length=100, blank=True)
	mantenedor = models.CharField(max_length=100, blank=True)

	def __str__(self):
		return self.nome


class Interface(models.Model):
	sistema = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name='interfaces')
	projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name='interfaces_projeto')
	interface_identifier = models.CharField(max_length=50, blank=True)
	nome = models.CharField(max_length=100)
	tipo = models.CharField(max_length=50)
	tipo_outro = models.CharField(max_length=80, blank=True)
	endpoint = models.TextField(blank=True)
	formato_dados = models.CharField(max_length=20, blank=True)
	metodos_permitidos = models.CharField(max_length=200, blank=True)
	autenticacao = models.CharField(max_length=200, blank=True)
	operacoes_suportadas = models.TextField(blank=True)
	throttling = models.TextField(blank=True)
	throttling_unit = models.CharField(max_length=20, blank=True)
	technical_interface_notes = models.TextField(blank=True)

	detalhes = models.JSONField(blank=True, null=True)
	exemplo_dados = models.TextField(blank=True)
	esquema = models.TextField(blank=True)

	def __str__(self):
		return f"{self.nome} ({self.sistema.nome})"


class EstiloIntegracao(models.Model):
	projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name='estilos_integracao')
	sistema_origem = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name='integracoes_origem')
	sistema_destino = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name='integracoes_destino')
	estilo = models.CharField(max_length=50)
	estilo_outro = models.CharField(max_length=80, blank=True)
	interfaces_usadas = models.ManyToManyField(Interface, blank=True, related_name='integracoes')
	architectural_rationale = models.TextField(blank=True)
	detalhes = models.JSONField(blank=True, null=True)

	def __str__(self):
		return f"{self.estilo} - {self.sistema_origem.nome} → {self.sistema_destino.nome}"


class ChatMessage(models.Model):
	ROLE_CHOICES = (
		('user', 'User'),
		('assistant', 'Assistant'),
		('system', 'System'),
	)

	projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name='mensagens')
	role = models.CharField(max_length=20, choices=ROLE_CHOICES)
	content = models.TextField()
	prompt_used = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f"{self.role} - {self.projeto_id}"
