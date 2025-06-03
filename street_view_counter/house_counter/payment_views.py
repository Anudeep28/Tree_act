import json
import razorpay
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import Subscription
from django.contrib import messages

client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

@login_required
def subscribe_view(request):
    """
    View to handle subscription page and payment initialization
    """
    # Create a Razorpay Order
    # Amount in paise (₹299 = 29900 paise)
    amount = 29900
    
    payment_data = {
        'amount': amount,
        'currency': 'INR',
        'receipt': f'order_rcptid_{request.user.id}',
        'notes': {
            'user_id': request.user.id,
            'purpose': 'Tree Act Monthly Subscription'
        }
    }
    
    # Create Razorpay Order
    order = client.order.create(data=payment_data)
    
    # Ensure user has a subscription object
    subscription, created = Subscription.objects.get_or_create(user=request.user)
    
    context = {
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
        'order_id': order['id'],
        'amount': amount
    }
    
    return render(request, 'subscribe.html', context)

@csrf_exempt
@login_required
def payment_success_view(request):
    """
    Handle successful payment callback from Razorpay
    """
    if request.method == 'POST':
        try:
            # Parse the JSON data from the request body
            payment_data = json.loads(request.body)
            
            # Verify the payment signature
            params_dict = {
                'razorpay_order_id': payment_data.get('razorpay_order_id'),
                'razorpay_payment_id': payment_data.get('razorpay_payment_id'),
                'razorpay_signature': payment_data.get('razorpay_signature')
            }
            
            # Verify the payment signature
            try:
                client.utility.verify_payment_signature(params_dict)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=400)
            
            # Get the subscription and activate it
            subscription = Subscription.objects.get(user=request.user)
            subscription.activate()
            
            messages.success(request, 'Payment successful! Your subscription is now active.')
            return JsonResponse({'status': 'success'})
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    
    return JsonResponse({'error': 'Invalid request method'}, status=400)
