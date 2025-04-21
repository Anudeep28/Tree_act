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
from django.http import JsonResponse
from django.urls import reverse
from .models import StreetSearch, StreetViewImage
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
    if request.method == 'POST':
        form = StreetSearchForm(request.POST)
        if form.is_valid():
            street_search = form.save()
            return redirect('process_street', search_id=street_search.id)
    
    # Get recent searches
    recent_searches = StreetSearch.objects.filter(status='completed').order_by('-created_at')[:5]
    
    return render(request, 'house_counter/home.html', {
        'form': form,
        'recent_searches': recent_searches,
        'MEDIA_URL': settings.MEDIA_URL
    })

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
    directions_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={start_lat},{start_lng}&destination={end_lat},{end_lng}&key={google_api_key}"
    directions_response = requests.get(directions_url)
    directions_data = directions_response.json()
    
    # Extract route points
    route_points = []
    if directions_data.get('status') == 'OK' and directions_data.get('routes'):
        # Get the first route
        route = directions_data['routes'][0]
        
        # Get the polyline that represents the route
        if 'overview_polyline' in route and 'points' in route['overview_polyline']:
            # Decode the polyline to get a list of lat/lng points
            try:
                # We'll need to import the polyline library
                import polyline
                points = polyline.decode(route['overview_polyline']['points'])
                route_points = points
            except ImportError:
                # If polyline library is not available, fall back to steps
                street_search.processing_message = "Using route steps (polyline library not available)..."
                street_search.save()
                
                # Extract points from each step in the route
                for leg in route['legs']:
                    for step in leg['steps']:
                        start_point = (step['start_location']['lat'], step['start_location']['lng'])
                        end_point = (step['end_location']['lat'], step['end_location']['lng'])
                        route_points.append(start_point)
                        route_points.append(end_point)
    
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
    
    # Select a subset of points to ensure we have a reasonable number of images
    # We want about 5-10 points along the route
    target_points = min(10, len(route_points))
    if len(route_points) > target_points:
        # Take evenly spaced points
        step = len(route_points) // target_points
        route_points = [route_points[i] for i in range(0, len(route_points), step)][:target_points]
    
    street_search.processing_message = f"Fetching Street View images for {len(route_points)} locations..."
    street_search.save()
    
    # Get images for each point along the route
    images = []
        
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
        else:
            # For the last point, use the heading from the previous segment
            heading = heading  # Use the last calculated heading
        
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
            
            # Get street view image
            results = google_streetview.api.results(params)
            results.download_links(str(search_dir))
            
            # Rename the downloaded file to our unique filename
            downloaded_files = list(search_dir.glob('*.jpg'))
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

def search_status(request, search_id):
    street_search = get_object_or_404(StreetSearch, id=search_id)
    return JsonResponse({
        'status': street_search.status,
        'total_trees': street_search.total_trees,
        'processing_message': street_search.processing_message
    })
