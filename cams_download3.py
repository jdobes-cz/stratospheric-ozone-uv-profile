import cdsapi

lat = 50.798056
lon = 4.357500

# Small box around your point (reduces file size)
area = [lat + 0.5, lon - 0.5, lat - 0.5, lon + 0.5]  # N, W, S, E

pressure_levels = [
    "1000","925","850","700","600","500","400","300","250","200",
    "150","100","70","50","30","20","10","7","5","3","2","1"
]

dataset = "cams-global-atmospheric-composition-forecasts"
request = {
    "date": "2026-04-20",         # init date (pressure-level fields 3-hourly, released ~8-10h after init)
    "time": "12:00",              # init time: 00:00 or 12:00 UTC only
    "leadtime_hour": ["72"],      # +72 h → 2026-04-23 12:00 UTC = 14:00 CEST (closest 3-h grid point to 13:00 target)
    "type": "forecast",
    "variable": ["ozone"],
    "pressure_level": pressure_levels,
    "area": area,
    "data_format": "netcdf"
}

client = cdsapi.Client()
client.retrieve(dataset, request, "cams_o3_profile_20260423_1400local.nc")
print("Saved: cams_o3_profile_20260423_1400local.nc")


