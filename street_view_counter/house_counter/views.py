import os
import uuid
# import json
import requests
# import os
import re
import math
import google.generativeai as genai
import glob
from PIL import Image
from io import BytesIO
import google_streetview.api
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import razorpay
from .models import StreetSearch, StreetViewImage, Subscription
from .forms import StreetSearchForm
# import openai
from pathlib import Path
from dotenv import load_dotenv
from django.conf import settings

# Load environment variables from .env file
load_dotenv()

# Create your views here.

def home(request):
    form = StreetSearchForm()
    
    # Check if user is authenticated and has active subscription before processing form
    if request.method == 'POST' and request.user.is_authenticated:
        # Check for active subscription
        try:
            subscription = Subscription.objects.get(user=request.user)
            if subscription.is_active():
                form = StreetSearchForm(request.POST)
                if form.is_valid():
                    street_search = form.save()
                    return redirect('process_street', search_id=street_search.id)
            else:
                messages.error(request, 'You need an active subscription to perform searches.')
                return redirect('subscribe')
        except Subscription.DoesNotExist:
            messages.error(request, 'You need a subscription to perform searches.')
            return redirect('subscribe')
    elif request.method == 'POST':
        # If not authenticated, redirect to login
        messages.info(request, 'Please login to perform searches.')
        return redirect('login')
    
    # Get recent searches
    recent_searches = StreetSearch.objects.filter(status='completed').order_by('-created_at')[:5]
    
    return render(request, 'house_counter/home.html', {
        'form': form,
        'recent_searches': recent_searches,
        'MEDIA_URL': settings.MEDIA_URL
    })

@login_required
def process_street(request, search_id):
    street_search = get_object_or_404(StreetSearch, id=search_id)
    street_search.processing_message = "Creating directories for image storage..."
    street_search.save()
    
    # Create media directory if it doesn't exist
    media_dir = Path(settings.MEDIA_ROOT)
    media_dir.mkdir(exist_ok=True)
    
    # Create directory for this search
    search_dir = media_dir / f'search_{search_id}'
    search_dir.mkdir(exist_ok=True)
    
    # Get coordinates for the street using Google Geocoding API
    street_search.processing_message = "Looking up street coordinates..."
    street_search.save()
    
    # Get API key from environment variable
    google_api_key = os.environ.get('GOOGLE_STREET_VIEW_API_KEY')
    geocode_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={street_search.query}&key={google_api_key}"
    geocode_response = requests.get(geocode_url)
    geocode_data = geocode_response.json()
    
    if geocode_data['status'] != 'OK':
        street_search.status = 'failed'
        street_search.save()
        return render(request, 'house_counter/error.html', {
            'message': f"Could not find location: {geocode_data['status']}"
        })
    
    # Get the coordinates
    location = geocode_data['results'][0]['formatted_address']
    lat = geocode_data['results'][0]['geometry']['location']['lat']
    lng = geocode_data['results'][0]['geometry']['location']['lng']
    
    # Get the street's bounding box to determine start and end points
    viewport = geocode_data['results'][0]['geometry'].get('viewport', {})
    
    # If we have viewport data, use it to get start and end points of the street
    if viewport:
        start_lat = viewport['southwest']['lat']
        start_lng = viewport['southwest']['lng']
        end_lat = viewport['northeast']['lat']
        end_lng = viewport['northeast']['lng']
    else:
        # If no viewport, create artificial start/end points by offsetting from the center
        start_lat = lat - 0.001  # Approximately 100m south
        start_lng = lng - 0.001  # Approximately 100m west
        end_lat = lat + 0.001    # Approximately 100m north
        end_lng = lng + 0.001    # Approximately 100m east
    
    # Get street view images at intervals along the street
    street_search.processing_message = "Planning route along the street..."
    street_search.save()
    
    # Use Google Directions API to get points along the actual street path
    street_search.processing_message = "Getting directions for the road..."
    street_search.save()
    
    # Use start and end coordinates for the route path
    directions_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={start_lat},{start_lng}&destination={end_lat},{end_lng}&key={google_api_key}"
    directions_response = requests.get(directions_url)
    directions_data = directions_response.json()
    
    # Extract route points or fallback to straight line interpolation
    if directions_data.get('status') == 'OK' and directions_data.get('routes'):
        route_points = extract_route_points(directions_data)
    else:
        street_search.processing_message = "Using straight line interpolation for the road..."
        street_search.save()
        # Create 10 evenly spaced points along the street
        route_points = [
            (start_lat + i/9*(end_lat - start_lat), start_lng + i/9*(end_lng - start_lng))
            for i in range(10)
        ]
    
    # Save the route information to the StreetSearch model
    if route_points:
        street_search.start_lat = route_points[0][0]
        street_search.start_lng = route_points[0][1]
        street_search.end_lat = route_points[-1][0]
        street_search.end_lng = route_points[-1][1]
        street_search.save()
    
    # If we couldn't get route points, create evenly spaced points along a straight line
    if not route_points:
        street_search.processing_message = "Creating evenly spaced points along the street..."
        street_search.save()
        
        # Create 10 evenly spaced points along a straight line from start to end
        for i in range(10):
            t = i / 9.0  # Parameter from 0 to 1
            point_lat = start_lat + t * (end_lat - start_lat)
            point_lng = start_lng + t * (end_lng - start_lng)
            route_points.append((point_lat, point_lng))
    
    # Filter out points that are too close to each other
    filtered_points = []
    min_distance = 0.00005  # Approximately 5 meters in lat/lng units - reduced to get more points
    
    for point in route_points:
        # Only add this point if it's not too close to any point we've already added
        if not filtered_points or all(
            math.sqrt((point[0] - p[0])**2 + (point[1] - p[1])**2) > min_distance 
            for p in filtered_points
        ):
            filtered_points.append(point)
    
    # If we have too few points, try to generate more by interpolation
    if len(filtered_points) < 5:
        # Create more points by interpolation between existing points
        more_points = []
        if len(filtered_points) >= 2:
            for i in range(len(filtered_points) - 1):
                p1 = filtered_points[i]
                p2 = filtered_points[i + 1]
                # Add 3 intermediate points between each pair
                for j in range(1, 4):
                    t = j / 4.0
                    new_lat = p1[0] + t * (p2[0] - p1[0])
                    new_lng = p1[1] + t * (p2[1] - p1[1])
                    more_points.append((new_lat, new_lng))
            
            # Add the interpolated points
            filtered_points.extend(more_points)
        else:
            # If we have only one point or none, create points in a small grid around it
            if filtered_points:
                center = filtered_points[0]
                offsets = [-0.0002, -0.0001, 0, 0.0001, 0.0002]  # ~20m increments
                for lat_offset in offsets:
                    for lng_offset in offsets:
                        if lat_offset == 0 and lng_offset == 0:
                            continue  # Skip the center point (already in the list)
                        new_lat = center[0] + lat_offset
                        new_lng = center[1] + lng_offset
                        more_points.append((new_lat, new_lng))
                filtered_points.extend(more_points)
            else:
                # If no points at all, use the original geocoded location
                filtered_points = [(lat, lng)]
                # And add points in a grid around it
                offsets = [-0.0002, -0.0001, 0.0001, 0.0002]  # ~20m increments
                for lat_offset in offsets:
                    for lng_offset in offsets:
                        new_lat = lat + lat_offset
                        new_lng = lng + lng_offset
                        filtered_points.append((new_lat, new_lng))
    
    # Make sure we have a reasonable number of points (5-10)
    route_points = filtered_points
    # We want at least 5 points, but no more than 10
    target_points = min(10, max(5, len(route_points)))
    if len(route_points) > target_points:
        # Take evenly spaced points
        step = len(route_points) // target_points
        route_points = [route_points[i] for i in range(0, len(route_points), step)][:target_points]
    
    street_search.processing_message = f"Fetching Street View images for {len(route_points)} locations..."
    street_search.save()
    
    # Get images for each point along the route
    images = []
        
    # Default heading (north) in case there's only one point
    default_heading = 0
    
    for i, point in enumerate(route_points):
        point_lat, point_lng = point
        
        # For each point, determine the heading based on the next point (direction of the street)
        if i < len(route_points) - 1:
            next_point = route_points[i + 1]
            next_lat, next_lng = next_point
            
            # Calculate heading (direction) to the next point
            # This is a simplified calculation - for more accuracy, use the haversine formula
            dx = next_lng - point_lng
            dy = next_lat - point_lat
            heading = math.degrees(math.atan2(dx, dy))
            
            # Normalize heading to 0-360 degrees
            heading = (heading + 360) % 360
            # Save this heading for potential use by the last point
            default_heading = heading
        elif i > 0 and len(route_points) > 1:
            # For the last point, use the heading from the previous segment
            # heading is already set from the previous iteration
            pass
        else:
            # If there's only one point or this is the first point and we can't calculate heading
            heading = default_heading
        
        # Capture both left and right side views at each position
        # Adjust headings to be perpendicular to the street direction
        side_views = [
            {'heading': str((heading - 90) % 360), 'side': 'left'},   # Left side of the road
            {'heading': str((heading + 90) % 360), 'side': 'right'}    # Right side of the road
        ]
        
        for view in side_views:
            # Configure parameters for this view
            params = [{
                'size': '800x400',  # Wider image size for better view
                'location': f'{point_lat},{point_lng}',
                'heading': view['heading'],  # Direction to look (left or right)
                'pitch': '0',  # Angle (0 = horizontal, 90 = vertical up)
                'fov': '90',   # Field of view
                'key': os.environ.get('GOOGLE_STREET_VIEW_API_KEY')
            }]
        
            # Create a unique filename including the side
            filename = f"streetview_{i}_{view['side']}_{uuid.uuid4().hex}.jpg"
            file_path = search_dir / filename
            
            # First check if Street View is available at this location
            # Use the metadata API to check if imagery is available
            metadata_params = {
                'location': f'{point_lat},{point_lng}',
                'key': os.environ.get('GOOGLE_STREET_VIEW_API_KEY')
            }
            metadata_url = f"https://maps.googleapis.com/maps/api/streetview/metadata?{requests.compat.urlencode(metadata_params)}"
            metadata_response = requests.get(metadata_url)
            metadata = metadata_response.json()
            
            # Skip this point if Street View imagery is not available
            if metadata.get('status') != 'OK':
                print(f"Street View not available at {point_lat},{point_lng}")
                continue
                
            # If we have a panorama ID from the metadata, use it to ensure we get a unique image
            pano_id = metadata.get('pano_id', '')
            if pano_id:
                params[0]['pano'] = pano_id
                
            # Get street view image
            results = google_streetview.api.results(params)
            
            # Clear any existing .jpg files in the directory before downloading
            for existing_file in search_dir.glob('gsv_*.jpg'):
                os.remove(existing_file)
                
            results.download_links(str(search_dir))
            
            # Rename the downloaded file to our unique filename
            downloaded_files = list(search_dir.glob('gsv_*.jpg'))
            if downloaded_files and len(downloaded_files) > 0:
                os.rename(downloaded_files[0], file_path)
                
                # Create StreetViewImage record
                street_view_image = StreetViewImage.objects.create(
                    street_search=street_search,
                    image_path=f'search_{search_id}/{filename}',
                    location=location,
                    latitude=point_lat,
                    longitude=point_lng,
                    sequence_number=i * 2 + (0 if view['side'] == 'left' else 1)  # Sequence: left then right
                )
                
                images.append(street_view_image)
    
    # Process images with LLM to count trees
    street_search.processing_message = "Analyzing images with AI to count trees..."
    street_search.save()
    
    total_trees = process_images_with_llm(images, street_search)
    
    # Update the search record
    street_search.total_trees = total_trees
    street_search.status = 'completed'
    street_search.save()
    
    return redirect('results', search_id=street_search.id)

def process_images_with_llm(images, street_search=None):
    """
    For each image, send it to Gemini Flash 2.0 multimodal endpoint using the google-generativeai library and extract the tree count.
    """
    

    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        raise Exception("Gemini API key not found in environment variables. Please check your .env file.")

    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    total_trees = 0

    # Debug: Print all images in the database
    print("Images in database:")
    for idx, img in enumerate(images):
        print(f"  {idx}. {img.image_path} (sequence: {img.sequence_number})")
    
    # Process each image
    total_images = len(images)
    for idx, image in enumerate(images):
        if street_search:
            street_search.processing_message = f"Analyzing image {idx+1} of {total_images}..."
            street_search.save()
        # Get the search_id from the image path
        parts = image.image_path.split('/')
        if len(parts) >= 1:
            search_dir = parts[0]  # e.g., 'search_8'
            
            # Debug: List all files in this search directory
            search_path = os.path.join(settings.MEDIA_ROOT, search_dir)
            print(f"Files in {search_path}:")
            try:
                for file in os.listdir(search_path):
                    print(f"  - {file}")
            except Exception as e:
                print(f"Error listing directory: {e}")
        
        # Normalize path to ensure consistent path separators
        image_path = os.path.normpath(os.path.join(settings.MEDIA_ROOT, str(image.image_path)))
        print(f"Attempting to open image: {image_path}")
        
        # Check if file exists
        if not os.path.exists(image_path):
            print(f"WARNING: File does not exist: {image_path}")
            # Try to find a similar file
            base_dir = os.path.dirname(image_path)
            if os.path.exists(base_dir):
                print(f"Looking for similar files in {base_dir}...")
                similar_files = glob.glob(os.path.join(base_dir, "*.jpg"))
                if similar_files:
                    print(f"Found similar files: {similar_files}")
                    # Use the first similar file
                    image_path = similar_files[0]
                    print(f"Using alternative file: {image_path}")
                else:
                    print("No similar files found")
                    continue  # Skip this image
            else:
                print(f"Directory does not exist: {base_dir}")
                continue  # Skip this image
        
        try:
            with open(image_path, "rb") as img_file:
                img_bytes = img_file.read()
            
            # Convert bytes to PIL Image
            pil_image = Image.open(BytesIO(img_bytes))
            
            # Send the prompt and PIL image to Gemini as a single list argument
            response = model.generate_content([
                """
                Count the number of established trees visible along the public footpath/sidewalk in this Google Street View image. 

                Important counting rules:
                - ONLY count trees that are:
                * Planted along the public footpath/sidewalk space between the road and private property boundaries
                * Established trees with substantial trunks (at least 10cm/4in diameter)
                * Clearly visible as individual trees (not obscured/ambiguous groupings)

                - Do NOT count:
                * Small saplings or newly planted trees with stakes
                * Shrubs, bushes, or ornamental plants (even if large)
                * Any plants in pots, planters, or containers
                * Trees inside private property boundaries/compounds/gardens
                * Trees in central road medians or traffic islands
                * Plants growing through fences or emerging from private properties
                * Palm plants or banana plants under 2m tall

                For your analysis:
                1. First, identify the road and footpath boundaries
                2. Scan methodically from left to right
                3. For each potential tree, explicitly verify it meets all inclusion criteria
                4. Number each qualifying tree in your analysis
                5. State your final count clearly at the end
                6. If uncertain about any particular tree, explain your reasoning for including/excluding it
                Respond ONLY with a number.
                """,
                pil_image
            ])
            text = response.text
            print("Output from gemini: ", text)
            match = re.search(r'\d+', text)
            tree_count = int(match.group(0)) if match else 0
        except Exception as e:
            tree_count = 0  # fallback if API fails
            print(f"Error processing image {image.image_path}: {e}")
        
        image.tree_count = tree_count
        image.save()
        total_trees += tree_count

    return total_trees

def results(request, search_id):
    street_search = get_object_or_404(StreetSearch, id=search_id)
    images = street_search.images.all().order_by('sequence_number')
    
    return render(request, 'house_counter/results.html', {
        'street_search': street_search,
        'images': images,
        'MEDIA_URL': settings.MEDIA_URL
    })

def extract_route_points(directions_data):
    """Extract points from Google Directions API response"""
    points = []
    route = directions_data['routes'][0]
    
    # First try to use the overview_polyline for a more detailed path
    if 'overview_polyline' in route and 'points' in route['overview_polyline']:
        polyline_points = decode_polyline(route['overview_polyline']['points'])
        # Add points at regular intervals along the polyline
        if len(polyline_points) > 2:
            points = polyline_points
            return points
    
    # Fallback to extracting points from legs and steps
    for leg in route['legs']:
        # Add the starting point of the leg
        leg_start = (leg['start_location']['lat'], leg['start_location']['lng'])
        if not points or points[-1] != leg_start:  # Avoid duplicates
            points.append(leg_start)
        
        for step in leg['steps']:
            # Add the starting point of each step
            step_start = (step['start_location']['lat'], step['start_location']['lng'])
            if not points or points[-1] != step_start:  # Avoid duplicates
                points.append(step_start)
            
            # Add intermediate points by polyline decoding if available
            if 'polyline' in step and 'points' in step['polyline']:
                polyline_points = decode_polyline(step['polyline']['points'])
                # Only add a subset of points to avoid too many close points
                if len(polyline_points) > 5:
                    # Take every nth point
                    n = len(polyline_points) // 5
                    for i in range(0, len(polyline_points), n):
                        p = polyline_points[i]
                        if not points or points[-1] != p:  # Avoid duplicates
                            points.append(p)
                else:
                    # If few points, add them all
                    for p in polyline_points:
                        if not points or points[-1] != p:  # Avoid duplicates
                            points.append(p)
            
            # Add the ending point of each step
            step_end = (step['end_location']['lat'], step['end_location']['lng'])
            if not points or points[-1] != step_end:  # Avoid duplicates
                points.append(step_end)
        
        # Add the ending point of the leg
        leg_end = (leg['end_location']['lat'], leg['end_location']['lng'])
        if not points or points[-1] != leg_end:  # Avoid duplicates
            points.append(leg_end)
    
    return points

def decode_polyline(polyline_str):
    """Decode a Google Maps encoded polyline string into a list of lat/lng points"""
    index, lat, lng = 0, 0, 0
    coordinates = []
    changes = {'lat': 0, 'lng': 0}

    # Coordinates have variable length when encoded, so just keep reading
    while index < len(polyline_str):
        for unit in ['lat', 'lng']:
            shift, result = 0, 0

            while True:
                byte = ord(polyline_str[index]) - 63
                index += 1
                result |= (byte & 0x1f) << shift
                shift += 5
                if not byte >= 0x20:
                    break

            if (result & 1):
                changes[unit] = ~(result >> 1)
            else:
                changes[unit] = (result >> 1)

        lat += changes['lat']
        lng += changes['lng']

        coordinates.append((lat / 100000.0, lng / 100000.0))

    return coordinates

def search_status(request, search_id):
    street_search = get_object_or_404(StreetSearch, id=search_id)
    return JsonResponse({
        'status': street_search.status,
        'total_trees': street_search.total_trees,
        'processing_message': street_search.processing_message
    })
