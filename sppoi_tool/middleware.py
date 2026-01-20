import json
import logging
import time
import uuid

from django.utils import timezone


def _get_client_ip(request):
	forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
	if forwarded:
		return forwarded.split(',')[0].strip()
	return request.META.get('REMOTE_ADDR')


class RequestAuditMiddleware:
	def __init__(self, get_response):
		self.get_response = get_response
		self.logger = logging.getLogger('chat.audit')

	def __call__(self, request):
		start_time = time.time()
		request_id = str(uuid.uuid4())
		request.request_id = request_id

		try:
			response = self.get_response(request)
		except Exception as exc:
			duration_ms = int((time.time() - start_time) * 1000)
			payload = {
				'event': 'exception',
				'request_id': request_id,
				'method': request.method,
				'path': request.path,
				'duration_ms': duration_ms,
				'ip': _get_client_ip(request),
				'user_agent': request.META.get('HTTP_USER_AGENT'),
				'referer': request.META.get('HTTP_REFERER'),
				'error_type': type(exc).__name__,
				'error_message': str(exc),
			}
			self.logger.exception(json.dumps(payload, ensure_ascii=False))
			raise

		duration_ms = int((time.time() - start_time) * 1000)
		try:
			session_key = request.session.session_key
			current_project_id = request.session.get('current_project_id')
		except Exception:
			session_key = None
			current_project_id = None

		user_id = None
		if hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
			user_id = request.user.id

		payload = {
			'event': 'request',
			'request_id': request_id,
			'method': request.method,
			'path': request.path,
			'status_code': getattr(response, 'status_code', None),
			'duration_ms': duration_ms,
			'ip': _get_client_ip(request),
			'user_agent': request.META.get('HTTP_USER_AGENT'),
			'referer': request.META.get('HTTP_REFERER'),
			'session_key': session_key,
			'current_project_id': current_project_id,
			'user_id': user_id,
		}
		self.logger.info(json.dumps(payload, ensure_ascii=False))
		return response


class SessionExpiryAtFourAMMiddleware:
	def __init__(self, get_response):
		self.get_response = get_response

	def __call__(self, request):
		now = timezone.localtime()
		four_am_today = now.replace(hour=4, minute=0, second=0, microsecond=0)
		if now < four_am_today:
			next_expiry = four_am_today
		else:
			next_expiry = four_am_today + timezone.timedelta(days=1)

		expires_at_iso = request.session.get('expires_at')
		if expires_at_iso:
			try:
				expires_at = timezone.datetime.fromisoformat(expires_at_iso)
				if timezone.is_naive(expires_at):
					expires_at = timezone.make_aware(expires_at)
				if now >= expires_at:
					request.session.flush()
			except Exception:
				request.session.flush()

		request.session['expires_at'] = next_expiry.isoformat()
		request.session.set_expiry(int((next_expiry - now).total_seconds()))

		response = self.get_response(request)
		return response
