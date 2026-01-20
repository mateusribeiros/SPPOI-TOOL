from django.contrib import admin
from .models import Projeto, Sistema, Interface, EstiloIntegracao, ChatMessage

admin.site.register(Projeto)
admin.site.register(Sistema)
admin.site.register(Interface)
admin.site.register(EstiloIntegracao)
admin.site.register(ChatMessage)
