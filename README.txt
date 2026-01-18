Step 1 - Download ozone prediction data from database. 
 - The prediciton is only 5 days / 120 hours ahead.
 - You need to register on the web page to key the access key. Save the key to ~/.cdsapirc. Here is the format of the file:
url: https://ads.atmosphere.copernicus.eu/api
key: ********-****-****-****-************

 - You need to acknowledge license on the dataset page to be able to access the dataset via API.
 - Adjust cams_download3.py for date/time and run it.
 - It creates cams_o3_profile_20260115_0000.nc file.

Step 2: Interpolate for specific point and save data.
 - Run interpolation1.py
 - It reads cams_o3_profile_20260115_0000.nc and creates o3_mmr.dat file.

Step 3: Donwload and build librantran library.

Step 4: Calculate UV in upward direction
 - (If you want to) check/adjust uvspec_template.inp
 - Note that the calculation is using the O3 profile downloaded in the first step
 - run run_loop.sh
 - It creates loop/eup*dat files with the UV profile at different altitude levels.
