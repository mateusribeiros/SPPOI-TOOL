from django.urls import path
from . import views

urlpatterns = [
	path('', views.index, name='index'),
	path('captcha/verify/', views.captcha_verify, name='captcha_verify'),
	path('chat/new/', views.new_chat, name='chat_new'),
	path('chat/', views.chat_view, name='chat_view'),
	path('chat/<int:project_id>/', views.chat_view_redirect, name='chat_view_by_id'),
	path('chat/stream/', views.chat_stream_current, name='chat_stream'),
	path('chat/<int:project_id>/stream/', views.chat_stream, name='chat_stream_by_id'),

	path('api/chats/', views.chat_list_api, name='chat_list_api'),
	path('api/chat/select/<int:project_id>/', views.chat_select_api, name='chat_select_api'),
	path('api/<int:project_id>/chat/clear/', views.chat_clear_api, name='chat_clear_api'),
	path('api/<int:project_id>/chat/delete/', views.chat_delete_api, name='chat_delete_api'),

	path('api/<int:project_id>/systems/', views.systems_api, name='systems_api'),
	path('api/<int:project_id>/systems/<int:system_id>/', views.system_detail_api, name='system_detail_api'),

	path('api/<int:project_id>/interfaces/', views.interfaces_api, name='interfaces_api'),
	path('api/<int:project_id>/interfaces/<int:interface_id>/', views.interface_detail_api, name='interface_detail_api'),

	path('api/<int:project_id>/integrations/', views.integrations_api, name='integrations_api'),
	path('api/<int:project_id>/integrations/<int:integration_id>/', views.integration_detail_api, name='integration_detail_api'),
]
