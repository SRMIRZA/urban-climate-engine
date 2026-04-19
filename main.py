from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ee

app = FastAPI()

# -------------------------------
# CORS CONFIGURATION
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# EARTH ENGINE INITIALIZATION
# -------------------------------
try:
    # Use your specific project ID
    ee.Initialize(project="uhi-research")
    print("✅ Earth Engine initialized successfully")
except Exception as e:
    print(f"❌ EE init failed: {e}")

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
def read_root():
    return {"status": "Microclimate Backend Running"}

@app.post("/get-indices")
def get_indices(data: AnalysisRequest):
    try:
        # 1. Format Coordinates for GEE (Leaflet returns nested arrays)
        raw_coords = data.coordinates[0]
        # Handle different Leaflet Draw nesting levels
        if isinstance(raw_coords[0], list):
            path = raw_coords[0]
        else:
            path = raw_coords
            
        ee_coords = [[float(p["lng"]), float(p["lat"])] for p in path]
        
        # Ensure polygon is closed for GEE
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

        # --- PHYSICS CALCULATIONS ---
        
        # A. LST (Land Surface Temp) - Scale factors for C2 L2
        lst = (image.select("ST_B10")
               .multiply(0.00341802)
               .add(149.0)
               .subtract(273.15)
               .clip(region))

        # B. NDVI (Vegetation)
        ndvi = image.normalizedDifference(['SR_B5', 'SR_B4']).clip(region)

        # C. NDBI (Built-Up/Buildings)
        ndbi = image.normalizedDifference(['SR_B6', 'SR_B5']).clip(region)

        # --- VISUALIZATION PARAMS ---
        vis_lst = {"min": 25, "max": 50, "palette": ["0000ff", "00ffff", "ffff00", "ff0000"]}
        vis_ndvi = {"min": 0, "max": 0.6, "palette": ["#ece2f0", "#a6bddb", "#1c9099", "#016c59"]}
        vis_ndbi = {"min": -0.1, "max": 0.4, "palette": ["#ffffff", "#f0f0f0", "#636363", "#000000"]}

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)