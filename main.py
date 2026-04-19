from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ee
import os
import json

app = FastAPI()

# -------------------------------
# CORS SETTINGS (Crucial for Web)
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # This allows GitHub Pages to connect
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# EARTH ENGINE INITIALIZATION
# -------------------------------
def initialize_ee():
    try:
        # Check if we are running on Render (GEE_JSON exists)
        gee_json = os.getenv("GEE_JSON")
        
        if gee_json:
            print("Running in Cloud mode...")
            info = json.loads(gee_json)
            credentials = ee.ServiceAccountCredentials(info['client_email'], key_data=gee_json)
            ee.Initialize(credentials, project="uhi-research")
        else:
            print("Running in Local mode...")
            ee.Initialize(project="uhi-research")
            
        print("✅ Earth Engine initialized successfully")
    except Exception as e:
        print(f"❌ EE init failed: {e}")

initialize_ee()

# -------------------------------
# DATA MODELS
# -------------------------------
class AnalysisRequest(BaseModel):
    coordinates: list
    start_date: str
    end_date: str

# -------------------------------
# ROUTES
# -------------------------------
@app.get("/")
def root():
    return {"message": "Microclimate Engine Backend Active"}

@app.post("/get-indices")
def get_indices(data: AnalysisRequest):
    try:
        # 1. Format Coordinates for GEE
        # Leaflet Draw nested array handling
        raw_coords = data.coordinates[0]
        if isinstance(raw_coords[0], list):
            path = raw_coords[0]
        else:
            path = raw_coords
            
        ee_coords = [[float(p["lng"]), float(p["lat"])] for p in path]
        
        # Ensure polygon is closed
        if ee_coords[0] != ee_coords[-1]:
            ee_coords.append(ee_coords[0])
            
        region = ee.Geometry.Polygon([ee_coords])

        # 2. Filter Landsat 8/9 Collection 2 Level 2
        collection = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                      .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
                      .filterBounds(region)
                      .filterDate(data.start_date, data.end_date)
                      .sort("CLOUD_COVER"))

        image = collection.first()

        if not image:
            raise HTTPException(status_code=404, detail="No clear imagery found for selected dates.")

        # --- CALCULATIONS ---
        # A. LST (Celsius)
        lst = (image.select("ST_B10")
               .multiply(0.00341802)
               .add(149.0)
               .subtract(273.15)
               .clip(region))

        # B. NDVI (Vegetation)
        ndvi = image.normalizedDifference(['SR_B5', 'SR_B4']).clip(region)

        # C. NDBI (Built-Up)
        ndbi = image.normalizedDifference(['SR_B6', 'SR_B5']).clip(region)

        # --- VISUALIZATION PALETTES ---
        vis_lst = {"min": 25, "max": 50, "palette": ["0000ff", "00ffff", "ffff00", "ff0000", "990000"]}
        vis_ndvi = {"min": 0, "max": 0.8, "palette": ["#654321", "#f5e79d", "#00ff00", "#008000", "#004d00"]}
        vis_ndbi = {"min": -0.1, "max": 0.4, "palette": ["#ffffff", "#cccccc", "#ff8c00", "#ff0000"]}

        return {
            "lst_url": lst.getMapId(vis_lst)["tile_fetcher"].url_format,
            "ndvi_url": ndvi.getMapId(vis_ndvi)["tile_fetcher"].url_format,
            "ndbi_url": ndbi.getMapId(vis_ndbi)["tile_fetcher"].url_format,
            "metadata": {
                "sensor": image.get("SPACECRAFT_ID").getInfo(),
                "date": image.date().format("YYYY-MM-DD").getInfo()
            }
        }

    except Exception as e:
        print(f"Server Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
