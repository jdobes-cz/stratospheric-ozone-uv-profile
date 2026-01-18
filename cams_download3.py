import cdsapi

lat = 50.798056
lon = 4.357500

# Small box around your point (reduces file size)
area = [lat + 0.5, lon - 0.5, lat - 0.5, lon + 0.5]  # N, W, S, E

pressure_levels = [
    "1000","925","850","700","600","500","400","300","250","200",
    "150","100","70","50","30","20","10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "0.5", "0.3"
]

dataset = "cams-global-atmospheric-composition-forecasts"
request = {
    "date": "2026-01-15",
    "time": "00:00",
    "leadtime_hour": ["0"],       # <-- ONLY the “one moment”
    "type": "forecast",
    "variable": ["ozone"],
    "pressure_level": pressure_levels,
    "area": area,
    "data_format": "netcdf"
}

client = cdsapi.Client()
client.retrieve(dataset, request, "cams_o3_profile_20260115_0000.nc")
print("Saved: cams_o3_profile_20260115_0000.nc")


