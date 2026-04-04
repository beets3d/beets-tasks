import base64
import hashlib
import hmac
import json
import logging
from django.conf import settings
from django.http import HttpRequest, JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import QuickBooksConfig
from .models import QuickBooksWebhookLog
from crm.models import Customer

logger = logging.getLogger(__name__)

def verify_signature(payload_body: bytes, intuit_signature: str, verifier_token: str) -> bool:
    if not verifier_token or not intuit_signature:
        return False
    # QuickBooks webhook verification requires hmac with the token
    hmac_obj = hmac.new(verifier_token.encode('utf-8'), payload_body, hashlib.sha256)
    expected_signature = base64.b64encode(hmac_obj.digest()).decode('utf-8')
    return hmac.compare_digest(expected_signature, intuit_signature)

@csrf_exempt
@require_POST
def qb_webhook(request: HttpRequest) -> JsonResponse:
    intuit_signature = request.headers.get("intuit-signature", "")
    config = QuickBooksConfig.objects.first()
    
    verifier_token = config.webhook_token if config else getattr(settings, "QUICKBOOKS_WEBHOOK_TOKEN", "")

    if not verify_signature(request.body, intuit_signature, verifier_token):
        logger.warning("QuickBooks webhook signature mismatch. Ensure Webhook Verifier Token is set.")
        QuickBooksWebhookLog.objects.create(
            body=request.body.decode('utf-8', errors='replace'),
            signature=intuit_signature,
            is_verified=False,
            error_message="Signature mismatch. Ensure Webhook Verifier Token is set."
        )
        return HttpResponseForbidden("Invalid signature")

    try:
        payload = json.loads(request.body)
        
        # Log to database for debugging
        QuickBooksWebhookLog.objects.create(
            body=request.body.decode('utf-8', errors='replace'),
            signature=intuit_signature,
            is_verified=True,
            error_message=""
        )
        
        # Parse the Event Notifications
        for notification in payload.get('eventNotifications', []):
            realm_id = notification.get('realmId')
            events = notification.get('dataChangeEvent', {}).get('entities', [])
            
            for event in events:
                entity_name = event.get('name')
                entity_id = event.get('id')
                operation = event.get('operation')
                
                # We specifically want to monitor Customer or Estimate updates
                if entity_name in ("Customer", "Estimate") and operation in ("Update", "Create"):
                    logger.info(f"QuickBooks Webhook: {entity_name} {entity_id} {operation}d for Realm {realm_id}.")
                    # Note: We just log the occurrence for now. A background celery task or thread 
                    # should ideally be spawned here to re-fetch the Customer from the QB API and 
                    # update the `crm.Customer` table to avoid blocking the webhook response.
                    # e.g., sync_customer_from_qb.delay(entity_id, realm_id)
                    
    except Exception as e:
        logger.error(f"Error processing QuickBooks webhook: {e}")
        # Even if processing fails, Intuit expects a 200 within 3 seconds, 
        # but 500 can be returned for unparseable data

    return JsonResponse({"status": "received"})
