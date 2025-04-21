# Street View Tree Counter

A Django web application that counts trees along streets using Google Street View images and AI.

## Overview

The Street View Tree Counter application allows users to:
1. Enter a street name or address
2. Automatically capture Google Street View images along the street
3. Use AI (Google Gemini) to analyze the images and count trees
4. View detailed results with tree counts for each location

## Features

- **Street Search**: Enter any street name to start the tree counting process
- **Automatic Image Capture**: Captures multiple Street View images along the street path
- **AI-Powered Tree Detection**: Uses Google Gemini to identify and count trees in images
- **Real-time Processing Updates**: Shows detailed status messages during processing
- **Results Dashboard**: Displays all images with tree counts and location data

## Technical Details

- **Backend**: Django (Python)
- **AI Integration**: Google Gemini Flash 2.0 for image analysis
- **Maps Integration**: Google Street View API, Google Directions API
- **Frontend**: Bootstrap, JavaScript

## Requirements

- Python 3.8+
- Django 5.0+
- Google Street View API key
- Google Gemini API key

## Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv myenv`
3. Activate the virtual environment: 
   - Windows: `myenv\Scripts\activate`
   - Linux/Mac: `source myenv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Create a `.env` file in the project root with your API keys:
   ```
   GOOGLE_STREET_VIEW_API_KEY=your_api_key_here
   GEMINI_API_KEY=your_gemini_api_key_here
   ```
6. Run migrations: `python manage.py migrate`
7. Start the server: `python manage.py runserver`

## Usage

1. Navigate to the home page
2. Enter a street name in the search box
3. Click "Count Trees"
4. View the processing status and wait for the analysis to complete
5. Explore the results showing tree counts for each location along the street

## License

MIT License
